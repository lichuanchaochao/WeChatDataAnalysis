"""Pure-Python open-source live reader for WeChat SQLCipher 4 + SQLite WAL databases.

Provides a read-only local fallback when the closed-source native broker is
expired, unlicensed, or unreachable offline. Uses the user's already-extracted
database key, caches per-database decrypted base snapshots, and incrementally
overlays committed WAL frames so newly received messages appear immediately.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .app_paths import get_data_dir
from .wechat_decrypt import (
    HMAC_SIZE,
    IV_SIZE,
    PAGE_SIZE,
    RESERVE_SIZE,
    SALT_SIZE,
    SQLITE_HEADER,
    _compute_page_hmac,
    _derive_mac_key,
    _resolve_page1_key_material,
)


_WAL_HEADER_SIZE = 32
_WAL_FRAME_HEADER_SIZE = 24
_WAL_MAGIC_LE = 0x377F0682
_WAL_MAGIC_BE = 0x377F0683
_WAL_FORMAT_VERSION = 3007000
_MAX_SNAPSHOT_RETRIES = 3
_RETRY_SLEEP_SECONDS = 0.015
_CRYPTO_BACKEND = default_backend()


class LocalSQLCipherRealtimeError(RuntimeError):
    """Raised when the pure-Python live SQLCipher + WAL reader cannot serve a query."""


@dataclass
class _MirrorCacheEntry:
    db_stat: tuple[int, int]
    wal_stat: tuple[int, int]
    commit_sig: tuple[int, int, int, int]
    base_path: Path
    active_path: Path
    has_wal_overlay: bool
    root_dir: Path


@dataclass(frozen=True)
class _ParsedWal:
    committed_pages: dict[int, bytes]
    final_pages: int
    commit_sig: tuple[int, int, int, int]


def _stat_signature(path: Path) -> tuple[int, int]:
    try:
        st = path.stat()
    except OSError:
        return (0, 0)
    mtime_ns = int(getattr(st, "st_mtime_ns", 0) or 0)
    if mtime_ns <= 0:
        mtime_ns = int(float(getattr(st, "st_mtime", 0.0) or 0.0) * 1_000_000_000)
    return (mtime_ns, int(st.st_size))


def _wal_checksum(data: bytes | memoryview, s0: int, s1: int, big_endian: bool) -> tuple[int, int]:
    fmt = ">2I" if big_endian else "<2I"
    unpack_from = struct.unpack_from
    for offset in range(0, len(data), 8):
        x0, x1 = unpack_from(fmt, data, offset)
        s0 = (s0 + x0 + s1) & 0xFFFFFFFF
        s1 = (s1 + x1 + s0) & 0xFFFFFFFF
    return s0, s1


def _parse_committed_wal_pages(wal_bytes: bytes, base_pages: int) -> _ParsedWal:
    if len(wal_bytes) < _WAL_HEADER_SIZE:
        return _ParsedWal({}, base_pages, (0, 0, 0, base_pages))

    magic, fmt_ver, page_size, ckpt_seq, s1, s2, c1, c2 = struct.unpack(">8I", wal_bytes[:_WAL_HEADER_SIZE])
    if magic not in (_WAL_MAGIC_LE, _WAL_MAGIC_BE):
        return _ParsedWal({}, base_pages, (0, 0, 0, base_pages))
    if fmt_ver != _WAL_FORMAT_VERSION or page_size != PAGE_SIZE:
        return _ParsedWal({}, base_pages, (0, 0, 0, base_pages))

    big_endian = magic == _WAL_MAGIC_BE
    s0, sum1 = _wal_checksum(wal_bytes[:24], 0, 0, big_endian)
    if s0 != c1 or sum1 != c2:
        return _ParsedWal({}, base_pages, (0, 0, 0, base_pages))

    frame_size = _WAL_FRAME_HEADER_SIZE + PAGE_SIZE
    total_frames = (len(wal_bytes) - _WAL_HEADER_SIZE) // frame_size
    if total_frames <= 0:
        return _ParsedWal({}, base_pages, (ckpt_seq, 0, 0, base_pages))

    view = memoryview(wal_bytes)
    committed: dict[int, bytes] = {}
    pending: dict[int, bytes] = {}
    final_pages = base_pages
    committed_frames = 0
    last_commit_cksum = 0

    for idx in range(total_frames):
        offset = _WAL_HEADER_SIZE + idx * frame_size
        frame_header = view[offset : offset + _WAL_FRAME_HEADER_SIZE]
        pgno, commit_sz, fs1, fs2, fc1, fc2 = struct.unpack(">6I", frame_header)
        if fs1 != s1 or fs2 != s2 or pgno == 0:
            break
        s0, sum1 = _wal_checksum(frame_header[:8], s0, sum1, big_endian)
        page_slice = view[offset + _WAL_FRAME_HEADER_SIZE : offset + frame_size]
        s0, sum1 = _wal_checksum(page_slice, s0, sum1, big_endian)
        if s0 != fc1 or sum1 != fc2:
            break
        pending[pgno] = bytes(page_slice)
        if commit_sz > 0:
            committed.update(pending)
            pending.clear()
            final_pages = commit_sz
            committed_frames = idx + 1
            last_commit_cksum = (fc1 << 32) | fc2

    return _ParsedWal(
        committed_pages=committed,
        final_pages=final_pages,
        commit_sig=(ckpt_seq, committed_frames, last_commit_cksum, final_pages),
    )


def _decrypt_encrypted_page(
    enc_pg: bytes,
    pgno: int,
    enc_key: bytes,
    mac_key: bytes,
    *,
    verify_hmac: bool,
) -> bytes:
    if len(enc_pg) < PAGE_SIZE:
        enc_pg = enc_pg + (b"\x00" * (PAGE_SIZE - len(enc_pg)))
    if verify_hmac:
        stored_hmac = enc_pg[PAGE_SIZE - HMAC_SIZE :]
        expected_hmac = _compute_page_hmac(mac_key, enc_pg, pgno)
        if not hmac.compare_digest(stored_hmac, expected_hmac):
            raise LocalSQLCipherRealtimeError(f"HMAC verification failed on page {pgno}.")

    iv = enc_pg[PAGE_SIZE - RESERVE_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE]
    offset = SALT_SIZE if pgno == 1 else 0
    decryptor = Cipher(algorithms.AES(enc_key), modes.CBC(iv), backend=_CRYPTO_BACKEND).decryptor()
    plaintext = decryptor.update(enc_pg[offset : PAGE_SIZE - RESERVE_SIZE]) + decryptor.finalize()
    if pgno == 1:
        return SQLITE_HEADER + plaintext + (b"\x00" * RESERVE_SIZE)
    return plaintext + (b"\x00" * RESERVE_SIZE)


def _atomic_write_bytes(target: Path, payload: bytes | bytearray) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.chmod(target.parent, 0o700)
        except OSError:
            pass
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        if sys.platform != "win32":
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while materializing SQLite mirror")
            view = view[written:]
        os.close(fd)
        fd = -1
        os.replace(tmp_path, target)
    except BaseException:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _clone_or_copy_file(src: Path, dst: Path) -> None:
    if sys.platform == "darwin":
        try:
            libc = ctypes.CDLL("/usr/lib/system/libsystem_c.dylib")
            clonefile = libc.clonefile
            clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
            clonefile.restype = ctypes.c_int
            dst.unlink(missing_ok=True)
            if clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0:
                return
        except Exception:
            pass
    shutil.copyfile(src, dst)


class LocalSQLCipherLiveReader:
    """Thread-safe local SQLCipher 4 + WAL mirror cache and SQLite query runner."""

    def __init__(self) -> None:
        self._mu = threading.Lock()
        self._build_locks: dict[str, threading.Lock] = {}
        self._entries: dict[str, _MirrorCacheEntry] = {}
        self._mac_key_cache: dict[tuple[bytes, bytes], bytes] = {}

    @staticmethod
    def _cache_root() -> Path:
        root = get_data_dir() / ".realtime-sqlite-cache"
        root.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(root, 0o700)
            except OSError:
                pass
        return root

    def _build_lock_for(self, cache_id: str) -> threading.Lock:
        with self._mu:
            lock = self._build_locks.get(cache_id)
            if lock is None:
                lock = threading.Lock()
                self._build_locks[cache_id] = lock
            return lock

    def _resolve_crypto_keys(
        self,
        page1: bytes,
        key_bytes: bytes,
        cached_raw_key: bytes | None,
    ) -> tuple[bytes, bytes] | None:
        if page1.startswith(SQLITE_HEADER):
            return None

        salt = page1[:SALT_SIZE]
        if cached_raw_key is not None and len(cached_raw_key) == 32:
            enc_key = bytes(cached_raw_key)
            key_pair = (salt, hashlib.sha256(enc_key).digest())
            with self._mu:
                mac_key = self._mac_key_cache.get(key_pair)
            if mac_key is None:
                mac_key = _derive_mac_key(enc_key, salt)
                with self._mu:
                    if len(self._mac_key_cache) >= 256:
                        self._mac_key_cache.clear()
                    self._mac_key_cache[key_pair] = mac_key
            stored_hmac = page1[PAGE_SIZE - HMAC_SIZE :]
            expected_hmac = _compute_page_hmac(mac_key, page1, 1)
            if hmac.compare_digest(stored_hmac, expected_hmac):
                return enc_key, mac_key

        resolved = _resolve_page1_key_material(key_bytes, page1)
        if resolved is None:
            raise LocalSQLCipherRealtimeError("Database key verification failed on page 1.")
        enc_key, mac_key, _mode = resolved
        return enc_key, mac_key

    @staticmethod
    def _cache_id(db_path: Path, key_bytes: bytes) -> str:
        norm = os.path.normcase(os.fspath(db_path.resolve(strict=False)))
        digest = hashlib.sha256(
            norm.encode("utf-8", errors="surrogatepass") + b"\0" + key_bytes
        ).hexdigest()
        return digest[:32]

    @staticmethod
    def _build_base_snapshot(
        db_bytes: bytes,
        base_path: Path,
        crypto_keys: tuple[bytes, bytes] | None,
    ) -> int:
        if crypto_keys is None:
            _atomic_write_bytes(base_path, db_bytes)
            return len(db_bytes) // PAGE_SIZE

        enc_key, mac_key = crypto_keys
        total_pages = (len(db_bytes) + PAGE_SIZE - 1) // PAGE_SIZE
        out = bytearray(total_pages * PAGE_SIZE)
        for cur in range(total_pages):
            pgno = cur + 1
            start = cur * PAGE_SIZE
            page = db_bytes[start : start + PAGE_SIZE]
            decrypted = _decrypt_encrypted_page(
                page,
                pgno,
                enc_key,
                mac_key,
                verify_hmac=(pgno == 1),
            )
            out[start : start + PAGE_SIZE] = decrypted
        _atomic_write_bytes(base_path, out)
        return total_pages

    @staticmethod
    def _build_wal_overlay(
        base_path: Path,
        live_path: Path,
        parsed_wal: _ParsedWal,
        crypto_keys: tuple[bytes, bytes] | None,
    ) -> None:
        live_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{live_path.name}.",
            suffix=".tmp",
            dir=str(live_path.parent),
        )
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            _clone_or_copy_file(base_path, tmp_path)
            if sys.platform != "win32":
                try:
                    os.chmod(tmp_path, 0o600)
                except OSError:
                    pass
            target_size = parsed_wal.final_pages * PAGE_SIZE
            with tmp_path.open("r+b") as stream:
                stream.truncate(target_size)
                for pgno, enc_pg in parsed_wal.committed_pages.items():
                    if pgno < 1 or pgno > parsed_wal.final_pages:
                        continue
                    if crypto_keys is None:
                        page_out = enc_pg[:PAGE_SIZE]
                        if len(page_out) < PAGE_SIZE:
                            page_out = page_out + (b"\x00" * (PAGE_SIZE - len(page_out)))
                    else:
                        enc_key, mac_key = crypto_keys
                        page_out = _decrypt_encrypted_page(
                            enc_pg,
                            pgno,
                            enc_key,
                            mac_key,
                            verify_hmac=True,
                        )
                    stream.seek((pgno - 1) * PAGE_SIZE)
                    stream.write(page_out)
                stream.flush()
            os.replace(tmp_path, live_path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _ensure_mirror(
        self,
        db_path: Path,
        root_dir: Path,
        *,
        key_bytes: bytes,
        cached_raw_key: bytes | None,
    ) -> Path:
        resolved_db = db_path.resolve(strict=True)
        wal_path = Path(f"{resolved_db}-wal")
        cache_id = self._cache_id(resolved_db, key_bytes)
        lock = self._build_lock_for(cache_id)

        with lock:
            db_sig_now = _stat_signature(resolved_db)
            wal_sig_now = _stat_signature(wal_path)
            with self._mu:
                cached = self._entries.get(cache_id)
            if (
                cached is not None
                and cached.db_stat == db_sig_now
                and cached.wal_stat == wal_sig_now
                and cached.active_path.is_file()
            ):
                return cached.active_path

            cache_root = self._cache_root()
            base_path = cache_root / f"{cache_id}.base.db"
            live_path = cache_root / f"{cache_id}.live.db"

            last_error: BaseException | None = None
            for attempt in range(_MAX_SNAPSHOT_RETRIES):
                db_before = _stat_signature(resolved_db)
                wal_before = _stat_signature(wal_path)
                try:
                    base_reused = (
                        cached is not None
                        and cached.db_stat == db_before
                        and base_path.is_file()
                    )
                    db_bytes: bytes | None = None
                    if not base_reused:
                        db_bytes = resolved_db.read_bytes()
                        if len(db_bytes) < PAGE_SIZE:
                            raise LocalSQLCipherRealtimeError(
                                f"Database file is smaller than one SQLite page: {resolved_db.name}"
                            )
                        page1 = db_bytes[:PAGE_SIZE]
                    else:
                        with resolved_db.open("rb") as stream:
                            page1 = stream.read(PAGE_SIZE)
                        if len(page1) < PAGE_SIZE:
                            raise LocalSQLCipherRealtimeError(
                                f"Database header is incomplete: {resolved_db.name}"
                            )

                    wal_bytes = wal_path.read_bytes() if wal_before[1] >= _WAL_HEADER_SIZE else b""
                    db_after = _stat_signature(resolved_db)
                    wal_after = _stat_signature(wal_path)
                    if db_before != db_after or wal_before != wal_after:
                        time.sleep(_RETRY_SLEEP_SECONDS)
                        continue

                    crypto_keys = self._resolve_crypto_keys(page1, key_bytes, cached_raw_key)
                    if not base_reused:
                        assert db_bytes is not None
                        base_pages = self._build_base_snapshot(db_bytes, base_path, crypto_keys)
                    else:
                        base_pages = base_path.stat().st_size // PAGE_SIZE

                    parsed_wal = _parse_committed_wal_pages(wal_bytes, base_pages)
                    if not parsed_wal.committed_pages:
                        active_path = base_path
                        has_wal = False
                    elif (
                        cached is not None
                        and base_reused
                        and cached.has_wal_overlay
                        and cached.commit_sig == parsed_wal.commit_sig
                        and live_path.is_file()
                    ):
                        active_path = live_path
                        has_wal = True
                    else:
                        self._build_wal_overlay(base_path, live_path, parsed_wal, crypto_keys)
                        active_path = live_path
                        has_wal = True

                    entry = _MirrorCacheEntry(
                        db_stat=db_before,
                        wal_stat=wal_before,
                        commit_sig=parsed_wal.commit_sig,
                        base_path=base_path,
                        active_path=active_path,
                        has_wal_overlay=has_wal,
                        root_dir=root_dir,
                    )
                    with self._mu:
                        self._entries[cache_id] = entry
                    return active_path
                except LocalSQLCipherRealtimeError as exc:
                    last_error = exc
                    if attempt + 1 < _MAX_SNAPSHOT_RETRIES:
                        time.sleep(_RETRY_SLEEP_SECONDS)
                        continue
                    raise
                except OSError as exc:
                    last_error = exc
                    if attempt + 1 < _MAX_SNAPSHOT_RETRIES:
                        time.sleep(_RETRY_SLEEP_SECONDS)
                        continue
                    raise LocalSQLCipherRealtimeError(str(exc)) from exc

            if last_error is not None:
                raise LocalSQLCipherRealtimeError(str(last_error)) from last_error
            raise LocalSQLCipherRealtimeError(
                f"Concurrent database modification prevented reading {resolved_db.name}"
            )

    def query(
        self,
        db_path: Path,
        root_dir: Path,
        sql: str,
        *,
        key_bytes: bytes,
        cached_raw_key: bytes | None = None,
        max_rows: int = 200_000,
    ) -> list[dict[str, Any]]:
        mirror_path = self._ensure_mirror(
            db_path,
            root_dir,
            key_bytes=key_bytes,
            cached_raw_key=cached_raw_key,
        )
        conn = sqlite3.connect(
            f"{mirror_path.resolve().as_uri()}?mode=ro",
            uri=True,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.text_factory = lambda raw: raw.decode("utf-8", errors="replace")
        try:
            cursor = conn.execute(sql)
            try:
                rows: list[dict[str, Any]] = []
                batch_limit = 4096
                while True:
                    chunk = cursor.fetchmany(batch_limit)
                    if not chunk:
                        break
                    if len(rows) + len(chunk) > max_rows:
                        raise LocalSQLCipherRealtimeError(
                            "Native-core query exceeded the application row limit."
                        )
                    rows.extend(dict(item) for item in chunk)
                return rows
            finally:
                cursor.close()
        except sqlite3.Error as exc:
            raise LocalSQLCipherRealtimeError(str(exc)) from exc
        finally:
            conn.close()

    def invalidate_root(self, root_dir: Path | None = None) -> None:
        normalized_root = (
            os.path.normcase(os.fspath(Path(root_dir).resolve(strict=False)))
            if root_dir is not None
            else None
        )
        with self._mu:
            keys_to_remove = [
                cache_id
                for cache_id, entry in self._entries.items()
                if normalized_root is None
                or os.path.normcase(os.fspath(entry.root_dir.resolve(strict=False))) == normalized_root
            ]
            removed = [self._entries.pop(cache_id) for cache_id in keys_to_remove]
            if normalized_root is None:
                self._mac_key_cache.clear()
        for entry in removed:
            for candidate in (entry.base_path, entry.active_path):
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass


LOCAL_SQLCIPHER_READER = LocalSQLCipherLiveReader()
