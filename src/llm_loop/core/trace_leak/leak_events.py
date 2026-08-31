"""五类泄漏检测事件统一出口与隔离区（tasks 3.3，design §2.2 组3，spec 6.3）.

事件类型名为冻结常量（spec 6.3-1 唯一性）：
  leak.channel_denied     拒绝写入
  leak.downgraded         降级写入
  leak.mislabel_detected  标记失真检出
  leak.channel_overreach  通道越权检出
  leak.signature_warned   特征兜底告警
（guard/detector 自身故障告警：leak.guard_fault / leak.detector_fault）

payload 对齐 spec 6.3：类型 / 入口标识 / 目标会话 / 内容 sha1 指纹 + 预览
≤200 字符 / 判定依据 basis 非空（禁止无依据拦截记录）。

落盘通道：注入式事件接收器（engine/SessionStore 的 _event_append，fire-and-forget
不阻塞）；被拦截内容写会话级 dead/ 风格隔离目录（可检索、不静默丢弃，spec 4.3-3）。
落盘失败 logger.warning fail-open（spec 4.2-1）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 冻结常量（spec 6.3-1：事件体系内唯一，禁止改名/复用） ──────────────────

LEAK_CHANNEL_DENIED = "leak.channel_denied"
LEAK_DOWNGRADED = "leak.downgraded"
LEAK_MISLABEL_DETECTED = "leak.mislabel_detected"
LEAK_CHANNEL_OVERREACH = "leak.channel_overreach"
LEAK_SIGNATURE_WARNED = "leak.signature_warned"
LEAK_GUARD_FAULT = "leak.guard_fault"
LEAK_DETECTOR_FAULT = "leak.detector_fault"

FROZEN_EVENT_KINDS: frozenset[str] = frozenset(
    {
        LEAK_CHANNEL_DENIED,
        LEAK_DOWNGRADED,
        LEAK_MISLABEL_DETECTED,
        LEAK_CHANNEL_OVERREACH,
        LEAK_SIGNATURE_WARNED,
    }
)

# 事件接收器契约：(session_id, event_type, payload) -> None
EventSink = Callable[[str, str, dict], None]

_DEFAULT_SINK: EventSink | None = None


def set_default_sink(sink: EventSink | None) -> None:
    """装配期注入默认事件接收器（fail-open：未注入时仅日志）。"""
    global _DEFAULT_SINK
    _DEFAULT_SINK = sink


def _content_digest(content: str) -> tuple[str, str]:
    text = str(content or "")
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest(), text[:200]


def quarantine_root(session_id: str) -> Path:
    """会话级隔离目录（dead/ 风格；对齐 interop 隔离先例，spec 4.3-3）。"""
    base = Path(os.environ.get("LFL_DATA_DIR", "data"))
    safe_sid = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(session_id))
    return base / "trace_leak_quarantine" / safe_sid


def write_quarantine(kind: str, *, session_id: str, content: str, basis: str) -> Path | None:
    """被拦截内容隔离留痕（可检索、不静默丢弃）；失败 fail-open 返回 None。"""
    try:
        root = quarantine_root(session_id)
        root.mkdir(parents=True, exist_ok=True)
        digest, _ = _content_digest(content)
        target = root / f"{int(time.time())}-{kind.replace('.', '_')}-{digest[:12]}.json"
        if target.exists():
            target = root / f"{target.stem}-{int(time.time() * 1000)}.json"
        target.write_text(
            __import__("json").dumps(
                {
                    "kind": kind,
                    "session_id": session_id,
                    "basis": basis,
                    "content": str(content or ""),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return target
    except Exception:  # noqa: BLE001 — 隔离失败 fail-open
        logger.warning("泄漏隔离写入失败（fail-open）", exc_info=True)
        return None


def emit_leak_event(
    kind: str,
    *,
    entry: str,
    session_id: str,
    content: str,
    basis: str,
    sink: EventSink | None = None,
    extra: dict | None = None,
) -> None:
    """五类泄漏事件统一出口（spec 6.3 字段齐备；fire-and-forget 不阻塞主链路）.

    basis 必须非空——禁止无依据的拦截记录（spec 6.3-5）。
    """
    if not basis:
        raise ValueError("emit_leak_event: basis 非空约束（spec 6.3-5）")
    digest, preview = _content_digest(content)
    payload: dict = {
        "kind": kind,
        "entry": str(entry or "?"),
        "session_id": str(session_id or "?"),
        "content_sha1": digest,
        "content_preview": preview,
        "basis": basis,
    }
    if extra:
        payload.update(extra)
    active = sink or _DEFAULT_SINK
    try:
        if active is not None:
            active(str(session_id or "?"), kind, payload)
        else:
            logger.warning(
                "leak event（未装配 sink，仅日志）: %s entry=%s sid=%s sha1=%s basis=%s",
                kind, entry, session_id, digest[:12], basis,
            )
    except Exception:  # noqa: BLE001 — 事件落盘失败 fail-open（spec 4.2-1）
        logger.warning("泄漏事件写入失败（fail-open）: %s", kind, exc_info=True)
