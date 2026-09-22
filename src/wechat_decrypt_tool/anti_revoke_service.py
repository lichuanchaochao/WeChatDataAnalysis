from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .app_paths import get_data_dir
from .key_store import (
    _KEY_STORE_PATH,
    _atomic_write_json,
    get_account_keys_from_store,
    load_account_keys_store,
)
from .logging_config import get_logger
from .media_helpers import _resolve_account_db_storage_dir
from .native_core_realtime import (
    close_account,
    exec_query,
    get_avatar_urls,
    get_display_names,
    open_account,
)

logger = get_logger(__name__)

# Excluded system usernames and service folders (similar to Weport's filter)
_EXCLUDED_USERNAMES = {
    "weixin",
    "brandsessionholder",
    "brandservicesessionholder",
    "notifymessage",
    "opencustomerservicemsg",
    "notification_messages",
    "userexperience_alarm",
    "helper_folders",
    "@helper_folders",
    "qqmail",
    "fmessage",
    "medianote",
    "floatbottle",
    "qmessage",
    "newsapp",
    "voip",
    "voicevoip",
    "voiceinput",
    "linkedinpartner",
    "blogapp",
}
_IGNORED_PREFIXES = ("gh_", "@placeholder")


def _is_valid_chat_session(username: str) -> bool:
    """Filter out official accounts, service holders, and internal system message folders."""
    if not username or username == "place_holder":
        return False
    if username in _EXCLUDED_USERNAMES:
        return False
    if any(username.startswith(prefix) for prefix in _IGNORED_PREFIXES):
        return False
    if "@placeholder" in username or "@kefu.openim" in username or "@weclaw" in username:
        return False
    return True


def _ensure_weflow_host_executable() -> str:
    """Ensure an executable named WeFlow.exe exists to pass the -1006 security check of wcdb_api.dll."""
    bin_dir = get_data_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    weflow_exe = bin_dir / "WeFlow.exe"

    if getattr(sys, "frozen", False):
        src_exe = Path(sys.executable).resolve()
    else:
        # In development mode, if running inside a virtualenv, sys.executable is a shim launcher
        # that delegates to python.exe (which causes GetModuleFileName to return python.exe).
        # We must use the base python executable so GetModuleFileName returns WeFlow.exe.
        base_py = Path(sys.base_exec_prefix) / "python.exe"
        if base_py.is_file():
            src_exe = base_py
        else:
            src_exe = Path(sys.executable).resolve()

    if not weflow_exe.is_file() or weflow_exe.stat().st_size != src_exe.stat().st_size:
        try:
            if weflow_exe.exists():
                weflow_exe.unlink(missing_ok=True)
            shutil.copyfile(src_exe, weflow_exe)
        except Exception as exc:
            logger.warning(f"Failed to create WeFlow.exe in bin dir: {exc}")
            # Fallback to temp directory
            tmp_exe = Path(tempfile.gettempdir()) / "WeFlow.exe"
            if not tmp_exe.is_file() or tmp_exe.stat().st_size != src_exe.stat().st_size:
                try:
                    shutil.copyfile(src_exe, tmp_exe)
                except Exception:
                    pass
            return str(tmp_exe)

    return str(weflow_exe)


def _resolve_account_info(account: str) -> tuple[Path, str, str]:
    """Returns (db_storage_dir, native_wxid, hex_key)."""
    keys = load_account_keys_store()
    item = keys.get(account) or {}
    if not item:
        # Search by suffix or prefix
        for k, v in keys.items():
            if account in k or k in account:
                item = v
                break

    hex_key = str(item.get("db_key") or "").strip()
    db_storage_str = str(item.get("db_key_source_db_storage_path") or "").strip()
    native_wxid = str(item.get("image_key_derived_wxid") or account).strip()

    if not db_storage_str:
        wxid_dir = str(item.get("db_key_source_wxid_dir") or "").strip()
        if wxid_dir:
            db_storage_str = os.path.join(wxid_dir, "db_storage")

    if not db_storage_str or not os.path.isdir(db_storage_str):
        # Fallback to default search
        candidate = Path(r"D:\微信\xwechat_files\wxid_p1hz4zqg7onh41_0847\db_storage")
        if candidate.is_dir():
            db_storage_dir = candidate
        else:
            raise FileNotFoundError(f"db_storage directory not found for account {account}")
    else:
        db_storage_dir = Path(db_storage_str).resolve()

    if not hex_key:
        raise ValueError(f"Database decryption key not found for account {account}")

    return db_storage_dir, native_wxid, hex_key


def _get_installed_trigger_info(handle: int, db_storage_dir: Path) -> tuple[Set[str], Set[str]]:
    """Fast, safe read-only detection of all tables with anti_revoke triggers and pending sessions."""
    installed_tables: Set[str] = set()
    pending_sessions: Set[str] = set()
    message_dir = db_storage_dir / "message"
    if not message_dir.is_dir():
        return installed_tables, pending_sessions

    for db_file in sorted(message_dir.glob("*.db")):
        try:
            rows = exec_query(
                handle,
                kind="message",
                path=str(db_file),
                sql="SELECT tbl_name FROM sqlite_master WHERE type='trigger' AND name LIKE 'anti_revoke_block_insert_%'",
            )
            for r in rows:
                tbl = str(r.get("tbl_name") or "").strip()
                if tbl:
                    installed_tables.add(tbl)
        except Exception as exc:
            logger.debug(f"Error querying triggers from {db_file.name}: {exc}")

        try:
            p_rows = exec_query(
                handle,
                kind="message",
                path=str(db_file),
                sql="SELECT session_id FROM _weflow_anti_revoke_pending",
            )
            for r in p_rows:
                sid = str(r.get("session_id") or "").strip()
                if sid:
                    pending_sessions.add(sid)
        except Exception:
            pass

    return installed_tables, pending_sessions


def get_anti_revoke_sessions(account: str) -> Dict[str, Any]:
    """Retrieve all chat sessions and their anti-revoke status."""
    db_storage_dir, native_wxid, hex_key = _resolve_account_info(account)
    session_db = db_storage_dir / "session" / "session.db"

    handle = open_account(
        account=account,
        native_wxid=native_wxid,
        db_storage_dir=db_storage_dir,
        session_db_path=session_db,
        key_hex=hex_key,
    )

    try:
        # 1. Query installed trigger tables and pending sessions
        installed_tables, pending_sessions = _get_installed_trigger_info(handle, db_storage_dir)

        # 2. Query sessions from SessionTable
        session_rows = exec_query(
            handle,
            kind="session",
            path=str(session_db),
            sql="SELECT username, last_timestamp, summary FROM SessionTable ORDER BY sort_timestamp DESC",
        )

        # 3. Filter valid chat sessions
        valid_rows: List[Dict[str, Any]] = []
        valid_usernames: List[str] = []
        for r in session_rows:
            u = str(r.get("username") or "").strip()
            if _is_valid_chat_session(u):
                valid_rows.append(r)
                valid_usernames.append(u)

        # 4. Resolve real display names and avatars via native_core_realtime
        display_names = get_display_names(handle, valid_usernames)
        avatar_urls = get_avatar_urls(handle, valid_usernames)

        sessions: List[Dict[str, Any]] = []
        installed_count = 0

        for row in valid_rows:
            username = str(row.get("username") or "").strip()
            tbl_hash = hashlib.md5(username.encode("utf-8")).hexdigest()
            tbl_name = f"Msg_{tbl_hash}"
            is_installed = (tbl_name in installed_tables) or (username in pending_sessions)

            if is_installed:
                installed_count += 1

            display_name = display_names.get(username) or username
            avatar_url = avatar_urls.get(username) or ""

            sessions.append({
                "username": username,
                "displayName": display_name,
                "avatarUrl": avatar_url,
                "installed": is_installed,
                "isChatroom": username.endswith("@chatroom"),
                "lastTimestamp": row.get("last_timestamp") or 0,
                "summary": str(row.get("summary") or ""),
            })

        return {
            "success": True,
            "installedCount": installed_count,
            "totalCount": len(sessions),
            "sessions": sessions,
        }
    finally:
        close_account(handle)


def _resolve_worker_script() -> Path:
    candidates = [
        Path(__file__).resolve().parent / "anti_revoke" / "worker.py",
        Path(sys.executable).resolve().parent / "anti_revoke" / "worker.py",
        Path(sys.executable).resolve().parent / "resources" / "backend" / "anti_revoke" / "worker.py",
        Path(sys.executable).resolve().parent / "backend" / "anti_revoke" / "worker.py",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return Path(__file__).resolve().parent / "anti_revoke" / "worker.py"


def _execute_worker_action(action: str, account: str, session_ids: List[str]) -> Dict[str, Any]:
    """Spawns WeFlow.exe with worker.py to install or uninstall triggers."""
    db_storage_dir, _native_wxid, hex_key = _resolve_account_info(account)
    weflow_exe = _ensure_weflow_host_executable()
    worker_script = _resolve_worker_script()

    payload = {
        "action": action,
        "db_storage_dir": str(db_storage_dir),
        "hex_key": hex_key,
        "session_ids": session_ids,
    }

    # Pass payload via temp json file to handle potential huge batch safely
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tf:
        json.dump(payload, tf)
        tmp_payload_path = tf.name

    worker_env = os.environ.copy()
    worker_env.pop("WECHAT_TOOL_NATIVE_CORE_ENDPOINT", None)
    worker_env.pop("WECHAT_TOOL_DESKTOP_PARENT_PID", None)
    worker_env.pop("ELECTRON_RUN_AS_NODE", None)
    src_dir = str(Path(__file__).resolve().parents[1])
    python_paths = [src_dir]

    if getattr(sys, "frozen", False):
        cmd = [weflow_exe, "--wcdb-worker", tmp_payload_path]
    else:
        site_packages = [p for p in sys.path if "site-packages" in p]
        python_paths.extend(site_packages)
        worker_env["PATH"] = str(sys.base_exec_prefix) + os.pathsep + worker_env.get("PATH", "")
        cmd = [weflow_exe, "-m", "wechat_decrypt_tool.backend_entry", "--wcdb-worker", tmp_payload_path]

    worker_env["PYTHONPATH"] = os.pathsep.join(python_paths) + (os.pathsep + worker_env.get("PYTHONPATH", "") if worker_env.get("PYTHONPATH") else "")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=worker_env,
            timeout=120,
        )
        if proc.returncode != 0:
            logger.error(f"Anti-revoke worker failed ({proc.returncode}): {proc.stderr}")
            return {"success": False, "error": proc.stderr or f"Worker exited with code {proc.returncode}"}

        out = proc.stdout.strip()
        result = json.loads(out)
        return result
    except Exception as exc:
        logger.exception(f"Anti-revoke {action} execution failed: {exc}")
        return {"success": False, "error": str(exc)}
    finally:
        try:
            os.unlink(tmp_payload_path)
        except Exception:
            pass


def install_anti_revoke_triggers(account: str, session_ids: List[str]) -> Dict[str, Any]:
    """Install anti-revoke triggers for the given sessions."""
    return _execute_worker_action("install", account, session_ids)


def uninstall_anti_revoke_triggers(account: str, session_ids: List[str]) -> Dict[str, Any]:
    """Uninstall anti-revoke triggers for the given sessions."""
    return _execute_worker_action("uninstall", account, session_ids)


def get_anti_revoke_config(account: str) -> Dict[str, Any]:
    """Get anti-revoke preferences for the account."""
    keys = load_account_keys_store()
    item = keys.get(account) or {}
    return {
        "antiRevokeAutoApplyNewGroups": bool(item.get("antiRevokeAutoApplyNewGroups", False)),
    }


def set_anti_revoke_config(account: str, auto_apply: bool) -> Dict[str, Any]:
    """Save anti-revoke preferences for the account."""
    keys = load_account_keys_store()
    if account not in keys:
        keys[account] = {}
    keys[account]["antiRevokeAutoApplyNewGroups"] = bool(auto_apply)
    _atomic_write_json(_KEY_STORE_PATH, keys)
    return {"success": True, "antiRevokeAutoApplyNewGroups": bool(auto_apply)}
