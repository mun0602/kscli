"""MuMu Player adapter — wraps mumutool CLI calls.

Ported from kuaishou-bot/core/device_manager.py with full feature parity.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Optional

from kscli.models.schemas import VMInfo

log = logging.getLogger(__name__)

# ── Tool paths ────────────────────────────────────────────────
_MUMUTOOL_CANDIDATES = [
    "/Applications/MuMuPlayer Pro.app/Contents/MacOS/mumutool",
    "/Applications/MuMu Launcher.app/Contents/MacOS/MuMu Player Pro.app/Contents/MacOS/mumutool",
]

def _find_mumutool() -> str:
    for p in _MUMUTOOL_CANDIDATES:
        if os.path.isfile(p):
            return p
    return _MUMUTOOL_CANDIDATES[0]  # fallback

MUMUTOOL = _find_mumutool()

_ADB_CANDIDATES = [
    os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
    "/usr/local/bin/adb",
    "/opt/homebrew/bin/adb",
]

def _find_adb() -> str:
    """Find ADB binary, preferring Android SDK."""
    for p in _ADB_CANDIDATES:
        if os.path.isfile(p):
            return p
    # last resort: rely on PATH
    return "adb"

ADB = _find_adb()

def ensure_mumu_running() -> bool:
    """Ensure the MuMu Player Pro daemon is running. 
    If not running, launch the application."""
    res = subprocess.run(["pgrep", "-f", "MuMuPlayer Pro.app/Contents/MacOS/MuMuPlayer Pro"], capture_output=True)
    if res.returncode == 0:
        return True # Already running
    
    log.info("[MuMu] Daemon not found. Launching MuMu Player Pro app...")
    subprocess.run(["open", "-a", "MuMuPlayer Pro"], capture_output=True)
    
    # Wait for daemon to become ready (mumutool info all returns valid json)
    for _ in range(15):
        time.sleep(1)
        out = subprocess.run([MUMUTOOL, "info", "all"], capture_output=True, text=True)
        try:
            json.loads(out.stdout)
            log.info("[MuMu] Daemon is ready.")
            return True
        except Exception:
            pass
    return False

def _run(args: list[str], timeout: int = 30) -> dict:
    """Run mumutool and return parsed JSON result."""
    try:
        result = subprocess.run(
            [MUMUTOOL] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"errcode": -1, "raw": result.stdout.strip(), "stderr": result.stderr.strip()}
    except FileNotFoundError as e:
        import traceback
        log.error(f"[DEBUG MuMu] FileNotFoundError! args was: {[MUMUTOOL] + args}, cwd is: {os.getcwd()}, exception: {e}")
        return {"errcode": -2, "raw": f"mumutool not found. Is MuMu Player Pro installed? {e}"}
    except subprocess.TimeoutExpired:
        return {"errcode": -3, "raw": "Timeout – operation took too long."}
    except Exception as e:
        log.error(f"[DEBUG MuMu] Exception! {type(e)}: {e}")
        return {"errcode": -4, "raw": str(e)}


# ── Query ────────────────────────────────────────────────────
def list_vms() -> list[VMInfo]:
    """List all VMs with real info from mumutool."""
    res = _run(["info", "all"])
    if res.get("errcode", -1) != 0:
        log.error(f"[MuMu] Lỗi lấy info: {res}")
        return []
    results = res.get("return", {}).get("results", [])
    vms: list[VMInfo] = []
    for item in results:
        try:
            vms.append(VMInfo(
                index=item["index"],
                name=item.get("vmName", item.get("name", f"VM{item['index']}")),
                status="running" if item.get("state") == "running" else "stopped",
                adb_port=item.get("adb_port", 0),
            ))
        except (KeyError, TypeError):
            continue
    return vms


def get_port(index: int) -> int | None:
    """Get ADB port for a running VM."""
    for vm in list_vms():
        if vm.index == index and vm.status == "running":
            return vm.adb_port
    return None


# ── Lifecycle ─────────────────────────────────────────────────
def boot_vm(index: int, wait: bool = True, max_wait: int = 60) -> tuple[bool, str]:
    """Boot a VM and optionally wait until it's running."""
    log.info(f"[MuMu] Khởi động máy #{index}...")
    res = _run(["open", str(index)])
    if res.get("errcode", -1) != 0:
        return False, f"Lỗi khởi động: {res.get('raw', str(res))}"

    if not wait:
        return True, f"Đã gửi lệnh boot VM #{index}."

    for elapsed in range(0, max_wait, 3):
        time.sleep(3)
        for vm in list_vms():
            if vm.index == index and vm.status == "running":
                log.info(f"[MuMu] Máy #{index} đã sẵn sàng (sau {elapsed+3}s).")
                return True, f"VM #{index} đã boot thành công."
    return True, f"VM #{index} đã gửi boot (state chưa confirm sau {max_wait}s)."


def stop_vm(index: int, wait: bool = True, max_wait: int = 30) -> tuple[bool, str]:
    res = _run(["close", str(index)])
    ok = res.get("errcode", -1) == 0
    if not ok:
        return False, f"Lỗi: {res.get('raw', '')}"

    if not wait:
        return True, "Đã gửi lệnh tắt."

    for elapsed in range(0, max_wait, 3):
        time.sleep(3)
        running = False
        for vm in list_vms():
            if vm.index == index and vm.status == "running":
                running = True
                break
        if not running:
            return True, "Đã tắt thành công."
            
    return True, f"Đã gửi lệnh tắt, nhưng VM vẫn báo chạy sau {max_wait}s."


# ── Management ────────────────────────────────────────────────
def create_vm(count: int = 1) -> tuple[bool, str]:
    args = ["create", "--type", "phone"]
    if count >= 2:
        args += ["--count", str(count)]
    res = _run(args)
    ok = res.get("errcode", -1) == 0
    return ok, f"Đã tạo {count} VM." if ok else f"Lỗi: {res.get('raw', '')}"


def clone_vm(src_index: int) -> tuple[bool, str]:
    res = _run(["clone", str(src_index)])
    ok = res.get("errcode", -1) == 0
    return ok, f"Đã clone VM #{src_index}." if ok else f"Lỗi: {res.get('raw', '')}"


def delete_vm(index: int) -> tuple[bool, str]:
    res = _run(["delete", str(index)])
    ok = res.get("errcode", -1) == 0
    return ok, f"Đã xoá VM #{index}." if ok else f"Lỗi: {res.get('raw', '')}"


def rename_vm(index: int, name: str) -> tuple[bool, str]:
    setting = json.dumps({"vmName": name})
    res = _run(["config", str(index), "--setting", setting])
    ok = res.get("errcode", -1) == 0
    return ok, f"Đã đổi tên VM #{index} → '{name}'." if ok else f"Lỗi: {res.get('raw', '')}"


def batch_rename(prefix: str) -> tuple[bool, str]:
    vms = list_vms()
    if not vms:
        return False, "Không tìm thấy VM nào."
    errors = []
    for vm in vms:
        new_name = f"{prefix} {vm.index + 1}"
        ok, msg = rename_vm(vm.index, new_name)
        if not ok:
            errors.append(f"#{vm.index}: {msg}")
    if errors:
        return False, "\n".join(errors)
    return True, f"Đã đổi tên {len(vms)} VM với prefix '{prefix}'."


# ── ADB / ATX ─────────────────────────────────────────────────
def adb_connect(port: int) -> bool:
    """Connect ADB to a specific port."""
    try:
        subprocess.run(
            [ADB, "connect", f"127.0.0.1:{port}"],
            capture_output=True, timeout=5,
        )
        return True
    except Exception:
        return False


def set_language(index: int, lang: str = "zh-CN") -> tuple[bool, str]:
    """
    Ép ngôn ngữ cho Android VM qua ADB.
    """
    port = get_port(index)
    if not port:
        return False, f"Không tìm thấy port cho VM #{index}."

    serial = f"127.0.0.1:{port}"
    adb_connect(port)

    l_parts = lang.split('-')
    lang_code = l_parts[0]
    country_code = l_parts[1] if len(l_parts) > 1 else ""

    # Lệnh hệ thống Android
    cmds = [
        f"settings put global system_locales {lang}",
        f"setprop persist.sys.locale {lang}",
        f"setprop persist.sys.language {lang_code}",
        f"setprop persist.sys.country {country_code}"
    ]

    try:
        import subprocess
        import time
        # Root the adb connection to set persist properties
        subprocess.run([ADB, "-s", serial, "root"], capture_output=True)
        time.sleep(2)
        adb_connect(port)
        
        for cmd in cmds:
            subprocess.run(f"{ADB} -s {serial} shell \"{cmd}\" ", shell=True, capture_output=True)
        
        # Stop and start the VM to apply the locale change
        log.info(f"Restarting VM #{index} to apply locale {lang}...")
        stop_vm(index)
        time.sleep(3)
        boot_vm(index, wait=False)

        return True, f"Đã áp dụng ngôn ngữ {lang}. Đang khởi động lại VM #{index}..."
    except Exception as e:
        return False, f"Lỗi khi đổi ngôn ngữ: {str(e)}"


def check_atx(index: int) -> dict:
    """Check if ATX is installed on a VM."""
    port = get_port(index)
    if not port:
        return {"index": index, "has_atx": False, "error": "VM not running"}
    serial = f"127.0.0.1:{port}"
    try:
        adb_connect(port)
        result = subprocess.run(
            [ADB, "-s", serial, "shell", "pm", "list", "packages", "com.github.uiautomator"],
            capture_output=True, text=True, timeout=10,
        )
        has = "com.github.uiautomator" in result.stdout
        return {"index": index, "has_atx": has, "serial": serial}
    except Exception as e:
        return {"index": index, "has_atx": False, "error": str(e)}


def install_atx(index: int) -> tuple[bool, str]:
    """Install ATX (uiautomator2 agent) lên VM qua CLI init."""
    port = get_port(index)
    if not port:
        return False, "VM chưa chạy, boot trước."
    serial = f"127.0.0.1:{port}"
    try:
        # Step 1: Kết nối ADB
        adb_connect(port)
        time.sleep(1)

        # Step 2: Push u2.jar lên device qua CLI
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "uiautomator2", "init", "--serial", serial],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip()
            log.error(f"[ATX] ❌ CLI init thất bại #{index}: {err}")
            return False, f"CLI init thất bại: {err[:200]}"

        # Step 3: Verify bằng cách connect u2
        import uiautomator2 as u2
        d = u2.connect(serial)
        info = d.info
        name = info.get("productName", "Unknown")
        log.info(f"[ATX] ✅ Cài ATX thành công #{index} ({serial}) — {name}")
        return True, f"ATX cài đặt thành công trên VM #{index} ({name})."
    except Exception as e:
        log.error(f"[ATX] ❌ Lỗi cài ATX #{index}: {e}")
        return False, str(e)


def install_atx_all() -> list[dict]:
    """Install ATX on all running VMs that don't have it yet."""
    vms = list_vms()
    running = [vm for vm in vms if vm.status == "running"]
    results = []
    for vm in running:
        info = check_atx(vm.index)
        if info.get("has_atx"):
            results.append({"index": vm.index, "ok": True, "status": "already_installed"})
        else:
            ok, msg = install_atx(vm.index)
            results.append({"index": vm.index, "ok": ok, "status": "installed" if ok else "failed", "msg": msg})
    return results


def mute_vm(index: int) -> bool:
    """Mute a running VM via ADB."""
    port = get_port(index)
    if not port:
        return False
    serial = f"127.0.0.1:{port}"
    try:
        subprocess.run(
            [ADB, "-s", serial, "shell", "media", "volume", "--set", "0", "--stream", "3"],
            capture_output=True, timeout=5,
        )
        return True
    except Exception:
        return False


# ── APK Management ────────────────────────────────────────────
def check_package(index: int, package: str = "com.smile.gifmaker") -> bool:
    """Check if a package is installed on a running VM."""
    port = get_port(index)
    if not port:
        return False
    serial = f"127.0.0.1:{port}"
    try:
        adb_connect(port)
        result = subprocess.run(
            [ADB, "-s", serial, "shell", "pm", "list", "packages", package],
            capture_output=True, text=True, timeout=10,
        )
        return package in result.stdout
    except Exception:
        return False


def install_apk(index: int, apk_path: str) -> tuple[bool, str]:
    """Install APK on a running VM via ADB."""
    port = get_port(index)
    if not port:
        return False, f"VM #{index} chưa chạy, boot trước."
    serial = f"127.0.0.1:{port}"
    if not os.path.isfile(apk_path):
        return False, f"Không tìm thấy file: {apk_path}"
    try:
        adb_connect(port)
        log.info(f"[APK] Đang cài {os.path.basename(apk_path)} lên VM #{index}...")

        # Try install with -r (replace), if downgrade error, retry with -r -d
        result = subprocess.run(
            [ADB, "-s", serial, "install", "-r", apk_path],
            capture_output=True, text=True, timeout=120,
        )
        if "Success" in result.stdout:
            log.info(f"[APK] ✅ Cài thành công trên VM #{index}")
            return True, f"Cài APK thành công trên VM #{index}."

        combined = result.stdout + result.stderr
        if "VERSION_DOWNGRADE" in combined:
            log.info(f"[APK] Phiên bản cũ hơn, thử cài với -d (allow downgrade)...")
            result = subprocess.run(
                [ADB, "-s", serial, "install", "-r", "-d", apk_path],
                capture_output=True, text=True, timeout=120,
            )
            if "Success" in result.stdout:
                log.info(f"[APK] ✅ Cài thành công (downgrade) trên VM #{index}")
                return True, f"Cài APK thành công (downgrade) trên VM #{index}."

        err = result.stdout.strip() + " " + result.stderr.strip()
        log.error(f"[APK] ❌ Lỗi cài APK: {err}")
        return False, f"Lỗi cài APK: {err[:200]}"
    except subprocess.TimeoutExpired:
        return False, "Timeout — cài APK quá lâu."
    except Exception as e:
        return False, str(e)


# ── APK Download & Batch Install ─────────────────────────────
DEFAULT_APK_URL = "https://dtdp.99a.fun/wp-content/apk/ks13.10.apk"
APK_CACHE_DIR = os.path.join(os.path.expanduser("~/.kuaishou_desktop_qt"), "apk_cache")


def download_apk(url: str | None = None, force: bool = False) -> tuple[bool, str]:
    """Download Kuaishou APK from URL. Returns (ok, local_path_or_error).

    Uses DEFAULT_APK_URL if no URL provided.
    Caches downloaded APK to avoid re-downloading.
    """
    import urllib.request
    import hashlib

    url = url or DEFAULT_APK_URL
    os.makedirs(APK_CACHE_DIR, exist_ok=True)

    # Cache key from URL filename
    filename = url.rsplit("/", 1)[-1] if "/" in url else "kuaishou.apk"
    if not filename.endswith(".apk"):
        filename += ".apk"
    local_path = os.path.join(APK_CACHE_DIR, filename)

    if os.path.isfile(local_path) and not force:
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        log.info(f"[APK] Cache hit: {filename} ({size_mb:.1f}MB)")
        return True, local_path

    log.info(f"[APK] Đang tải: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KuaishouBot/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 256  # 256KB chunks

            with open(local_path + ".tmp", "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        if pct % 10 == 0:
                            log.info(f"[APK] Tải: {pct}% ({downloaded // (1024*1024)}MB/{total // (1024*1024)}MB)")

        os.rename(local_path + ".tmp", local_path)
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        log.info(f"[APK] ✅ Tải xong: {filename} ({size_mb:.1f}MB)")
        return True, local_path

    except Exception as e:
        # Cleanup partial download
        for f in [local_path + ".tmp", local_path]:
            if os.path.isfile(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        log.error(f"[APK] ❌ Lỗi tải: {e}")
        return False, str(e)


def install_apk_all(
    apk_path: str | None = None,
    url: str | None = None,
    vm_indices: list[int] | None = None,
    auto_boot: bool = True,
    package: str = "com.smile.gifmaker",
    skip_installed: bool = True,
) -> list[dict]:
    """Download APK (if needed) and install on all/specified VMs.

    Args:
        apk_path: Local APK path. If None, downloads from url.
        url: APK download URL. Defaults to DEFAULT_APK_URL.
        vm_indices: List of VM indices to install on. None = all VMs.
        auto_boot: Auto-boot stopped VMs before installing.
        package: Package name to check if already installed.
        skip_installed: Skip VMs that already have the package.

    Returns:
        List of {index, ok, status, message} dicts.
    """
    ensure_mumu_running()

    # Step 1: Resolve APK path
    if not apk_path:
        ok, result = download_apk(url)
        if not ok:
            return [{"index": -1, "ok": False, "status": "download_failed", "message": result}]
        apk_path = result

    if not os.path.isfile(apk_path):
        return [{"index": -1, "ok": False, "status": "file_not_found", "message": f"APK not found: {apk_path}"}]

    # Step 2: Resolve target VMs
    all_vms = list_vms()
    if vm_indices is not None:
        targets = [vm for vm in all_vms if vm.index in vm_indices]
    else:
        targets = all_vms

    if not targets:
        return [{"index": -1, "ok": False, "status": "no_vms", "message": "Không tìm thấy VM nào."}]

    log.info(f"[APK] Cài hàng loạt: {os.path.basename(apk_path)} → {len(targets)} VM")
    results = []

    for vm in targets:
        idx = vm.index
        log.info(f"[APK] ── VM #{idx} ({vm.name}) ──")

        # Boot if needed
        if vm.status != "running":
            if not auto_boot:
                results.append({"index": idx, "ok": False, "status": "stopped", "message": f"VM #{idx} đang tắt, bỏ qua."})
                continue
            log.info(f"[APK] Boot VM #{idx}...")
            ok, msg = boot_vm(idx, wait=True)
            if not ok:
                results.append({"index": idx, "ok": False, "status": "boot_failed", "message": msg})
                continue

        # Check if already installed
        if skip_installed and check_package(idx, package):
            log.info(f"[APK] ⏭ VM #{idx}: {package} đã cài rồi, bỏ qua.")
            results.append({"index": idx, "ok": True, "status": "already_installed", "message": f"{package} đã có trên VM #{idx}."})
            continue

        # Install ATX first (needed for bot to work)
        atx_info = check_atx(idx)
        if not atx_info.get("has_atx"):
            log.info(f"[APK] Cài ATX trên VM #{idx}...")
            install_atx(idx)

        # Install APK
        ok, msg = install_apk(idx, apk_path)
        results.append({
            "index": idx,
            "ok": ok,
            "status": "installed" if ok else "failed",
            "message": msg,
        })

        # Small delay between VMs
        if ok:
            time.sleep(1)

    # Summary
    installed = sum(1 for r in results if r["status"] == "installed")
    skipped = sum(1 for r in results if r["status"] == "already_installed")
    failed = sum(1 for r in results if not r["ok"])
    log.info(f"[APK] 📊 Tổng kết: {installed} cài mới, {skipped} đã có, {failed} lỗi")

    return results

