"""err1210 P0 恢复组件（.codeartsdoer/specs/err1210_locating，tasks 任务组 3）.

根因口径（2026-08-28 归档：结构触发已定位，回执 .codeartsdoer/specs/
err1210_verdict_p1/receipt.md；历史时点 P0-C 降级口径见 1f167f3）:
智谱 GLM 400/1210 根因 = 请求尾部连续 user 角色消息条数（结构触发，
内容无关；实测尾部 1 条成功、5/8 条失败，精确边界 ∈ [2,7] 待工单）。
compact 首请求必带尾部注入群 5-8 条连续 user，故 11/11 必犯。
P1 = 尾部注入聚合（AGGREGATED 单条 user，主控裁决合规重放 81c0503）。
P0 = 安全诊断/降级框架保留（剥离尾部注入 → defer 回存槽位 → 单次重试；
观测落差已归因：trigger=11 / retry 1 / success 0，逐项解释见 verdict.md 三A）。

关键约束（design 1.1.2 / 2.1.3-P0）:
- 注入产物 dict 不打标（wire 字节敏感）——剥离识别依赖 build 旁路登记 + 前缀复核双保险；
- defer 回存 = 槽位复位（非独立队列），对齐"单一数据源派生"原则；
- 全路径 fail-open：内部异常等价 recovered=False，绝不劣化现行行为；
- env ERR1210_RECOVERY=0 完全旁路（零行为）。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条)

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from llm_loop.core.message import Message
from llm_loop.llm.errors import LLMError, LLMHTTPError, parse_provider_error_code

if TYPE_CHECKING:

    from llm_loop.core.message import Message

logger = logging.getLogger(__name__)

_SNAPSHOT_SCHEMA = 1
_DEFER_REPLAY_TOTAL_LIMIT = 8  # spec 6.3-5: 待回放总量 ≤8


def content_prefix_sha(content: str) -> str:
    """content 前 32 字符的 sha256（build 登记与剥离身份复核共用口径）."""
    return hashlib.sha256((content or "")[:32].encode("utf-8")).hexdigest()


def is_err1210(exc: LLMError) -> bool:
    """[design 2.2.2-②] 触发条件 a: LLMHTTPError + status 400 + provider code 1210."""
    if not isinstance(exc, LLMHTTPError) or exc.status_code != 400:
        return False
    return parse_provider_error_code(exc.body or "") == "1210"


class SlotKind(StrEnum):
    INTEROP = "interop"
    TIP = "tip"
    HOTCARD = "hotcard"
    GATE_NOTE = "gate_note"
    AGGREGATED = "aggregated"  # P1 9.1: 四槽聚合单条（strip/defer 消费端拆解分支）
    USER_ENVELOPE = "user_envelope"  # R6: program appendix + fixed boundary + exact user truth


_AGG_SLOT_RE = re.compile(
    # Cognitive Runtime 2.3（tier 分级）: 兼容两种段标记——
    # 新: --- [tier:hot][slot:interop] ---（COG_RUNTIME_TIER_ENABLED=1，compiler.py 打标）
    # 旧: --- [slot:interop] ---（TIER_ENABLED=0 回退平铺，原行为零回归）
    # group(1) 恒为 slot 名（defer 回存按槽位复位，tier 为投射信息不参与复位）。
    r"^--- \[(?:tier:(?:hot|warm|cold)\]\[)?slot:(interop|tip|hotcard|gate_note|memory|hint)\] ---$"
)


def parse_aggregated_slots(content: str) -> list[tuple[str, str]]:
    """聚合消息 content → [(slot, seg)] 段列表（P1 9.1 defer 拆解用）.

    build 统一聚合器产物格式: 各段以 "--- [slot:xxx] ---" 或 tier 分级变体
    "--- [tier:hot][slot:xxx] ---" 行起始（build.py 9.1 / cognitive compiler 2.3）。
    hint 段为非消费提示（local 行为提示），仅透传内容不参与槽复位。
    解析不到任何段标记时返回空列表（调用方按 fail-open 处理）。
    """
    parts: list[tuple[str, str]] = []
    cur: str | None = None
    buf: list[str] = []
    for ln in content.split("\n"):
        m = _AGG_SLOT_RE.match(ln)
        if m:
            if cur is not None:
                parts.append((cur, "\n".join(buf).strip("\n")))
            cur = m.group(1)
            buf = []
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        parts.append((cur, "\n".join(buf).strip("\n")))
    return parts


@dataclass(frozen=True)
class InjectedEntry:
    """build 时刻旁路登记的一条注入（wire 不打标，此处是唯一权威记录）."""

    msg_idx: int  # built 产物中的绝对下标
    slot_kind: SlotKind
    prefix_sha: str  # content 前 32 字符 sha256（剥离时身份复核）
    message_ref: Message | None = None  # interop/tip 原 Message（defer 回填）；hotcard/gate_note 为 None
    # CR-R1.1（审查项5）: AGGREGATED 恢复源——投影前各段 (slot, 原始内容)。
    # Projection 是 view 不是 Source of Truth：WARM 投影截断后 wire 反推会把
    # 原文永久缩水（审查实测 314→120 chars），defer 恢复必须走此原始记录。
    seg_sources: tuple[tuple[str, str], ...] = ()
    # R6: USER_ENVELOPE strip must preserve the exact human suffix. Empty for legacy entries.
    user_truth: str = ""


@dataclass(frozen=True)
class InjectionSpan:
    """登记条目集合（msg_idx 升序）；剥离前须校验构成尾部连续段."""

    entries: tuple[InjectedEntry, ...]

    def is_tail_contiguous(self, messages: list[dict]) -> bool:
        if not self.entries:
            return False
        idxs = [e.msg_idx for e in self.entries]
        if idxs != sorted(set(idxs)):
            return False
        if any(i < 0 or i >= len(messages) for i in idxs):
            return False
        return idxs == list(range(idxs[0], len(messages)))


@dataclass
class Err1210RecoveryResult:
    """P0 主入口返回值（design 2.2.2-④）."""

    attempted: bool = False  # 触发条件成立（1210 + compact 首请求）
    recovered: bool = False  # 重试成功（engine 据此取 resp）
    exhausted: bool = False  # 重试仍 1210 / 本 compact 事件已耗尽（走既有上抛）
    resp: Any | None = None
    stripped_count: int = 0  # 剥离条数（观测）
    deferred_ok: bool = False  # defer 四槽是否全部回存成功（观测）


# ── defer_trace 审计流（append-only，事件化不做第二真相，design 2.3.2）──


def record_defer_event(
    event: str, session_id: str, slot_kind: str, payload: dict | None = None
) -> None:
    """写 data/audit/defer_trace.jsonl 一行事件（env ERR1210_DEFER_TRACE=1 开关，fail-open）.

    五事件: defer_stored / defer_replayed / defer_dropped / defer_exhausted /
    defer_lost_on_reinject（spec 4.4-2、5.1.3-5）。
    """
    if os.environ.get("ERR1210_DEFER_TRACE", "1") != "1":
        return
    try:
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "session_id": session_id,
            "slot_kind": slot_kind,
            "payload": payload or {},
        }
        # LFL_DATA_DIR 先例（interop 写方同款）：测试隔离 + 部署根可配
        base = os.environ.get("LFL_DATA_DIR", "data")
        path = Path(base) / "audit" / "defer_trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 审计失败 fail-open
        logger.debug("defer_trace 事件写入失败（fail-open）", exc_info=True)


# ── offending payload 快照（P2 重放数据源，design 2.2.2-⑦）──


def snapshot_offending_payload(
    *,
    messages: list[dict],
    tools: list[dict],
    params: dict[str, Any],
    session_id: str,
    model: str,
    is_compact_first: bool,
    span: InjectionSpan | None,
    data_dir: str | Path,
) -> Path | None:
    """1210 失败载荷全量落盘 <data_dir>/audit/offending_payloads/<UTCts>_<sid8>.json.

    排除 headers/凭据（入参即不含）；写失败返回 None 仅 WARN（fail-open，spec 4.2-2）。
    env ERR1210_SNAPSHOT=1 开关。
    """
    if os.environ.get("ERR1210_SNAPSHOT", "1") != "1":
        return None
    try:
        from datetime import UTC, datetime

        ts = datetime.now(UTC)
        ts_str = ts.strftime("%Y%m%dT%H%M%S") + f"{ts.microsecond // 1000:03d}Z"
        out_dir = Path(data_dir) / "audit" / "offending_payloads"
        out_dir.mkdir(parents=True, exist_ok=True)
        snap = {
            "schema": _SNAPSHOT_SCHEMA,
            "ts_utc": ts.isoformat(),
            "session_id": session_id,
            "model": model,
            "is_compact_first": is_compact_first,
            "messages": messages,
            "tools": tools,
            "params": params,
            "injection_span": (
                [
                    {
                        "msg_idx": e.msg_idx,
                        "slot_kind": str(e.slot_kind),
                        "prefix_sha": e.prefix_sha,
                    }
                    for e in span.entries
                ]
                if span
                else None
            ),
            # trace 关联键: payload_trace 按 session_id + 秒级本地时间戳对齐（spec 6.1）
            "trace_key": {
                "session_id": session_id,
                "local_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        }
        path = out_dir / f"{ts_str}_{session_id[:8]}.json"
        path.write_text(
            json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return path
    except Exception:  # noqa: BLE001 — 快照失败 fail-open
        logger.warning("offending payload 快照落盘失败（fail-open）", exc_info=True)
        return None


# ── R9 B5-W1-03 迁移占位 ──
# 原 _Err1210Mixin（P0 状态机 14 法）于 R9 Phase 5 退役（design :475 改造类引用面）：
# 方法体逐字平移至 engine_services/recovery_controller.py（RecoveryController，
# 宿主实例态 _err1210_attempted/_err1210_run_seq/_deferred_replay_* 经 self._host
# 读写，行为零变化）。本文件保留模块级组件供新 service 与外部引用：
# content_prefix_sha / is_err1210 / SlotKind / parse_aggregated_slots / InjectedEntry /
# InjectionSpan / Err1210RecoveryResult / record_defer_event / snapshot_offending_payload。
# 类占位随 R9 收尾批清理。
