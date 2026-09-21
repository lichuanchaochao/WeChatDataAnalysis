"""Real image payloads exercise selection, byte preservation and cache upgrades."""

import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch
import zipfile

from PIL import Image

from wechat_decrypt_tool.export_images import cache_export_image, select_export_image


MD5 = "a" * 32
USERNAME = "wxid_quality_test"


def payload(width, height, fmt="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), (19, 82, 136)).save(stream, format=fmt)
    return stream.getvalue()


def sources(tmp_path):
    account = tmp_path / "account"
    account.mkdir()
    wxid = tmp_path / "wechat"
    folder = wxid / "msg" / "attach" / hashlib.md5(USERNAME.encode()).hexdigest() / "2026-09" / "Img"
    folder.mkdir(parents=True)
    (account / "_source.json").write_text(json.dumps({"wxid_dir": str(wxid)}))
    cache = account / "resource" / MD5[:2] / f"{MD5}.png"
    cache.parent.mkdir(parents=True)
    return account, folder, cache


def select(account, cache, index=None):
    return select_export_image(account_dir=account, username=USERNAME, md5=MD5,
                               file_id="", initial_source=cache, media_index=index)


def test_cached_thumb_does_not_hide_plain_dat_or_webp(tmp_path):
    account, folder, cache = sources(tmp_path)
    cache.write_bytes(payload(150, 50))
    high = payload(956, 307, "WEBP")
    (folder / f"{MD5}.dat").write_bytes(high)
    result = select(account, cache)
    assert result.data == high
    assert (result.width, result.height, result.extension) == (956, 307, "webp")
    cache_export_image(account, MD5, result)
    assert not cache.exists()
    assert cache.with_suffix(".webp").read_bytes() == high


def test_pixels_beat_misleading_name_and_byte_size(tmp_path):
    account, folder, cache = sources(tmp_path)
    cache.write_bytes(payload(96, 150))
    # A small image with lots of trailing bytes must not beat more pixels.
    (folder / f"{MD5}_hd.dat").write_bytes(payload(100, 100, "JPEG") + b"padding" * 10000)
    large = payload(363, 567)
    (folder / f"{MD5}.dat").write_bytes(large)
    # Same prefix but another identifier must not be selected.
    (folder / f"{MD5}deadbeef.dat").write_bytes(payload(1000, 1000))
    assert select(account, cache).data == large


def test_failed_high_candidate_keeps_valid_cached_image(tmp_path):
    account, folder, cache = sources(tmp_path)
    good = payload(363, 567)
    cache.write_bytes(good)
    (folder / f"{MD5}_h.dat").write_bytes(b"not an image")
    (folder / f"{MD5}_t.dat").write_bytes(payload(96, 150))
    assert select(account, cache).data == good


def test_new_download_overrides_negative_index_without_restart(tmp_path):
    account, folder, cache = sources(tmp_path)
    low = payload(96, 150)
    cache.write_bytes(low)
    index = Mock()
    index.resolve.return_value = None
    assert select(account, cache, index).data == low
    high = payload(363, 567)
    (folder / f"{MD5}.h.dat").write_bytes(high)
    assert select(account, cache, index).data == high


def test_thumbnail_only_is_reported(tmp_path):
    account, folder, cache = sources(tmp_path)
    (folder / f"{MD5}_t.dat").write_bytes(payload(96, 150))
    result = select(account, cache)
    assert result.thumbnail
    assert result.width == 96


def test_zip_exports_exact_bytes_and_source_evidence(tmp_path):
    from wechat_decrypt_tool.chat_export_service import _materialize_media
    account, folder, cache = sources(tmp_path)
    cache.write_bytes(payload(96, 150))
    high = payload(363, 567)
    source = folder / f"{MD5}.dat"
    source.write_bytes(high)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        path, written = _materialize_media(zf=archive, account_dir=account,
            conv_username=USERNAME, kind="image", md5=MD5, file_id="",
            media_written={}, suggested_name="", media_index=None)
        assert written
    with zipfile.ZipFile(stream) as archive:
        assert archive.read(path) == high
        assert archive.read(path + ".source.dat") == source.read_bytes()
        evidence = json.loads(archive.read(path + ".quality.json"))
        assert evidence["sha256"] == hashlib.sha256(high).hexdigest()
        assert evidence["width"] == 363
        assert evidence["height"] == 567
        assert evidence["originalConfirmed"] is False


def test_atomic_write_failure_keeps_previous_cache(tmp_path):
    account, folder, cache = sources(tmp_path)
    previous = payload(96, 150)
    cache.write_bytes(previous)
    (folder / f"{MD5}.dat").write_bytes(payload(363, 567, "WEBP"))
    result = select(account, cache)
    with patch("wechat_decrypt_tool.export_images.os.replace", side_effect=OSError("disk full")):
        try:
            cache_export_image(account, MD5, result)
        except OSError:
            pass
        else:
            raise AssertionError("expected atomic replace failure")
    assert cache.read_bytes() == previous
    assert not list(cache.parent.glob(".image-upgrade-*"))


def test_recheck_upgrades_unchanged_conversation_and_keeps_other_conversation(tmp_path):
    from test_chat_incremental_export import TestChatIncrementalExport as FolderFixture
    fixture = FolderFixture()
    account_name = "wxid_quality_account"
    other = "wxid_other"
    with patch.dict(os.environ, {"WECHAT_TOOL_DATA_DIR": str(tmp_path)}):
        account = fixture._prepare_account(tmp_path, account=account_name, username=USERNAME)
        fixture._add_conversation(account, username=other, display_name="Other")
        service = fixture._reload_export_modules()
        cache = account / "resource" / "aa" / f"{MD5}.jpg"
        low, high = payload(96, 150, "JPEG"), payload(363, 567, "JPEG")
        cache.write_bytes(low)
        output = tmp_path / "exports"
        first = fixture._create_folder_job(service.CHAT_EXPORT_MANAGER,
            account=account_name, usernames=[USERNAME, other], output_dir=output,
            message_types=["image", "text"], include_media=True)
        assert first.status == "done", first.error
        folder = output / "聊天增量测试"
        state = json.loads((folder / ".wechat-chat-export.json").read_text(encoding="utf-8"))
        other_state = next(value for value in state["conversations"].values() if value["displayName"] == "Other")
        other_file = folder / other_state["directory"] / "messages.json"
        other_bytes = other_file.read_bytes()
        other_mtime = other_file.stat().st_mtime_ns
        image_path = folder / "media" / "images" / f"{MD5}.jpg"
        assert image_path.read_bytes() == low
        wxid = tmp_path / "wxid_data" / account_name
        img_dir = wxid / "msg" / "attach" / hashlib.md5(USERNAME.encode()).hexdigest() / "2026-09" / "Img"
        img_dir.mkdir(parents=True)
        encrypted = bytes(value ^ 0x5A for value in high)
        (img_dir / f"{MD5}.dat").write_bytes(encrypted)
        second = fixture._create_folder_job(service.CHAT_EXPORT_MANAGER,
            account=account_name, username=USERNAME, output_dir=output,
            message_types=["image", "text"], include_media=True, recheck_media=True)
        assert second.status == "done", second.error
        assert image_path.read_bytes() == high
        assert Path(str(image_path) + ".source.dat").read_bytes() == encrypted
        assert other_file.read_bytes() == other_bytes
        assert other_file.stat().st_mtime_ns == other_mtime
        state = json.loads((folder / ".wechat-chat-export.json").read_text(encoding="utf-8"))
        for suffix in ("", ".quality.json", ".source.dat"):
            assert len(state["files"][f"media/images/{MD5}.jpg" + suffix]["owners"]) == 1


def test_thumbnail_status_survives_missing_live_source(tmp_path):
    account, folder, cache = sources(tmp_path)
    source = folder / f"{MD5}_t.dat"
    source.write_bytes(payload(96, 150))
    result = select(account, cache)
    cache_export_image(account, MD5, result)
    source.unlink()
    assert select(account, cache).thumbnail
