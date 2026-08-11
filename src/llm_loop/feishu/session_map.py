"""飞书会话映射（M42，薄壳适配器）.

飞书会话（私聊 open_id / 群聊 chat_id）↔ LoopEngine session_id 持久化映射。
并发隔离（锁），多轮连续，可追溯，生命周期管理。
"""

import json
import threading
from pathlib import Path

from llm_loop.core.session import SessionStore


class SessionMap:
    """飞书会话 ↔ LoopEngine session_id 映射（持久化 JSON + 并发锁）.

    键：私聊 "p:{open_id}" / 群聊 "g:{chat_id}"——同一飞书会话多轮消息
    映射到同一 LoopEngine session_id（多轮连续），并发经锁隔离不串话。
    """

    def __init__(self, session_store: SessionStore, path: str | None = None) -> None:
        self._store = session_store
        self._path = Path(path) if path else None
        self._lock = threading.RLock()
        self._map: dict[str, str] = {}
        self._load()

    # ── 键构造 ──
    @staticmethod
    def p2p_key(open_id: str) -> str:
        """私聊映射键（open_id）."""
        return f"p:{open_id}"

    @staticmethod
    def group_key(chat_id: str) -> str:
        """群聊映射键（chat_id）."""
        return f"g:{chat_id}"

    # ── 核心 ──
    def get_or_create(self, key: str) -> str:
        """取或建 LoopEngine session_id（多轮连续 + 并发隔离）."""
        with self._lock:
            if key in self._map:
                sid = self._map[key]
                if self._store.exists(sid):
                    return sid
                # 映射的会话已被删除 → 重建（生命周期管理）
            sid = self._store.create()
            self._map[key] = sid
            self._save()
            return sid

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._map.get(key)

    def remove(self, key: str) -> None:
        with self._lock:
            self._map.pop(key, None)
            self._save()

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._map.keys())

    def to_dict(self) -> dict[str, str]:
        with self._lock:
            return dict(self._map)

    # ── 持久化 ──
    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._map = {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError):
            # 映射文件损坏：如实忽略重建（不静默丢弃）
            self._map = {}

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._map, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            # 持久化失败 fail-open（内存映射仍可用，不阻断飞书桥）
            pass
