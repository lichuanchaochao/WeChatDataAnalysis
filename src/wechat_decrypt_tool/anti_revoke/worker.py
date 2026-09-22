from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _resolve_wcdb_dll() -> str:
    current_dir = Path(__file__).resolve().parent
    candidates = [
        current_dir / "wcdb_api.dll",
        current_dir / "native" / "wcdb_api.dll",
        Path(sys.executable).resolve().parent / "anti_revoke" / "wcdb_api.dll",
        Path(sys.executable).resolve().parent / "resources" / "backend" / "anti_revoke" / "wcdb_api.dll",
        Path(sys.executable).resolve().parent / "resources" / "anti_revoke" / "wcdb_api.dll",
        current_dir.parents[2] / "desktop" / "resources" / "anti_revoke" / "wcdb_api.dll",
        current_dir.parents[2] / "resources" / "anti_revoke" / "wcdb_api.dll",
        Path(r"D:\03_开源项目\Weport-main\resources\wcdb\win32\x64\wcdb_api.dll"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise FileNotFoundError("wcdb_api.dll not found in candidate paths")


def main() -> None:
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.loads(sys.stdin.read())

    action = str(payload.get("action") or "check").lower().strip()
    db_storage_dir = str(payload.get("db_storage_dir") or "").strip()
    hex_key = str(payload.get("hex_key") or "").strip().encode("utf-8")
    session_ids = list(payload.get("session_ids") or [])

    if not db_storage_dir or not hex_key:
        print(json.dumps({"success": False, "error": "db_storage_dir and hex_key are required"}))
        return

    # Check for non-ASCII path
    has_non_ascii = any(ord(c) >= 128 for c in db_storage_dir)
    junction = None
    created_junction = False

    try:
        if has_non_ascii:
            public_dir = os.environ.get("PUBLIC", r"C:\Users\Public")
            hash_suffix = hashlib.md5(db_storage_dir.encode("utf-8")).hexdigest()[:8]
            junction = os.path.join(public_dir, f"wcdb_junc_{hash_suffix}")
            account_dir = os.path.dirname(os.path.abspath(db_storage_dir))
            if not os.path.exists(junction):
                mk = subprocess.run(f'cmd /c mklink /J "{junction}" "{account_dir}"', shell=True, capture_output=True)
                if mk.returncode == 0:
                    created_junction = True
            session_db = os.path.join(junction, "db_storage", "session", "session.db")
            if not os.path.isfile(session_db):
                # Try direct session.db in junction
                session_db = os.path.join(junction, "session", "session.db")
        else:
            session_db = os.path.join(db_storage_dir, "session", "session.db")

        dll_path = _resolve_wcdb_dll()
        dll_dir = os.path.dirname(os.path.abspath(dll_path))
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(dll_dir)
            except Exception:
                pass
        lib = ctypes.CDLL(dll_path)

        rc = lib.wcdb_init()
        if rc != 0:
            print(json.dumps({"success": False, "error": f"wcdb_init failed with code {rc}"}))
            return

        lib.wcdb_open_account.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int64)]
        lib.wcdb_open_account.restype = ctypes.c_int32
        handle = ctypes.c_int64()
        rc = lib.wcdb_open_account(session_db.encode("utf-8"), hex_key, ctypes.byref(handle))
        if rc != 0 or handle.value <= 0:
            print(json.dumps({"success": False, "error": f"wcdb_open_account failed with code {rc}"}))
            return

        results: dict[str, bool] = {}
        if action == "check":
            lib.wcdb_check_message_anti_revoke_trigger.argtypes = [ctypes.c_int64, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32)]
            lib.wcdb_check_message_anti_revoke_trigger.restype = ctypes.c_int32
            for sid in session_ids:
                installed = ctypes.c_int32()
                c_rc = lib.wcdb_check_message_anti_revoke_trigger(handle.value, str(sid).encode("utf-8"), ctypes.byref(installed))
                results[str(sid)] = bool(installed.value) if c_rc == 0 else False
        elif action == "install":
            lib.wcdb_install_message_anti_revoke_trigger.argtypes = [ctypes.c_int64, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
            lib.wcdb_install_message_anti_revoke_trigger.restype = ctypes.c_int32
            for sid in session_ids:
                out_err = ctypes.c_void_p()
                i_rc = lib.wcdb_install_message_anti_revoke_trigger(handle.value, str(sid).encode("utf-8"), ctypes.byref(out_err))
                results[str(sid)] = (i_rc == 0)
        elif action == "uninstall":
            lib.wcdb_uninstall_message_anti_revoke_trigger.argtypes = [ctypes.c_int64, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
            lib.wcdb_uninstall_message_anti_revoke_trigger.restype = ctypes.c_int32
            for sid in session_ids:
                out_err = ctypes.c_void_p()
                u_rc = lib.wcdb_uninstall_message_anti_revoke_trigger(handle.value, str(sid).encode("utf-8"), ctypes.byref(out_err))
                results[str(sid)] = (u_rc == 0)

        lib.wcdb_close_account.argtypes = [ctypes.c_int64]
        lib.wcdb_close_account.restype = ctypes.c_int32
        lib.wcdb_close_account(handle.value)

        print(json.dumps({"success": True, "results": results}))
    finally:
        pass


if __name__ == "__main__":
    main()
