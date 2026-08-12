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

    def __init__(
        self,
        session_store: SessionStore,
        path: str | None = None,
        owner_open_id: str = "",
    ) -> None:
        self._store = session_store
        self._path = Path(path) if path else None
        self._owner = owner_open_id  # 跨端共享：owner 私聊与 Web 共享同一会话（空=不启用）
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
        """取或建 LoopEngine session_id（多轮连续 + 并发隔离）.

        跨端共享（M-new）: 仅配置了 owner_open_id 且键为其私聊（p:{owner}）时，
        优先复用共享当前会话——Web/飞书同一上下文，一端说话另一端能感知。
        其余私聊/群聊保持独立映射（多用户不串话）。
        """
        with self._lock:
            is_owner = bool(self._owner) and key == f"p:{self._owner}"
            if is_owner:
                shared = self._store.get_shared_current()
                if shared is not None:
                    self._map[key] = shared
                    self._mark_channel(shared, key)
                    self._save()
                    return shared
            if key in self._map:
                sid = self._map[key]
                if self._store.exists(sid):
                    # M56：补标记来源通道（兼容既有映射/旧会话无 channel 字段）
                    self._mark_channel(sid, key)
                    return sid
                # 映射的会话已被删除 → 重建（生命周期管理）
            sid = self._store.create()
            if is_owner:
                self._store.set_shared_current(sid)  # owner 私聊新建 → 设为跨端共享当前
            self._map[key] = sid
            self._mark_channel(sid, key)
            self._save()
            return sid

    def _mark_channel(self, sid: str, key: str) -> None:
        """按映射键标记会话来源通道（p:→feishu:p2p，g:→feishu:group；fail-open）.

        供 Web 端识别飞书来源会话并实时推送；set_channel 幂等（已标记不覆盖）。
        """
        if key.startswith("p:"):
            channel = f"feishu:p2p:{key[2:]}"
        elif key.startswith("g:"):
            channel = f"feishu:group:{key[2:]}"
        else:
            return
        from contextlib import suppress

        with suppress(Exception):  # 标记失败不阻断飞书主链路
            self._store.set_channel(sid, channel)

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
