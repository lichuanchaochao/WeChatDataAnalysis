"""Select local image variants for export; never re-encode ordinary images."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from .image_quality import image_dimensions, image_payload_score
from .logging_config import get_logger
from .media_helpers import (
    MediaPathIndex,
    _detect_image_extension,
    _get_decrypted_resource_path,
    _is_probably_valid_image,
    _normalize_variant_basename,
    _read_and_maybe_decrypt_media,
    _resolve_account_wxid_dir,
    _resolve_media_path_from_hardlink,
)

logger = get_logger(__name__)
_IMAGE_SUFFIXES = {".dat", ".jpg", ".jpeg", ".png", ".gif", ".webp"}
_CACHE_LOCKS = [threading.Lock() for _ in range(64)]


@dataclass(frozen=True)
class ExportImage:
    source: Path
    data: bytes
    extension: str
    width: int
    height: int
    thumbnail: bool


def _same_image_variants(path: Path) -> list[Path]:
    """Exact normalized base matching excludes unrelated prefix matches."""
    base = _normalize_variant_basename(path.stem)
    paths = [path]
    try:
        paths.extend(
            child for child in path.parent.glob(f"{base}*")
            if child.suffix.lower() in _IMAGE_SUFFIXES
            and _normalize_variant_basename(child.stem) == base
            and child.is_file()
        )
    except OSError:
        pass
    return paths


def select_export_image(
    *, account_dir: Path, username: str, md5: str, file_id: str,
    initial_source: Path | None, media_index: MediaPathIndex | None,
) -> ExportImage | None:
    candidates: list[Path] = []
    if initial_source:
        candidates.append(initial_source)
    valid_md5 = bool(re.fullmatch(r"[a-fA-F0-9]{32}", md5 or ""))
    if valid_md5:
        # Include all cached formats, not merely the first extension found.
        for extension in ("jpg", "png", "gif", "webp", "dat"):
            candidates.append(_get_decrypted_resource_path(account_dir, md5.lower(), extension))
    if media_index is not None:
        try:
            source = media_index.resolve(kind="image", md5=md5, file_id=file_id, username=username)
            if source:
                candidates.append(source)
        except Exception:
            logger.debug("Image index lookup failed", exc_info=True)

    wxid_dir = _resolve_account_wxid_dir(account_dir)
    if wxid_dir and valid_md5:
        try:
            source = _resolve_media_path_from_hardlink(
                hardlink_db_path=account_dir / "hardlink.db", wxid_dir=wxid_dir,
                md5=md5, kind="image", username=username or None,
                extra_roots=[wxid_dir / "msg" / "attach", wxid_dir / "cache"],
            )
            if source:
                candidates.append(source)
        except Exception:
            logger.debug("Image hardlink lookup failed", exc_info=True)

    # Probe only this conversation's image folders. A stale/negative index must
    # not hide a large variant downloaded since the previous export.
    bases = {md5.lower()} if valid_md5 else set()
    token = _normalize_variant_basename(Path(str(file_id or "").replace("\\", "/")).stem)
    if re.fullmatch(r"[a-fA-F0-9]{16,64}", token):
        bases.add(token.lower())
    if wxid_dir and username and bases:
        chat_hash = hashlib.md5(username.encode("utf-8")).hexdigest()
        chat_dir = wxid_dir / "msg" / "attach" / chat_hash
        try:
            folders = list(chat_dir.glob("*/Img")) + [chat_dir / "Img"]
            for folder in folders:
                for base in bases:
                    candidates.extend(
                        path for path in folder.glob(f"{base}*")
                        if path.suffix.lower() in _IMAGE_SUFFIXES
                        and _normalize_variant_basename(path.stem) == base
                    )
        except OSError:
            logger.debug("Image conversation probe failed", exc_info=True)

    expanded: list[Path] = []
    for candidate in candidates:
        if candidate.is_file():
            expanded.extend(_same_image_variants(candidate))
    seen: set[str] = set()
    best: ExportImage | None = None
    best_score = (-1, -1)
    for candidate in expanded:
        key = os.path.normcase(str(candidate.resolve()))
        if key in seen:
            continue
        seen.add(key)
        try:
            data, media_type = _read_and_maybe_decrypt_media(
                candidate, account_dir=account_dir, weixin_root=wxid_dir,
            )
            if not media_type.startswith("image/") or not _is_probably_valid_image(data, media_type):
                continue
            score = image_payload_score(data, media_type)
            # When bytes are identical prefer a live DAT over a cache file:
            # retain source evidence and its thumbnail designation on re-export.
            identical_live = bool(best and data == best.data and candidate.suffix.lower() == ".dat"
                                  and best.source.suffix.lower() != ".dat")
            if score < best_score or (score == best_score and not identical_live):
                continue
            width, height = image_dimensions(data, media_type)
            thumbnail = candidate.stem.lower().endswith(("_t", ".t", "_thumb", ".thumb", "_thumbnail", ".thumbnail"))
            try:
                metadata = json.loads(candidate.with_suffix(".quality.json").read_text(encoding="utf-8"))
                if metadata.get("sha256") == hashlib.sha256(data).hexdigest():
                    thumbnail = thumbnail or metadata.get("thumbnail") is True
            except (OSError, ValueError, AttributeError):
                pass
            best = ExportImage(candidate, data, _detect_image_extension(data), width, height, thumbnail)
            best_score = score
        except Exception:
            # One failed large variant must not suppress another valid source.
            logger.debug("Image candidate could not be decoded: %s", candidate.name, exc_info=True)
    return best


def cache_export_image(account_dir: Path, md5: str, image: ExportImage) -> None:
    if not re.fullmatch(r"[a-fA-F0-9]{32}", md5 or ""):
        return
    lock = _CACHE_LOCKS[int(md5[:2], 16) % len(_CACHE_LOCKS)]
    with lock:
        _cache_export_image_locked(account_dir, md5.lower(), image)


def _atomic_write(target: Path, data: bytes) -> None:
    # Replace the new payload before deleting alternate extensions; an interrupted
    # write must leave the previous cache readable.
    fd, temporary = tempfile.mkstemp(prefix=".image-upgrade-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _cache_export_image_locked(account_dir: Path, md5: str, image: ExportImage) -> None:
    target = _get_decrypted_resource_path(account_dir, md5, image.extension)
    target.parent.mkdir(parents=True, exist_ok=True)
    incoming_score = image_payload_score(image.data)
    for extension in ("jpg", "png", "gif", "webp"):
        previous = _get_decrypted_resource_path(account_dir, md5, extension)
        if previous.is_file() and image_payload_score(previous.read_bytes()) > incoming_score:
            return  # Another export may have upgraded the cache in the meantime.
    if not target.is_file() or target.read_bytes() != image.data:
        _atomic_write(target, image.data)
    _atomic_write(target.with_suffix(".quality.json"), json.dumps({
        "sha256": hashlib.sha256(image.data).hexdigest(), "thumbnail": image.thumbnail,
    }).encode("utf-8"))
    for extension in ("jpg", "png", "gif", "webp", "dat"):
        stale = _get_decrypted_resource_path(account_dir, md5, extension)
        if stale != target:
            stale.unlink(missing_ok=True)
