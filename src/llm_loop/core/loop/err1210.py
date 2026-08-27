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
from typing import TYPE_CHECKING, Any, cast

from llm_loop.llm.errors import LLMError, LLMHTTPError, parse_provider_error_code

if TYPE_CHECKING:
    from collections.abc import Iterator

    from llm_loop.core.message import Message
    from llm_loop.core.session import ModelSession

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


_AGG_SLOT_RE = re.compile(r"^--- \[slot:(interop|tip|hotcard|gate_note|memory|hint)\] ---$")


def parse_aggregated_slots(content: str) -> list[tuple[str, str]]:
    """聚合消息 content → [(slot, seg)] 段列表（P1 9.1 defer 拆解用）.

    build 统一聚合器产物格式: 各段以 "--- [slot:xxx] ---" 行起始（build.py 9.1）。
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


class _Err1210Mixin:
    """P0 状态机（engine 挂载；self 属性由 LoopEngine.__init__ 提供）."""

    if TYPE_CHECKING:
        _err1210_attempted: dict[str, int]
        _last_request_msg_count_by_session: dict[str, int]

    # ── 3.2 compact 首请求判定 ──

    def _is_compact_first_request(self, sess: ModelSession, messages: list[dict]) -> bool:
        """主信号: build.py:561 显式标记；辅助信号: 会话级相邻请求消息数骤降（≥30% 且 ≥8 条）.

        任一成立即 True（spec 5.1.1-1"或"语义）。
        """
        if getattr(self, "_last_history_compacted", False):
            return True
        counts = getattr(self, "_last_request_msg_count_by_session", None) or {}
        prev = counts.get(sess.session_id)
        if prev and len(messages) < prev:
            drop = prev - len(messages)
            if drop >= 8 and drop >= prev * 0.30:
                return True
        return False

    # ── 3.3 尾部注入剥离 ──

    def _strip_tail_injections(self, messages: list[dict]) -> tuple[list[dict], InjectionSpan] | None:
        """读 build 登记，身份复核 + 尾部连续段校验 → copy-on-write 剥离副本.

        任一失败返回 None 记 WARN（spec 5.1.1-5a：无法区分则整体保留放弃降级）。
        登记区间记录法天然正确处理"尾部 user 末位为真实输入"形态（只切登记过的条目）。
        """
        try:
            entries = sorted(
                getattr(self, "_last_build_injections", None) or [],
                key=lambda e: e.msg_idx,
            )
            if not entries:
                logger.info("err1210: 无注入登记，放弃降级（1210 或与注入群无关）")
                return None
            span = InjectionSpan(entries=tuple(entries))
            if not span.is_tail_contiguous(messages):
                logger.warning(
                    "err1210: 注入登记未构成尾部连续段，放弃降级（安全侧不误剥）idxs=%s n=%d",
                    [e.msg_idx for e in entries],
                    len(messages),
                )
                return None
            from llm_loop.core.cache_health import GATE_NOTE_CONTENT
            from llm_loop.core.loop.focus import _INJECTION_PREFIX

            for e in entries:
                m = messages[e.msg_idx]
                content = m.get("content")
                if not isinstance(content, str) or m.get("role") != "user":
                    logger.warning("err1210: 注入身份复核失败（非 user/非 str），放弃降级 idx=%d", e.msg_idx)
                    return None
                if content_prefix_sha(content) != e.prefix_sha:
                    logger.warning("err1210: 注入前缀 sha 不匹配，放弃降级 idx=%d", e.msg_idx)
                    return None
                if e.slot_kind == SlotKind.GATE_NOTE:
                    if content != GATE_NOTE_CONTENT:
                        logger.warning("err1210: gate_note 恒等校验失败，放弃降级 idx=%d", e.msg_idx)
                        return None
                elif not content.startswith(_INJECTION_PREFIX):
                    logger.warning(
                        "err1210: 注入前缀标识缺失（绕过 wrap_injection?），放弃降级 idx=%d", e.msg_idx
                    )
                    return None
            # copy-on-write：新 list，前缀逐字节不变（spec 5.1.1-2a）
            stripped = list(messages[: entries[0].msg_idx])
            return stripped, span
        except Exception:  # noqa: BLE001 — 剥离失败 fail-open（放弃降级）
            logger.warning("err1210: 剥离过程异常，放弃降级（fail-open）", exc_info=True)
            return None

    # ── 3.4 defer 回存（槽位复位语义）──

    def _defer_store(
        self,
        sess: ModelSession,
        entries: list[InjectedEntry],
        messages: list[dict] | None = None,
    ) -> bool:
        """按 slot_kind 分派复位；幂等；≤8 上限超限优先保留 interop（spec 6.3-5）.

        回存失败仅 WARN 不阻断重试（spec 4.2-2）。返回是否全部成功（观测用）。
        messages 为 build 产物（P1 9.1 AGGREGATED 拆解用，可空）。
        """
        ok = True
        try:
            by_slot: dict[SlotKind, list[InjectedEntry]] = {}
            for e in entries:
                by_slot.setdefault(e.slot_kind, []).append(e)
            # P1 9.1: AGGREGATED 拆解——聚合 entry 还原段级槽位后回存。
            # interop/tip 段重建 Message（原 message_ref 聚合时已弃，内容语义保真）；
            # hotcard/gate_note 段回流 by_slot 复用既有复位分支；hint 段跳过。
            agg_es = by_slot.pop(SlotKind.AGGREGATED, None) or []
            for e in agg_es:
                try:
                    m = (
                        messages[e.msg_idx]
                        if messages and 0 <= e.msg_idx < len(messages)
                        else {}
                    )
                    segs = parse_aggregated_slots(str(m.get("content") or ""))
                except Exception:  # noqa: BLE001 — 取段失败按空处理
                    segs = []
                if not segs:
                    logger.warning(
                        "err1210: AGGREGATED 拆解为空（idx=%d），该聚合条目按丢失处理（fail-open）",
                        e.msg_idx,
                    )
                    ok = False
                    continue
                from llm_loop.core.message import Message, MessageSource

                for slot_s, seg in segs:
                    if not seg:
                        continue
                    try:
                        k = SlotKind(slot_s)
                    except ValueError:
                        continue  # hint 段非消费槽
                    try:
                        if k in (SlotKind.INTEROP, SlotKind.TIP):
                            attr = (
                                "_interop_tail_messages"
                                if k == SlotKind.INTEROP
                                else "_tip_tail_messages"
                            )
                            r = Message(
                                role="system", content=seg, source=MessageSource.SYSTEM
                            )
                            active = getattr(self, attr, None) or []
                            setattr(self, attr, [r] + active)  # 前置拼接（旧先注入）
                            self._deferred_replay_refs = list(
                                getattr(self, "_deferred_replay_refs", None) or []
                            )
                            self._deferred_replay_refs.append((k, r))
                            record_defer_event(
                                "defer_stored",
                                sess.session_id,
                                str(k),
                                {"count": 1, "via": "aggregated"},
                            )
                        else:
                            # hotcard/gate_note 段回流既有复位分支（338 行后）
                            by_slot.setdefault(k, []).append(
                                InjectedEntry(
                                    msg_idx=e.msg_idx,
                                    slot_kind=k,
                                    prefix_sha=content_prefix_sha(seg),
                                    message_ref=None,
                                )
                            )
                    except Exception:  # noqa: BLE001 — 单段失败不阻断其余段
                        ok = False
                        logger.warning(
                            "err1210: AGGREGATED 段回存失败 slot=%s（fail-open）",
                            slot_s,
                            exc_info=True,
                        )
            # 总量 ≤8（interop/tip 按消息条数，hotcard/gate_note 各 1）
            total = sum(len(v) for k, v in by_slot.items() if k in (SlotKind.INTEROP, SlotKind.TIP))
            total += 1 if SlotKind.HOTCARD in by_slot else 0
            total += 1 if SlotKind.GATE_NOTE in by_slot else 0
            dropped_overflow: list[SlotKind] = []
            if total > _DEFER_REPLAY_TOTAL_LIMIT:
                keep_interop = by_slot.get(SlotKind.INTEROP, [])[:_DEFER_REPLAY_TOTAL_LIMIT]
                for k in (SlotKind.TIP, SlotKind.HOTCARD, SlotKind.GATE_NOTE):
                    if k in by_slot:
                        dropped_overflow.append(k)
                        del by_slot[k]
                if len(keep_interop) < len(by_slot.get(SlotKind.INTEROP, [])):
                    for _e in by_slot[SlotKind.INTEROP][_DEFER_REPLAY_TOTAL_LIMIT:]:
                        record_defer_event(
                            "defer_dropped",
                            sess.session_id,
                            str(SlotKind.INTEROP),
                            {"reason": "overflow"},
                        )
                    by_slot[SlotKind.INTEROP] = keep_interop
                for k in dropped_overflow:
                    record_defer_event(
                        "defer_dropped", sess.session_id, str(k), {"reason": "overflow"}
                    )

            # interop/tip: 回填内存槽（deferred 前置拼接——旧消息先注入，spec 5.1.3-3；
            # is 身份去重保证幂等：重复回存同一 Message 不累积，spec 5.1.1-3b）
            for slot, attr in ((SlotKind.INTEROP, "_interop_tail_messages"), (SlotKind.TIP, "_tip_tail_messages")):
                es = by_slot.get(slot)
                if not es:
                    continue
                refs = [e.message_ref for e in es if e.message_ref is not None]
                try:
                    active = getattr(self, attr, None) or []
                    new_refs = [r for r in refs if not any(r is a for a in active)]
                    if new_refs:
                        setattr(self, attr, new_refs + active)  # 幂等：整槽赋值语义
                        # 重注入检测（build 消费时 is 身份匹配 → defer_replayed）
                        self._deferred_replay_refs = list(getattr(self, "_deferred_replay_refs", None) or [])
                        self._deferred_replay_refs.extend((slot, r) for r in new_refs)
                    record_defer_event(
                        "defer_stored",
                        sess.session_id,
                        str(slot),
                        {"count": len(refs), "shas": [e.prefix_sha for e in es]},
                    )
                except Exception:  # noqa: BLE001 — 单槽失败不阻断其余
                    ok = False
                    logger.warning("err1210: defer 回填 %s 失败（fail-open）", slot, exc_info=True)

            # hotcard: consumed 复位（身份校验防复活陈旧卡）
            if SlotKind.HOTCARD in by_slot:
                try:
                    from llm_loop.core.loop.hotcard import reset_hotcard_consumed

                    if reset_hotcard_consumed(
                        session_id=sess.session_id, data_dir=self.settings.data_dir
                    ):
                        self._deferred_replay_slots = set(self._deferred_replay_slots)
                        self._deferred_replay_slots.add(str(SlotKind.HOTCARD))
                        record_defer_event(
                            "defer_stored", sess.session_id, str(SlotKind.HOTCARD), {}
                        )
                    else:
                        ok = False
                        logger.warning("err1210: hotcard consumed 复位未生效（校验不匹配/无卡）")
                except Exception:  # noqa: BLE001
                    ok = False
                    logger.warning("err1210: hotcard 复位异常（fail-open）", exc_info=True)

            # gate_note: pending 置位
            if SlotKind.GATE_NOTE in by_slot:
                try:
                    self._cache_monitor.restore_gate_note(sess.session_id)
                    self._deferred_replay_slots = set(self._deferred_replay_slots)
                    self._deferred_replay_slots.add(str(SlotKind.GATE_NOTE))
                    record_defer_event("defer_stored", sess.session_id, str(SlotKind.GATE_NOTE), {})
                except Exception:  # noqa: BLE001
                    ok = False
                    logger.warning("err1210: gate_note 复位异常（fail-open）", exc_info=True)
            return ok
        except Exception:  # noqa: BLE001 — defer 整体失败不阻断重试
            logger.warning("err1210: defer 回存异常（fail-open，不阻断重试）", exc_info=True)
            return False

    # ── 3.6 P0 主入口 ──

    def _try_err1210_recovery(
        self,
        *,
        exc: LLMError,
        sess: ModelSession,
        messages: list[dict],
        tools_param: list[dict],
        llm_client: Any,
        chat_model_arg: str | None,
        timeout_s: float | None,
        session_id: str,
    ) -> Err1210RecoveryResult:
        """编排: 判定 → 快照 → 剥离 → defer 回存 → 单次重试 → 耗尽标记（design 2.2.2-④）.

        recovered=False 时 engine 按既有错误路径继续（overflow/fallback/如实反馈）。
        全路径 fail-open：内部未捕获异常等价 recovered=False。
        """
        result = Err1210RecoveryResult()
        if os.environ.get("ERR1210_RECOVERY", "1") != "1":
            return result  # 总开关关闭：零行为（完全回到现行）
        try:
            if not is_err1210(exc):
                return result
            if not self._is_compact_first_request(sess, messages):
                return result
            seq = getattr(self, "_compact_event_seq", 0)
            attempted = getattr(self, "_err1210_attempted", None) or {}
            if attempted.get(session_id) == seq:
                # 本 compact 事件内已耗尽（spec 5.1.1-4：单次重试防循环）
                result.attempted = True
                result.exhausted = True
                return result
            result.attempted = True

            compact_first = True
            model_ref = (
                chat_model_arg
                or getattr(llm_client, "model", "")
                or getattr(self.settings, "llm_model", "")
            )
            entries = sorted(
                getattr(self, "_last_build_injections", None) or [],
                key=lambda e: e.msg_idx,
            )
            span = InjectionSpan(entries=tuple(entries)) if entries else None

            # ① 快照（剥离前完整载荷；失败不阻断）
            snapshot_offending_payload(
                messages=messages,
                tools=tools_param,
                params={
                    "model": model_ref,
                    "max_tokens": getattr(llm_client, "max_tokens", None),
                    "thinking_mode": getattr(llm_client, "thinking_mode", None),
                    "reasoning_effort": getattr(llm_client, "reasoning_effort", None),
                    "timeout_s": timeout_s,
                    "provider": getattr(llm_client, "provider", ""),
                },
                session_id=session_id,
                model=model_ref,
                is_compact_first=compact_first,
                span=span,
                data_dir=self.settings.data_dir,
            )

            # ② defer 回存（消费过的槽复位——无论剥离成败，防注入随一次性消费丢失）
            # P1 9.1: 传 messages 供 AGGREGATED 拆解（聚合 entry → 段级槽位复位）
            result.deferred_ok = self._defer_store(sess, entries, messages)

            # ③ 剥离
            stripped = self._strip_tail_injections(messages)
            if stripped is None:
                self._record_action(
                    "err1210.recovery",
                    "aborted",
                    f"剥离校验失败放弃降级；defer_ok={result.deferred_ok}",
                )
                # 耗尽标记仍写入（本 compact 事件不再尝试，防循环）
                self._err1210_attempted = {**attempted, session_id: seq}
                return result
            retry_messages, span = stripped
            result.stripped_count = len(span.entries)

            # ④ 单次重试（先标记防循环——本 compact 事件至多一次降级）
            self._err1210_attempted = {**attempted, session_id: seq}
            resp, retry_exc = self._retry_consume_stream(
                llm_client=llm_client,
                messages=retry_messages,
                tools_param=tools_param,
                chat_model_arg=chat_model_arg,
                timeout_s=timeout_s,
                session_id=session_id,
            )
            if resp is not None:
                result.resp = resp
                result.recovered = True
                self._record_action(
                    "err1210.recovery",
                    "recovered",
                    f"剥离 {result.stripped_count} 条后重试成功；defer_ok={result.deferred_ok}",
                )
            elif retry_exc is not None and is_err1210(retry_exc):
                result.exhausted = True
                record_defer_event(
                    "defer_exhausted", session_id, "all", {"stripped": result.stripped_count}
                )
                self._record_action(
                    "err1210.recovery",
                    "exhausted",
                    f"剥离 {result.stripped_count} 条后重试仍 1210（耗尽上抛）",
                )
            else:
                # 非 1210 二次异常（网络/超时）：recovered=False，原 1210 语义不被掩盖，
                # 详情已在 _retry_consume_stream 内记 action——engine 继续既有错误链
                pass
            return result
        except Exception:  # noqa: BLE001 — 外层兜底等价 recovered=False
            logger.warning("err1210: 恢复过程异常（fail-open 等价 recovered=False）", exc_info=True)
            return result

    def _retry_consume_stream(
        self,
        *,
        llm_client: Any,
        messages: list[dict],
        tools_param: list[dict],
        chat_model_arg: str | None,
        timeout_s: float | None,
        session_id: str,
    ) -> tuple[Any | None, LLMError | None]:
        """单次重试并完整消费新流（不 yield 增量——外层已过 yield 点，design 风险 6）.

        返回 (resp, retry_exc)：成功 resp 非 None；失败 resp=None 且 retry_exc 为二次
        异常（1210 复现 / 网络 / 超时——调用方区分耗尽与其他失败）。
        1210 在响应体阶段抛出、原流尚无 delta 输出——无重复输出风险。
        """
        kwargs: dict[str, Any] = {
            "messages": messages,
            "tools": tools_param,
            "timeout_s": timeout_s,
        }
        if chat_model_arg:
            kwargs["model"] = chat_model_arg
        stream_fn = getattr(llm_client, "chat_stream", None)
        try:
            if callable(stream_fn):
                it = cast("Iterator[Any]", stream_fn(**kwargs))
                while True:  # 完整消费至流尾；StopIteration.value 即完整 resp（client 侧聚合）
                    try:
                        next(it)
                    except StopIteration as stop:
                        return stop.value, None
            return llm_client.chat(**kwargs), None
        except Exception as retry_exc:  # noqa: BLE001 — 二次异常不掩盖原 1210
            self._record_action(
                "err1210.recovery",
                "retry_error",
                f"重试失败: {str(retry_exc)[:200]}",
            )
            return None, retry_exc if isinstance(retry_exc, LLMError) else None

    # ── 供 build/engine 接线调用的辅助（任务组 4）──

    def _note_defer_replayed(self, session_id: str, slot_kind: SlotKind, count: int = 1) -> None:
        """build 消费 defer 回填消息时记 defer_replayed（观测闭环，spec 4.4-2）."""
        record_defer_event(
            "defer_replayed", session_id, str(slot_kind), {"count": count}
        )
        self._last_build_defer_replayed = True

    # ── engine 接线点（任务组 4.3 瘦身: engine.py 行数守卫只留最小调用）──

    def _err1210_init(self) -> None:
        """engine.__init__ 调用（tasks 4.2）: per-session 恢复状态字段初始化.

        - _err1210_attempted: per-session 耗尽标记（值 = compact 事件 seq；新事件自然不等 → 降级机会重获）
        - _last_request_msg_count_by_session: 骤降兜底判定数据源（每次成功请求后更新）

        其余六个恢复状态字段（注入登记/compact 事件 seq/defer 重注入检测等）已迁
        _RunState per-session 桶（runstate.py，属性 shim 保旧名——err1210 P0-A）。
        """
        self._err1210_attempted: dict[str, int] = {}
        self._last_request_msg_count_by_session: dict[str, int] = {}

    def _err1210_attempt_recovery(
        self,
        *,
        exc: LLMError,
        sess: ModelSession,
        messages: list[dict],
        tools_param: list[dict],
        llm_client: Any,
        chat_model_arg: str | None,
        session_id: str,
        current_resp: Any,
        current_round_ms: float,
    ) -> tuple[bool, Any, float]:
        """engine except 接线点（tasks 4.3）: compact 首请求 1210 定向降级重试.

        剥离尾部一次性注入槽 → defer 回存 → 单次重试（重试流完整消费、不 yield
        增量——design 风险 6）。恢复成功返回 (True, 新 resp, 0.0)——engine 控制流
        自然落回 action.llm_decide 正常路径（与 fallback 成功合流同构）；
        失败返回 (False, current_resp, current_round_ms) 原样继续既有错误链
        （1210 本就 4xx 不进 fallback，走如实反馈——fail-open 与现行行为一致；
        恢复轮无 TTFT/耗时单列——design 风险 6，如实不伪造）。
        env ERR1210_RECOVERY=0 完全旁路。
        """
        try:
            result = self._try_err1210_recovery(
                exc=exc, sess=sess, messages=messages, tools_param=tools_param,
                llm_client=llm_client, chat_model_arg=chat_model_arg,
                timeout_s=self._runtime_timeout(), session_id=session_id,
            )
            if result.recovered and result.resp is not None:
                return True, result.resp, 0.0
        except Exception:  # noqa: BLE001 — P0 fail-open 兜底（等价未恢复）
            logger.warning("err1210: engine 接线异常（fail-open）", exc_info=True)
        return False, current_resp, current_round_ms

    def _err1210_note_defer_lost(self, session_id: str, reason: str) -> None:
        """defer 重注入轮再次失败 → 槽丢失观测（spec 5.1.3-5；fail-open）."""
        if getattr(self, "_last_build_defer_replayed", False):
            record_defer_event(
                "defer_lost_on_reinject", session_id, "all", {"reason": reason}
            )
            self._last_build_defer_replayed = False

    def _err1210_note_request_count(self, session_id: str, msg_count: int) -> None:
        """骤降兜底判定数据源（tasks 4.2）: 仅成功轮更新本会话最近请求消息数.

        失败轮不更新——P0 判定读到的 prev 恒为上一次成功请求，骤降语义正确。
        """
        self._last_request_msg_count_by_session[session_id] = msg_count
