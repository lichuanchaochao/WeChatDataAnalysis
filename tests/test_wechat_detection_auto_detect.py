import asyncio
import io
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class TestWechatDetectionAutoDetect(unittest.TestCase):
    def test_detection_route_succeeds_when_backend_stdout_uses_cp950(self):
        from wechat_decrypt_tool import wechat_detection as wd
        from wechat_decrypt_tool.routers import wechat_detection as detection_router

        with TemporaryDirectory() as td:
            data_root = Path(td) / "xwechat_files"
            login_dir = data_root / "all_users" / "login" / "wxid_demo"
            login_dir.mkdir(parents=True)
            (login_dir / "key_info.db").write_bytes(b"demo")
            account_dir = data_root / "wxid_demo_suffix"
            db_storage = account_dir / "db_storage"
            db_storage.mkdir(parents=True)
            (db_storage / "contact.db").write_bytes(b"demo")

            cp950_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp950", errors="strict")
            with (
                patch.object(sys, "stdout", cp950_stdout),
                patch.object(wd, "get_process_list", return_value=[]),
            ):
                result = asyncio.run(detection_router.detect_wechat_detailed(str(data_root)))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["statistics"]["total_user_accounts"], 1)
        self.assertEqual(result["data"]["current_account"]["current_account"], "wxid_demo")

    def test_current_account_detection_does_not_write_chinese_debug_text_to_cp950_stdout(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            cp950_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp950", errors="strict")
            with (
                patch.object(sys, "stdout", cp950_stdout),
                patch.object(
                    wd,
                    "parse_global_config",
                    return_value={"wxid": "wxid_demo", "nickname": "demo", "avatar": None},
                ),
            ):
                result = wd.detect_current_logged_in_account(td)

        self.assertEqual(result["current_account"], "wxid_demo")

    def test_recent_key_info_activity_wins_over_stale_global_config(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            data_root = Path(td)
            login_root = data_root / "all_users" / "login"
            stale_dir = login_root / "wxid_stale"
            active_dir = login_root / "wxid_active"
            stale_dir.mkdir(parents=True)
            active_dir.mkdir(parents=True)
            stale_key = stale_dir / "key_info.db"
            active_key = active_dir / "key_info.db"
            stale_key.write_bytes(b"stale")
            active_key.write_bytes(b"active")
            os.utime(stale_key, (100, 100))
            os.utime(active_key, (200, 200))

            with patch.object(
                wd,
                "parse_global_config",
                return_value={"wxid": "wxid_stale", "nickname": "旧账号", "avatar": "old.png"},
            ):
                result = wd.detect_current_logged_in_account(str(data_root))

        self.assertEqual(result["current_account"], "wxid_active")
        self.assertEqual(result["source"], "key_info_mtime")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["global_config_account"], "wxid_stale")
        self.assertIsNone(result.get("nickname"))
        self.assertIsNone(result.get("avatar"))

    def test_key_info_wal_counts_as_recent_account_activity(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            login_root = Path(td) / "all_users" / "login"
            first_dir = login_root / "wxid_first"
            active_dir = login_root / "wxid_active"
            first_dir.mkdir(parents=True)
            active_dir.mkdir(parents=True)
            first_key = first_dir / "key_info.db"
            active_key = active_dir / "key_info.db"
            active_wal = active_dir / "key_info.db-wal"
            first_key.write_bytes(b"first")
            active_key.write_bytes(b"active")
            active_wal.write_bytes(b"wal")
            os.utime(first_key, (300, 300))
            os.utime(active_key, (100, 100))
            os.utime(active_wal, (400, 400))

            with patch.object(wd, "parse_global_config", return_value=None):
                result = wd.detect_current_logged_in_account(td)

        self.assertEqual(result["current_account"], "wxid_active")
        self.assertEqual(result["latest_time"], 400)
        self.assertEqual(result["source"], "key_info_mtime")
        self.assertEqual(result["confidence"], "medium")
        self.assertIsNone(result["global_config_account"])

    def test_global_config_is_used_as_fallback_and_keeps_profile(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            parsed = {"wxid": "wxid_saved", "nickname": "已保存", "avatar": "saved.png"}
            with patch.object(wd, "parse_global_config", return_value=parsed):
                result = wd.detect_current_logged_in_account(td)

        self.assertEqual(result["current_account"], "wxid_saved")
        self.assertEqual(result["source"], "global_config")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["global_config_account"], "wxid_saved")
        self.assertEqual(result["nickname"], "已保存")
        self.assertEqual(result["avatar"], "saved.png")

    def test_macos_process_probe_accepts_wechat_process_name(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            process_cwd = Path(td) / "runtime"
            data_root = process_cwd / "xwechat_files"
            db_storage = data_root / "wxid_process_demo" / "db_storage"
            db_storage.mkdir(parents=True)

            process = unittest.mock.Mock()
            process.cwd.return_value = str(process_cwd)
            with (
                patch.object(wd.sys, "platform", "darwin"),
                patch.object(wd, "_build_auto_detect_scan_paths", return_value=[]),
                patch.object(wd, "get_process_list", return_value=[(42, "WeChat")]),
                patch.object(wd.psutil, "Process", return_value=process),
            ):
                detected_dirs = wd.auto_detect_wechat_data_dirs()

            self.assertEqual(detected_dirs, [str(data_root)])
            process.cwd.assert_called_once_with()

    def test_detect_wechat_installation_finds_nested_custom_data_root(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            nested_scan_root = Path(td) / "abc"
            wechat_parent = nested_scan_root / "wechatMSG"
            xwechat_root = wechat_parent / "xwechat_files"

            login_dir = xwechat_root / "all_users" / "login" / "wxid_demo"
            login_dir.mkdir(parents=True, exist_ok=True)
            (login_dir / "key_info.db").write_bytes(b"demo")

            account_dir = xwechat_root / "wxid_demo_nested"
            account_dir.mkdir(parents=True, exist_ok=True)
            (account_dir / "contact.db").write_bytes(b"demo")

            with (
                patch.object(wd, "_build_auto_detect_scan_paths", return_value=[str(nested_scan_root)]),
                patch.object(wd, "get_process_list", return_value=[]),
                patch.object(wd, "_get_xwechat_data_dir_from_config", return_value=None),
            ):
                detected_dirs = wd.auto_detect_wechat_data_dirs()
                result = wd.detect_wechat_installation()

            self.assertEqual(detected_dirs, [str(wechat_parent)])
            self.assertEqual(result["total_accounts"], 1)
            self.assertEqual(result["accounts"][0]["account_name"], "wxid_demo")
            self.assertEqual(result["accounts"][0]["data_dir"], str(account_dir))
            self.assertEqual(result["total_databases"], 1)

    def test_macos_detects_accounts_nested_under_xwechat_files(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            version_root = Path(td) / "2.0b4.0.9"
            key_value_dir = version_root / "KeyValue" / "account_hash"
            key_value_dir.mkdir(parents=True)
            (key_value_dir / "KeyValue.db").write_bytes(b"demo")
            account_dir = version_root / "xwechat_files" / "wxid_demo_abcd"
            db_storage = account_dir / "db_storage"
            db_storage.mkdir(parents=True)
            (db_storage / "contact.db").write_bytes(b"demo")

            with (
                patch.object(wd.sys, "platform", "darwin"),
                patch.object(wd, "_build_auto_detect_scan_paths", return_value=[str(version_root)]),
                patch.object(wd, "get_process_list", return_value=[]),
            ):
                detected_dirs = wd.auto_detect_wechat_data_dirs()
                accounts = wd.detect_wechat_accounts_from_data_root(str(version_root))

            self.assertEqual(detected_dirs, [str(version_root)])
            self.assertEqual([item["account_name"] for item in accounts], ["wxid_demo_abcd"])
            self.assertEqual(accounts[0]["data_dir"], str(account_dir))
            self.assertEqual(accounts[0]["database_count"], 1)


    def test_xwechat_config_ini_real_path_returns_data_root(self):
        import hashlib
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            root = Path(td) / "root"
            data_root = root / "xwechat_files"
            data_root.mkdir(parents=True)
            appdata = Path(td) / "appdata"
            config_dir = appdata / "Tencent" / "xwechat" / "config"
            config_dir.mkdir(parents=True)
            ini_name = hashlib.md5(wd.XWECHAT_CONFIG_KEY_NAME.encode("utf-8")).hexdigest() + ".ini"
            (config_dir / ini_name).write_text(str(root), encoding="utf-8")

            with (
                patch.object(wd.sys, "platform", "win32"),
                patch.dict(os.environ, {"APPDATA": str(appdata)}),
            ):
                result = wd._get_xwechat_data_dir_from_config()

        self.assertEqual(result, str(data_root))

    def test_xwechat_config_ini_my_document_token(self):
        import hashlib
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            root = Path(td) / "root"
            data_root = root / "xwechat_files"
            data_root.mkdir(parents=True)
            appdata = Path(td) / "appdata"
            config_dir = appdata / "Tencent" / "xwechat" / "config"
            config_dir.mkdir(parents=True)
            ini_name = hashlib.md5(wd.XWECHAT_CONFIG_KEY_NAME.encode("utf-8")).hexdigest() + ".ini"
            (config_dir / ini_name).write_text("MyDocument:1073741829", encoding="utf-8")

            with (
                patch.object(wd.sys, "platform", "win32"),
                patch.dict(os.environ, {"APPDATA": str(appdata)}),
                patch.object(wd, "_resolve_known_folder", return_value=str(root)),
            ):
                result = wd._get_xwechat_data_dir_from_config()

        self.assertEqual(result, str(data_root))

    def test_xwechat_config_ini_missing_returns_none(self):
        import hashlib
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            appdata = Path(td) / "appdata"
            appdata.mkdir()
            with (
                patch.object(wd.sys, "platform", "win32"),
                patch.dict(os.environ, {"APPDATA": str(appdata)}),
            ):
                result = wd._get_xwechat_data_dir_from_config()

        self.assertIsNone(result)

    def test_xwechat_config_ini_data_root_not_exists_returns_none(self):
        import hashlib
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            root = Path(td) / "root"
            root.mkdir()
            appdata = Path(td) / "appdata"
            config_dir = appdata / "Tencent" / "xwechat" / "config"
            config_dir.mkdir(parents=True)
            ini_name = hashlib.md5(wd.XWECHAT_CONFIG_KEY_NAME.encode("utf-8")).hexdigest() + ".ini"
            (config_dir / ini_name).write_text(str(root), encoding="utf-8")

            with (
                patch.object(wd.sys, "platform", "win32"),
                patch.dict(os.environ, {"APPDATA": str(appdata)}),
            ):
                result = wd._get_xwechat_data_dir_from_config()

        self.assertIsNone(result)

    def test_auto_detect_injects_xwechat_config_dir_first(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            data_root = Path(td) / "xwechat_files"
            data_root.mkdir()
            with (
                patch.object(wd.sys, "platform", "win32"),
                patch.object(wd, "_get_xwechat_data_dir_from_config", return_value=str(data_root)),
                patch.object(wd, "_build_auto_detect_scan_paths", return_value=[]),
                patch.object(wd, "get_process_list", return_value=[]),
            ):
                result = wd.auto_detect_wechat_data_dirs()

        self.assertEqual(result, [str(data_root)])


    def test_parse_global_config_falls_back_to_len_in_crc_meta(self):
        """有的微信版本把 global_config 文件头写成 0，真正的长度在 crc 的 28..32。"""
        import struct
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from wechat_decrypt_tool import wechat_detection as wd

        def varint(n):
            out = bytearray()
            while True:
                b = n & 0x7F
                n >>= 7
                if n:
                    out.append(b | 0x80)
                else:
                    out.append(b)
                    return bytes(out)

        body = bytearray()
        for key_name, value in (("mmkv_key_user_name", "wxid_zero_header"), ("mmkv_key_nick_name", "ZeroHeader")):
            kb = key_name.encode("utf-8"); vb = value.encode("utf-8")
            payload = varint(len(vb)) + vb
            body += varint(len(kb)) + kb + varint(len(payload)) + payload
        plaintext = b"\x00\x00\x00\x00" + bytes(body)
        iv = b"\x22" * 16
        encryptor = Cipher(algorithms.AES(wd._GLOBAL_CONFIG_CRYPT_KEY), modes.CFB(iv)).encryptor()
        encrypted = encryptor.update(plaintext) + encryptor.finalize()

        with TemporaryDirectory() as td:
            config_dir = Path(td) / "all_users" / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "global_config").write_bytes(b"\x00\x00\x00\x00" + encrypted)   # 文件头是 0
            (config_dir / "global_config.crc").write_bytes(
                b"\x00" * 12 + iv + struct.pack("<I", len(encrypted)) + b"\x00" * 12
            )
            result = wd.parse_global_config(td)

        self.assertIsNotNone(result)
        self.assertEqual(result["wxid"], "wxid_zero_header")
        self.assertEqual(result["nickname"], "ZeroHeader")

    def test_parse_global_config_uses_iv_from_crc_meta(self):
        import struct
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from wechat_decrypt_tool import wechat_detection as wd

        def varint(n):
            out = bytearray()
            while True:
                b = n & 0x7F
                n >>= 7
                if n:
                    out.append(b | 0x80)
                else:
                    out.append(b)
                    return bytes(out)

        key = wd._GLOBAL_CONFIG_CRYPT_KEY
        entries = [
            ("mmkv_key_user_name", "wxid_demo"),
            ("mmkv_key_nick_name", "DemoNick"),
            ("mmkv_key_head_img_url", "http://example.com/avatar/0"),
            ("some_other", "value"),
        ]
        body = bytearray()
        for key_name, value in entries:
            key_bytes = key_name.encode("utf-8")
            value_bytes = value.encode("utf-8")
            # 字符串 value 内部还有一层 varint 长度前缀
            value_payload = varint(len(value_bytes)) + value_bytes
            body += varint(len(key_bytes)) + key_bytes + varint(len(value_payload)) + value_payload
        plaintext = b"\x00\x00\x00\x00" + bytes(body)
        iv = b"\x11" * 16
        encryptor = Cipher(algorithms.AES(key), modes.CFB(iv)).encryptor()
        encrypted = encryptor.update(plaintext) + encryptor.finalize()

        with TemporaryDirectory() as td:
            config_dir = Path(td) / "all_users" / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "global_config").write_bytes(struct.pack("<I", len(plaintext)) + encrypted)
            (config_dir / "global_config.crc").write_bytes(b"\x00" * 12 + iv + b"\x00" * 16)

            result = wd.parse_global_config(td)

        self.assertEqual(result, {
            "wxid": "wxid_demo",
            "nickname": "DemoNick",
            "avatar": "http://example.com/avatar/0",
        })

    def test_parse_global_config_missing_crc_returns_none(self):
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            config_dir = Path(td) / "all_users" / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "global_config").write_bytes(b"\x00" * 8)

            result = wd.parse_global_config(td)

        self.assertIsNone(result)

    def test_macos_auto_detect_ignores_unrelated_db_and_backup_dirs(self):
        """确保不会把用户的 .cc-switch / .workbuddy / cdp_profile / 第三方 Backup / 工具自身目录误判为微信账号。"""
        from wechat_decrypt_tool import wechat_detection as wd

        with TemporaryDirectory() as td:
            home = Path(td)
            # 1. Home 下的隐藏工具目录与非微信 Backup
            for hidden_name, db_name in (
                (".cc-switch", "cc-switch.db"),
                (".workbuddy", "workbuddy.db"),
                (".net.gtht.fy.richeasy", "fytrade.db"),
                (".workbuddy-backup-20261022-194047", "backup.db"),
            ):
                d = home / hidden_name
                d.mkdir(parents=True)
                (d / db_name).write_bytes(b"sqlite")
            (home / ".someapp" / "Backup" / "tasks_index-1793959877805-c85cefea").mkdir(parents=True)

            # 2. 桌面中名字含“微信”但实际为浏览器配置目录的子目录
            desktop = home / "Desktop"
            chrome_tool = desktop / "微信记录转单文件_工具" / "cdp_profile_patch"
            chrome_tool.mkdir(parents=True)
            (chrome_tool / "cookies.db").write_bytes(b"sqlite")

            # 3. Downloads 下的非微信下载器及本分析工具源码目录
            downloads = home / "Downloads"
            dy = downloads / "Dy-Downloader"
            dy.mkdir(parents=True)
            (dy / "tasks.db").write_bytes(b"sqlite")

            self_repo = desktop / "01高仿微信WeChatDataAnalysis-main"
            (self_repo / "src" / "wechat_decrypt_tool").mkdir(parents=True)
            dec_out = self_repo / "output" / "databases" / "wxid_real"
            dec_out.mkdir(parents=True)
            (dec_out / "contact.db").write_bytes(b"decrypted")

            # 4. 唯一的真实微信账号目录（在 macOS 容器目录下）
            xwechat_root = (
                home
                / "Library"
                / "Containers"
                / "com.tencent.xinWeChat"
                / "Data"
                / "Documents"
                / "xwechat_files"
            )
            login_dir = xwechat_root / "all_users" / "login"
            (login_dir / "wxid_real").mkdir(parents=True)
            (login_dir / "wxid_real" / "key_info.db").write_bytes(b"key")
            (login_dir / ".DS_Store").write_bytes(b"finder")

            real_acc = xwechat_root / "wxid_real_0847" / "db_storage"
            real_acc.mkdir(parents=True)
            (real_acc / "contact.db").write_bytes(b"contact")
            (real_acc / "message_0.db").write_bytes(b"msg")

            scan_paths = [
                str(xwechat_root),
                str(desktop),
                str(downloads),
                str(home),
            ]
            with (
                patch.object(wd.sys, "platform", "darwin"),
                patch.object(wd, "_build_auto_detect_scan_paths", return_value=scan_paths),
                patch.object(wd, "get_process_list", return_value=[]),
            ):
                detected_dirs = wd.auto_detect_wechat_data_dirs()
                result = wd.detect_wechat_installation()

        self.assertEqual(detected_dirs, [str(xwechat_root)])
        self.assertEqual(result["total_accounts"], 1)
        self.assertEqual(result["accounts"][0]["account_name"], "wxid_real")
        self.assertEqual(result["accounts"][0]["database_count"], 2)


if __name__ == "__main__":
    unittest.main()
