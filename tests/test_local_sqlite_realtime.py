import hashlib
import hmac
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wechat_decrypt_tool import anti_revoke_service, native_core_realtime
from wechat_decrypt_tool.local_sqlite_realtime import (
    LOCAL_SQLCIPHER_READER,
    _wal_checksum,
)
from wechat_decrypt_tool.native_core_client import (
    NativeCorePolicyError,
    NativeCoreStatus,
    NativeCoreUnavailableError,
)
from wechat_decrypt_tool.wechat_decrypt import (
    IV_SIZE,
    PAGE_SIZE,
    RESERVE_SIZE,
    SALT_SIZE,
    _compute_page_hmac,
    _derive_mac_key,
    _derive_sqlcipher_enc_key,
)


def _init_plain_sqlite_with_reserve(plain_path: Path, reserve_bytes: int = RESERVE_SIZE) -> None:
    """Create an empty SQLite DB whose header reserves `reserve_bytes` per page for SQLCipher IV+HMAC."""
    conn = sqlite3.connect(str(plain_path))
    conn.execute(f"PRAGMA page_size = {PAGE_SIZE}")
    conn.execute("CREATE TABLE _init(x INTEGER)")
    conn.execute("DROP TABLE _init")
    conn.execute("VACUUM")
    conn.commit()
    conn.close()

    raw = bytearray(plain_path.read_bytes())
    assert len(raw) == PAGE_SIZE
    raw[20] = reserve_bytes
    usable_end = PAGE_SIZE - reserve_bytes
    # Update B-tree page 1 cell content offset (byte 105, big-endian uint16)
    struct.pack_into(">H", raw, 105, usable_end)
    # Increment file change counter (offset 24) so SQLite refreshes its cached schema header
    change_cnt = struct.unpack_from(">I", raw, 24)[0] + 1
    struct.pack_into(">I", raw, 24, change_cnt)
    plain_path.write_bytes(bytes(raw))


def _encrypt_sqlite_file(plain_path: Path, enc_path: Path, passphrase: bytes, salt: bytes) -> tuple[bytes, bytes]:
    raw = bytearray(plain_path.read_bytes())
    assert len(raw) % PAGE_SIZE == 0 and len(raw) >= PAGE_SIZE
    # Clear reserve area just like SQLCipher reserve=80 expects
    enc_key = _derive_sqlcipher_enc_key(passphrase, salt)
    mac_key = _derive_mac_key(enc_key, salt)
    backend = default_backend()
    out = bytearray()
    total_pages = len(raw) // PAGE_SIZE
    for cur in range(total_pages):
        pgno = cur + 1
        page = bytearray(raw[cur * PAGE_SIZE : (cur + 1) * PAGE_SIZE])
        iv = bytes((pgno + i) & 0xFF for i in range(IV_SIZE))
        offset = SALT_SIZE if pgno == 1 else 0
        plain_slice = bytes(page[offset : PAGE_SIZE - RESERVE_SIZE])
        encryptor = Cipher(algorithms.AES(enc_key), modes.CBC(iv), backend=backend).encryptor()
        ciphertext = encryptor.update(plain_slice) + encryptor.finalize()
        enc_page = bytearray(PAGE_SIZE)
        if pgno == 1:
            enc_page[:SALT_SIZE] = salt
        enc_page[offset : PAGE_SIZE - RESERVE_SIZE] = ciphertext
        enc_page[PAGE_SIZE - RESERVE_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE] = iv
        enc_page[PAGE_SIZE - 64 :] = _compute_page_hmac(mac_key, bytes(enc_page), pgno)
        out.extend(enc_page)
    enc_path.write_bytes(bytes(out))
    return enc_key, mac_key


def _build_encrypted_wal(
    plain_wal_path: Path,
    enc_wal_path: Path,
    enc_key: bytes,
    mac_key: bytes,
    salt: bytes,
) -> None:
    wb = bytearray(plain_wal_path.read_bytes())
    assert len(wb) >= 32
    magic, fmt_ver, pg_sz, ckpt_seq, s1, s2, _c1, _c2 = struct.unpack(">8I", wb[:32])
    assert pg_sz == PAGE_SIZE
    be = magic == 0x377F0683
    backend = default_backend()

    out = bytearray(wb[:32])
    sum0, sum1 = _wal_checksum(out[:24], 0, 0, be)
    struct.pack_into(">2I", out, 24, sum0, sum1)

    frame_size = 24 + PAGE_SIZE
    n_frames = (len(wb) - 32) // frame_size
    for idx in range(n_frames):
        off = 32 + idx * frame_size
        f_hdr = bytearray(wb[off : off + 24])
        pgno, _csz, fs1, fs2, _fc1, _fc2 = struct.unpack(">6I", f_hdr)
        if fs1 != s1 or fs2 != s2:
            break
        plain_pg = bytes(wb[off + 24 : off + frame_size])
        iv = bytes((pgno + idx + 7 + i) & 0xFF for i in range(IV_SIZE))
        offset = SALT_SIZE if pgno == 1 else 0
        encryptor = Cipher(algorithms.AES(enc_key), modes.CBC(iv), backend=backend).encryptor()
        ciphertext = encryptor.update(plain_pg[offset : PAGE_SIZE - RESERVE_SIZE]) + encryptor.finalize()
        enc_pg = bytearray(PAGE_SIZE)
        if pgno == 1:
            enc_pg[:SALT_SIZE] = salt
        enc_pg[offset : PAGE_SIZE - RESERVE_SIZE] = ciphertext
        enc_pg[PAGE_SIZE - RESERVE_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE] = iv
        enc_pg[PAGE_SIZE - 64 :] = _compute_page_hmac(mac_key, bytes(enc_pg), pgno)

        sum0, sum1 = _wal_checksum(f_hdr[:8], sum0, sum1, be)
        sum0, sum1 = _wal_checksum(bytes(enc_pg), sum0, sum1, be)
        struct.pack_into(">2I", f_hdr, 16, sum0, sum1)
        out.extend(f_hdr)
        out.extend(enc_pg)

    enc_wal_path.write_bytes(bytes(out))


class TestLocalSQLiteRealtime(unittest.TestCase):
    def setUp(self) -> None:
        native_core_realtime.close_all()

    def tearDown(self) -> None:
        native_core_realtime.close_all()

    def test_live_reader_decrypts_main_and_committed_wal_frames(self) -> None:
        passphrase = b"\x42" * 32
        salt = b"\x11" * 16

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / "data"
            db_storage = root / "wxid_demo" / "db_storage"
            session_dir = db_storage / "session"
            session_dir.mkdir(parents=True)

            plain_db = root / "plain_session.db"
            _init_plain_sqlite_with_reserve(plain_db)
            conn = sqlite3.connect(str(plain_db))
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                "CREATE TABLE SessionTable (username TEXT PRIMARY KEY, summary TEXT, sort_timestamp INTEGER, payload BLOB)"
            )
            conn.execute(
                "INSERT INTO SessionTable VALUES ('wxid_alice', 'initial-msg', 100, ?)",
                (b"\x01\x02\x03\x04",),
            )
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

            enc_db = session_dir / "session.db"
            enc_key, mac_key = _encrypt_sqlite_file(plain_db, enc_db, passphrase, salt)

            with patch.dict(os.environ, {"WECHAT_TOOL_DATA_DIR": str(data_dir)}):
                rows = LOCAL_SQLCIPHER_READER.query(
                    enc_db,
                    db_storage,
                    "SELECT username, summary, sort_timestamp, payload FROM SessionTable ORDER BY sort_timestamp DESC",
                    key_bytes=passphrase,
                    cached_raw_key=enc_key,
                )
                self.assertEqual(
                    rows,
                    [
                        {
                            "username": "wxid_alice",
                            "summary": "initial-msg",
                            "sort_timestamp": 100,
                            "payload": b"\x01\x02\x03\x04",
                        }
                    ],
                )

                # Now append an uncheckpointed WAL transaction (simulating WeChat receiving a new message)
                conn2 = sqlite3.connect(str(plain_db))
                conn2.execute("PRAGMA journal_mode = WAL")
                conn2.execute("PRAGMA wal_autocheckpoint = 0")
                conn2.execute(
                    "INSERT INTO SessionTable VALUES ('wxid_bob', 'wal-realtime-msg', 200, ?)",
                    (b"\xaa\xbb",),
                )
                conn2.commit()
                plain_wal = Path(f"{plain_db}-wal")
                enc_wal = Path(f"{enc_db}-wal")
                _build_encrypted_wal(plain_wal, enc_wal, enc_key, mac_key, salt)
                conn2.close()

                updated_rows = LOCAL_SQLCIPHER_READER.query(
                    enc_db,
                    db_storage,
                    "SELECT username, summary, sort_timestamp, payload FROM SessionTable ORDER BY sort_timestamp DESC",
                    key_bytes=passphrase,
                    cached_raw_key=enc_key,
                )
                self.assertEqual(
                    updated_rows,
                    [
                        {
                            "username": "wxid_bob",
                            "summary": "wal-realtime-msg",
                            "sort_timestamp": 200,
                            "payload": b"\xaa\xbb",
                        },
                        {
                            "username": "wxid_alice",
                            "summary": "initial-msg",
                            "sort_timestamp": 100,
                            "payload": b"\x01\x02\x03\x04",
                        },
                    ],
                )

    def test_native_core_realtime_switches_to_local_reader_when_license_unavailable(self) -> None:
        passphrase = b"\x55" * 32
        salt = b"\x22" * 16

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / "data"
            db_storage = root / "wxid_demo" / "db_storage"
            session_dir = db_storage / "session"
            session_dir.mkdir(parents=True)

            plain_db = root / "plain_session.db"
            _init_plain_sqlite_with_reserve(plain_db)
            conn = sqlite3.connect(str(plain_db))
            conn.execute(
                "CREATE TABLE SessionTable (username TEXT PRIMARY KEY, sort_timestamp INTEGER)"
            )
            conn.execute("INSERT INTO SessionTable VALUES ('wxid_friend', 999)")
            conn.commit()
            conn.close()

            enc_db = session_dir / "session.db"
            _encrypt_sqlite_file(plain_db, enc_db, passphrase, salt)

            class _ExpiredClient:
                def open_database(self, *_args, **_kwargs):
                    raise NativeCorePolicyError(
                        "license required",
                        status=int(NativeCoreStatus.LICENSE_REQUIRED),
                    )

            with (
                patch.dict(os.environ, {"WECHAT_TOOL_DATA_DIR": str(data_dir)}),
                patch.object(native_core_realtime, "managed_native_core_operation", side_effect=lambda **_kw: __import__("contextlib").nullcontext()),
                patch.object(native_core_realtime, "get_native_core_client", return_value=_ExpiredClient()),
                patch.object(
                    native_core_realtime,
                    "refresh_native_core_lease",
                    side_effect=NativeCoreUnavailableError("Native core license service retry is delayed after a network failure."),
                ) as refresh_mock,
            ):
                handle = native_core_realtime.open_account(
                    account="wxid_demo",
                    native_wxid="wxid_demo",
                    db_storage_dir=db_storage,
                    session_db_path=enc_db,
                    key_hex=passphrase.hex(),
                )
                self.assertTrue(native_core_realtime._is_local_realtime_fallback_active())
                sessions = native_core_realtime.get_sessions(handle)
                self.assertEqual(sessions, [{"username": "wxid_friend", "sort_timestamp": 999}])
                # Second call should NOT hit refresh_native_core_lease again once latched.
                self.assertEqual(refresh_mock.call_count, 1)

    def test_macos_anti_revoke_install_requires_wechat_quit_when_running(self) -> None:
        with (
            patch.object(anti_revoke_service.sys, "platform", "darwin"),
            patch.object(
                anti_revoke_service,
                "_resolve_account_info",
                return_value=(Path("/tmp/db_storage"), "wxid_demo", "11" * 32),
            ),
            patch(
                "wechat_decrypt_tool.macos_anti_revoke.is_wechat_running_macos",
                return_value=True,
            ),
        ):
            res = anti_revoke_service.install_anti_revoke_triggers("wxid_demo", ["wxid_a"])
        self.assertFalse(res.get("success"))
        self.assertIn("退出微信", str(res.get("error") or ""))


if __name__ == "__main__":
    unittest.main()
