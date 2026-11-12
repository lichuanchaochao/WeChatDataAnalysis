import os
import sqlite3
import struct
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient

from wechat_decrypt_tool import anti_revoke_service
from wechat_decrypt_tool.routers.chat_media import router as chat_media_router


ROOT = Path(__file__).resolve().parents[1]


def _make_png(width: int, height: int) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    raw_rows = b"".join(b"\x00" + (b"\xff\x00\x00\xff" * width) for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw_rows)) + chunk(b"IEND", b"")


def _seed_media_account(root: Path, account: str = "wxid_test", username: str = "wxid_peer") -> tuple[Path, Path]:
    account_dir = root / "output" / "databases" / account
    wxid_dir = root / "wxid_source"
    account_dir.mkdir(parents=True, exist_ok=True)
    wxid_dir.mkdir(parents=True, exist_ok=True)

    c_conn = sqlite3.connect(str(account_dir / "contact.db"))
    c_conn.execute("CREATE TABLE contact (username TEXT PRIMARY KEY, nick_name TEXT, remark TEXT)")
    c_conn.execute("INSERT INTO contact VALUES (?, ?, '')", (account, "Self"))
    c_conn.execute("INSERT INTO contact VALUES (?, ?, '')", (username, "Peer"))
    c_conn.commit()
    c_conn.close()

    s_conn = sqlite3.connect(str(account_dir / "session.db"))
    s_conn.execute("CREATE TABLE SessionTable (username TEXT PRIMARY KEY, summary TEXT, last_timestamp INTEGER)")
    s_conn.execute("INSERT INTO SessionTable VALUES (?, 'hi', 1700000000)", (username,))
    s_conn.commit()
    s_conn.close()

    (account_dir / "_source.json").write_text(f'{{"wxid_dir": "{wxid_dir.as_posix()}"}}', encoding="utf-8")
    return account_dir, wxid_dir


def test_chat_image_resolution_header_for_thumb_vs_hd() -> None:
    app = FastAPI()
    app.include_router(chat_media_router)

    with TemporaryDirectory() as td:
        root = Path(td)
        account = "wxid_test"
        username = "wxid_peer"
        md5_thumb = "11111111111111111111111111111111"
        md5_hd = "22222222222222222222222222222222"
        md5_missing = "33333333333333333333333333333333"

        account_dir, _ = _seed_media_account(root, account=account, username=username)
        res_dir = account_dir / "resource"
        thumb_dir = res_dir / md5_thumb[:2]
        thumb_dir.mkdir(parents=True, exist_ok=True)
        (thumb_dir / f"{md5_thumb}.png").write_bytes(_make_png(8, 8))
        (thumb_dir / f"{md5_thumb}.quality.json").write_text('{"thumbnail": true}', encoding="utf-8")

        hd_dir = res_dir / md5_hd[:2]
        hd_dir.mkdir(parents=True, exist_ok=True)
        (hd_dir / f"{md5_hd}.png").write_bytes(_make_png(32, 32))
        (hd_dir / f"{md5_hd}.quality.json").write_text('{"thumbnail": false}', encoding="utf-8")

        prev_data = os.environ.get("WECHAT_TOOL_DATA_DIR")
        client = TestClient(app)
        try:
            os.environ["WECHAT_TOOL_DATA_DIR"] = str(root)

            r_thumb = client.get(
                "/api/chat/media/image",
                params={"account": account, "username": username, "md5": md5_thumb, "fetch_remote": "true"},
            )
            assert r_thumb.status_code == 200
            assert r_thumb.headers.get("X-Image-Resolution") == "thumb"
            assert "X-Image-Resolution" in (r_thumb.headers.get("Access-Control-Expose-Headers") or "")

            r_hd = client.get(
                "/api/chat/media/image",
                params={"account": account, "username": username, "md5": md5_hd, "fetch_remote": "true"},
            )
            assert r_hd.status_code == 200
            assert r_hd.headers.get("X-Image-Resolution") == "hd"

            r_miss = client.get(
                "/api/chat/media/image",
                params={"account": account, "username": username, "md5": md5_missing, "fetch_remote": "true"},
            )
            assert r_miss.status_code == 404
            assert "点开该图片" in str(r_miss.json().get("detail") or "")
        finally:
            client.close()
            if prev_data is None:
                os.environ.pop("WECHAT_TOOL_DATA_DIR", None)
            else:
                os.environ["WECHAT_TOOL_DATA_DIR"] = prev_data


def test_anti_revoke_sessions_includes_platform_safety_metadata(monkeypatch) -> None:
    monkeypatch.setattr(anti_revoke_service, "_resolve_account_info", lambda _a: (Path("/tmp"), "wxid_self", "00" * 32))
    monkeypatch.setattr(anti_revoke_service, "open_account", lambda **_kw: object())
    monkeypatch.setattr(anti_revoke_service, "close_account", lambda _h: None)
    monkeypatch.setattr(anti_revoke_service, "_get_installed_trigger_info", lambda *_a, **_kw: (set(), set()))
    monkeypatch.setattr(
        anti_revoke_service,
        "exec_query",
        lambda *_a, **_kw: [{"username": "wxid_friend", "summary": "hi", "last_timestamp": 1}],
    )
    monkeypatch.setattr(anti_revoke_service, "get_display_names", lambda *_a, **_kw: {"wxid_friend": "Friend"})
    monkeypatch.setattr(anti_revoke_service, "get_avatar_urls", lambda *_a, **_kw: {})

    res = anti_revoke_service.get_anti_revoke_sessions("wxid_self")
    assert res["success"] is True
    assert "platform" in res
    assert res["requiresWechatQuit"] is (anti_revoke_service.sys.platform != "win32")
    assert isinstance(res["wechatRunning"], bool)


def test_frontend_components_match_local_media_and_antirecall_contracts() -> None:
    settings = (ROOT / "frontend" / "components" / "SettingsDialog.vue").read_text(encoding="utf-8")
    assert "自动获取原图" not in settings
    assert "toggleCdnImage" not in settings
    assert "纯本地只读" in settings

    msg_content = (ROOT / "frontend" / "components" / "chat" / "MessageContent.vue").read_text(encoding="utf-8")
    assert "刷新本地大图" in msg_content

    chat_msgs = (ROOT / "frontend" / "composables" / "chat" / "useChatMessages.js").read_text(encoding="utf-8")
    assert "X-Image-Resolution" in chat_msgs
    assert "resolution === 'thumb'" in chat_msgs

    antirecall = (ROOT / "frontend" / "pages" / "antirecall.vue").read_text(encoding="utf-8")
    assert "requiresWechatQuit" in antirecall
    assert "wechatRunning" in antirecall
    assert "code === 'wechat_running'" in antirecall
