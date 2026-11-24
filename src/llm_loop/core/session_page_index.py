"""Optional, rebuildable byte-position index for canonical session JSON.

No message body or authorization fact is duplicated. Only the writer's exact
pretty-printed snapshot is indexed; legacy/changed/corrupt files use normal load.
"""
from __future__ import annotations

import json
import os
import struct
import tempfile
import zlib
from collections.abc import Callable
from contextlib import suppress

_MAGIC = b"LFLPAGE1"
_HEADER = struct.Struct(">8s8Q")  # magic, source identity (5), count, array start/end
_RECORD = struct.Struct(">QI")  # byte offset and corruption check bound to ordinal
_MIN_MESSAGES = 1000
_MAX_MESSAGES = 200_000
_MAX_SOURCE_BYTES = 128 * 1024 * 1024
_MAX_PAGE_BYTES = 8 * 1024 * 1024
_MESSAGE_START = b"\n    {"
_ARRAY_START = b'\n  "messages": [\n'
_ARRAY_END = b"\n  ]\n}"


def source_key(st: os.stat_result) -> tuple[int, int, int, int, int]:
    return st.st_mtime_ns, st.st_size, st.st_dev, st.st_ino, st.st_ctime_ns


def index_path(path: str) -> str:
    return path + ".history.idx"


def eligible(count: int, size: int) -> bool:
    return _MIN_MESSAGES <= count <= _MAX_MESSAGES and size <= _MAX_SOURCE_BYTES


def _record_crc(ordinal: int, offset: int) -> int:
    return zlib.crc32(struct.pack(">QQ", ordinal, offset))


def publish_index(path: str, payload: bytes, count: int, key: tuple[int, int, int, int, int]) -> bool:
    """Called under the existing session writer lock after canonical replace."""
    target = index_path(path)
    tmp = None
    try:
        if not eligible(count, len(payload)):
            return False
        start = payload.rfind(_ARRAY_START)
        end = len(payload) - len(_ARRAY_END)
        if start < 0 or not payload.endswith(_ARRAY_END):
            return False
        start += len(_ARRAY_START)
        # json.dumps escapes newlines inside strings and indents nested objects
        # deeper than four spaces. Use C-level byte search, not a per-byte regex.
        offsets = []
        pos = start - 1
        while (pos := payload.find(_MESSAGE_START, pos, end)) >= 0:
            offsets.append(pos + 5)
            if len(offsets) > count:
                return False
            pos += len(_MESSAGE_START)
        if len(offsets) != count or offsets[0] != start + 4 or source_key(os.stat(path)) != key:
            return False
        with tempfile.NamedTemporaryFile(mode="wb", dir=os.path.dirname(path), prefix=".history-index-", delete=False) as f:
            tmp = f.name
            f.write(_HEADER.pack(_MAGIC, *key, count, start, end))
            f.write(b"".join(_RECORD.pack(off, _record_crc(i, off)) for i, off in enumerate(offsets)))
        if source_key(os.stat(path)) == key:
            os.replace(tmp, target)
            return True
        return False
    except (OSError, ValueError, struct.error):
        # The index is never needed to commit a session.
        return False
    finally:
        if tmp is not None:
            with suppress(OSError):
                os.unlink(tmp)


def rebuild_index(path: str, session_id: str, validate_message: Callable[[dict], object]) -> bool:
    """Explicit maintenance only; never called by a Web read request."""
    try:
        with open(path, "rb") as source:
            key = source_key(os.fstat(source.fileno()))
            if key[1] > _MAX_SOURCE_BYTES:
                return False
            payload = source.read(_MAX_SOURCE_BYTES + 1)
            if len(payload) != key[1] or source_key(os.fstat(source.fileno())) != key:
                return False
        data = json.loads(payload)
        if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
            return False
        if data.get("session_id", session_id) != session_id or not eligible(len(data["messages"]), key[1]):
            return False
        for row in data["messages"]:
            if not isinstance(row, dict):
                return False
            validate_message(row)
        return publish_index(path, payload, len(data["messages"]), key)
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return False


def read_page(path: str, limit: int, offset: int) -> tuple[list[dict], int] | None:
    """Read only the requested contiguous message range, or decline safely."""
    if not 1 <= limit <= 100 or offset < 0:
        return None
    try:
        with open(path, "rb") as source, open(index_path(path), "rb") as index:
            key = source_key(os.fstat(source.fileno()))
            magic, *values = _HEADER.unpack(index.read(_HEADER.size))
            count, array_start, array_end = values[5:]
            if (magic != _MAGIC or tuple(values[:5]) != key
                or not _MIN_MESSAGES <= count <= _MAX_MESSAGES
                or not 0 < array_start < array_end < key[1] <= _MAX_SOURCE_BYTES
                or os.fstat(index.fileno()).st_size != _HEADER.size + count * _RECORD.size):
                return None
            source.seek(array_start - len(_ARRAY_START))
            if source.read(len(_ARRAY_START)) != _ARRAY_START:
                return None
            source.seek(array_end)
            if source.read(len(_ARRAY_END)) != _ARRAY_END:
                return None
            end = max(0, count - offset)
            start = max(0, end - limit)
            if start == end:
                return [], count
            index.seek(_HEADER.size + start * _RECORD.size)
            n = end - start + int(end < count)
            positions = []
            for i in range(start, start + n):
                pos, crc = _RECORD.unpack(index.read(_RECORD.size))
                if crc != _record_crc(i, pos) or not array_start <= pos < array_end:
                    return None
                if positions and pos <= positions[-1]:
                    return None
                positions.append(pos)
            first = positions[0]
            last = positions[-1] if end < count else array_end
            if not 0 < last - first <= _MAX_PAGE_BYTES:
                return None
            source.seek(first - 4)
            if source.read(5) != b"    {":
                return None
            source.seek(first)
            raw = source.read(last - first).rstrip()
            if end < count:
                if not raw.endswith(b","):
                    return None
                raw = raw[:-1]
            rows = json.loads(b"[" + raw + b"]")
            if len(rows) != end - start or any(not isinstance(row, dict) or "role" not in row for row in rows):
                return None
            if source_key(os.fstat(source.fileno())) != key:
                return None
            return rows, count
    except (OSError, ValueError, TypeError, struct.error, OverflowError):
        return None
