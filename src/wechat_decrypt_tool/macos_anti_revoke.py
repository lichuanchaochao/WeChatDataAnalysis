"""macOS pure-Python offline anti-revoke trigger installer/uninstaller.

Requires WeChat to be completely quit before modifying encrypted SQLCipher
message databases so no concurrent WAL/-shm writer can corrupt the database.
Creates a safety backup before writing, applies the standard WeFlow/Weport
SQLite triggers on a verified plaintext copy, and re-encrypts every page with
validated AES-256-CBC + HMAC-SHA512 checksums.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .app_paths import get_data_dir
from .database_filters import should_skip_source_database
from .local_sqlite_realtime import (
    LOCAL_SQLCIPHER_READER,
    LocalSQLCipherRealtimeError,
    _atomic_write_bytes,
    _decrypt_encrypted_page,
    _parse_committed_wal_pages,
)
from .logging_config import get_logger
from .wechat_decrypt import (
    HMAC_SIZE,
    IV_SIZE,
    PAGE_SIZE,
    RESERVE_SIZE,
    SALT_SIZE,
    SQLITE_HEADER,
    _compute_page_hmac,
    _derive_mac_key,
    _derive_sqlcipher_enc_key,
    _resolve_page1_key_material,
)

logger = get_logger(__name__)
_CRYPTO_BACKEND = default_backend()
_MAX_BACKUPS_PER_DB = 3
_PENDING_TABLE = "_weflow_anti_revoke_pending"
_DELETED_CACHE_TABLE = "_weflow_anti_revoke_deleted_cache"
_REVOKE_NOTICE_TEXT = "对方尝试撤回此消息"

_TRIGGER_PREFIXES = (
    "anti_revoke_capture_delete_",
    "anti_revoke_block_insert_",
    "anti_revoke_block_delete_",
    "anti_revoke_restore_",
    "anti_revoke_notify_",
)

_DELETED_CACHE_DDL = (
    "CREATE TABLE IF NOT EXISTS _weflow_anti_revoke_deleted_cache ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "tbl TEXT NOT NULL, "
    "local_id INTEGER, server_id INTEGER, local_type INTEGER, sort_seq INTEGER, "
    "real_sender_id INTEGER, create_time INTEGER, status INTEGER, "
    "upload_status INTEGER, download_status INTEGER, server_seq INTEGER, "
    "origin_source INTEGER, source TEXT, message_content TEXT, "
    "compress_content TEXT, packed_info_data BLOB, "
    "WCDB_CT_message_content INTEGER, WCDB_CT_source INTEGER, deleted_at INTEGER)"
)

_PENDING_DDL = (
    "CREATE TABLE IF NOT EXISTS _weflow_anti_revoke_pending ("
    "session_id TEXT PRIMARY KEY, updated_at INTEGER)"
)


def _quote_ident(name: str) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def _sql_str(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def is_wechat_running_macos() -> bool:
    """Return True if the macOS WeChat main client process is currently running."""
    try:
        res = subprocess.run(
            ["pgrep", "-x", "WeChat"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if res.returncode == 0 and any(line.strip().isdigit() for line in res.stdout.splitlines()):
            return True
    except Exception:
        pass
    try:
        res2 = subprocess.run(
            ["pgrep", "-f", "WeChat.app/Contents/MacOS/WeChat"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return res2.returncode == 0 and any(
            line.strip().isdigit() for line in res2.stdout.splitlines()
        )
    except Exception:
        return False


def _iter_message_db_files(db_storage_dir: Path) -> list[Path]:
    msg_dir = db_storage_dir / "message"
    if not msg_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(msg_dir.glob("*.db"), key=lambda p: p.name.lower()):
        lower = path.name.lower()
        if should_skip_source_database(path.name):
            continue
        if lower in {"message_fts.db", "message_resource.db"}:
            continue
        if "message" not in lower:
            continue
        files.append(path)
    # Put primary shard message_0.db first for pending-session placement.
    files.sort(key=lambda p: (0 if p.name.lower() == "message_0.db" else 1, p.name.lower()))
    return files


def _resolve_db_crypto(page1: bytes, key_bytes: bytes) -> tuple[bytes, bytes, bytes] | None:
    if page1.startswith(SQLITE_HEADER):
        return None
    salt = page1[:SALT_SIZE]
    resolved = _resolve_page1_key_material(key_bytes, page1)
    if resolved is None:
        enc_key = _derive_sqlcipher_enc_key(key_bytes, salt)
        mac_key = _derive_mac_key(enc_key, salt)
        raise LocalSQLCipherRealtimeError(
            f"Database key verification failed on page 1 (salt={salt[:4].hex()}...)."
        )
    enc_key, mac_key, _mode = resolved
    return salt, enc_key, mac_key


def _decrypt_db_with_wal(db_path: Path, key_bytes: bytes) -> tuple[bytes, tuple[bytes, bytes, bytes] | None]:
    db_bytes = db_path.read_bytes()
    if len(db_bytes) < PAGE_SIZE or len(db_bytes) % PAGE_SIZE != 0:
        raise LocalSQLCipherRealtimeError(f"Invalid SQLite file size for {db_path.name}")

    crypto = _resolve_db_crypto(db_bytes[:PAGE_SIZE], key_bytes)
    base_pages = len(db_bytes) // PAGE_SIZE
    wal_path = Path(f"{db_path}-wal")
    wal_bytes = wal_path.read_bytes() if wal_path.is_file() and wal_path.stat().st_size >= 32 else b""
    parsed_wal = _parse_committed_wal_pages(wal_bytes, base_pages)
    final_pages = parsed_wal.final_pages

    out = bytearray(final_pages * PAGE_SIZE)
    for pgno in range(1, final_pages + 1):
        enc_pg = parsed_wal.committed_pages.get(pgno)
        from_wal = enc_pg is not None
        if enc_pg is None:
            pos = (pgno - 1) * PAGE_SIZE
            enc_pg = db_bytes[pos : pos + PAGE_SIZE]
        if crypto is None:
            plain_pg = enc_pg[:PAGE_SIZE]
            if len(plain_pg) < PAGE_SIZE:
                plain_pg = plain_pg + (b"\x00" * (PAGE_SIZE - len(plain_pg)))
        else:
            _salt, enc_key, mac_key = crypto
            plain_pg = _decrypt_encrypted_page(
                enc_pg,
                pgno,
                enc_key,
                mac_key,
                verify_hmac=(pgno == 1 or from_wal),
            )
        start = (pgno - 1) * PAGE_SIZE
        out[start : start + PAGE_SIZE] = plain_pg

    return bytes(out), crypto


def _encrypt_plaintext_sqlite(
    plain_bytes: bytes,
    crypto: tuple[bytes, bytes, bytes] | None,
) -> bytes:
    if len(plain_bytes) < PAGE_SIZE or len(plain_bytes) % PAGE_SIZE != 0:
        raise LocalSQLCipherRealtimeError("Modified plaintext SQLite has invalid page alignment.")
    if not plain_bytes.startswith(SQLITE_HEADER):
        raise LocalSQLCipherRealtimeError("Modified SQLite file lost its header.")
    if crypto is None:
        return plain_bytes

    salt, enc_key, mac_key = crypto
    total_pages = len(plain_bytes) // PAGE_SIZE
    out = bytearray(total_pages * PAGE_SIZE)
    for idx in range(total_pages):
        pgno = idx + 1
        start = idx * PAGE_SIZE
        plain_pg = plain_bytes[start : start + PAGE_SIZE]
        iv = os.urandom(IV_SIZE)
        offset = SALT_SIZE if pgno == 1 else 0
        encryptor = Cipher(algorithms.AES(enc_key), modes.CBC(iv), backend=_CRYPTO_BACKEND).encryptor()
        ciphertext = encryptor.update(plain_pg[offset : PAGE_SIZE - RESERVE_SIZE]) + encryptor.finalize()
        enc_pg = bytearray(PAGE_SIZE)
        if pgno == 1:
            enc_pg[:SALT_SIZE] = salt
        enc_pg[offset : PAGE_SIZE - RESERVE_SIZE] = ciphertext
        enc_pg[PAGE_SIZE - RESERVE_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE] = iv
        enc_pg[PAGE_SIZE - HMAC_SIZE :] = _compute_page_hmac(mac_key, bytes(enc_pg), pgno)
        out[start : start + PAGE_SIZE] = enc_pg

    # Round-trip sanity check on page 1 before writing back
    check_p1 = _decrypt_encrypted_page(bytes(out[:PAGE_SIZE]), 1, enc_key, mac_key, verify_hmac=True)
    if not check_p1.startswith(SQLITE_HEADER):
        raise LocalSQLCipherRealtimeError("Re-encrypted page 1 round-trip verification failed.")
    return bytes(out)


def _backup_message_db(db_path: Path, account: str) -> None:
    safe_acc = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in account)[:64] or "account"
    backup_root = get_data_dir() / "backups" / "anti_revoke" / safe_acc / time.strftime("%Y%m%d_%H%M%S")
    backup_root.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = Path(f"{db_path}{suffix}")
        if src.is_file():
            shutil.copy2(src, backup_root / src.name)
    # Prune older snapshot folders beyond _MAX_BACKUPS_PER_DB
    parent = backup_root.parent
    snapshots = sorted([p for p in parent.iterdir() if p.is_dir()], key=lambda p: p.name)
    for stale in snapshots[:-_MAX_BACKUPS_PER_DB]:
        shutil.rmtree(stale, ignore_errors=True)


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({_quote_ident(table_name)})").fetchall()
    return {str(row[1]) for row in rows if len(row) > 1}


def _install_triggers_for_table(conn: sqlite3.Connection, table_name: str, self_rowid: int | None) -> None:
    cols = _table_columns(conn, table_name)
    required = {
        "local_id", "server_id", "local_type", "sort_seq", "real_sender_id",
        "create_time", "status", "upload_status", "download_status", "server_seq",
        "origin_source", "source", "message_content", "compress_content", "packed_info_data",
    }
    if not required.issubset(cols):
        raise LocalSQLCipherRealtimeError(f"Unsupported Msg table schema in {table_name}")

    has_wcdb_ct_msg = "WCDB_CT_message_content" in cols
    has_wcdb_ct_src = "WCDB_CT_source" in cols
    old_ct_msg = "OLD.WCDB_CT_message_content" if has_wcdb_ct_msg else "NULL"
    old_ct_src = "OLD.WCDB_CT_source" if has_wcdb_ct_src else "NULL"
    msg_ct_cols = (
        (", WCDB_CT_message_content" if has_wcdb_ct_msg else "")
        + (", WCDB_CT_source" if has_wcdb_ct_src else "")
    )
    msg_ct_nulls = (
        (", NULL" if has_wcdb_ct_msg else "")
        + (", NULL" if has_wcdb_ct_src else "")
    )

    quoted_tbl = _quote_ident(table_name)
    tbl_lit = _sql_str(table_name)
    self_delete_guard = f" AND COALESCE(OLD.real_sender_id, 0) <> {int(self_rowid)}" if self_rowid else ""
    cond = (
        f"tbl = {tbl_lit} AND ("
        f"(COALESCE(NEW.server_id, 0) <> 0 AND server_id = NEW.server_id) OR "
        f"(COALESCE(NEW.server_id, 0) = 0 AND COALESCE(NEW.local_id, 0) <> 0 AND local_id = NEW.local_id)"
        f")"
    )
    self_insert_guard = (
        f" AND COALESCE((SELECT real_sender_id FROM {_DELETED_CACHE_TABLE} WHERE {cond} ORDER BY id DESC LIMIT 1), 0) <> {int(self_rowid)}"
        if self_rowid
        else ""
    )

    capture_trigger = _quote_ident(f"anti_revoke_capture_delete_{table_name}")
    block_trigger = _quote_ident(f"anti_revoke_block_insert_{table_name}")

    conn.execute(
        f"CREATE TRIGGER IF NOT EXISTS {capture_trigger} "
        f"AFTER DELETE ON {quoted_tbl} "
        f"FOR EACH ROW WHEN OLD.local_type != 10000{self_delete_guard} "
        f"BEGIN "
        f"INSERT INTO {_DELETED_CACHE_TABLE} ("
        f"tbl, local_id, server_id, local_type, sort_seq, real_sender_id, create_time, "
        f"status, upload_status, download_status, server_seq, origin_source, source, "
        f"message_content, compress_content, packed_info_data, WCDB_CT_message_content, "
        f"WCDB_CT_source, deleted_at"
        f") VALUES ("
        f"{tbl_lit}, OLD.local_id, OLD.server_id, OLD.local_type, OLD.sort_seq, OLD.real_sender_id, OLD.create_time, "
        f"OLD.status, OLD.upload_status, OLD.download_status, OLD.server_seq, OLD.origin_source, OLD.source, "
        f"OLD.message_content, OLD.compress_content, OLD.packed_info_data, {old_ct_msg}, "
        f"{old_ct_src}, CAST(strftime('%s','now') AS INTEGER)"
        f"); END"
    )

    conn.execute(
        f"CREATE TRIGGER IF NOT EXISTS {block_trigger} "
        f"BEFORE INSERT ON {quoted_tbl} "
        f"FOR EACH ROW WHEN NEW.local_type = 10000 "
        f"AND COALESCE(NEW.message_content, '') <> {_sql_str(_REVOKE_NOTICE_TEXT)} "
        f"AND EXISTS (SELECT 1 FROM {_DELETED_CACHE_TABLE} WHERE {cond})"
        f"{self_insert_guard} "
        f"BEGIN "
        f"DELETE FROM {_DELETED_CACHE_TABLE} "
        f"WHERE tbl = {tbl_lit} AND deleted_at < CAST(strftime('%s','now') AS INTEGER) - 86400; "
        f"INSERT INTO {quoted_tbl} ("
        f"server_id, local_type, sort_seq, real_sender_id, create_time, "
        f"status, upload_status, download_status, server_seq, origin_source, "
        f"source, message_content, compress_content, packed_info_data{msg_ct_cols}"
        f") SELECT "
        f"COALESCE(server_id, COALESCE(NEW.server_id, 0)), "
        f"COALESCE(local_type, 1), "
        f"COALESCE(sort_seq, COALESCE(NEW.sort_seq, 0)), "
        f"COALESCE(real_sender_id, COALESCE(NEW.real_sender_id, 0)), "
        f"COALESCE(create_time, COALESCE(NEW.create_time, 0)), "
        f"COALESCE(status, 3), "
        f"COALESCE(upload_status, 0), "
        f"COALESCE(download_status, 0), "
        f"COALESCE(server_seq, COALESCE(NEW.server_seq, 0)), "
        f"COALESCE(origin_source, 0), "
        f"COALESCE(source, ''), "
        f"COALESCE(message_content, ''), "
        f"compress_content, packed_info_data{msg_ct_cols} "
        f"FROM {_DELETED_CACHE_TABLE} "
        f"WHERE id = (SELECT id FROM {_DELETED_CACHE_TABLE} WHERE {cond} ORDER BY id DESC LIMIT 1); "
        f"DELETE FROM {_DELETED_CACHE_TABLE} "
        f"WHERE id = (SELECT id FROM {_DELETED_CACHE_TABLE} WHERE {cond} ORDER BY id DESC LIMIT 1); "
        f"INSERT INTO {quoted_tbl} ("
        f"server_id, local_type, sort_seq, real_sender_id, create_time, "
        f"status, upload_status, download_status, server_seq, origin_source, "
        f"source, message_content, compress_content, packed_info_data{msg_ct_cols}"
        f") VALUES ("
        f"COALESCE(NEW.server_id, 0), 10000, COALESCE(NEW.sort_seq, 0) + 1, "
        f"COALESCE(NEW.real_sender_id, 0), COALESCE(NEW.create_time, 0) + 1, "
        f"4, 0, 0, COALESCE(NEW.server_seq, 0), 0, '', "
        f"{_sql_str(_REVOKE_NOTICE_TEXT)}, NULL, NULL{msg_ct_nulls}"
        f"); "
        f"SELECT RAISE(IGNORE); END"
    )


def _uninstall_triggers_for_table(conn: sqlite3.Connection, table_name: str) -> None:
    for prefix in _TRIGGER_PREFIXES:
        conn.execute(f"DROP TRIGGER IF EXISTS {_quote_ident(prefix + table_name)}")
    try:
        conn.execute(f"DELETE FROM {_DELETED_CACHE_TABLE} WHERE tbl = ?", (table_name,))
    except sqlite3.Error:
        pass


def _inspect_db_plan(
    db_file: Path,
    db_storage_dir: Path,
    key_bytes: bytes,
    self_candidates: Iterable[str],
) -> dict[str, Any]:
    tables: set[str] = set()
    block_triggers: set[str] = set()
    capture_triggers: set[str] = set()
    all_anti_triggers: set[str] = set()
    pending: set[str] = set()
    self_rowid: int | None = None

    for row in LOCAL_SQLCIPHER_READER.query(
        db_file,
        db_storage_dir,
        "SELECT type, name, tbl_name FROM sqlite_master WHERE type IN ('table', 'trigger')",
        key_bytes=key_bytes,
    ):
        obj_type = str(row.get("type") or "")
        name = str(row.get("name") or "")
        tbl_name = str(row.get("tbl_name") or "")
        if obj_type == "table" and name.startswith("Msg_"):
            tables.add(name)
        elif obj_type == "trigger" and name.startswith("anti_revoke_"):
            all_anti_triggers.add(tbl_name)
            if name.startswith("anti_revoke_block_insert_"):
                block_triggers.add(tbl_name)
            elif name.startswith("anti_revoke_capture_delete_"):
                capture_triggers.add(tbl_name)

    try:
        for row in LOCAL_SQLCIPHER_READER.query(
            db_file,
            db_storage_dir,
            f"SELECT session_id FROM {_PENDING_TABLE}",
            key_bytes=key_bytes,
        ):
            sid = str(row.get("session_id") or "").strip()
            if sid:
                pending.add(sid)
    except Exception:
        pass

    candidates = [c for c in self_candidates if c]
    if candidates:
        placeholders = ",".join(_sql_str(c) for c in candidates)
        try:
            rows = LOCAL_SQLCIPHER_READER.query(
                db_file,
                db_storage_dir,
                f"SELECT rowid FROM Name2Id WHERE user_name IN ({placeholders}) LIMIT 1",
                key_bytes=key_bytes,
            )
            if rows and rows[0].get("rowid") is not None:
                self_rowid = int(rows[0]["rowid"])
        except Exception:
            pass

    return {
        "tables": tables,
        "installed_tables": block_triggers & capture_triggers,
        "any_trigger_tables": all_anti_triggers,
        "pending": pending,
        "self_rowid": self_rowid,
    }


def _rewrite_db_with_ops(
    db_file: Path,
    key_bytes: bytes,
    account: str,
    *,
    action: str,
    table_ops: list[str],
    pending_ops: list[str],
    pending_delete_ops: list[str] | None = None,
    self_rowid: int | None,
) -> None:
    plain_bytes, crypto = _decrypt_db_with_wal(db_file, key_bytes)
    with tempfile.TemporaryDirectory(prefix="wda_ar_") as td:
        plain_path = Path(td) / db_file.name
        plain_path.write_bytes(plain_bytes)

        conn = sqlite3.connect(str(plain_path))
        try:
            check = conn.execute("PRAGMA quick_check").fetchall()
            if check != [("ok",)]:
                raise LocalSQLCipherRealtimeError(
                    f"Pre-write integrity check failed for {db_file.name}: {check}"
                )
            conn.execute(_PENDING_DDL)
            if action == "install":
                conn.execute(_DELETED_CACHE_DDL)
                for tbl in table_ops:
                    _install_triggers_for_table(conn, tbl, self_rowid)
                now_ts = int(time.time())
                for sid in pending_ops:
                    conn.execute(
                        f"REPLACE INTO {_PENDING_TABLE}(session_id, updated_at) VALUES (?, ?)",
                        (sid, now_ts),
                    )
                for sid in pending_delete_ops or ():
                    conn.execute(f"DELETE FROM {_PENDING_TABLE} WHERE session_id = ?", (sid,))
            else:
                for tbl in table_ops:
                    _uninstall_triggers_for_table(conn, tbl)
                for sid in [*pending_ops, *(pending_delete_ops or ())]:
                    conn.execute(f"DELETE FROM {_PENDING_TABLE} WHERE session_id = ?", (sid,))
            conn.commit()
            post_check = conn.execute("PRAGMA quick_check").fetchall()
            if post_check != [("ok",)]:
                raise LocalSQLCipherRealtimeError(
                    f"Post-write integrity check failed for {db_file.name}: {post_check}"
                )
        finally:
            conn.close()

        modified_plain = plain_path.read_bytes()
    encrypted = _encrypt_plaintext_sqlite(modified_plain, crypto)

    _backup_message_db(db_file, account)
    _atomic_write_bytes(db_file, encrypted)
    for suffix in ("-wal", "-shm"):
        stale = Path(f"{db_file}{suffix}")
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass


def execute_macos_anti_revoke_action(
    action: str,
    account: str,
    session_ids: list[str],
    *,
    db_storage_dir: Path,
    native_wxid: str,
    hex_key: str,
    is_wechat_running: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Install or uninstall WeChat anti-revoke triggers directly via pure-Python SQLCipher."""
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"install", "uninstall"}:
        return {"success": False, "error": f"Unsupported anti-revoke action: {action}"}

    cleaned_ids = [str(s or "").strip() for s in session_ids if str(s or "").strip()]
    if not cleaned_ids:
        return {"success": True, "action": normalized_action, "results": {}, "rows": []}

    running_fn = is_wechat_running or is_wechat_running_macos
    if running_fn():
        return {
            "success": False,
            "code": "wechat_running",
            "error": "为避免写库冲突并保护聊天记录安全，请先完全退出微信客户端（Cmd+Q），再点击安装/卸载防撤回；完成后重新打开微信即可生效。",
        }

    key_bytes = bytes.fromhex(str(hex_key or "").strip())
    msg_dbs = _iter_message_db_files(db_storage_dir)
    if not msg_dbs:
        return {"success": False, "error": f"未找到消息数据库目录: {db_storage_dir / 'message'}"}

    self_candidates = list(dict.fromkeys([native_wxid, account]))
    plans: dict[Path, dict[str, Any]] = {}
    table_to_db: dict[str, Path] = {}
    for db_file in msg_dbs:
        plan = _inspect_db_plan(db_file, db_storage_dir, key_bytes, self_candidates)
        plans[db_file] = plan
        for tbl in plan["tables"]:
            table_to_db.setdefault(tbl, db_file)

    primary_db = msg_dbs[0]
    db_table_ops: dict[Path, list[str]] = {}
    db_pending_ops: dict[Path, list[str]] = {}
    db_pending_delete_ops: dict[Path, list[str]] = {}
    results: dict[str, bool] = {}

    for sid in cleaned_ids:
        tbl_name = f"Msg_{hashlib.md5(sid.encode('utf-8')).hexdigest()}"
        target_db = table_to_db.get(tbl_name)
        if normalized_action == "install":
            if target_db is not None:
                plan = plans[target_db]
                if tbl_name not in plan["installed_tables"]:
                    db_table_ops.setdefault(target_db, []).append(tbl_name)
                for db_file, db_plan in plans.items():
                    if sid in db_plan["pending"]:
                        db_pending_delete_ops.setdefault(db_file, []).append(sid)
                results[sid] = True
            else:
                if any(sid in p["pending"] for p in plans.values()):
                    results[sid] = True
                else:
                    db_pending_ops.setdefault(primary_db, []).append(sid)
                    results[sid] = True
        else:
            if target_db is not None and tbl_name in plans[target_db]["any_trigger_tables"]:
                db_table_ops.setdefault(target_db, []).append(tbl_name)
            for db_file, plan in plans.items():
                if sid in plan["pending"]:
                    db_pending_ops.setdefault(db_file, []).append(sid)
            results[sid] = True

    touched_dbs = set(db_table_ops.keys()) | set(db_pending_ops.keys()) | set(db_pending_delete_ops.keys())
    if touched_dbs:
        if running_fn():
            return {
                "success": False,
                "code": "wechat_running",
                "error": "检测到微信客户端刚刚启动，已中止写入以确保数据库安全。请先完全退出微信后重试。",
            }
        try:
            for db_file in msg_dbs:
                if db_file not in touched_dbs:
                    continue
                _rewrite_db_with_ops(
                    db_file,
                    key_bytes,
                    account,
                    action=normalized_action,
                    table_ops=db_table_ops.get(db_file, []),
                    pending_ops=db_pending_ops.get(db_file, []),
                    pending_delete_ops=db_pending_delete_ops.get(db_file, []),
                    self_rowid=plans[db_file]["self_rowid"],
                )
        except PermissionError:
            return {
                "success": False,
                "error": "缺少修改微信容器目录的磁盘权限。请在“系统设置 -> 隐私与安全性 -> 完全磁盘访问权限”中授权当前终端或应用后重试。",
            }
        except Exception as exc:
            logger.exception("macOS anti-revoke %s failed for %s: %s", normalized_action, account, exc)
            return {"success": False, "error": f"防撤回写入失败（原库未受影响或已留备份）：{exc}"}
        finally:
            LOCAL_SQLCIPHER_READER.invalidate_root(db_storage_dir)

    rows = [{"sessionId": sid, "success": bool(ok)} for sid, ok in results.items()]
    return {"success": True, "action": normalized_action, "results": results, "rows": rows}
