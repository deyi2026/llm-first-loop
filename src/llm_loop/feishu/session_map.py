"""飞书会话映射（M42，薄壳适配器）.

飞书会话（私聊 open_id / 群聊 chat_id）↔ LoopEngine session_id 持久化映射。
并发隔离（锁），多轮连续，可追溯，生命周期管理。
"""

import json
import threading
from contextlib import suppress
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
    def get_or_create(
        self,
        key: str,
        force_new: bool = False,
        inherit_model_override: bool = False,
    ) -> str:
        """取或建 LoopEngine session_id（多轮连续 + 并发隔离）.

        跨端共享（M-new）: 仅配置了 owner_open_id 且键为其私聊（p:{owner}）时，
        优先复用共享当前会话——Web/飞书同一上下文，一端说话另一端能感知。
        其余私聊/群聊保持独立映射（多用户不串话）。

        force_new=True 跳过 owner 跨端共享与旧映射复用（用于 /clear /new 指令，
        强制创建新 session）。

        inherit_model_override=True（M52-fix）: 新建时继承旧会话的 model_override
        （映射中的旧 sid 或 owner 共享当前），使 /new·/clear 后新会话沿用用户
        所选模型而非回落装配默认；旧会话缺失/损坏 fail-open 为 None。
        """
        with self._lock:
            is_owner = bool(self._owner) and key == f"p:{self._owner}"
            if is_owner and not force_new:
                shared = self._store.get_shared_current()
                if shared is not None:
                    self._map[key] = shared
                    self._mark_channel(shared, key)
                    self._save()
                    return shared
            if not force_new and key in self._map:
                sid = self._map[key]
                if self._store.exists(sid):
                    # M56：补标记来源通道（兼容既有映射/旧会话无 channel 字段）
                    self._mark_channel(sid, key)
                    return sid
                # 映射的会话已被删除 → 重建（生命周期管理）
            # M52-fix: 继承旧会话模型覆盖（/new·/clear 不回落装配默认）
            inherit_override: str | None = None
            if inherit_model_override:
                old_sid = self._map.get(key)
                if old_sid is None and is_owner:
                    old_sid = self._store.get_shared_current()
                if old_sid is not None:
                    with suppress(Exception):  # fail-open: 旧会话缺失/损坏不阻断新建
                        inherit_override = self._store.load(old_sid).model_override
            sid = self._store.create(model_override=inherit_override)
            if is_owner:
                # owner 跨端共享: 新建时设为共享当前
                self._store.set_shared_current(sid)  # owner 私聊新建 → 设为跨端共享当前
            elif force_new:
                # force_new=True: 旧 shared_current 应清掉(避免下次 owner 自动恢复),新 sid 不设为 shared
                # 但保留调用方上下文(非 owner key 也可能想要干净隔离)
                pass
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
