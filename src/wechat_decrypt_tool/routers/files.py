from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from ..chat_accounts import resolve_chat_account_context
from ..chat_helpers import (
    _decode_message_content,
    _extract_xml_tag_or_attr,
    _extract_xml_tag_text,
    _format_session_time,
    _resolve_account_dir,
)
from ..logging_config import get_logger
from .chat_media import (
    _convert_silk_to_browser_audio,
    _resolve_account_db_storage_dir,
    _resolve_account_wxid_dir,
    _resolve_media_path_for_kind,
)

logger = get_logger(__name__)
router = APIRouter()

CategoryType = Literal["all", "doc", "video", "voice", "image", "archive", "other"]
SourceType = Literal["all", "chat", "favorite"]

DOC_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "txt", "csv", "md", "markdown", "epub", "mobi", "wps", "et", "dps", "rtf", "json", "xml", "html", "htm"
}
VIDEO_EXTENSIONS = {"mp4", "mov", "mkv", "avi", "flv", "wmv", "webm", "m4v", "3gp"}
VOICE_EXTENSIONS = {"silk", "mp3", "wav", "m4a", "aac", "ogg", "flac", "amr", "wma", "aud"}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "heic", "svg"}
ARCHIVE_EXTENSIONS = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "dmg"}


def _determine_category(ext: str, render_type: str = "") -> str:
    ext = (ext or "").lower().lstrip(".")
    if ext in DOC_EXTENSIONS or render_type == "doc":
        return "doc"
    if ext in VIDEO_EXTENSIONS or render_type == "video":
        return "video"
    if ext in VOICE_EXTENSIONS or render_type == "voice":
        return "voice"
    if ext in IMAGE_EXTENSIONS or render_type == "image":
        return "image"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    if render_type == "file":
        return "doc" if ext in DOC_EXTENSIONS else "other"
    return "other"


def _format_size(size_bytes: int) -> str:
    if size_bytes < 0:
        return "未知"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _clean_fts_filename(text: str) -> str:
    s = str(text or "").strip()
    # If characters are single-spaced (like FTS segmented text), condense them
    if " " in s:
        tokens = s.split()
        if len(tokens) > 2 and all(len(t) <= 2 for t in tokens[:6]):
            s = "".join(tokens)
    s = re.sub(r"^\[\s*(文件|文档|视频|语音|图片)\s*\]\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def _build_disk_indexes(wxid_dir: Optional[Path]) -> tuple[dict[str, Path], dict[str, Path]]:
    if not wxid_dir or not wxid_dir.exists():
        return {}, {}
    file_map: dict[str, Path] = {}
    fav_map: dict[str, Path] = {}

    # Index msg/file
    msg_file = wxid_dir / "msg" / "file"
    if msg_file.exists():
        for root, _, files in os.walk(msg_file):
            for f in files:
                if not f.startswith("."):
                    p = Path(root) / f
                    file_map[f.lower()] = p

    # Index business/favorite
    fav_dir = wxid_dir / "business" / "favorite"
    if fav_dir.exists():
        for root, _, files in os.walk(fav_dir):
            for f in files:
                if not f.startswith("."):
                    p = Path(root) / f
                    fav_map[f.lower()] = p

    return file_map, fav_map


def _sanitize_path_component(name: str) -> str:
    s = str(name or "").strip()
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = s.strip(". ")
    return s[:80] or "未命名"


class ContactNameResolver:
    def __init__(self, account_dir: Path):
        self.account_dir = account_dir
        self._cache: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        contact_db = self.account_dir / "contact.db"
        if not contact_db.exists():
            return
        try:
            conn = sqlite3.connect(str(contact_db))
            conn.row_factory = sqlite3.Row
            for r in conn.execute("SELECT username, nick_name, remark FROM contact"):
                u = r["username"]
                disp = r["remark"] or r["nick_name"] or u
                if disp:
                    self._cache[u] = str(disp).strip()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to load contact names: {e}")

    def get_name(self, username: str, fallback: str = "") -> str:
        if not username:
            return fallback or "未知"
        self._ensure_loaded()
        return self._cache.get(username) or fallback or username


def _find_chat_disk_file(
    file_map: dict[str, Path],
    wxid_dir: Optional[Path],
    filename: str,
    create_time: int,
    ext: str = "",
) -> Optional[Path]:
    if not filename:
        return None
    # 1. Check in fast in-memory disk file map
    fn_lower = filename.lower()
    if fn_lower in file_map:
        return file_map[fn_lower]

    if not wxid_dir:
        return None

    dt = datetime.fromtimestamp(create_time) if create_time > 0 else datetime.now()
    month_str = dt.strftime("%Y-%m")

    msg_file_dir = wxid_dir / "msg" / "file"
    if msg_file_dir.exists():
        candidate = msg_file_dir / month_str / filename
        if candidate.exists() and candidate.is_file():
            return candidate
        candidate = msg_file_dir / filename
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def _find_favorite_disk_file(
    fav_map: dict[str, Path],
    file_map: dict[str, Path],
    wxid_dir: Optional[Path],
    md5: str,
    filename: str = "",
) -> Optional[Path]:
    md5_lower = (md5 or "").strip().lower()
    if md5_lower and md5_lower in fav_map:
        return fav_map[md5_lower]

    fn_lower = (filename or "").strip().lower()
    if fn_lower:
        if fn_lower in file_map:
            return file_map[fn_lower]
        if fn_lower in fav_map:
            return fav_map[fn_lower]

    return None


def _unwrap_param(val: Any, default: Any) -> Any:
    if hasattr(val, "default"):
        d = getattr(val, "default")
        return default if d is ... else d
    return default if val is None else val


@router.get("/api/files/list", summary="获取聊天与收藏文件统一列表")
async def list_unified_files(
    account: str = Query(..., description="微信账号标识"),
    source: SourceType = Query("all", description="来源筛选：all/chat/favorite"),
    category: CategoryType = Query("all", description="类型筛选：all/doc/video/voice/image/archive/other"),
    keyword: str = Query("", description="搜索关键词（文件名/来源/发送人）"),
    source_id: Optional[str] = Query(None, description="按具体群聊或好友wxid筛选"),
    exclude_sources: Optional[str] = Query(None, description="排除/隐藏的来源wxid列表，英文逗号分隔"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100000),
):
    source = str(_unwrap_param(source, "all") or "all").lower()
    category = str(_unwrap_param(category, "all") or "all").lower()
    keyword = str(_unwrap_param(keyword, "") or "").strip()
    source_id = str(_unwrap_param(source_id, "") or "").strip()
    exclude_raw = str(_unwrap_param(exclude_sources, "") or "").strip()
    exclude_set = {s.strip() for s in exclude_raw.split(",") if s.strip()}
    try:
        offset = int(_unwrap_param(offset, 0))
    except Exception:
        offset = 0
    try:
        limit = int(_unwrap_param(limit, 50))
    except Exception:
        limit = 50
    account_dir = _resolve_account_dir(account)
    if not account_dir.exists():
        raise HTTPException(status_code=404, detail="Account directory not found.")

    wxid_dir = _resolve_account_wxid_dir(account_dir)
    file_map, fav_map = _build_disk_indexes(wxid_dir)
    contact_resolver = ContactNameResolver(account_dir)

    all_items: list[dict[str, Any]] = []
    source_stats: dict[str, dict[str, Any]] = {}

    # 1. Fetch Chat Files if source is 'all' or 'chat'
    if source in ("all", "chat"):
        index_db_path = account_dir / "chat_search_index.db"
        if index_db_path.exists():
            try:
                conn = sqlite3.connect(str(index_db_path))
                conn.row_factory = sqlite3.Row
                # Select files, videos, voices
                query = (
                    "SELECT rowid, text, username, render_type, create_time, local_id, server_id, sender_username "
                    "FROM message_meta WHERE render_type IN ('file', 'video', 'voice') "
                    "ORDER BY create_time DESC"
                )
                rows = conn.execute(query).fetchall()
                conn.close()

                for r in rows:
                    raw_text = r["text"] or ""
                    clean_name = _clean_fts_filename(raw_text)
                    rt = r["render_type"]
                    ctime = int(r["create_time"] or 0)
                    sid = str(r["server_id"] or "")
                    lid = str(r["local_id"] or "")
                    username = str(r["username"] or "")
                    sender_u = str(r["sender_username"] or "")

                    # Determine extension and category
                    ext = ""
                    if "." in clean_name:
                        ext = clean_name.rsplit(".", 1)[-1].lower()
                    elif rt == "video":
                        ext = "mp4"
                        clean_name = f"视频_{ctime}.mp4"
                    elif rt == "voice":
                        ext = "mp3"
                        clean_name = f"语音_{ctime}.mp3"

                    cat = _determine_category(ext, rt)
                    if category != "all" and cat != category:
                        continue

                    # Filter keyword
                    source_title = contact_resolver.get_name(username, fallback=username)
                    sender_name = contact_resolver.get_name(sender_u, fallback=sender_u)

                    if keyword:
                        kw = keyword.lower()
                        if (
                            kw not in clean_name.lower()
                            and kw not in source_title.lower()
                            and kw not in sender_name.lower()
                        ):
                            continue

                    # Record source stats for dropdown selection
                    if username:
                        if username not in source_stats:
                            source_stats[username] = {
                                "source_id": username,
                                "source_title": source_title,
                                "is_group": username.endswith("@chatroom"),
                                "count": 0,
                            }
                        source_stats[username]["count"] += 1

                    # Apply source_id filter or exclude_sources filter
                    if source_id and username != source_id:
                        continue
                    if username in exclude_set:
                        continue

                    # Check disk existence
                    disk_path = _find_chat_disk_file(file_map, wxid_dir, clean_name, ctime, ext)
                    size_bytes = disk_path.stat().st_size if disk_path and disk_path.exists() else -1

                    item = {
                        "id": f"chat_{lid}_{sid}",
                        "source_type": "chat",
                        "source_id": username,
                        "source_title": source_title,
                        "is_group": username.endswith("@chatroom"),
                        "sender_username": sender_u,
                        "sender_name": sender_name,
                        "filename": clean_name,
                        "extension": ext,
                        "category": cat,
                        "size_bytes": size_bytes,
                        "size_formatted": _format_size(size_bytes),
                        "create_time": ctime,
                        "time_formatted": datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M:%S") if ctime else "",
                        "is_local_exists": bool(disk_path and disk_path.exists()),
                        "local_path": str(disk_path) if disk_path else "",
                        "server_id": sid,
                        "local_id": lid,
                    }
                    all_items.append(item)
            except Exception as e:
                logger.warning(f"Error querying chat files: {e}")

    # 2. Fetch Favorite Files if source is 'all' or 'favorite'
    if source in ("all", "favorite"):
        fav_db_path = account_dir / "favorite.db"
        if fav_db_path.exists():
            try:
                conn = sqlite3.connect(str(fav_db_path))
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT local_id, server_id, type, fromusr, realchatname, update_time, content FROM fav_db_item ORDER BY update_time DESC"
                ).fetchall()
                conn.close()

                for r in rows:
                    content = r["content"]
                    if not content:
                        continue
                    lid = str(r["local_id"])
                    sid = str(r["server_id"] or "")
                    utime = int(r["update_time"] or 0)
                    fromusr = str(r["fromusr"] or "")
                    realchat = str(r["realchatname"] or "")

                    source_owner = realchat or fromusr
                    source_title = contact_resolver.get_name(source_owner, fallback=source_owner)

                    try:
                        root = ET.fromstring(content)
                    except Exception:
                        continue

                    title = root.findtext("title") or root.findtext("favtitle") or ""
                    dataitems = root.findall(".//dataitem")
                    for d_idx, d in enumerate(dataitems):
                        dtype = d.get("datatype") or ""
                        # We care about files(8), videos(5), voice(4), images(2)
                        dtitle = d.findtext("datatitle") or title or ""
                        dext = (d.findtext("datafmt") or d.findtext("dataext") or "").lower().lstrip(".")
                        dsize_str = d.findtext("fullsize") or d.findtext("datasize") or "-1"
                        try:
                            dsize = int(dsize_str)
                        except Exception:
                            dsize = -1
                        dmd5 = d.findtext("fullmd5") or d.findtext("head256md5") or ""

                        # If title has extension, use it
                        clean_name = dtitle
                        if not clean_name:
                            clean_name = f"收藏附件_{lid}_{d_idx + 1}"
                            if dext:
                                clean_name += f".{dext}"
                        elif "." in clean_name and not dext:
                            dext = clean_name.rsplit(".", 1)[-1].lower()
                        elif dext and not clean_name.lower().endswith(f".{dext}"):
                            clean_name = f"{clean_name}.{dext}"

                        render_type = "file" if dtype == "8" else "video" if dtype in ("4", "5") else "voice" if dtype == "3" else "image" if dtype == "2" else "other"
                        cat = _determine_category(dext, render_type)
                        if category != "all" and cat != category:
                            continue

                        if keyword:
                            kw = keyword.lower()
                            if (
                                kw not in clean_name.lower()
                                and kw not in source_title.lower()
                                and kw not in title.lower()
                            ):
                                continue

                        fav_source_id = realchat or fromusr or f"fav_{lid}"
                        if fav_source_id:
                            if fav_source_id not in source_stats:
                                source_stats[fav_source_id] = {
                                    "source_id": fav_source_id,
                                    "source_title": source_title or f"微信收藏 #{lid}",
                                    "is_group": fav_source_id.endswith("@chatroom"),
                                    "count": 0,
                                }
                            source_stats[fav_source_id]["count"] += 1

                        if source_id and fav_source_id != source_id:
                            continue
                        if fav_source_id in exclude_set:
                            continue

                        disk_path = _find_favorite_disk_file(fav_map, file_map, wxid_dir, dmd5, clean_name)
                        if disk_path and disk_path.exists() and dsize <= 0:
                            dsize = disk_path.stat().st_size

                        item = {
                            "id": f"fav_{lid}_{d_idx}",
                            "source_type": "favorite",
                            "source_id": fav_source_id,
                            "source_title": f"收藏 · {title}" if title else f"微信收藏 #{lid}",
                            "is_group": fav_source_id.endswith("@chatroom"),
                            "sender_username": source_owner,
                            "sender_name": source_title,
                            "filename": clean_name,
                            "extension": dext,
                            "category": cat,
                            "size_bytes": dsize,
                            "size_formatted": _format_size(dsize),
                            "create_time": utime,
                            "time_formatted": datetime.fromtimestamp(utime).strftime("%Y-%m-%d %H:%M:%S") if utime else "",
                            "is_local_exists": bool(disk_path and disk_path.exists()),
                            "local_path": str(disk_path) if disk_path else "",
                            "server_id": sid,
                            "local_id": lid,
                            "md5": dmd5,
                        }
                        all_items.append(item)
            except Exception as e:
                logger.warning(f"Error querying favorite files: {e}")

    # Sort all items by create_time DESC
    all_items.sort(key=lambda x: x.get("create_time", 0), reverse=True)

    # Compute category & source statistics
    summary = {
        "total_count": len(all_items),
        "chat_count": sum(1 for it in all_items if it["source_type"] == "chat"),
        "favorite_count": sum(1 for it in all_items if it["source_type"] == "favorite"),
        "doc_count": sum(1 for it in all_items if it["category"] == "doc"),
        "video_count": sum(1 for it in all_items if it["category"] == "video"),
        "voice_count": sum(1 for it in all_items if it["category"] == "voice"),
        "image_count": sum(1 for it in all_items if it["category"] == "image"),
        "archive_count": sum(1 for it in all_items if it["category"] == "archive"),
        "other_count": sum(1 for it in all_items if it["category"] == "other"),
        "local_ready_count": sum(1 for it in all_items if it["is_local_exists"]),
    }

    available_sources = sorted(source_stats.values(), key=lambda x: x["count"], reverse=True)
    paginated = all_items[offset : offset + limit]
    return {
        "status": "success",
        "total": len(all_items),
        "offset": offset,
        "limit": limit,
        "summary": summary,
        "available_sources": available_sources[:500],
        "items": paginated,
    }


@router.get("/api/files/download", summary="下载指定文件")
async def download_file(
    account: str = Query(...),
    id: str = Query(...),
):
    account_dir = _resolve_account_dir(account)
    wxid_dir = _resolve_account_wxid_dir(account_dir)
    res = await list_unified_files(account=account, source="all", category="all", limit=5000)
    target_item = next((it for it in res["items"] if it["id"] == id), None)
    if not target_item or not target_item.get("local_path"):
        raise HTTPException(status_code=404, detail="文件不存在或未在本地缓存。")

    p = Path(target_item["local_path"])
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="本地文件缺失。")

    filename = target_item.get("filename") or p.name
    return FileResponse(
        str(p),
        filename=filename,
        media_type="application/octet-stream",
    )


class OpenFileFolderRequest(BaseModel):
    account: str
    id: Optional[str] = None
    path: Optional[str] = None


@router.post("/api/files/open_folder", summary="在系统访达或资源管理器中定位文件")
async def open_file_folder(req: OpenFileFolderRequest):
    target_path: Optional[Path] = None
    if req.path:
        target_path = Path(req.path)
    elif req.id:
        account_dir = _resolve_account_dir(req.account)
        res = await list_unified_files(account=req.account, source="all", category="all", limit=5000)
        target_item = next((it for it in res["items"] if it["id"] == req.id), None)
        if target_item and target_item.get("local_path"):
            target_path = Path(target_item["local_path"])

    if not target_path or not target_path.exists():
        raise HTTPException(status_code=404, detail="未找到目标文件所在目录。")

    try:
        tp = target_path.resolve()
        if os.name == "nt":
            if tp.is_file():
                subprocess.Popen(["explorer.exe", "/select,", str(tp)])
            else:
                subprocess.Popen(["explorer.exe", str(tp)])
        elif sys.platform == "darwin":
            if tp.is_file():
                subprocess.Popen(["open", "-R", str(tp)])
            else:
                subprocess.Popen(["open", str(tp)])
        else:
            raise HTTPException(status_code=400, detail="不支持的系统。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败: {e}")

    return {"status": "success", "path": str(target_path)}


class ExportCategorizedFilesRequest(BaseModel):
    account: str
    source: SourceType = "all"
    category: CategoryType = "all"
    keyword: Optional[str] = ""
    source_id: Optional[str] = None
    exclude_sources: Optional[str] = None
    selected_ids: Optional[list[str]] = None
    target_mode: Literal["folder", "zip"] = "folder"
    custom_dir: Optional[str] = None


@router.post("/api/files/export_categorized", summary="分类导出微信聊天与收藏文件到本地")
async def export_categorized_files(req: ExportCategorizedFilesRequest):
    account_dir = _resolve_account_dir(req.account)
    res = await list_unified_files(
        account=req.account,
        source=req.source,
        category=req.category,
        keyword=req.keyword or "",
        source_id=req.source_id,
        exclude_sources=req.exclude_sources,
        offset=0,
        limit=100000,
    )
    items = res.get("items", [])
    if req.selected_ids:
        selected_set = set(req.selected_ids)
        items = [it for it in items if it["id"] in selected_set]

    # Filter only files that exist locally
    valid_items = [it for it in items if it.get("is_local_exists") and it.get("local_path")]
    if not valid_items:
        raise HTTPException(status_code=400, detail="没有可在本地导出的文件（文件可能未在微信中下载）。")

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"微信文件分类归档_{req.account}_{timestamp_str}"

    if req.custom_dir:
        base_dir = Path(req.custom_dir)
    else:
        # Default to ~/Downloads or output/exported_files
        downloads = Path.home() / "Downloads"
        base_dir = (downloads if downloads.exists() else account_dir / "exported_files") / folder_name

    base_dir.mkdir(parents=True, exist_ok=True)

    # Categories subdirectories
    chat_root = base_dir / "01_聊天文件"
    fav_root = base_dir / "02_微信收藏"

    exported_count = 0
    total_bytes = 0
    manifest_rows: list[dict[str, Any]] = []

    for it in valid_items:
        src_path = Path(it["local_path"])
        if not src_path.exists() or not src_path.is_file():
            continue

        stype = it["source_type"]
        stitle = _sanitize_path_component(it["source_title"])
        sname = _sanitize_path_component(it["sender_name"])
        fname = it["filename"]
        cat = it["category"]

        if stype == "chat":
            # Group or Friend dir
            group_prefix = "[群聊]" if it.get("is_group") else "[私聊]"
            dest_dir = chat_root / f"{group_prefix} {stitle}" / cat
        else:
            # Favorite dir
            dest_dir = fav_root / cat / stitle

        dest_dir.mkdir(parents=True, exist_ok=True)
        # Avoid duplicate filenames
        final_fname = f"[{sname}] {fname}" if stype == "chat" else fname
        final_fname = _sanitize_path_component(final_fname.rsplit(".", 1)[0]) + (f".{it['extension']}" if it.get("extension") else "")
        dest_file = dest_dir / final_fname

        # Copy file
        try:
            shutil.copy2(src_path, dest_file)
            exported_count += 1
            fsize = dest_file.stat().st_size
            total_bytes += fsize
            manifest_rows.append({
                "序号": exported_count,
                "来源分类": "聊天记录" if stype == "chat" else "微信收藏",
                "来源出处": it["source_title"],
                "发送人": it["sender_name"],
                "文件名": fname,
                "文件类型": cat,
                "文件大小": _format_size(fsize),
                "时间": it["time_formatted"],
                "归档相对路径": str(dest_file.relative_to(base_dir)),
            })
        except Exception as e:
            logger.warning(f"Failed to copy file {src_path} -> {dest_file}: {e}")

    # Write CSV manifest (UTF-8 with BOM for Excel)
    manifest_csv = base_dir / "归档文件清单.csv"
    try:
        with open(manifest_csv, "w", encoding="utf-8-sig", newline="") as f:
            if manifest_rows:
                writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
                writer.writeheader()
                writer.writerows(manifest_rows)
    except Exception as e:
        logger.warning(f"Failed to write manifest csv: {e}")

    # If ZIP requested, zip the folder and return zip path
    if req.target_mode == "zip":
        zip_path = base_dir.parent / f"{folder_name}.zip"
        shutil.make_archive(str(base_dir.parent / folder_name), "zip", str(base_dir))
        return {
            "status": "success",
            "mode": "zip",
            "exported_count": exported_count,
            "total_bytes": total_bytes,
            "total_formatted": _format_size(total_bytes),
            "output_path": str(zip_path),
        }

    # Automatically reveal in Finder / Explorer
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(base_dir)])
        elif os.name == "nt":
            subprocess.Popen(["explorer.exe", str(base_dir)])
    except Exception:
        pass

    return {
        "status": "success",
        "mode": "folder",
        "exported_count": exported_count,
        "total_bytes": total_bytes,
        "total_formatted": _format_size(total_bytes),
        "output_path": str(base_dir),
    }
