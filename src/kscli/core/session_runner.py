"""Session runner — orchestrates farm sessions across VMs.

Port from kuaishou-bot: boots VMs, connects ADB, runs bot actions.
When PySide6 is available, runs in QThread. Otherwise uses pure-Python stubs
so the CLI can work without any Qt dependency.
"""
from __future__ import annotations

import logging
import os
import random
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    from PySide6.QtCore import QObject, QThread, Signal
    _HAS_QT = True
except ImportError:
    # ── Pure-Python stubs so CLI works without PySide6 ──
    _HAS_QT = False

    class _FakeSignal:
        """No-op Signal replacement."""
        def __init__(self, *_types): pass
        def emit(self, *args): pass
        def connect(self, *args): pass

    class QObject:  # type: ignore[no-redef]
        pass

    class QThread(threading.Thread, QObject):  # type: ignore[no-redef]
        def __init__(self, parent=None):
            threading.Thread.__init__(self, daemon=True)
            self._stop_flag = False

    Signal = _FakeSignal  # type: ignore[misc,assignment]

from kscli.core import mumu_adapter as mumu
from kscli.models.database import Database
from kscli.models.schemas import ActionLog, BotSettings

log = logging.getLogger(__name__)

# ── Kuaishou Resource IDs (verified on English UI build) ──────
RID_LIKE         = "com.smile.gifmaker:id/like_button"
RID_FOLLOW       = "com.smile.gifmaker:id/slide_play_right_follow_button"  # sidebar follow, VERIFIED
RID_FOLLOW_ALT   = "com.smile.gifmaker:id/follow_button"                   # fallback
RID_COMMENT_BTN  = "com.smile.gifmaker:id/comment_button"
RID_COMMENT_TRG  = "com.smile.gifmaker:id/editor_holder_text"
RID_COMMENT_EDT  = "com.smile.gifmaker:id/editor"
RID_COMMENT_SEND = "com.smile.gifmaker:id/finish_button"
APP_PACKAGE      = "com.smile.gifmaker"

# Add Friend flow — Me tab → Add Friend entry (VERIFIED)
RID_TAB_ME            = "com.smile.gifmaker:id/tab_me"              # thường không có, dùng text="Me"
RID_ADDFRIEND_ENTRY   = "com.smile.gifmaker:id/profile_add_friends_viewstub"  # VERIFIED WORKING
RID_ADDFRIEND_ENTRY2  = "com.smile.gifmaker:id/add_friend_entrance"           # fallback cũ
RID_ADDFRIEND_BTN     = "com.smile.gifmaker:id/add_friend_btn"                # thường không có, dùng text="Follow"



def should_do(rate: int) -> bool:
    if rate >= 100:
        return True
    if rate <= 0:
        return False
    return random.randint(1, 100) <= rate


class FarmWorker(QThread):
    """Runs a full farm session in a background thread."""

    log_message = Signal(str)         # text log
    stats_updated = Signal(dict)      # {"likes": int, "follows": int, "comments": int}
    session_finished = Signal(bool)   # True = completed, False = stopped/error

    def __init__(
        self,
        settings: BotSettings,
        vm_indices: list[int],
        video_count: int,
        comments: list[str],
        db: Database,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.vm_indices = vm_indices
        self.video_count = video_count
        self.comments = comments or ["太有趣了！", "牛逼！👍", "支持一下❤", "非常好看！"]
        self.db = db
        self._stop_flag = False
        self._total = {"likes": 0, "follows": 0, "comments": 0, "addfriends": 0}

    def request_stop(self) -> None:
        self._stop_flag = True

    def run(self) -> None:
        try:
            self._do_run()
        except Exception as e:
            self._log(f"❌ Lỗi nghiêm trọng: {e}")
            self.session_finished.emit(False)

    def _do_run(self) -> None:
        import uiautomator2 as u2

        s = self.settings
        self._log(f"🚀 Bắt đầu farm — {len(self.vm_indices)} máy × {self.video_count} video")
        self._log(f"📊 Rates: Like={s.like_rate}% Follow={s.follow_rate}% Comment={s.comment_rate}% AddFriend={s.addfriend_rate}%")
        self._log(f"🔧 AddFriend range: {s.addfriend_min}-{s.addfriend_max}, Enabled: L={s.like_enabled} F={s.follow_enabled} C={s.comment_enabled} AF={s.addfriend_enabled}")

        # Apply proxy config if enabled
        from kscli.core.proxy_config import load_proxy_config
        proxy_cfg = load_proxy_config()
        if proxy_cfg and proxy_cfg.get("host") and proxy_cfg.get("port"):
            proxy_type = proxy_cfg.get("type", "http")
            host = proxy_cfg["host"]
            port = proxy_cfg["port"]
            user = proxy_cfg.get("username", "")
            pwd = proxy_cfg.get("password", "")
            auth = f"{user}:{pwd}@" if user else ""
            proxy_url = f"{proxy_type}://{auth}{host}:{port}"
            os.environ["HTTP_PROXY"] = proxy_url
            os.environ["HTTPS_PROXY"] = proxy_url
            self._log(f"🔐 Proxy bật: {proxy_type}://{host}:{port}")
        else:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)

        # Check daytime constraint
        # if s.daytime_only:
        #     hour = datetime.now().hour
        #     if hour < 7 or hour >= 22:
        #         self._log("⏰ Ngoài giờ ban ngày (7h–22h). Farm bị huỷ tạm thời.")
        #         self.session_finished.emit(False)
        #         return


        # ── Chia VM thành các batch theo slot_count ──
        # slot_count = 1 → xử lý tuần tự từng máy (boot → farm → shutdown → next)
        # slot_count = 3 → mở 3 máy cùng lúc, farm song song, đóng, rồi batch tiếp
        batch_size = max(1, s.slot_count)
        total_vms = len(self.vm_indices)
        is_single_slot = (batch_size == 1)
        self._log(f"⚡ Chế độ: {batch_size} máy/đợt, tổng {total_vms} máy")
        if is_single_slot:
            self._log("🔒 Single-slot mode: chỉ cho phép 1 giả lập chạy tại mỗi thời điểm")

        vm_processed = 0

        for batch_start in range(0, total_vms, batch_size):
            if self._stop_flag:
                break

            batch_indices = self.vm_indices[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            self._log(f"\n{'='*40}")
            self._log(f"🔄 ĐỢT {batch_num}: VM {batch_indices}")
            self._log(f"{'='*40}")

            # ── Single-slot guard: ép tắt tất cả VM đang chạy trước khi boot ──
            if is_single_slot:
                running_vms = [vm for vm in mumu.list_vms() if vm.status == "running"]
                if running_vms:
                    self._log(f"⚠ Phát hiện {len(running_vms)} VM đang chạy, ép đóng trước...")
                    for vm in running_vms:
                        try:
                            ok, msg = mumu.stop_vm(vm.index)
                            self._log(f"  🔻 Đóng VM #{vm.index}: {msg}")
                        except Exception as e:
                            self._log(f"  ⚠ Lỗi đóng VM #{vm.index}: {e}")
                    self._sleep(2, 3)

            # ── Boot & connect batch ──
            devices: dict[int, u2.Device] = {}
            for idx in batch_indices:
                if self._stop_flag:
                    break
                self._log(f"📱 Boot VM #{idx}...")
                ok, msg = mumu.boot_vm(idx)
                self._log(f"  → {msg}")
                if not ok:
                    continue

                port = mumu.get_port(idx)
                if not port:
                    self._log(f"  ⚠ Không tìm thấy port cho VM #{idx}")
                    continue

                serial = f"127.0.0.1:{port}"
                mumu.adb_connect(port)
                self._sleep(3, 4)

                try:
                    d = u2.connect(serial)
                    info = d.info

                    # Tắt Phantom Process Killer (Android 12+)
                    try:
                        import subprocess
                        subprocess.run(
                            [mumu.ADB, "-s", serial, "shell",
                             "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"],
                            timeout=5, capture_output=True
                        )
                    except Exception:
                        pass

                    # Reset uiautomator2 service
                    try:
                        d.service("uiautomator").stop()
                        time.sleep(1)
                        d.service("uiautomator").start()
                    except Exception:
                        pass

                    devices[idx] = d
                    self._log(f"  ✅ Kết nối ADB → {info.get('productName', serial)}")
                except Exception as e:
                    self._log(f"  ❌ ADB lỗi: {e}")

            if not devices:
                self._log(f"  ⚠ Đợt {batch_num}: không kết nối được máy nào, bỏ qua.")
                continue

            # ── Mute batch ──
            for idx in devices:
                mumu.mute_vm(idx)
            self._log(f"🔇 Đã tắt tiếng {len(devices)} máy")

            # ── Farm batch ──
            max_workers = min(batch_size, len(devices))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._farm_single_device, idx, d): idx
                    for idx, d in devices.items()
                    if not self._stop_flag
                }
                for future in as_completed(futures):
                    if self._stop_flag:
                        break
                    try:
                        future.result()
                    except Exception as e:
                        self._log(f"❌ Lỗi trên device #{futures[future]}: {e}")

            vm_processed += len(devices)

            # ── Shutdown batch ──
            self._log(f"🔻 Đóng máy đợt {batch_num}...")
            # Đóng tất cả VM trong batch, không chỉ những VM connect ADB thành công
            for idx in batch_indices:
                try:
                    # Ngắt kết nối u2 nếu có
                    if idx in devices:
                        try:
                            # Thử ngắt kết nối uiautomator2 an toàn
                            devices[idx].service("uiautomator").stop()
                        except Exception:
                            pass
                    ok, msg = mumu.stop_vm(idx)
                    self._log(f"  VM #{idx}: {msg}")
                except Exception as e:
                    self._log(f"  VM #{idx}: lỗi đóng - {e}")

            if batch_start + batch_size < total_vms and not self._stop_flag:
                self._log("⏳ Chờ 3s trước khi mở đợt tiếp...")
                self._sleep(3, 4)

        # Done
        self._log(
            f"\n📊 TỔNG KẾT: ❤ {self._total['likes']} | ➕ {self._total['follows']} "
            f"| 💬 {self._total['comments']} | 🤝 {self._total['addfriends']}"
        )
        self._log(f"✅ Đã xử lý {vm_processed}/{total_vms} máy.")
        self.session_finished.emit(not self._stop_flag)

    def _dismiss_popups(self, d) -> None:
        """Dismiss common popups/dialogs (update, permissions, ads)."""
        import subprocess
        
        try:
            # Try to dismiss various popups — tìm nút Dissmiss/Close/Later
            attempts = 0
            while attempts < 5 and not self._stop_flag:
                # 1. Close button (X symbol) — thường ở góc
                close_btn = d(resourceId="com.smile.gifmaker:id/image_close")
                if not close_btn.exists:
                    close_btn = d(description="关闭")
                if not close_btn.exists:
                    close_btn = d(text="关闭")
                if not close_btn.exists:
                    close_btn = d(descriptionContains="close")
                
                if close_btn.exists:
                    close_btn.click()
                    self._sleep(0.5, 1.0)
                    attempts += 1
                    continue

                # 2. 稍后 (Later) button — update dialog
                later_btn = d(text="稍后")
                if not later_btn.exists:
                    later_btn = d(description="稍后")
                
                if later_btn.exists:
                    later_btn.click()
                    self._sleep(0.5, 1.0)
                    attempts += 1
                    continue

                # 3. 允许 (Allow) or 拒绝 (Deny) — permission dialog
                allow_btn = d(text="允许")
                if allow_btn.exists:
                    allow_btn.click()
                    self._sleep(0.5, 1.0)
                    attempts += 1
                    continue

                # 4. Dismiss (English)
                dismiss_btn = d(text="Dismiss")
                if not dismiss_btn.exists:
                    dismiss_btn = d(text="OK")
                
                if dismiss_btn.exists:
                    dismiss_btn.click()
                    self._sleep(0.5, 1.0)
                    attempts += 1
                    continue

                # No more popups detected
                break

        except Exception as e:
            self._log(f"  ⚠ Lỗi khi dismiss popups: {e}")

    def _farm_single_device(self, idx: int, d) -> None:
        """Farm all videos on a single device (runs in thread pool)."""
        self._log(f"\n{'='*40}\n📱 Farm trên VM #{idx}\n{'='*40}")

        # Open Kuaishou — dùng am start trực tiếp (verified working trên MuMu)
        KUAISHOU_ACTIVITY = "com.smile.gifmaker/com.yxcorp.gifshow.HomeActivity"
        current = d.app_current().get("package", "")
        if current != APP_PACKAGE:
            self._log(f"[App] Đang mở Kuaishou...")
            import subprocess
            # am start -n là cách đáng tin cậy nhất trên MuMu emulator
            subprocess.run(
                [mumu.ADB, "-s", d.serial, "shell", "am", "start", "-n", KUAISHOU_ACTIVITY],
                capture_output=True, timeout=10,
            )
            self._sleep(5, 6)
            
            curr_pkg = d.app_current().get("package", "")
            if curr_pkg != APP_PACKAGE:
                # Fallback: thử app_start của uiautomator2
                self._log("  ⚠ am start thất bại, thử fallback...")
                d.app_start(APP_PACKAGE, stop=False)
                d.app_wait(APP_PACKAGE, timeout=10.0)
                self._sleep(4, 5)
                curr_pkg = d.app_current().get("package", "")
            
            if curr_pkg != APP_PACKAGE:
                self._log(f"  ❌ Không mở được Kuaishou! Đang ở: {curr_pkg}")
                raise Exception("Không thể mở ứng dụng Kuaishou.")
                
            self._log("  ✅ Kuaishou đã mở thành công.")
        else:
            self._log("  ✅ Kuaishou đang chạy.")

        self._sleep(2, 3)
        
        # Dismiss any startup popups
        self._dismiss_popups(d)


        # Action 1: Xem video + tương tác (Like/Follow/Comment)
        for i in range(self.video_count):
            if self._stop_flag:
                self._log("⏹ Dừng theo yêu cầu.")
                break

            self._log(f"  🎬 Video {i + 1}/{self.video_count}")
            
            # Retry logic — nếu lỗi, thử lại max 3 lần
            retry_count = 0
            max_retries = 3
            while retry_count < max_retries:
                try:
                    self._run_interaction(d, idx)
                    
                    if i < self.video_count - 1:
                        self._swipe_next(d)
                    break  # Success, move to next video
                except Exception as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        self._log(f"    ❌ Video {i + 1} thất bại sau {max_retries} lần: {e}")
                        break
                    else:
                        self._log(f"    ⚠ Lỗi video {i + 1}, retry {retry_count}/{max_retries}: {e}")
                        self._sleep(2, 3)
                        # Try to dismiss popups before retry
                        self._dismiss_popups(d)

        # Action 2: Add Friend (chạy sau khi xem video xong)
        if self.settings.addfriend_enabled and not self._stop_flag:
            self._log(f"\n🤝 Add Friend trên VM #{idx}...")
            count = self._run_addfriend(d, idx)
            if count > 0:
                self._total["addfriends"] += count
                self._log(f"  ✅ Đã thêm {count} bạn trên VM #{idx}")
            else:
                self._log(f"  ⚠ Không thêm được bạn nào trên VM #{idx}")

    def _run_interaction(self, d, device_idx: int) -> dict:
        s = self.settings
        result = {"like": False, "follow": False, "comment": False}

        # Watch
        watch_sec = random.uniform(s.watch_min_sec, s.watch_max_sec)
        self._log(f"    👁 Xem {watch_sec:.1f}s...")
        self._sleep(watch_sec, watch_sec)
        if self._stop_flag: return result
        self.db.write_log(ActionLog(device_idx, "watch", True))
        self.db.increment_stat(device_idx, "watch")

        # Like
        # Like
        if s.like_enabled:
            # 🎲 Roll the dice
            if should_do(s.like_rate):
                btn = d(resourceId=RID_LIKE)
                if btn.exists:
                    btn.click()
                    self._sleep(0.5, 1.0)
                    result["like"] = True
                    self._total["likes"] += 1
                    self.db.write_log(ActionLog(device_idx, "like", True))
                    self.db.increment_stat(device_idx, "like")
                    self._log(f"    ❤️ Liked (rate: {s.like_rate}%)")
                self._sleep(s.action_delay_min, s.action_delay_max)
            else:
                self._log(f"    ⏭ Bỏ qua Like (tỉ lệ: {s.like_rate}%)")

        # Follow — verified ZH: desc="关注" (chưa follow), desc="已关注" (đã follow)
        if s.follow_enabled:
            if should_do(s.follow_rate):
                already = (
                    d(description="已关注").exists
                    or d(text="已关注").exists
                    or d(description="Following").exists
                    or d(text="Following").exists
                )
                if not already:
                    btn = d(resourceId=RID_FOLLOW)
                    if not btn.exists:
                        btn = d(resourceId=RID_FOLLOW_ALT)
                    if not btn.exists:
                        btn = d(description="关注")
                    if btn.exists:
                        btn.click()
                        self._sleep(1.0, 1.5)
                        result["follow"] = True
                        self._total["follows"] += 1
                        self.db.write_log(ActionLog(device_idx, "follow", True))
                        self.db.increment_stat(device_idx, "follow")
                        self._log(f"    ➕ Followed (rate: {s.follow_rate}%)")
                else:
                    self._log("    ⏭ Bỏ qua Follow (Đã theo dõi từ trước)")
                self._sleep(s.action_delay_min, s.action_delay_max)
            else:
                self._log(f"    ⏭ Bỏ qua Follow (tỉ lệ: {s.follow_rate}%)")

        # Comment
        if s.comment_enabled and self.comments:
            if should_do(s.comment_rate):
                msg = random.choice(self.comments)
                ok = self._post_comment(d, msg)
                if ok:
                    result["comment"] = True
                    self._total["comments"] += 1
                    self.db.write_log(ActionLog(device_idx, "comment", True, msg))
                    self.db.increment_stat(device_idx, "comment")
                    self._log(f"    💬 Comment: '{msg}' (rate: {s.comment_rate}%)")
                self._sleep(s.action_delay_min, s.action_delay_max)
            else:
                self._log(f"    ⏭ Bỏ qua Comment (tỉ lệ: {s.comment_rate}%)")

        self.stats_updated.emit(self._total.copy())
        return result

    def _post_comment(self, d, text: str) -> bool:
        """Full comment flow — verified selectors 2026-04-02."""
        # 1. Mở comment panel
        cmt_btn = d(resourceId=RID_COMMENT_BTN)
        if not cmt_btn.exists:
            return False
        cmt_btn.click()
        self._sleep(2.0, 3.0)

        # 2. Click input area — editor_holder_text KHÔNG clickable!
        #    Dùng ll_editor_container hoặc text_holder_container_layout
        trigger = d(resourceId="com.smile.gifmaker:id/ll_editor_container")
        if not trigger.exists:
            trigger = d(resourceId="com.smile.gifmaker:id/text_holder_container_layout")
        if not trigger.exists:
            trigger = d(resourceId=RID_COMMENT_TRG)  # fallback cũ
        if not trigger.exists:
            self._log("    ⚠ Không tìm thấy ô nhập comment")
            close = d(resourceId="com.smile.gifmaker:id/tabs_panel_close")
            if close.exists:
                close.click()
            else:
                d.press("back")
            self._sleep(0.5)
            return False
        trigger.click()
        self._sleep(1.5, 2.0)

        # 3. Nhập text vào editor (EditText)
        editor = d(resourceId=RID_COMMENT_EDT)
        if not editor.exists:
            editor = d(className="android.widget.EditText")
        if not editor.exists:
            self._log("    ⚠ Không tìm thấy editor")
            d.press("back")
            self._sleep(0.3)
            d.press("back")
            return False

        editor.click()
        self._sleep(0.5, 0.8)
        editor.clear_text()
        editor.set_text(text)
        self._sleep(0.8, 1.2)

        # 4. Gửi — finish_button clickable=False, dùng finish_button_wrapper
        send = d(resourceId="com.smile.gifmaker:id/finish_button_wrapper")
        if not send.exists:
            send = d(text="发送")
        if not send.exists:
            send = d(resourceId=RID_COMMENT_SEND)
        if send.exists:
            send.click()
        else:
            d.press("enter")
        self._sleep(1.5, 2.0)

        # 5. Verify comment sent
        editor_still = d(resourceId=RID_COMMENT_EDT)
        if editor_still.exists and editor_still.get_text() == text:
            self._log("    ⚠ Comment có thể chưa gửi được")
            d.press("back")
            self._sleep(0.3)
            d.press("back")
            return False

        # 6. Đóng panel — tabs_panel_close verified
        close = d(resourceId="com.smile.gifmaker:id/tabs_panel_close")
        if not close.exists:
            close = d(description="关闭评论区")
        if not close.exists:
            close = d(descriptionContains="关闭")
        if close.exists:
            close.click()
        else:
            d.press("back")
        self._sleep(0.5, 1.0)
        return True

    def _run_addfriend(self, d, device_idx: int) -> int:
        """Navigate Me → Add Friend, add some friends, then return to feed."""
        added = 0
        try:
            if self._stop_flag:
                return 0

            # Step 1: Tap "我" tab — verified: text="我" hoặc desc="我"
            me_tab = d(text="我")
            if not me_tab.exists:
                me_tab = d(description="我")
            if not me_tab.exists:
                me_tab = d(resourceId=RID_TAB_ME)
            if not me_tab.exists:
                me_tab = d(text="Me")
            if not me_tab.exists:
                # Detect login page — nếu chưa đăng nhập thì skip
                if d(text="请输入手机号").exists:
                    self._log("    ⚠ Tài khoản chưa đăng nhập! Bỏ qua AddFriend.")
                    return 0
                self._log("    ⚠ Không tìm thấy tab '我'")
                return 0
            me_tab.click()
            self._sleep(2.0, 3.0)
            if self._stop_flag:
                return added

            # Detect login page trước khi tìm Add Friend
            if d(text="请输入手机号").exists:
                self._log("    ⚠ Tài khoản chưa đăng nhập! Bỏ qua AddFriend.")
                self._return_to_feed(d)
                return 0

            # Step 2: Find "添加朋友" entry — verified: rid + desc="添加朋友"
            af_entry = d(resourceId=RID_ADDFRIEND_ENTRY)
            if not af_entry.exists:
                af_entry = d(description="添加朋友")
            if not af_entry.exists:
                af_entry = d(text="添加朋友")
            if not af_entry.exists:
                af_entry = d(resourceId="com.smile.gifmaker:id/profile_add_friends")
            if not af_entry.exists:
                af_entry = d(textContains="加朋友")
            if not af_entry.exists:
                af_entry = d(textContains="添加好友")

            if not af_entry.exists:
                self._log("    ⚠ Không tìm thấy nút 'Add Friend' trong Me")
                self._return_to_feed(d)
                return 0
            af_entry.click()
            self._sleep(2.5, 3.5)
            if self._stop_flag:
                self._return_to_feed(d)
                return added

            # Step 3: Add friends from suggestion list (configurable min-max)
            target_count = random.randint(self.settings.addfriend_min, self.settings.addfriend_max)
            for i in range(target_count):
                if self._stop_flag:
                    break
                add_btn = d(resourceId=RID_ADDFRIEND_BTN)
                if not add_btn.exists:
                    add_btn = d(textContains="加好友")
                if not add_btn.exists:
                    add_btn = d(text="关注")
                if not add_btn.exists:
                    add_btn = d(text="添加")
                if not add_btn.exists:
                    add_btn = d(text="Follow")
                if not add_btn.exists:
                    add_btn = d(text="Add")
                if add_btn.exists:
                    add_btn.click()
                    delay = random.uniform(self.settings.addfriend_delay_min, self.settings.addfriend_delay_max)
                    self._sleep(delay, delay)
                    added += 1
                    self.db.write_log(ActionLog(device_idx, "addfriend", True))
                    self.db.increment_stat(device_idx, "addfriend")
                else:
                    # Scroll down fto find more
                    w, h = d.info["displayWidth"], d.info["displayHeight"]
                    d.swipe(w // 2, int(h * 0.7), w // 2, int(h * 0.3), duration=0.4)
                    self._sleep(1.5, 2.5)

            # Step 4: Return to main feed
            self._return_to_feed(d)

        except Exception as e:
            self._log(f"    ❌ AddFriend lỗi: {e}")
            self._return_to_feed(d)

        return added

    def _return_to_feed(self, d) -> None:
        """Navigate back to the main video feed."""
        # Press back until we're at main feed
        for _ in range(3):
            d.press("back")
            self._sleep(0.5, 0.8)
        # Tap first tab — verified: desc="精选" hoặc desc="首页"
        home_tab = d(description="精选")
        if not home_tab.exists:
            home_tab = d(description="首页")
        if not home_tab.exists:
            home_tab = d(text="精选")
        if not home_tab.exists:
            home_tab = d(text="首页")
        if home_tab.exists:
            home_tab.click()
        self._sleep(1.5, 2.5)

    def _swipe_next(self, d) -> None:
        try:
            w, h = d.info.get("displayWidth", 1080), d.info.get("displayHeight", 1920)
            d.swipe(
                w // 2, int(h * 0.72),
                w // 2, int(h * 0.28),
                duration=random.uniform(0.35, 0.6),
            )
            self._sleep(self.settings.swipe_delay_min, self.settings.swipe_delay_max)
            self._log("    👆 Swipe next")
        except Exception as e:
            self._log(f"    ⚠ Lỗi swipe, đang thử fallback: {e}")
            self._sleep(1.0, 2.0)

    def _log(self, msg: str) -> None:
        log.info(msg)
        self.log_message.emit(msg)

    def _sleep(self, mn: float = 1.0, mx: float = 2.5) -> None:
        delay = random.uniform(mn, mx)
        slept = 0.0
        while slept < delay and not self._stop_flag:
            time.sleep(0.1)
            slept += 0.1
