from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from dataclasses import asdict
from typing import Any

from kscli.core.cli_runner import run_cli_farm_session
from kscli.core import mumu_adapter as mumu
from kscli.models.database import Database

log = logging.getLogger(__name__)


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _emit(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
        return 0 if payload.get("ok", True) else 1

    if "message" in payload:
        print(payload["message"])
    elif "data" in payload:
        print(payload["data"])
    else:
        print(payload)
    return 0 if payload.get("ok", True) else 1


def _vm_list_payload(vms: list[Any]) -> list[dict[str, Any]]:
    return [asdict(vm) if hasattr(vm, "__dataclass_fields__") else vm.__dict__ for vm in vms]


def _add_vm_target_args(parser: argparse.ArgumentParser, *, require_target: bool = False) -> None:
    parser.add_argument("--vms", help="Danh sách VM, ví dụ 0,1,2")
    parser.add_argument("--vm", type=int, help="VM đơn lẻ")
    if require_target:
        parser.add_argument("--bat-neu-tat", action="store_true", help="Tự boot VM nếu đang tắt")


def _resolve_vm_indices(args, settings, *, default_from_settings: bool = True) -> list[int]:
    vm_indices = [args.vm] if getattr(args, "vm", None) is not None else _parse_vm_indices(getattr(args, "vms", None))
    if vm_indices is None and default_from_settings:
        all_vms = mumu.list_vms()
        vm_indices = [vm.index for vm in all_vms[: settings.machine_count]]
    return vm_indices or []


def _maybe_boot_targets(vm_indices: list[int], *, auto_boot: bool) -> None:
    if not auto_boot:
        return
    current = {vm.index: vm for vm in mumu.list_vms()}
    for vm_index in vm_indices:
        vm = current.get(vm_index)
        if vm and vm.status != "running":
            mumu.boot_vm(vm_index, wait=True)


def _run_session_with_settings(args, db: Database, settings, comments: list[str], *, video_count: int | None = None) -> int:
    mumu.ensure_mumu_running()
    vm_indices = _resolve_vm_indices(args, settings)
    if not vm_indices:
        return _emit({"ok": False, "message": "No VM indices available for session run"}, args.json)

    if getattr(args, "seed", None) is not None:
        random.seed(args.seed)

    if getattr(args, "bat_neu_tat", False):
        _maybe_boot_targets(vm_indices, auto_boot=True)

    if video_count is None:
        requested_videos = getattr(args, "videos", None)
        video_count = requested_videos or random.randint(settings.video_min, settings.video_max)

    result = run_cli_farm_session(
        settings=settings,
        vm_indices=vm_indices,
        video_count=video_count,
        comments=comments,
        db=db,
    )
    return _emit({"ok": result["completed"], "data": result}, args.json)


def build_parser() -> argparse.ArgumentParser:
    output_parser = argparse.ArgumentParser(add_help=False)
    output_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    parser = argparse.ArgumentParser(
        prog="python main.py --cli",
        description="AI-friendly CLI for Kuaishou Desktop backend control.",
        parents=[output_parser],
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ensure-mumu", help="Ensure MuMu Player daemon is running", parents=[output_parser])
    subparsers.add_parser("list-vms", aliases=["ds", "danhsach", "list", "fleet"], help="List MuMu virtual machines", parents=[output_parser])
    subparsers.add_parser("stats", aliases=["thongke"], help="Show persisted today stats", parents=[output_parser])
    subparsers.add_parser("load-settings", aliases=["caidat", "settings"], help="Show persisted bot settings", parents=[output_parser])
    comments_parser = subparsers.add_parser("load-comments", help="Show persisted comments", parents=[output_parser])
    comments_parser.add_argument("--limit", type=int, default=0, help="Optional number of comments to return")

    boot_parser = subparsers.add_parser("boot", aliases=["bat", "mo"], help="Boot a VM", parents=[output_parser])
    boot_parser.add_argument("--vm", type=int, required=True)
    boot_parser.add_argument("--no-wait", action="store_true")

    stop_parser = subparsers.add_parser("stop", aliases=["tat", "dong"], help="Stop a VM", parents=[output_parser])
    stop_parser.add_argument("--vm", type=int, required=True)
    stop_parser.add_argument("--no-wait", action="store_true")

    create_parser = subparsers.add_parser("create", help="Create VM(s)", parents=[output_parser])
    create_parser.add_argument("--count", type=int, default=1)

    clone_parser = subparsers.add_parser("clone", help="Clone a VM", parents=[output_parser])
    clone_parser.add_argument("--vm", type=int, required=True)

    delete_parser = subparsers.add_parser("delete", help="Delete a VM", parents=[output_parser])
    delete_parser.add_argument("--vm", type=int, required=True)

    rename_parser = subparsers.add_parser("rename", help="Rename a VM", parents=[output_parser])
    rename_parser.add_argument("--vm", type=int, required=True)
    rename_parser.add_argument("--name", required=True)

    batch_rename_parser = subparsers.add_parser("batch-rename", help="Batch rename VMs", parents=[output_parser])
    batch_rename_parser.add_argument("--prefix", required=True)

    lang_parser = subparsers.add_parser("set-language", help="Set Android language on a VM", parents=[output_parser])
    lang_parser.add_argument("--vm", type=int, required=True)
    lang_parser.add_argument("--lang", default="zh-CN")

    atx_parser = subparsers.add_parser("install-atx", help="Install ATX on a running VM", parents=[output_parser])
    atx_parser.add_argument("--vm", type=int, required=True)

    add_friends_parser = subparsers.add_parser("add-friends", help="Run add-friend flow on one or more VMs", parents=[output_parser])
    _add_vm_target_args(add_friends_parser)
    add_friends_parser.add_argument("--count", type=int, help="Fixed add-friend target count per VM")
    add_friends_parser.add_argument("--seed", type=int, help="Optional RNG seed")

    farm_parser = subparsers.add_parser("run-session", help="Run one farm session from CLI", parents=[output_parser])
    _add_vm_target_args(farm_parser)
    farm_parser.add_argument("--videos", type=int, help="Fixed video count for this session")
    farm_parser.add_argument("--seed", type=int, help="Optional RNG seed for reproducible selection")
    farm_parser.add_argument("--comment", action="append", default=[], help="Inline comment. Can be repeated")

    ketban_parser = subparsers.add_parser("ketban", aliases=["kếtbạn", "them-ban", "themban"], help="Preset tiếng Việt: chỉ chạy flow kết bạn", parents=[output_parser])
    _add_vm_target_args(ketban_parser, require_target=True)
    ketban_parser.add_argument("--count", type=int, help="Số bạn muốn thêm mỗi VM")
    ketban_parser.add_argument("--seed", type=int, help="Seed random")

    tuongtac_parser = subparsers.add_parser("tuongtac", aliases=["tuong-tac", "interact"], help="Preset tiếng Việt: xem video và tương tác", parents=[output_parser])
    _add_vm_target_args(tuongtac_parser, require_target=True)
    tuongtac_parser.add_argument("--videos", type=int, help="Số video cố định")
    tuongtac_parser.add_argument("--seed", type=int, help="Seed random")
    tuongtac_parser.add_argument("--comment", action="append", default=[], help="Comment bổ sung. Có thể lặp lại")

    nuoinick_parser = subparsers.add_parser("nuoinick", aliases=["nuoi-nick", "farmnick"], help="Preset tiếng Việt: nuôi nick nhẹ, chỉ xem video", parents=[output_parser])
    _add_vm_target_args(nuoinick_parser, require_target=True)
    nuoinick_parser.add_argument("--videos", type=int, help="Số video cố định")
    nuoinick_parser.add_argument("--seed", type=int, help="Seed random")

    install_app_parser = subparsers.add_parser("install-app", aliases=["caiapp", "installapp"], help="Install APK lên VM", parents=[output_parser])
    install_app_parser.add_argument("--vm", type=int, required=True)
    install_app_parser.add_argument("--apk", required=True, help="Đường dẫn file APK")

    check_app_parser = subparsers.add_parser("check-app", aliases=["kiemtra", "checkapp"], help="Kiểm tra app đã cài trên VM", parents=[output_parser])
    check_app_parser.add_argument("--vm", type=int, required=True)
    check_app_parser.add_argument("--package", default="com.smile.gifmaker", help="Package name")

    install_all_parser = subparsers.add_parser("install-all", aliases=["caitatca", "installall", "setup"], help="Tải APK + cài hàng loạt lên tất cả VM", parents=[output_parser])
    install_all_parser.add_argument("--url", default=None, help=f"URL tải APK (mặc định: server)")
    install_all_parser.add_argument("--apk", default=None, help="Dùng file APK local thay vì tải")
    install_all_parser.add_argument("--vms", default=None, help="Chỉ cài lên các VM này, ví dụ 0,1,2")
    install_all_parser.add_argument("--force", action="store_true", help="Tải lại APK + cài đè lên VM đã có")

    dl_parser = subparsers.add_parser("download-apk", aliases=["taiapk", "downloadapk"], help="Chỉ tải APK về máy (không cài)", parents=[output_parser])
    dl_parser.add_argument("--url", default=None, help="URL tải APK")
    dl_parser.add_argument("--force", action="store_true", help="Tải lại dù đã có cache")

    subparsers.add_parser("apk-url", aliases=["linkapp", "apkurl"], help="Hiện URL tải APK mặc định", parents=[output_parser])

    login_parser = subparsers.add_parser("dangnhap", aliases=["login", "signin"], help="Auto-login vào Kuaishou dùng 5SIM", parents=[output_parser])
    login_parser.add_argument("--vm", type=int, required=True, help="VM cần login")
    login_parser.add_argument("--phone", default=None, help="SĐT cụ thể (nếu không dùng 5SIM)")
    login_parser.add_argument("--otp", default=None, help="OTP code (nếu đã có)")
    login_parser.add_argument("--password", default=None, help="Password thay vì OTP")
    login_parser.add_argument("--use-5sim", action="store_true", default=True, help="Dùng 5SIM để lấy SĐT mới (mặc định)")
    login_parser.add_argument("--no-wait", action="store_true", help="Không chờ app")

    return parser


def _parse_vm_indices(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    values = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    return values or None


def run_cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    
    # Normalize aliases to canonical commands
    aliases_map = {
        "ds": "list-vms", "danhsach": "list-vms", "list": "list-vms", "fleet": "list-vms",
        "thongke": "stats",
        "caidat": "load-settings", "settings": "load-settings",
        "bat": "boot", "mo": "boot",
        "tat": "stop", "dong": "stop",
        "kếtbạn": "ketban", "them-ban": "ketban", "themban": "ketban",
        "tuong-tac": "tuongtac", "interact": "tuongtac",
        "nuoi-nick": "nuoinick", "farmnick": "nuoinick",
        "caiapp": "install-app", "installapp": "install-app",
        "kiemtra": "check-app", "checkapp": "check-app",
        "caitatca": "install-all", "installall": "install-all", "setup": "install-all",
        "taiapk": "download-apk", "downloadapk": "download-apk",
        "linkapp": "apk-url", "apkurl": "apk-url",
        "login": "dangnhap", "signin": "dangnhap",
        "addfriend": "ketban", "add-friends": "ketban"
    }
    if args.command in aliases_map:
        args.command = aliases_map[args.command]
        
    db = Database()

    try:
        if args.command == "ensure-mumu":
            ok = mumu.ensure_mumu_running()
            return _emit({"ok": ok, "message": "MuMu is running" if ok else "MuMu failed to start"}, args.json)

        if args.command == "list-vms":
            mumu.ensure_mumu_running()
            vms = mumu.list_vms()
            return _emit({"ok": True, "data": _vm_list_payload(vms)}, args.json)

        if args.command == "stats":
            return _emit({"ok": True, "data": db.get_today_stats()}, args.json)

        if args.command == "load-settings":
            return _emit({"ok": True, "data": asdict(db.load_settings())}, args.json)

        if args.command == "load-comments":
            comments = db.load_comments()
            if args.limit and args.limit > 0:
                comments = comments[:args.limit]
            return _emit({"ok": True, "data": comments}, args.json)

        if args.command == "boot":
            ok, message = mumu.boot_vm(args.vm, wait=not args.no_wait)
            return _emit({"ok": ok, "message": message, "vm": args.vm}, args.json)

        if args.command == "stop":
            ok, message = mumu.stop_vm(args.vm, wait=not args.no_wait)
            return _emit({"ok": ok, "message": message, "vm": args.vm}, args.json)

        if args.command == "create":
            ok, message = mumu.create_vm(args.count)
            return _emit({"ok": ok, "message": message, "count": args.count}, args.json)

        if args.command == "clone":
            ok, message = mumu.clone_vm(args.vm)
            return _emit({"ok": ok, "message": message, "vm": args.vm}, args.json)

        if args.command == "delete":
            ok, message = mumu.delete_vm(args.vm)
            return _emit({"ok": ok, "message": message, "vm": args.vm}, args.json)

        if args.command == "rename":
            ok, message = mumu.rename_vm(args.vm, args.name)
            return _emit({"ok": ok, "message": message, "vm": args.vm, "name": args.name}, args.json)

        if args.command == "batch-rename":
            ok, message = mumu.batch_rename(args.prefix)
            return _emit({"ok": ok, "message": message, "prefix": args.prefix}, args.json)

        if args.command == "set-language":
            ok, message = mumu.set_language(args.vm, args.lang)
            return _emit({"ok": ok, "message": message, "vm": args.vm, "lang": args.lang}, args.json)

        if args.command == "install-atx":
            ok, message = mumu.install_atx(args.vm)
            return _emit({"ok": ok, "message": message, "vm": args.vm}, args.json)

        if args.command == "add-friends":
            mumu.ensure_mumu_running()
            settings = db.load_settings()
            settings.like_enabled = False
            settings.follow_enabled = False
            settings.comment_enabled = False
            settings.addfriend_enabled = True

            if args.count is not None:
                settings.addfriend_min = args.count
                settings.addfriend_max = args.count

            vm_indices = _resolve_vm_indices(args, settings)
            if not vm_indices:
                return _emit({"ok": False, "message": "No VM indices available for add-friend flow"}, args.json)

            if args.seed is not None:
                random.seed(args.seed)

            result = run_cli_farm_session(
                settings=settings,
                vm_indices=vm_indices,
                video_count=0,
                comments=[],
                db=db,
            )
            payload = {
                "ok": result["completed"],
                "message": "Add-friend flow completed" if result["completed"] else "Add-friend flow failed",
                "data": result,
            }
            return _emit(payload, args.json)

        if args.command == "ketban":
            mumu.ensure_mumu_running()
            settings = db.load_settings()
            settings.like_enabled = False
            settings.follow_enabled = False
            settings.comment_enabled = False
            settings.addfriend_enabled = True
            if args.count is not None:
                settings.addfriend_min = args.count
                settings.addfriend_max = args.count
            vm_indices = _resolve_vm_indices(args, settings)
            if not vm_indices:
                return _emit({"ok": False, "message": "Khong co VM nao de ket ban"}, args.json)
            if args.seed is not None:
                random.seed(args.seed)
            if args.bat_neu_tat:
                _maybe_boot_targets(vm_indices, auto_boot=True)
            result = run_cli_farm_session(
                settings=settings,
                vm_indices=vm_indices,
                video_count=0,
                comments=[],
                db=db,
            )
            return _emit(
                {
                    "ok": result["completed"],
                    "message": "Ket ban xong" if result["completed"] else "Ket ban that bai",
                    "data": result,
                },
                args.json,
            )

        if args.command == "tuongtac":
            settings = db.load_settings()
            settings.addfriend_enabled = False
            comments = args.comment or db.load_comments()
            return _run_session_with_settings(args, db, settings, comments)

        if args.command == "nuoinick":
            settings = db.load_settings()
            settings.like_enabled = False
            settings.follow_enabled = False
            settings.comment_enabled = False
            settings.addfriend_enabled = False
            return _run_session_with_settings(args, db, settings, comments=[], video_count=args.videos)

        if args.command == "run-session":
            settings = db.load_settings()
            comments = args.comment or db.load_comments()
            return _run_session_with_settings(args, db, settings, comments)

        if args.command == "install-app":
            mumu.ensure_mumu_running()
            # Auto-boot if not running
            vm_running = any(vm.index == args.vm and vm.status == "running" for vm in mumu.list_vms())
            if not vm_running:
                ok, msg = mumu.boot_vm(args.vm, wait=True)
                if not ok:
                    return _emit({"ok": False, "message": f"Không boot được VM #{args.vm}: {msg}"}, args.json)
            ok, msg = mumu.install_apk(args.vm, args.apk)
            return _emit({"ok": ok, "message": msg, "vm": args.vm}, args.json)

        if args.command == "check-app":
            mumu.ensure_mumu_running()
            vm_running = any(vm.index == args.vm and vm.status == "running" for vm in mumu.list_vms())
            if not vm_running:
                ok, msg = mumu.boot_vm(args.vm, wait=True)
                if not ok:
                    return _emit({"ok": False, "message": f"Không boot được VM #{args.vm}: {msg}"}, args.json)
            has = mumu.check_package(args.vm, args.package)
            return _emit({"ok": True, "installed": has, "package": args.package, "vm": args.vm,
                          "message": f"{args.package} {'đã cài' if has else 'CHƯA cài'} trên VM #{args.vm}"}, args.json)

        if args.command == "install-all":
            vm_indices = _parse_vm_indices(getattr(args, "vms", None))
            results = mumu.install_apk_all(
                apk_path=args.apk,
                url=args.url,
                vm_indices=vm_indices,
                skip_installed=not args.force,
            )
            installed = sum(1 for r in results if r["status"] == "installed")
            skipped = sum(1 for r in results if r["status"] == "already_installed")
            failed = sum(1 for r in results if not r["ok"])
            return _emit({
                "ok": failed == 0,
                "message": f"Cài xong: {installed} mới, {skipped} đã có, {failed} lỗi",
                "data": results,
                "summary": {"installed": installed, "skipped": skipped, "failed": failed},
            }, args.json)

        if args.command == "download-apk":
            ok, result = mumu.download_apk(url=args.url, force=args.force)
            if ok:
                return _emit({"ok": True, "message": f"APK đã tải: {result}", "path": result}, args.json)
            else:
                return _emit({"ok": False, "message": f"Lỗi tải APK: {result}"}, args.json)

        if args.command == "dangnhap":
            """Auto-login to Kuaishou using 5SIM or manual phone."""
            import uiautomator2 as u2
            from kscli.core.account_manager import KuaishouAccountManager
            from kscli.config import get_config
            
            mumu.ensure_mumu_running()
            
            # Boot VM if needed
            vm_idx = args.vm
            vm_running = any(vm.index == vm_idx and vm.status == "running" for vm in mumu.list_vms())
            if not vm_running:
                log.info(f"🚀 Boot VM #{vm_idx}...")
                ok, msg = mumu.boot_vm(vm_idx, wait=True)
                if not ok:
                    return _emit({"ok": False, "message": f"❌ Không boot được VM #{vm_idx}: {msg}"}, args.json)
            
            # Connect to device
            port = mumu.get_port(vm_idx)
            if not port:
                return _emit({"ok": False, "message": f"❌ Không tìm port cho VM #{vm_idx}"}, args.json)
            
            serial = f"127.0.0.1:{port}"
            mumu.adb_connect(port)
            
            try:
                d = u2.connect(serial, timeout=10)
            except Exception as e:
                return _emit({"ok": False, "message": f"❌ ADB lỗi: {e}"}, args.json)
            
            try:
                # Initialize account manager
                cfg = get_config()
                api_key = cfg.fivesim.api_key or os.getenv("KUAISHOU_5SIM_API_KEY", "")
                mgr = KuaishouAccountManager(api_key=api_key if api_key else None)
                
                # Login logic
                if args.use_5sim and not args.phone:
                    # Auto 5SIM mode
                    log.info("🔑 Auto-login với 5SIM...")
                    success = mgr.auto_login_with_5sim(
                        d,
                        use_password=args.password,
                        country=cfg.fivesim.country,
                        operator=cfg.fivesim.operator,
                        product=cfg.fivesim.product,
                    )
                elif args.phone and args.otp:
                    # Manual phone + OTP
                    log.info(f"🔑 Login với SĐT: {args.phone}")
                    success = mgr.login_otp(
                        d,
                        phone=args.phone,
                        otp=args.otp,
                        use_password=False,
                    )
                elif args.phone and args.password:
                    # Manual phone + password
                    log.info(f"🔑 Login với SĐT: {args.phone} + password")
                    success = mgr.login_otp(
                        d,
                        phone=args.phone,
                        password=args.password,
                        use_password=True,
                    )
                else:
                    return _emit({"ok": False, "message": "❌ Cung cấp --phone hoặc --otp hoặc --password"}, args.json)
                
                if success:
                    return _emit({
                        "ok": True,
                        "message": f"✅ Đăng nhập thành công trên VM #{vm_idx}",
                        "vm": vm_idx,
                    }, args.json)
                else:
                    return _emit({
                        "ok": False,
                        "message": f"❌ Đăng nhập thất bại trên VM #{vm_idx}",
                        "vm": vm_idx,
                    }, args.json)
                    
            except Exception as e:
                log.exception(f"Login error on VM #{vm_idx}")
                return _emit({
                    "ok": False,
                    "message": f"❌ Lỗi đăng nhập: {e}",
                    "error_type": type(e).__name__,
                }, args.json)
            finally:
                try:
                    d.service("uiautomator").stop()
                except Exception:
                    pass

        if args.command == "apk-url":
            return _emit({
                "ok": True,
                "url": mumu.DEFAULT_APK_URL,
                "cache_dir": mumu.APK_CACHE_DIR,
                "message": f"URL mặc định: {mumu.DEFAULT_APK_URL}\nCache: {mumu.APK_CACHE_DIR}",
            }, args.json)

        return _emit({"ok": False, "message": f"Unsupported command: {args.command}"}, args.json)
    except Exception as exc:
        log.exception("CLI command failed")
        return _emit({"ok": False, "message": str(exc), "error_type": type(exc).__name__}, args.json)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
