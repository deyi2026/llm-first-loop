"""飞书 ← Web 跨端会话同步（2026-08-15 用户需求：两端统一会话，一边输入输出另一边同步）.

桥进程内后台线程：轮询会话目录（与 Web /api/v1/events 指纹思路同源，零新依赖），
对 session_map 映射到飞书聊天的会话（含 owner 跨端共享当前会话）做增量检测——
发现桥自身之外的新消息（Web 侧用户输入 / AI 输出）→ 以卡片推送到对应飞书聊天。

基线机制：`mark_processed(sid)` 由 handler 在桥自身回复完成后调用 → 该会话基线
刷新，桥自己的输出不被重复推送；Web 侧增量在轮询时按条数 diff 推送（多条合并
一条，速率受限）。首见会话只建基线不推历史（启动不刷屏）。

fail-open：异常仅记日志，不阻断桥主体；推送失败不推进基线（下轮重试）。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_POLL_S = float(os.environ.get("FEISHU_CROSS_SYNC_POLL_S", "1.5"))
_MIN_INTERVAL_S = float(os.environ.get("FEISHU_CROSS_SYNC_MIN_INTERVAL_S", "3.0"))
_MAX_CHARS = int(os.environ.get("FEISHU_CROSS_SYNC_MAX_CHARS", "10000"))
_ENABLED = os.environ.get("FEISHU_CROSS_SYNC", "1").strip().lower() not in {
    "0",
    "off",
    "false",
    "no",
}


def _key_target(key: str) -> tuple[str, str] | None:
    """映射键 → (receive_id, receive_id_type)；未知键 None（不推送）."""
    if key.startswith("p:"):
        return (key[2:], "open_id")
    if key.startswith("g:"):
        return (key[2:], "chat_id")
    return None


class CrossSyncWatcher:
    """飞书 ← Web 增量同步器（线程内轮询；start/stop 生命周期）."""

    def __init__(
        self,
        session_store: Any,
        session_map: Any,
        reply_fn: Any,
        sessions_dir: str | Path,
        *,
        poll_s: float = _POLL_S,
        min_interval_s: float = _MIN_INTERVAL_S,
        max_chars: int = _MAX_CHARS,
        skip_fn: Any | None = None,
    ) -> None:
        self._store = session_store
        self._map = session_map
        self._reply = reply_fn
        self._dir = Path(sessions_dir)
        self._poll_s = poll_s
        self._min_interval = min_interval_s
        self._max_chars = max_chars
        # P1-11(2026-08-16): skip_fn(sid) → True 时跳过该会话（桥正在处理的会话）——
        # 只防桥自己的回答被当 Web 侧增量重复推; 其他会话照常实时同步（不做全局暂停）
        self._skip_fn = skip_fn
        self._baseline: dict[str, tuple[int, str]] = {}  # sid → (message_count, updated_at)
        self._last_push: dict[str, float] = {}  # receive_id → 上次推送时刻（速率限制）
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── 生命周期 ──
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="feishu-cross-sync", daemon=True
        )
        self._thread.start()
        logger.info("飞书跨端同步已启动（轮询 %.1fs）", self._poll_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def mark_processed(self, sid: str) -> None:
        """桥自身输出完成后调用：刷新基线，避免重复推送自己的回复."""
        try:
            meta = self._store.get_meta(sid)
        except Exception:  # noqa: BLE001 — 基线刷新失败不影响主体
            return
        if meta is not None:
            self._baseline[sid] = (meta.message_count, meta.updated_at)

    # ── 核心 ──
    def _watched_sids(self) -> dict[str, list[str]]:
        """被监控会话 → 飞书映射键列表（映射反查 + owner 跨端共享当前会话）."""
        out: dict[str, list[str]] = {}
        try:
            with self._map._lock:  # noqa: SLF001 — 薄壳适配器内部锁
                items = list(self._map._map.items())  # noqa: SLF001
        except Exception:  # noqa: BLE001 — 锁不可用按快照
            items = list(getattr(self._map, "_map", {}).items())
        for key, sid in items:
            out.setdefault(sid, []).append(key)
        # owner 跨端共享：Web 新建会话（无映射键）也推给 owner 私聊
        try:
            shared = self._store.get_shared_current()
            owner = getattr(self._map, "_owner", "")
        except Exception:  # noqa: BLE001
            shared, owner = None, ""
        if shared and owner:
            keys = out.setdefault(shared, [])
            owner_key = f"p:{owner}"
            if owner_key not in keys:
                keys.append(owner_key)
        return out

    def poll_once(self) -> None:
        """单轮增量检测（可测试直接调用）."""
        try:
            metas = {m.session_id: m for m in self._store.list_sessions()}
        except Exception as exc:  # noqa: BLE001
            logger.debug("跨端同步会话列表读取失败（fail-open）: %s", exc)
            return
        for sid, keys in self._watched_sids().items():
            try:
                self._check_session(sid, keys, metas.get(sid))
            except Exception as exc:  # noqa: BLE001 — 单会话异常不拖垮整轮
                logger.warning("跨端同步检查会话 %s 异常（fail-open）: %s", sid, exc)

    def _check_session(self, sid: str, keys: list[str], meta) -> None:
        # P1-11: 只跳过"桥正在处理的那个会话"（防桥自己的回答被当 Web 增量重复推）；
        # 其他会话照常实时同步（busy 全局暂停改为按会话精确跳过，忙时跨端不再全停）
        if self._skip_fn is not None:
            try:
                if self._skip_fn(sid):
                    return
            except Exception:  # noqa: BLE001 — 探测失败按不阻塞处理
                pass
        if meta is None:
            return
        cur = (meta.message_count, meta.updated_at)
        base = self._baseline.get(sid)
        if base is None:
            self._baseline[sid] = cur  # 首见只建基线（启动不推历史）
            return
        if cur == base:
            return
        if meta.message_count < base[0]:
            # 会话被清理/瘦身 → 基线刷新，不推送
            self._baseline[sid] = cur
            return
        if meta.message_count == base[0]:
            # 条数未变但内容变动（修复/覆盖）→ 基线刷新，不推送
            self._baseline[sid] = cur
            return
        # 增量消息（Web 侧输入/输出）
        try:
            sess = self._store.load(sid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("跨端同步加载会话 %s 失败（fail-open）: %s", sid, exc)
            return
        new = sess.messages[base[0] :]
        if not new:
            self._baseline[sid] = cur
            return
        target = next((t for k in keys if (t := _key_target(k)) is not None), None)
        if target is None:
            self._baseline[sid] = cur
            return
        now = time.monotonic()
        if now - self._last_push.get(target[0], 0.0) < self._min_interval:
            return  # 速率受限：基线不推进，下轮合并推送
        texts = self._format_push(getattr(meta, "title", "") or "未命名", new)
        try:
            for text in texts:
                self._reply(target[0], text, target[1])
            self._last_push[target[0]] = now
            self._baseline[sid] = cur  # 推送成功才推进基线
        except Exception as exc:  # noqa: BLE001 — 推送失败不推进基线（下轮重试，fail-open）
            logger.warning("跨端同步推送失败（fail-open，下轮重试）: %s", exc)

    def _format_push(self, title: str, messages: list) -> list[str]:
        """增量消息推送分段（角色标注 + 多条合并为一批；整批超 max_chars 拆多段，段标 i/N）.

        信息零丢失——不再 "…" 截断（2026-08-16 用户需求：单条上限 10000，超出分段显示）。
        M51/M52/M58（2026-08-17 修复）：assistant 消息追加模型/token 脚注，与 web 端
        buildAssistantNote / handlers.py footer 格式一致（—— {model} · {入}入/{出}出）。
        """
        header = f"[跨端同步] Web 端会话「{title}」新增 {len(messages)} 条消息："
        lines: list[str] = []
        for m in messages:
            role = "👤 用户" if m.role == "user" else "🤖 AI" if m.role == "assistant" else f"⚙️ {m.role}"
            content = (m.content or "").strip() or "（空消息）"
            line = f"{role}: {content}"
            if m.role == "assistant" and getattr(m, "model_used", ""):
                from llm_loop.core.loop import format_tokens

                footer = f"\n—— {m.model_used}"
                if getattr(m, "tokens_in", 0) or getattr(m, "tokens_out", 0):
                    footer += f" · {format_tokens(m.tokens_in)}入/{format_tokens(m.tokens_out)}出"
                if getattr(m, "tokens_cache_hit", 0):
                    footer += f" · 缓存{format_tokens(m.tokens_cache_hit)}"
                line += footer
            lines.append(line)
        body = "\n".join(lines)
        budget = max(50, self._max_chars - len(header) - 8)  # 预留段头/段标空间
        chunks = self._split_text(body, budget)
        if len(chunks) == 1:
            return [f"{header}\n{chunks[0]}"]
        total = len(chunks)
        return [f"{header}（{i}/{total}）\n{c}" for i, c in enumerate(chunks, 1)]

    @staticmethod
    def _split_text(text: str, budget: int) -> list[str]:
        """把 text 切成 ≤ budget 的块，优先在换行符处断开；信息零丢失."""
        chunks: list[str] = []
        rest = text
        while len(rest) > budget:
            cut = rest.rfind("\n", 0, budget + 1)
            if cut < budget // 2:  # 换行符太靠前/没有 → 硬切，避免碎段
                cut = budget
            chunks.append(rest[:cut].rstrip("\n"))
            rest = rest[cut:].lstrip("\n")
        if rest:
            chunks.append(rest)
        return chunks

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_s):
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 — 轮询异常 fail-open
                logger.debug("跨端同步轮询异常（fail-open）: %s", exc)
