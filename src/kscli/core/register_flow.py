"""
Kuaishou Registration Flow — tích hợp 5sim.net
============================================================
Flow:
  1. Mua số điện thoại từ 5sim (england virtual59 - rate 52%)
  2. Mở Kuaishou trên VM
  3. Nhập số điện thoại lên màn hình đăng ký
  4. Chờ SMS về từ 5sim (tối đa 3 phút)
  5. Nhập OTP vào Kuaishou
  6. Hoàn tất đăng ký

Dùng: dk dangnhap --vm 0
"""

from __future__ import annotations

import logging
import re
import time

import requests
import uiautomator2 as u2

from kscli.core.mumu_adapter import adb_connect, ensure_mumu_running, get_port

log = logging.getLogger(__name__)

FIVE_SIM_TOKEN = ""  # Set via env or config
FIVE_SIM_BASE  = "https://5sim.net/v1"
KS_PACKAGE     = "com.smile.gifmaker"

# Số tốt nhất — england virtual59 (rate ~52%)
DEFAULT_COUNTRY  = "england"
DEFAULT_OPERATOR = "virtual59"
DEFAULT_PRODUCT  = "kwai"


# ── 5sim helpers ────────────────────────────────────────────

class FiveSimClient:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def _get(self, path: str) -> dict:
        resp = requests.get(f"{FIVE_SIM_BASE}{path}", headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def balance(self) -> float:
        return self._get("/user/profile").get("balance", 0)

    def buy_number(
        self,
        country: str = DEFAULT_COUNTRY,
        operator: str = DEFAULT_OPERATOR,
        product: str = DEFAULT_PRODUCT,
    ) -> dict:
        """Mua số mới. Trả về order dict có {id, phone}."""
        data = self._get(f"/user/buy/activation/{country}/{operator}/{product}")
        return data  # {id, phone, status, ...}

    def check_order(self, order_id: int) -> dict:
        return self._get(f"/user/check/{order_id}")

    def finish_order(self, order_id: int) -> dict:
        return self._get(f"/user/finish/{order_id}")

    def cancel_order(self, order_id: int) -> dict:
        return self._get(f"/user/cancel/{order_id}")

    def wait_sms(self, order_id: int, timeout: int = 180) -> str | None:
        """Poll mỗi 5s, trả về code OTP hoặc None nếu timeout."""
        deadline = time.time() + timeout
        log.info(f"[5SIM] Chờ SMS order #{order_id} (max {timeout}s)...")
        while time.time() < deadline:
            try:
                data = self.check_order(order_id)
                status = data.get("status", "")
                sms_list = data.get("sms") or []
                if sms_list:
                    raw = sms_list[0].get("text", "")
                    # Extract 4-6 digit code
                    m = re.search(r"\b(\d{4,6})\b", raw)
                    if m:
                        code = m.group(1)
                        log.info(f"[5SIM] ✅ OTP: {code}")
                        return code
                if status in ("CANCELED", "EXPIRED", "TIMEOUT"):
                    log.error(f"[5SIM] Order {status}.")
                    return None
            except Exception as e:
                log.warning(f"[5SIM] check_order lỗi: {e}")
            time.sleep(5)
        log.error("[5SIM] Timeout chờ SMS.")
        return None


# ── UI helpers on device ──────────────────────────────────────

def _dismiss_popups(d: u2.Device, quick: bool = False) -> None:
    """Đóng popup cơ bản."""
    candidates = [
        d(text="同意并继续"),   # Agree TOS
        d(text="同意"),          # Accept
        d(text="确定"),          # OK
        d(text="稍后"),          # Later
        d(text="关闭"),          # Close
        d(text="跳过"),          # Skip
        d(textContains="允许"),  # Allow
    ]
    for e in candidates:
        if e.exists(timeout=0.5 if quick else 1.5):
            e.click()
            time.sleep(0.5)


def _wait_text(d: u2.Device, text: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if d(text=text).exists or d(textContains=text).exists:
            return True
        time.sleep(1)
    return False


def _get_phone_simple(phone: str) -> str:
    """Kuaishou thường chỉ cần số không prefix. England: +44xxxxxxxxxx → 0xxxxxxxxxx."""
    phone = phone.strip()
    if phone.startswith("+44"):
        return "0" + phone[3:]
    if phone.startswith("44"):
        return "0" + phone[2:]
    return phone


# ── Main registration flow ────────────────────────────────────

def register_account(
    vm_index: int,
    five_sim_token: str,
    country: str = DEFAULT_COUNTRY,
    operator: str = DEFAULT_OPERATOR,
    product: str = DEFAULT_PRODUCT,
) -> dict:
    """
    Đăng ký tài khoản Kuaishou trên VM qua 5sim.

    Returns:
        {"ok": bool, "phone": str, "message": str}
    """
    ensure_mumu_running()
    port = get_port(vm_index)
    if not port:
        return {"ok": False, "phone": "", "message": f"VM #{vm_index} chưa chạy."}

    adb_connect(port)
    serial = f"127.0.0.1:{port}"
    d = u2.connect(serial)

    five = FiveSimClient(five_sim_token)

    # 1. Check balance
    bal = five.balance()
    log.info(f"[REG] 5sim balance: ${bal:.4f}")
    if bal < 0.10:
        return {"ok": False, "phone": "", "message": f"Số dư 5sim không đủ: ${bal:.4f}"}

    # 2. Mua số
    log.info(f"[REG] Mua số {country}/{operator}/{product}...")
    try:
        order = five.buy_number(country, operator, product)
    except Exception as e:
        return {"ok": False, "phone": "", "message": f"Mua số thất bại: {e}"}

    order_id = order["id"]
    raw_phone = order.get("phone", "")
    log.info(f"[REG] Đơn #{order_id} — SĐT: {raw_phone}")

    phone_for_ks = _get_phone_simple(raw_phone)
    log.info(f"[REG] Nhập vào Kuaishou: {phone_for_ks}")

    try:
        # 3. Mở Kuaishou, chờ về login
        log.info("[REG] Mở Kuaishou...")
        d.app_start(KS_PACKAGE, stop=True)
        time.sleep(5)
        _dismiss_popups(d)

        # 4. Tìm nút đăng ký hoặc đăng nhập bằng SĐT
        # Kuaishou thường có "手机号注册" hoặc "手机号码登录" hoặc "Log In", "Me" bản Quốc tế
        reg_btn = None
        for txt in ["手机号注册", "手机号码登录", "账号登录", "登录/注册", "Login", "Log In", "Sign up", "Me", "我"]:
            el = d(text=txt)
            if not el.exists:
                el = d(textContains=txt)
            if not el.exists:
                el = d(description=txt) # Gỡ lỗi "Me" thường ở description
            if el.exists(timeout=2):
                reg_btn = el
                break

        if reg_btn is None:
            five.cancel_order(order_id)
            return {"ok": False, "phone": raw_phone, "message": "Không tìm thấy nút đăng nhập/đăng ký."}

        reg_btn.click()
        time.sleep(2)
        _dismiss_popups(d, quick=True)

        # 5. Nhập SĐT
        phone_input = d(focused=True)
        attempts = 0
        for rid in [
            "com.smile.gifmaker:id/et_phone_number",
            "com.smile.gifmaker:id/phone_edit_text",
            "com.smile.gifmaker:id/input_phone",
        ]:
            el = d(resourceId=rid)
            if el.exists(timeout=2):
                phone_input = el
                break
            attempts += 1

        phone_input.click()
        time.sleep(0.5)
        d.clear_text()
        phone_input.send_keys(phone_for_ks)
        time.sleep(1)
        log.info(f"[REG] Đã nhập SĐT: {phone_for_ks}")

        # 6. Bấm nút gửi OTP
        for send_txt in ["获取验证码", "发送验证码", "Send", "Next", "下一步"]:
            btn = d(text=send_txt)
            if btn.exists(timeout=1):
                btn.click()
                break
        time.sleep(2)
        _dismiss_popups(d, quick=True)

        # 7. Chờ SMS từ 5sim
        code = five.wait_sms(order_id, timeout=180)
        if not code:
            five.cancel_order(order_id)
            return {"ok": False, "phone": raw_phone, "message": "Không nhận được OTP từ 5sim."}

        # 8. Nhập OTP
        otp_input = None
        for rid in [
            "com.smile.gifmaker:id/et_verify_code",
            "com.smile.gifmaker:id/verify_code_input",
            "com.smile.gifmaker:id/input_code",
        ]:
            el = d(resourceId=rid)
            if el.exists(timeout=3):
                otp_input = el
                break

        if otp_input is None:
            # Fallback: tìm input focused
            otp_input = d(focused=True)

        otp_input.click()
        time.sleep(0.5)
        d.clear_text()
        otp_input.send_keys(code)
        time.sleep(1)
        log.info(f"[REG] Đã nhập OTP: {code}")

        # 9. Submit
        for confirm_txt in ["登录", "确认", "Confirm", "Submit", "完成"]:
            btn = d(text=confirm_txt)
            if btn.exists(timeout=1):
                btn.click()
                break
        time.sleep(3)
        _dismiss_popups(d)

        # 10. Xác nhận đăng nhập thành công — tìm tab Home
        success = False
        for tab_txt in ["精选", "首页", "Home", "发现"]:
            if d(description=tab_txt).exists(timeout=5) or d(text=tab_txt).exists(timeout=1):
                success = True
                break

        five.finish_order(order_id)

        if success:
            log.info(f"[REG] ✅ Đăng ký thành công: {raw_phone}")
            return {"ok": True, "phone": raw_phone, "message": f"Đăng ký thành công: {raw_phone}"}
        else:
            return {"ok": False, "phone": raw_phone, "message": "OTP đã nhập nhưng chưa xác nhận vào được feed."}

    except Exception as e:
        log.exception("[REG] Lỗi không mong đợi")
        try:
            five.cancel_order(order_id)
        except Exception:
            pass
        return {"ok": False, "phone": raw_phone, "message": f"Lỗi: {e}"}
