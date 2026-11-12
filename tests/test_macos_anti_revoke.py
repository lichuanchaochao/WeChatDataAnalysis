import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_local_sqlite_realtime import _encrypt_sqlite_file, _init_plain_sqlite_with_reserve

from wechat_decrypt_tool import native_core_realtime
from wechat_decrypt_tool.local_sqlite_realtime import LOCAL_SQLCIPHER_READER
from wechat_decrypt_tool.macos_anti_revoke import (
    _decrypt_db_with_wal,
    execute_macos_anti_revoke_action,
)


class TestMacOSAntiRevoke(unittest.TestCase):
    def setUp(self) -> None:
        native_core_realtime.close_all()

    def tearDown(self) -> None:
        native_core_realtime.close_all()

    def test_install_blocks_peer_recall_allows_self_recall_and_uninstalls_cleanly(self) -> None:
        passphrase = b"\x33" * 32
        salt = b"\x77" * 16
        peer = "wxid_peer_001"
        pending_peer = "wxid_pending_002"
        tbl = f"Msg_{hashlib.md5(peer.encode('utf-8')).hexdigest()}"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / "data"
            db_storage = root / "wxid_self" / "db_storage"
            msg_dir = db_storage / "message"
            msg_dir.mkdir(parents=True)

            plain_db = root / "plain_msg0.db"
            _init_plain_sqlite_with_reserve(plain_db)
            conn = sqlite3.connect(str(plain_db))
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("CREATE TABLE Name2Id(user_name TEXT PRIMARY KEY, is_session INTEGER)")
            conn.execute("INSERT INTO Name2Id(rowid, user_name, is_session) VALUES (1, 'wxid_self', 0)")
            conn.execute("INSERT INTO Name2Id(rowid, user_name, is_session) VALUES (2, ?, 1)", (peer,))
            conn.execute(
                f"CREATE TABLE {tbl}("
                "local_id INTEGER PRIMARY KEY AUTOINCREMENT, server_id INTEGER, local_type INTEGER, "
                "sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER, status INTEGER, "
                "upload_status INTEGER, download_status INTEGER, server_seq INTEGER, origin_source INTEGER, "
                "source TEXT, message_content TEXT, compress_content TEXT, packed_info_data BLOB, "
                "WCDB_CT_message_content INTEGER DEFAULT NULL, WCDB_CT_source INTEGER DEFAULT NULL)"
            )
            conn.execute(
                f"INSERT INTO {tbl}(server_id, local_type, sort_seq, real_sender_id, create_time, status, message_content) "
                "VALUES (1001, 1, 1000, 2, 1700000000, 3, 'important peer message')"
            )
            conn.execute(
                f"INSERT INTO {tbl}(server_id, local_type, sort_seq, real_sender_id, create_time, status, message_content) "
                "VALUES (1002, 1, 2000, 1, 1700000010, 2, 'self message')"
            )
            conn.commit()
            conn.close()

            enc_msg0 = msg_dir / "message_0.db"
            _encrypt_sqlite_file(plain_db, enc_msg0, passphrase, salt)

            with patch.dict(os.environ, {"WECHAT_TOOL_DATA_DIR": str(data_dir)}):
                res = execute_macos_anti_revoke_action(
                    "install",
                    "wxid_self",
                    [peer, pending_peer],
                    db_storage_dir=db_storage,
                    native_wxid="wxid_self",
                    hex_key=passphrase.hex(),
                    is_wechat_running=lambda: False,
                )
                self.assertTrue(res["success"])
                self.assertEqual(res["results"], {peer: True, pending_peer: True})

                # Pre-write safety backup must exist
                backup_files = list((data_dir / "backups" / "anti_revoke").rglob("message_0.db"))
                self.assertTrue(backup_files)

                # Local reader should observe both triggers and pending session
                triggers = LOCAL_SQLCIPHER_READER.query(
                    enc_msg0,
                    db_storage,
                    "SELECT name FROM sqlite_master WHERE type='trigger'",
                    key_bytes=passphrase,
                )
                trigger_names = {row["name"] for row in triggers}
                self.assertIn(f"anti_revoke_capture_delete_{tbl}", trigger_names)
                self.assertIn(f"anti_revoke_block_insert_{tbl}", trigger_names)

                pending_rows = LOCAL_SQLCIPHER_READER.query(
                    enc_msg0,
                    db_storage,
                    "SELECT session_id FROM _weflow_anti_revoke_pending",
                    key_bytes=passphrase,
                )
                self.assertEqual([r["session_id"] for r in pending_rows], [pending_peer])

                # Decrypt modified DB to simulate WeChat runtime recall SQL behavior
                plain_after, _crypto = _decrypt_db_with_wal(enc_msg0, passphrase)
                sim_path = root / "sim_recall.db"
                sim_path.write_bytes(plain_after)
                sim = sqlite3.connect(str(sim_path))
                # Peer recalls server_id=1001: WeChat deletes row and inserts local_type=10000
                sim.execute(f"DELETE FROM {tbl} WHERE server_id = 1001")
                sim.execute(
                    f"INSERT INTO {tbl}(server_id, local_type, sort_seq, real_sender_id, create_time, message_content) "
                    "VALUES (1001, 10000, 1000, 2, 1700000000, 'Peer recalled a message')"
                )
                # Self recalls server_id=1002: should NOT be blocked
                sim.execute(f"DELETE FROM {tbl} WHERE server_id = 1002")
                sim.execute(
                    f"INSERT INTO {tbl}(server_id, local_type, sort_seq, real_sender_id, create_time, message_content) "
                    "VALUES (1002, 10000, 2000, 1, 1700000010, 'You recalled a message')"
                )
                sim.commit()
                rows = sim.execute(
                    f"SELECT server_id, local_type, message_content FROM {tbl} ORDER BY create_time ASC"
                ).fetchall()
                sim.close()

                self.assertEqual(
                    rows,
                    [
                        (1001, 1, "important peer message"),
                        (1001, 10000, "对方尝试撤回此消息"),
                        (1002, 10000, "You recalled a message"),
                    ],
                )

                # Uninstall should drop triggers and remove pending row cleanly
                unres = execute_macos_anti_revoke_action(
                    "uninstall",
                    "wxid_self",
                    [peer, pending_peer],
                    db_storage_dir=db_storage,
                    native_wxid="wxid_self",
                    hex_key=passphrase.hex(),
                    is_wechat_running=lambda: False,
                )
                self.assertTrue(unres["success"])
                triggers_after = LOCAL_SQLCIPHER_READER.query(
                    enc_msg0,
                    db_storage,
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'anti_revoke_%'",
                    key_bytes=passphrase,
                )
                self.assertEqual(triggers_after, [])
                pending_after = LOCAL_SQLCIPHER_READER.query(
                    enc_msg0,
                    db_storage,
                    "SELECT session_id FROM _weflow_anti_revoke_pending",
                    key_bytes=passphrase,
                )
                self.assertEqual(pending_after, [])


if __name__ == "__main__":
    unittest.main()
