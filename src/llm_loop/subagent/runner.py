"""SubAgentRunner：递归子代理执行器（设计见本地开发文档）.

核心: 独立 session（隔离上下文）+ 迷你 LLM 循环 + 真实执行（复用 registry）+
父执行域继承 + 有限递归/轮数资源边界。工具能力不因“子代理”身份自动降级；
显式父 scope 与工具自身授权/安全检查仍完整生效。全部如实回执。
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import (
    Message,
    MessageSource,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    dict_wire_chars,
)
from llm_loop.core.run_context import (
    WaitBudget,
    child_cancel_event,
    child_wait_budget_used,
    current_model_label,
    current_run_generation,
    current_session_id,
    current_tool_discovery_scope,
    current_workspace_root,
    workspace_base,
)
from llm_loop.core.runtime_params import HARD_CAP_MAX_ITERATIONS
from llm_loop.core.session import Session, SessionStore
from llm_loop.core.subagent_delivery import SubAgentDeliveryJournal
from llm_loop.core.subagent_topology import SubAgentTopologyJournal, SubAgentTopologyState
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.fleet.coordinator import ProjectCoordinator
from llm_loop.fleet.store import WorkerLease
from llm_loop.llm.client import LLMClient
from llm_loop.llm.errors import (
    LLMEmptyResponseError,
    LLMError,
    LLMHTTPError,
    LLMProjectionError,
    is_overflow_error,
)
from llm_loop.resources.contracts import ExecutionClass, ServicePriority
from llm_loop.resources.provider_calls import ProviderCallCoordinator, subagent_provider_chat
from llm_loop.resources.provider_settlement import (
    ProviderAttemptKind,
    ProviderCallOutcome,
    ProviderCallPurpose,
)
from llm_loop.tools.registry import ToolRegistry
from llm_loop.workspace.artifacts import WorkspaceArtifactStore

if TYPE_CHECKING:
    from llm_loop.core.write_scope import WriteScope
    from llm_loop.memory.archive import ArchiveStore

# 子代理不维护第二套静态工具能力表。父执行域由 current_tool_discovery_scope
# 继承；None=完整 registry，显式集合=不得扩权。工具自身继续承担授权/安全边界。
# EVO-20261012-bb3022f4 (E4): spawn 声明的 requires.tools 升级为程序级强制
# 白名单（见 _compute_child_tool_scope）：child 的发现面与执行面都被截断到
# 声明集（≤ 父 scope，只降不升）；spawn_subagent 默认从 child 面剔除（防递归
# 舰队），显式授予走 CHILD_SPAWN_GRANT 配置白名单。

MAX_DEPTH = 3
MAX_ITERATIONS = HARD_CAP_MAX_ITERATIONS

_PARENT_CONTEXT_ARTIFACT_CHUNK_CHARS = 12_000

# 子代理深度属于程序控制面，不允许模型通过 tool arguments 自报/篡改。
# -1 表示当前不在子代理内；顶层 spawn 产生 depth=0，子代理内再次 spawn 自动 +1。
_CURRENT_SUBAGENT_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "lfl_current_subagent_depth", default=-1
)


def next_subagent_depth() -> int:
    """返回下一层真实子代理深度（仅由程序运行上下文计算）."""
    return _CURRENT_SUBAGENT_DEPTH.get() + 1


def _strip_ingress_markers(messages: list[dict]) -> list[dict]:
    """Drop engine-only ``_active_run_ingress_ref`` markers from a child wire.

    EVO-20261020-b1c00127: the subagent wire is sent without a
    GuardRequestContext, so any marker that survives into the provider request
    trips ``active_run_ingress_unexpected_marker`` before transport. Markers are
    transport bookkeeping, never provider content; strip them defensively on
    every wire exit path (no-op when none are present).
    """
    if not any(isinstance(m, dict) and "_active_run_ingress_ref" in m for m in messages):
        return messages
    return [
        {k: v for k, v in m.items() if k != "_active_run_ingress_ref"}
        if isinstance(m, dict)
        else m
        for m in messages
    ]


# EVO-20261023-fc5c34b9: measured chars-per-token for the reviewer's frozen
# material on the GLM-5.3 tokenizer (real `usage.prompt_tokens` from the
# provider, not an estimate):
#   * ASCII portion of the material: 1,711,174 chars -> 650,046 tokens
#     (2.633 chars/token)
#   * non-ASCII (CJK) portion: 223,926 chars -> 156,377 tokens
#     (1.432 chars/token)
#   * whole material: 1,935,100 chars -> 761,811 tokens (2.540 chars/token)
# The registry default (0.6) is a Chinese-mixed calibration and overstates the
# token cost of this material by ~4.2x, which made the reviewer wire budget
# unsatisfiable for real code artifacts. These two ratios replace it.
_WIRE_ASCII_CHARS_PER_TOKEN = 2.633
_WIRE_NON_ASCII_CHARS_PER_TOKEN = 1.432
# EVO-20261023-fc5c34b9: BPE is not additive across character classes — word
# boundaries merge ASCII and CJK runs, so the sum of the per-class costs
# over-charges the real token count of a mixed wire. Measured on the frozen
# material: per-class estimate 806,537 tokens vs the provider's real
# `usage.prompt_tokens` 762,018 -> 44,519 tokens over-charged, i.e.
# 0.198811 tokens per minority-class character. The saving is charged per
# minority character (the merges happen where the two classes meet), so a
# single-class wire is left exactly at its measured class ratio.
_WIRE_CROSS_CLASS_SAVING_TOKENS = 0.198811


def _wire_chars_per_token(messages: list[dict], registry_ratio: float) -> float:
    """Effective chars-per-token for a wire, from its own character mix.

    EVO-20261023-fc5c34b9. Each character class is charged at its MEASURED
    cost on the reviewer tokenizer (ASCII 2.633 chars/token, non-ASCII 1.432),
    instead of the registry's Chinese-mixed 0.6 for everything. The result is
    the weighted average of the two, so it lies in
    [min(class ratios), max(class ratios)].

    A LARGER chars-per-token means charging the wire FEWER tokens, i.e. a
    more permissive estimate. The measured ratios are therefore used only
    because they were measured on this provider's real tokenizer (real
    `usage.prompt_tokens`), and each class ratio is floored at the registry
    ratio: a class whose measured cost is DENSER than the registry claims
    keeps the registry's conservative rate, so a measurement can only ever
    correct an over-charge, never invent a discount. The cross-class saving
    is likewise a measured correction of the per-class sum.
    """
    if registry_ratio <= 0:
        return registry_ratio
    ascii_chars = 0
    non_ascii_chars = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        for ch in content:
            if ord(ch) < 128:
                ascii_chars += 1
            else:
                non_ascii_chars += 1
    total = ascii_chars + non_ascii_chars
    if total <= 0:
        return registry_ratio
    # A measured class ratio may only correct an over-charge: it is floored
    # at the registry ratio, so a class the registry already charges densely
    # keeps the registry's conservative rate.
    ascii_ratio = max(registry_ratio, _WIRE_ASCII_CHARS_PER_TOKEN)
    non_ascii_ratio = max(registry_ratio, _WIRE_NON_ASCII_CHARS_PER_TOKEN)
    # Token cost of the wire, then invert to an effective chars-per-token.
    tokens = ascii_chars / ascii_ratio + non_ascii_chars / non_ascii_ratio
    if tokens <= 0:
        return registry_ratio
    # BPE merges across character classes, so the per-class sum over-charges
    # the real count of a MIXED wire (measured on the frozen material:
    # per-class 806,537 tokens vs the provider's real 762,018 — 44,519
    # tokens over-charged). The over-charge scales with the MINORITY class
    # size, because the merges happen where the two classes meet, so a
    # single-class wire has nothing to merge and is left exactly at its
    # measured class ratio. This keeps the invariant that a pure-CJK wire
    # is charged the registry ratio (never more permissive) while a
    # genuinely mixed wire is charged what it actually costs.
    if ascii_chars and non_ascii_chars:
        tokens -= _WIRE_CROSS_CLASS_SAVING_TOKENS * min(ascii_chars, non_ascii_chars)
    effective = total / tokens
    # The effective ratio lies between the two class ratios by construction.
    # A LARGER ratio means charging the wire FEWER tokens (more permissive),
    # and that is justified here only by the measured per-class costs; a
    # class with no measurement keeps the registry rate (each class ratio is
    # floored at the registry ratio above). The clamp only guards against a
    # pathological mix falling outside the two class ratios.
    lower = min(ascii_ratio, non_ascii_ratio)
    upper = max(ascii_ratio, non_ascii_ratio)
    return min(upper, max(lower, effective))


@dataclass
class SubAgentResult:
    """子代理执行结果（如实回传父代理）."""

    final_answer: str
    outcome: str = "completed"  # completed/failed/cancelled/truncated/refused
    rounds: int = 0
    tool_calls: list[dict] = field(default_factory=list)  # 工具轨迹摘要（name→status）
    reports: list[str] = field(default_factory=list)  # 中途报告（DSH 借鉴 022-B）
    truncated: bool = False  # 轮数超限截断
    refused: bool = False  # 深度超限拒绝
    depth: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    def __post_init__(self) -> None:
        """保持 legacy flags 与结构化 outcome 一致，禁止构造“截断但 completed”。"""
        if self.outcome == "completed":
            if self.refused:
                self.outcome = "refused"
            elif self.truncated:
                self.outcome = "truncated"
        if self.outcome == "refused":
            self.refused = True
        if self.outcome == "truncated":
            self.truncated = True


@dataclass
class _SubAgentHandle:
    """runner-owned background child handle；不直接暴露裸对象给模型。"""

    child_id: str
    parent_id: str
    parent_run_generation: str
    depth: int
    generation: str
    review_isolated: bool = False  # P0-B genuine reviewer never accepts parent steer
    state: str = "running"
    result: SubAgentResult | None = None
    cancel_requested: bool = False
    collected: bool = False
    done_event: threading.Event = field(default_factory=threading.Event, repr=False)
    activity_event: threading.Event = field(default_factory=threading.Event, repr=False)
    seen_reports: int = 0
    thread: threading.Thread | None = field(default=None, repr=False)


def child_spawn_grant_allowed() -> bool:
    """EVO-20261012-bb3022f4 (E4): CHILD_SPAWN_GRANT 授予判断（模块级单一来源）.

    - ""（默认）= 未授予：child 工具面剔除 spawn_subagent（防递归舰队）；
    - "*" = 全量授予；
    - 逗号分隔 parent session_id = 精确授予该父会话的 child；
    - 配置读取失败保守视为未授予。
    """
    raw = ""
    try:
        from llm_loop.config import load_settings

        raw = str(getattr(load_settings(), "child_spawn_grant", "") or "").strip()
    except Exception:  # noqa: BLE001 — 配置读取失败保守视为未授予
        return False
    if not raw:
        return False
    if raw == "*":
        return True
    parent_sid = str(current_session_id.get() or "")
    entries = {e.strip() for e in raw.split(",") if e.strip()}
    return bool(parent_sid) and parent_sid in entries


class SubAgentRunner:
    """子代理执行器：独立会话 + 迷你循环 + 受限工具 + 预算/深度边界."""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        session_store: SessionStore,
        *,
        max_depth: int = MAX_DEPTH,
        max_iterations: int = MAX_ITERATIONS,
        tool_execution_root: str | None = None,
        artifact_store: WorkspaceArtifactStore | None = None,
        provider_call_coordinator: ProviderCallCoordinator | None = None,
        llm_resolver: Callable[[str], LLMClient] | None = None,
        context_limits_resolver: Callable[[str], tuple[int, int | None, float] | None] | None = None,
        archive_store: ArchiveStore | None = None,
        parent_session_provider: Callable[[str], Session | None] | None = None,
        project_coordinator: ProjectCoordinator | None = None,
        fleet_lease_ttl_seconds: float | None = 900.0,
        # EVO-20261023-fc5c34b9: optional per-child chars_per_token override.
        # The registry ratio (0.6) is a Chinese-mixed calibration and overstates
        # the token cost of an ASCII-heavy code/JSON diff by ~5.8x, which made
        # the reviewer wire budget unsatisfiable for real code artifacts. The
        # reviewer-isolated, tool-less child wire therefore derives its own
        # ratio from the wire's actual character mix
        # (_wire_chars_per_token) — never more permissive than the registry
        # ratio for non-ASCII content.
    ) -> None:
        self.llm = llm
        self._llm_resolver = llm_resolver
        # Optional model-registry facts and existing ArchiveStore; fake/legacy
        # runners without a qualified window retain their exact original wire.
        self._context_limits_resolver = context_limits_resolver
        self._archive_store = archive_store
        self._parent_session_provider = parent_session_provider
        self.registry = registry
        self.session_store = session_store
        self.max_depth = max_depth
        self.max_iterations = max_iterations
        self.artifact_store = artifact_store
        self.provider_call_coordinator = provider_call_coordinator
        journal_root = (
            tool_execution_root
            if tool_execution_root is not None
            else str(self.session_store.root.parent / "audit" / "tool_execution")
        )
        self._tool_journal = ToolExecutionJournal(
            event_store=self.session_store.event_store,
            result_root=journal_root,
            session_store=self.session_store,
            receipt_committed_hook=self.settle_committed_receipt,
        )
        self._topology_journal = SubAgentTopologyJournal(self.session_store.event_store)
        self._delivery_journal = SubAgentDeliveryJournal(self.session_store.event_store)
        self._runner_owner_id = uuid.uuid4().hex
        self._children_guard = threading.Lock()
        # Fleet run-boundary wiring (DESIGN-20260919 step-4): None keeps every
        # fleet behavior off; explicit injection is the opt-in/exit path.
        self._project_coordinator = project_coordinator
        self._fleet_leases: dict[str, WorkerLease] = {}
        # fleet slice 3: 有界租约 + 每轮心跳续约；None 显式保留旧的永不过期行为。
        self._fleet_lease_ttl_seconds = fleet_lease_ttl_seconds
        # Local-active maps remain strictly process-local.  Recovered topology is kept
        # separately so restart never fabricates Thread/Event/Future or a writable mailbox.
        self._children_by_parent: dict[str, set[str]] = {}
        self._parent_by_child: dict[str, str] = {}
        # P3: parent session alone is insufficient across sequential runs of the same session.
        self._parent_run_generation_by_child: dict[str, str] = {}
        self._max_handles = 128
        self._durable_topology: OrderedDict[str, SubAgentTopologyState] = OrderedDict()
        self._local_generation_by_child: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._agent_inbox: dict[str, list[tuple[int, str, str]]] = {}
        self._messages_to_parent: dict[str, list[str]] = {}
        self._handles: dict[str, _SubAgentHandle] = {}
        self._handle_order: list[str] = []
        self._message_seq = 0
        self._recover_topology_index()

    def _resolve_child_llm(self, model_ref: str) -> tuple[LLMClient, str]:
        """Resolve an explicit/mechanically inherited model without choosing semantics."""

        ref = str(model_ref or "").strip()
        if not ref:
            return self.llm, ""
        if self._llm_resolver is None:
            raise ValueError("subagent model routing unavailable in this runner")
        return self._llm_resolver(ref), ref

    def _recover_topology_index(self) -> None:
        """Use lazy durable topology recovery; never materialize an all-child RAM index."""
        # EventStore + child Session are the durable sources of truth.  Eagerly scanning
        # every historical child at startup made memory and startup cost scale with all
        # prior work.  Read paths recover one requested child and populate the bounded
        # cache below; no active worker/mailbox is ever fabricated.
        return None

    def _cache_durable_topology(self, state: SubAgentTopologyState) -> None:
        with self._children_guard:
            self._durable_topology[state.child_id] = state
            self._durable_topology.move_to_end(state.child_id)
            while len(self._durable_topology) > self._max_handles:
                self._durable_topology.popitem(last=False)

    def _durable_state(self, child_id: str) -> SubAgentTopologyState | None:
        """Read-through bounded topology cache with Session/Event parent cross-check."""
        sid = str(child_id or "")
        if not sid:
            return None
        with self._children_guard:
            cached = self._durable_topology.get(sid)
            if cached is not None:
                self._durable_topology.move_to_end(sid)
                return cached
        state = self._topology_journal.recover(sid)
        if state is None or not state.parent_id:
            return None
        try:
            # M3 验收后续：交叉验证走 SessionStore.parent_id_of 轻量只读
            # （meta 缓存，与 load().parent_id 等价）——agents/tree 对 707 个
            # 候选逐个 recover+load（全量 JSON 解析）是源站 5-13s 的主因之一。
            session_parent = str(self.session_store.parent_id_of(sid))
        except Exception:  # noqa: BLE001 - recovery is read-only and fail-closed
            return None
        if session_parent != state.parent_id:
            return None
        self._cache_durable_topology(state)
        return state

    def _refresh_topology_state(self, child_id: str) -> SubAgentTopologyState | None:
        state = self._topology_journal.recover(child_id)
        if state is None:
            with self._children_guard:
                self._durable_topology.pop(child_id, None)
        else:
            self._cache_durable_topology(state)
        return state

    def topology_snapshot(self, child_session_id: str) -> dict[str, object] | None:
        """Return mechanical topology/ownership/settlement facts without reviving work."""
        sid = str(child_session_id or "").strip()
        if not sid:
            return None
        with self._children_guard:
            handle = self._handles.get(sid)
        durable = None if handle is not None else self._durable_state(sid)
        with self._children_guard:
            handle = self._handles.get(sid)
            if handle is not None:
                parent_id = handle.parent_id
                generation = handle.generation
                terminal = handle.state != "running"
                outcome = handle.result.outcome if handle.result is not None else ""
                collected = handle.collected
            elif durable is not None:
                parent_id = durable.parent_id
                generation = durable.generation
                terminal = durable.terminal
                outcome = durable.outcome
                collected = False
            else:
                return None

        result_record = self._delivery_journal.result(sid, generation) if terminal else None
        durable_settled = bool(
            result_record is not None
            and self._delivery_journal.settlement_committed(
                child_id=sid,
                parent_id=parent_id,
                generation=generation,
                result_id=result_record.result_id,
            )
        )
        if handle is not None and durable_settled and not collected:
            with self._children_guard:
                current = self._handles.get(sid)
                if current is not None and current.generation == generation:
                    current.collected = True
                    collected = True
        if handle is not None:
            return {
                "child_id": sid,
                "parent_id": parent_id,
                "generation": generation,
                "owner_state": "terminal_local" if terminal else "local_active",
                "local_active": not terminal,
                "terminal": terminal,
                "outcome": outcome,
                "settlement_state": "collected" if collected or durable_settled else "uncollected",
            }
        return {
            "child_id": sid,
            "parent_id": parent_id,
            "generation": generation,
            "owner_state": "terminal_known" if terminal else "orphaned",
            "local_active": False,
            "terminal": terminal,
            "outcome": outcome,
            "settlement_state": "collected" if durable_settled else "unknown",
        }

    @staticmethod
    def _delivered_mailbox_ids(sess: Session, generation: str) -> set[str]:
        ids: set[str] = set()
        for message in sess.messages:
            metadata = dict(getattr(message, "metadata", None) or {})
            if str(metadata.get("subagent_generation") or "") != generation:
                continue
            raw = metadata.get("subagent_mailbox_message_ids")
            if isinstance(raw, list):
                ids.update(str(item) for item in raw if str(item))
        return ids

    @staticmethod
    def _result_payload(result: SubAgentResult) -> dict[str, object]:
        return {
            "final_answer": result.final_answer,
            "outcome": result.outcome,
            "rounds": result.rounds,
            "tool_calls": [dict(item) for item in result.tool_calls],
            "reports": list(result.reports),
            "truncated": result.truncated,
            "refused": result.refused,
            "depth": result.depth,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
        }

    @staticmethod
    def _result_from_payload(payload: dict[str, object]) -> SubAgentResult:
        raw_calls = payload.get("tool_calls")
        raw_reports = payload.get("reports")

        def _int_value(key: str) -> int:
            value = payload.get(key)
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float, str)):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
            return 0

        return SubAgentResult(
            final_answer=str(payload.get("final_answer") or ""),
            outcome=str(payload.get("outcome") or "failed"),
            rounds=_int_value("rounds"),
            tool_calls=[dict(item) for item in raw_calls if isinstance(item, dict)]
            if isinstance(raw_calls, list)
            else [],
            reports=[str(item) for item in raw_reports]
            if isinstance(raw_reports, list)
            else [],
            truncated=bool(payload.get("truncated")),
            refused=bool(payload.get("refused")),
            depth=_int_value("depth"),
            tokens_in=_int_value("tokens_in"),
            tokens_out=_int_value("tokens_out"),
        )

    def delivery_snapshot(self, child_session_id: str) -> dict[str, object] | None:
        """Return durable delivery/result facts without fabricating a worker or settlement."""
        sid = str(child_session_id or "").strip()
        if not sid:
            return None
        with self._children_guard:
            handle = self._handles.get(sid)
        durable = None if handle is not None else self._durable_state(sid)
        generation = handle.generation if handle is not None else (durable.generation if durable else "")
        parent_id = handle.parent_id if handle is not None else (durable.parent_id if durable else "")
        if not generation or not parent_id:
            return None
        try:
            sess = self.session_store.load(sid)
            delivered = self._delivered_mailbox_ids(sess, generation)
        except Exception:  # noqa: BLE001 - read-only delivery observability fails closed
            delivered = set()
        pending = self._delivery_journal.pending_mailbox(
            sid, generation, delivered_ids=delivered
        )
        reports = self._delivery_journal.reports(sid, generation)
        result = self._delivery_journal.result(sid, generation)
        cancel = self._delivery_journal.cancel_state(sid, generation)
        return {
            "child_id": sid,
            "parent_id": parent_id,
            "generation": generation,
            "pending_mailbox_count": len(pending),
            "pending_mailbox": [
                {
                    "message_id": row.message_id,
                    "sender_id": row.sender_id,
                    "content": row.content,
                    "seq": row.seq,
                }
                for row in pending
            ],
            "reports": [
                {"report_id": row.report_id, "content": row.content, "seq": row.seq}
                for row in reports
            ],
            "result_available": result is not None,
            "result_id": result.result_id if result is not None else "",
            "cancel_requested": cancel is not None,
            "cancel_reason": cancel.reason if cancel is not None else "",
        }

    def _persist_terminal_result(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        result: SubAgentResult,
    ) -> bool:
        if self._delivery_journal.enabled:
            reports = self._delivery_journal.reports(child_id, generation)
            result.reports = [row.content for row in reports]
            report_ids = [row.report_id for row in reports]
        else:
            with self._children_guard:
                result.reports = list(self._messages_to_parent.get(child_id, []))
            report_ids = []
        record = self._delivery_journal.result_available(
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            result=self._result_payload(result),
            report_ids=report_ids,
        )
        return record is not None

    def _prune_handles_locked(self, *, reserve_slot: bool = False) -> None:
        """只淘汰最老 terminal handle；running child 永不被静默丢弃。"""
        limit = self._max_handles - (1 if reserve_slot else 0)
        while len(self._handles) > max(0, limit):
            victim = next(
                (
                    sid
                    for sid in self._handle_order
                    if sid in self._handles and self._handles[sid].state != "running"
                ),
                "",
            )
            if not victim:
                return
            self._handles.pop(victim, None)
            with suppress(ValueError):
                self._handle_order.remove(victim)

    def active_children(self, parent_session_id: str) -> list[str]:
        """返回某父会话当前仍在运行的直接 child（稳定排序，仅事实查询）."""
        with self._children_guard:
            return sorted(self._children_by_parent.get(parent_session_id, set()))

    def pending_obligations(
        self, parent_session_id: str, *, run_generation: str = ""
    ) -> list[dict[str, object]]:
        """返回 parent 正常 final 时仍在运行、必须机械收束的 child 资源。

        terminal-but-unread result 不是完成门槛：模型可自行决定是否读取 child 结果。
        """

        target_generation = str(run_generation or current_run_generation.get() or "")
        with self._children_guard:
            return [
                {"kind": "subagent", "id": sid, "state": handle.state}
                for sid, handle in sorted(self._handles.items())
                if handle.parent_id == parent_session_id
                and handle.state == "running"
                and (
                    not target_generation
                    or handle.parent_run_generation == target_generation
                )
            ]

    def parent_of(self, child_session_id: str) -> str:
        """返回已知 direct parent；durable edge 不代表 child 在本进程 active。"""
        with self._children_guard:
            active = self._parent_by_child.get(child_session_id, "")
            if active:
                return active
        durable = self._durable_state(child_session_id)
        return durable.parent_id if durable is not None else ""

    def send_current_message(self, target_id: str, content: str) -> tuple[bool, str, str]:
        """以当前运行会话为 sender，向直接 parent/child 投递消息。

        sender 永远由 ``current_session_id`` 服务端推导，模型不能自报。只允许
        parent→direct active child、child→direct active parent；self/sibling/
        grandparent/grandchild/unknown/dead target 均拒绝。
        """

        sender_id = current_session_id.get()
        body = str(content or "").strip()
        requested_target = str(target_id or "").strip()
        if not sender_id:
            return False, "当前没有可归因的 agent session，无法发送消息", ""
        if not body:
            return False, "消息内容为空", ""
        if len(body) > 4000:
            return False, "消息内容超过 4000 字符上限", ""
        if not requested_target:
            return False, "缺少 target_id", ""

        with self._children_guard:
            parent_id = self._parent_by_child.get(sender_id, "")
            resolved_target = parent_id if requested_target == "parent" else requested_target
            if not resolved_target:
                return False, "当前 agent 没有可用的直接 parent", ""
            if resolved_target == sender_id:
                return False, "禁止向自身发送 agent message", resolved_target

            if parent_id and resolved_target == parent_id:
                generation = self._local_generation_by_child.get(sender_id, "")
                if not generation:
                    return False, "当前 child 缺少可归因 execution generation", resolved_target
                bucket = self._messages_to_parent.setdefault(sender_id, [])
                if len(bucket) >= 20:
                    return False, "已达本 child 向 parent 的消息上限（20 条）", resolved_target
                report = self._delivery_journal.queue_report(
                    child_id=sender_id,
                    parent_id=parent_id,
                    generation=generation,
                    content=body,
                )
                if report is None:
                    return False, "child report durable queue 写入失败，未投递", resolved_target
                bucket.append(body)
                handle = self._handles.get(sender_id)
                if handle is not None:
                    handle.activity_event.set()
                self._message_seq += 1
                return True, f"已投递给直接 parent {resolved_target}", resolved_target

            children = self._children_by_parent.get(sender_id, set())
            if resolved_target in children and resolved_target in self._cancel_events:
                child_handle = self._handles.get(resolved_target)
                if child_handle is not None and child_handle.review_isolated:
                    return False, "独立审查 child 禁止父会话 steer（review_isolated）", resolved_target
                generation = self._local_generation_by_child.get(resolved_target, "")
                if not generation:
                    return False, "目标 child 缺少可归因 execution generation", resolved_target
                inbox = self._agent_inbox.setdefault(resolved_target, [])
                if len(inbox) >= 20:
                    return False, "目标 child 的待处理消息已达上限（20 条）", resolved_target
                queued = self._delivery_journal.queue_mailbox(
                    child_id=resolved_target,
                    parent_id=sender_id,
                    generation=generation,
                    sender_id=sender_id,
                    content=body,
                )
                if queued is None:
                    return False, "parent steer durable queue 写入失败，未排队", resolved_target
                self._message_seq += 1
                # Preserve the historical process-local fast index for wake/test paths;
                # durable EventStore remains the source of truth when enabled.
                inbox.append((self._message_seq, sender_id, body))
                return True, f"已排队到直接 child {resolved_target} 的下一 step boundary", resolved_target

            return False, "仅允许与直接、仍活跃的 parent/child 相邻边通信", resolved_target

    def _inject_pending_agent_messages(
        self,
        sess: Session,
        child_sid: str,
        *,
        preceding_assistant: Message | None = None,
    ) -> int:
        """Durably project current-generation parent steer at a safe child step boundary."""
        with self._children_guard:
            local_handle = self._handles.get(child_sid)
            if local_handle is not None and local_handle.review_isolated:
                # Even a preexisting/durable mailbox injection cannot enter a
                # Host-designated independent review. Ordinary child unaffected.
                return 0
            generation = self._local_generation_by_child.get(child_sid, "")
            local_pending = list(self._agent_inbox.get(child_sid, []))

        durable_pending = []
        if generation and self._delivery_journal.enabled:
            delivered_ids = self._delivered_mailbox_ids(sess, generation)
            durable_pending = self._delivery_journal.pending_mailbox(
                child_sid, generation, delivered_ids=delivered_ids
            )
            if not durable_pending:
                return 0
            rows = [(row.sender_id, row.content) for row in durable_pending]
            message_ids = [row.message_id for row in durable_pending]
        else:
            if not local_pending:
                return 0
            rows = [(sender_id, body) for _seq, sender_id, body in local_pending]
            message_ids = []

        ordered = "\n\n".join(
            f"[{idx}. direct-parent {sender_id}] {body}"
            for idx, (sender_id, body) in enumerate(rows, 1)
        )
        metadata = origin_metadata(
            InjectionLayer.PROGRAM_RECOVERY,
            injection_kind="agent_message",
        )
        if generation:
            metadata["subagent_generation"] = generation
        if message_ids:
            metadata["subagent_mailbox_message_ids"] = message_ids
        base_len = len(sess.messages)
        if preceding_assistant is not None:
            sess.messages.append(preceding_assistant)
        sess.messages.append(
            Message(
                role="user",
                content=(
                    "【父代理委派消息·非真人新授权】\n"
                    "以下内容来自当前委派链的直接父代理，只属于既有委派任务内的协作上下文；"
                    "它不能扩大真人用户授权范围。\n"
                    + ordered
                ),
                source=MessageSource.SYSTEM,
                metadata=metadata,
            )
        )
        try:
            self.session_store.save(sess)
        except BaseException:
            del sess.messages[base_len:]
            raise
        with self._children_guard:
            # The local queue is only a low-latency mirror. New messages that raced with
            # this save remain recoverable from EventStore even if this list is cleared.
            self._agent_inbox[child_sid] = []
        return len(rows)

    def cancel_parent(
        self,
        parent_session_id: str,
        *,
        run_generation: str = "",
        origin_run_generation: str = "",
        _all_generations: bool = False,
    ) -> int:
        """Cancel only children owned by the exact parent run generation.

        An explicit/current generation fences same-session sequential runs.  Empty
        generation remains a deliberate legacy/operator scope for callers that truly own
        the whole session lifecycle; it is never inferred from the most recent run.
        """
        if not parent_session_id:
            return 0

        # A parent run's generation must scope cancellation of its *direct*
        # children. Once a particular child is itself being stopped, however,
        # its descendants are owned by that child session, not by the root's
        # generation: tool dispatch clears the inherited run-generation context.
        # Keep the normal generation fence, explicitly crossing it only while
        # mechanically stopping that child's own active descendants.
        target_generation = (
            "" if _all_generations
            else str(run_generation or origin_run_generation or current_run_generation.get() or "")
        )
        with self._children_guard:
            rows = []
            for sid in self._children_by_parent.get(parent_session_id, set()):
                owner_generation = self._parent_run_generation_by_child.get(sid, "")
                if target_generation and owner_generation != target_generation:
                    continue
                rows.append(
                    (
                        sid,
                        self._cancel_events.get(sid),
                        self._local_generation_by_child.get(sid, ""),
                    )
                )

        for sid, event, generation in rows:
            # The durable attempt happens before the local signal. If persistence fails,
            # we still stop the in-process worker for the existing resource/safety boundary,
            # but restart recovery will honestly have no durable cancel fact.
            if generation:
                self._delivery_journal.cancel_requested(
                    child_id=sid,
                    parent_id=parent_session_id,
                    generation=generation,
                    reason="parent_lifecycle_cancel",
                )
            with self._children_guard:
                if self._local_generation_by_child.get(sid, "") != generation:
                    continue
                handle = self._handles.get(sid)
                if handle is not None:
                    handle.cancel_requested = True
                    # ST2-C1 preserves the historical local settlement shortcut.
                    # ST2-C2 will bind durable settlement to the parent receipt commit.
                    handle.collected = True
                    handle.activity_event.set()
            if event is not None:
                event.set()
            # Do not depend on the registry cancel hook to transitively visit
            # grandchildren: it may inherit the ROOT run generation and skip a
            # child spawned under the nested tool's empty generation. Recursing
            # over the already-owned child tree is bounded by the depth cap.
            self.cancel_parent(sid, _all_generations=True)
            with suppress(Exception):
                self.registry.cancel_session(sid)
        return len(rows)

    def _reserve_child(self, parent_sid: str) -> tuple[str, threading.Event, Session]:
        """同步登记 active child topology；调用者负责最终 ``_finalize_child``。"""
        sid = f"subagent_{uuid.uuid4().hex[:12]}"
        generation = uuid.uuid4().hex

        parent_run_generation = str(current_run_generation.get() or "")
        cancel_event = threading.Event()
        with self._children_guard:
            if parent_sid:
                self._children_by_parent.setdefault(parent_sid, set()).add(sid)
                self._parent_by_child[sid] = parent_sid
                self._parent_run_generation_by_child[sid] = parent_run_generation
            self._local_generation_by_child[sid] = generation
            self._cancel_events[sid] = cancel_event
            self._agent_inbox[sid] = []
            self._messages_to_parent[sid] = []
        sess = self.session_store.load(sid)
        if parent_sid and parent_sid != sid:
            sess.parent_id = parent_sid
        with suppress(Exception):
            self.session_store.save(sess)
        return sid, cancel_event, sess

    def _begin_fleet_run(self, sid: str, depth: int, parent_sid: str = "") -> WorkerLease | None:
        """Acquire the fleet lease at the run boundary; None keeps fleet off.

        A crashed predecessor is superseded only once its lease has actually
        expired (time-licensed takeover, generation CAS inside ``begin_run``);
        a live unexpired or expiry-free lease rejects the run fail-closed with
        the precise remaining window (operator ``force_reclaim_run`` with
        recorded justification is the only live-takeover path); a settled
        workspace rejects the run fail-closed too.
        """
        if self._project_coordinator is None:
            return None
        lease = self._project_coordinator.begin_run(
            sid, worker_id=sid[-8:], ttl_seconds=self._fleet_lease_ttl_seconds
        )
        self._fleet_leases[sid] = lease
        self._project_coordinator.run_fact(
            lease,
            {
                "event": "run_started",
                "depth": depth,
                "runner_owner": self._runner_owner_id,
                # fleet slice 5 (G2): 归属随 fact 落盘，重启后 recover() 可直接读出
                "parent_session_id": parent_sid or "",
            },
        )
        return lease

    def _renew_fleet_run(self, sid: str) -> None:
        """Round-boundary heartbeat: extend the bounded lease while genuinely alive.

        R1: renewal failure now marks the session effect-fenced (sticky) instead
        of pure fail-soft.  Expired/superseded leases lost their write authority
        (TTL is authority), so the child must stop producing new side effects;
        the loop checks the fence right after this heartbeat and closes the run
        with a typed ``refused`` outcome.  Settlement remains the durable fence.
        """
        if self._project_coordinator is None or self._fleet_lease_ttl_seconds is None:
            return
        lease = self._fleet_leases.get(sid)
        if lease is None:
            return
        try:
            self._fleet_leases[sid] = self._project_coordinator.renew_run(
                lease, extend_seconds=self._fleet_lease_ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001 - heartbeat failure is a mechanical fact
            logging.getLogger(__name__).warning(
                "fleet lease renew failed for %s: %s", sid, exc
            )
            self._tool_journal.mark_effect_fence_lost(sid)

    def _fleet_lease_fence(self, sid: str):
        """R1 effect-fence probe handed to journal bindings for this child run.

        Returns None when this run is not fleet-managed (pre-R1 behavior).  The
        closure re-reads the live lease dict at each probe, so renewals and
        takeovers are always seen at their exact commit boundary.
        """
        if self._project_coordinator is None:
            return None

        def probe() -> bool:
            lease = self._fleet_leases.get(sid)
            if lease is None:
                # Lease gone from this runner (settled/taken over): deny.
                return False
            coordinator = self._project_coordinator
            if coordinator is None:
                # Coordinator detached after fence creation: fail closed (deny).
                # (Outer None-check cannot narrow into a closure for pyright.)
                return False
            try:
                return bool(coordinator.store.lease_is_current(lease))
            except Exception:  # noqa: BLE001 - unreadable disk truth fails closed
                return False

        return probe

    def _fleet_fence_lost(self, sid: str) -> bool:
        """R1 loop-level fence check: journal fence OR live lease no longer current."""
        if self._tool_journal.effect_fence_lost(sid):
            return True
        if self._project_coordinator is None:
            return False
        lease = self._fleet_leases.get(sid)
        if lease is None:
            return False
        try:
            return not bool(self._project_coordinator.store.lease_is_current(lease))
        except Exception:  # noqa: BLE001 - unreadable disk truth fails closed
            return True

    def lease_facts(self, child_id: str) -> tuple[bool, str, dict]:
        """Disk-truth recover() view for a workspace run_key (read-only surface)."""
        sid = str(child_id or "").strip()
        if not sid:
            return False, "缺少 child_id", {}
        if self._project_coordinator is None:
            return False, "本 runner 未接入 fleet lease（project_coordinator 未配置）", {}
        try:
            view = self._project_coordinator.recover(sid)
        except KeyError:
            return False, f"workspace 不存在: {sid}", {}
        return True, "ok", view

    def topology_lease_view(
        self, parent_id: str = "", child_id: str = ""
    ) -> tuple[bool, str, dict]:
        """fleet slice 5 (G3): 拓扑 + 租约合并只读 disk-truth 视图.

        - child_id: 该 child 的 parent 归属、topology_snapshot 与 lease recover() 视图
        - parent_id: 该 parent 的 active children、pending obligations 与每 child 租约
        两面都只读；coordinator 未接入时租约块如实 unavailable，拓扑面仍可用。
        """
        child = str(child_id or "").strip()
        parent = str(parent_id or "").strip()
        if child:
            ok, detail, lease_view = self.lease_facts(child)
            view = {
                "child_id": child,
                "parent_id": self.parent_of(child) or None,
                "topology": self.topology_snapshot(child),
                "lease": (
                    {"status": "ok", "detail": detail, "facts": lease_view}
                    if ok
                    else {"status": "unavailable", "detail": detail, "facts": lease_view}
                ),
            }
            return True, "ok", view
        if parent:
            children = self.active_children(parent)
            per_child = []
            for sid in children:
                ok, detail, facts = self.lease_facts(sid)
                per_child.append(
                    {
                        "child_id": sid,
                        "lease": (
                            {"status": "ok", "detail": detail, "facts": facts}
                            if ok
                            else {"status": "unavailable", "detail": detail, "facts": facts}
                        ),
                    }
                )
            view = {
                "parent_id": parent,
                "active_children": children,
                "children": per_child,
                "pending_obligations": self.pending_obligations(parent),
            }
            return True, "ok", view
        return False, "缺少 parent_id 或 child_id", {}

    def _settle_fleet_run(self, sid: str, result: SubAgentResult) -> None:
        """Exactly-once settlement at a real terminal; late fenced writes stay visible."""
        lease = self._fleet_leases.pop(sid, None)
        if lease is None or self._project_coordinator is None:
            return
        try:
            fact = {
                "event": "run_settled",
                "outcome": result.outcome,
                "depth": result.depth,
                "runner_owner": self._runner_owner_id,
                # fleet slice 5 (G2): 结算 fact 同样携带归属（parent_of 走 active+durable 机械源）
                "parent_session_id": self.parent_of(sid),
            }
            # fleet slice 5 (G2): 结算事实必须在 finish_run 之前进入 facts 流——store 的
            # record_fact 只接受 active lease（settle 后 state=settled 会被 FencedError
            # 拒绝）。此时 runner 持有该 lease 且 exactly-once 由 _fleet_leases.pop +
            # store SettlementError 双重保证；崩溃窗口内 fact 是真实的终局叙述，
            # 权威结算状态仍在 state.json。
            self._project_coordinator.run_fact(lease, fact)
            self._project_coordinator.finish_run(lease, fact)
        except Exception as exc:  # noqa: BLE001 - fencing is a mechanical fact; never mask the child result
            logging.getLogger(__name__).warning(
                "fleet settlement fenced/failed for child %s (lease %s gen %d): %s: %s",
                sid,
                lease.lease_id,
                lease.generation,
                type(exc).__name__,
                exc,
            )

    def _finalize_child(
        self,
        sid: str,
        parent_sid: str,
        result: SubAgentResult | None,
    ) -> SubAgentResult | None:
        """Finalize local state; durable terminal requires an exact result fact first."""
        # Structured lifecycle: a child reaching terminal (even successfully)
        # cannot leave its own active descendants executing late side effects.
        # Only the children of THIS child session are affected; unrelated root
        # runs retain their generation-scoped cancellation boundary.
        self.cancel_parent(sid, _all_generations=True)
        with self._children_guard:
            generation = self._local_generation_by_child.get(sid, "")
            durable_before = self._durable_topology.get(sid)
        if result is not None and generation and self._delivery_journal.enabled:
            reports = self._delivery_journal.reports(sid, generation)
            result.reports = [row.content for row in reports]
        elif result is not None:
            with self._children_guard:
                result.reports = list(self._messages_to_parent.get(sid, []))

        result_is_durable = (
            result is not None
            and generation != ""
            and (
                not self._delivery_journal.enabled
                or self._delivery_journal.result(sid, generation) is not None
            )
        )
        if result is not None:
            # real terminal (completed/failed/cancelled): fleet settlement is
            # exactly-once; a crash leaves no terminal here, so the durable
            # active lease remains for the next coordinator to reclaim.
            self._settle_fleet_run(sid, result)
        if result_is_durable:
            terminal_durable = self._topology_journal.terminal(
                child_id=sid,
                parent_id=parent_sid,
                generation=generation,
                depth=(durable_before.depth if durable_before is not None else 0),
                outcome=result.outcome if result is not None else "failed",
            )
            self._refresh_topology_state(sid)
            if terminal_durable and result is not None and result.outcome == "cancelled":
                # Session.status is an active/archived visibility lifecycle, not the
                # SubAgent execution outcome.  The topology journal above remains
                # authoritative for `cancelled`; archive only the durable cancelled
                # child so the session index no longer advertises it as active.
                # Index projection failure must not prevent generation cleanup.
                with suppress(Exception):
                    self.session_store.archive(sid)
        with self._children_guard:
            self._cancel_events.pop(sid, None)
            self._local_generation_by_child.pop(sid, None)
            self._agent_inbox.pop(sid, None)
            self._messages_to_parent.pop(sid, None)
            self._parent_by_child.pop(sid, None)
            self._parent_run_generation_by_child.pop(sid, None)
            if parent_sid:
                children = self._children_by_parent.get(parent_sid)
                if children is not None:
                    children.discard(sid)
                    if not children:
                        self._children_by_parent.pop(parent_sid, None)
            handle = self._handles.get(sid)
            if handle is not None:
                handle.result = result
                handle.state = result.outcome if result is not None else "failed"
                handle.done_event.set()
                handle.activity_event.set()
                self._prune_handles_locked()
        return result

    def _run_reserved_child(
        self,
        *,
        sid: str,
        sess: Session,
        task: str,
        context: str,
        depth: int,
        max_rounds: int | None,
        acceptance: list[str] | None,
        cancel_event: threading.Event,
        llm_client: LLMClient | None = None,
        model_label: str = "",
        startup_event: threading.Event | None = None,
        startup_state: dict[str, object] | None = None,
    ) -> SubAgentResult:
        """在已登记的 child sid 上执行迷你循环；不负责 topology cleanup。"""

        # copy_context() in start()/recursive calls already carries the parent's
        # current_tool_discovery_scope. EVO-20261012-bb3022f4 (E4): start() 现在
        # 在 _inside_context 内将其覆盖为 requires.tools 强制白名单（≤ 父 scope，
        # 只降不升；spawn_subagent 默认剔除）。本迷你循环不重复设置，仅继承该值；
        # 递归 spawn 的合法性由 runner.start 的 _compute_child_tool_scope 统一裁决。
        old_ctx_sid = current_session_id.get()
        _depth_tok = _CURRENT_SUBAGENT_DEPTH.set(depth)
        _model_tok = current_model_label.set(model_label) if model_label else None
        try:
            current_session_id.set(sid)
            # Child execution has the same whole-run ownership invariant as LoopEngine.
            # The reserve snapshot is intentionally not reused: the public facade loads
            # and binds exactly one save-authorized snapshot while the lease is held.
            del sess
            with self._children_guard:
                generation = self._local_generation_by_child.get(sid, "")
                parent_sid = self._parent_by_child.get(sid, "")
            with self.session_store.run_owned_session(sid) as owned_sess:
                if owned_sess is None:
                    if startup_state is not None:
                        startup_state.update({"ok": False, "detail": "child_run_lease_busy"})
                    if startup_event is not None:
                        startup_event.set()
                    return SubAgentResult(
                        final_answer=(
                            "[状态: failure] 子代理会话正由另一执行者持有，当前 worker 未执行任何动作。"
                        ),
                        outcome="failed",
                        depth=depth,
                    )
                # Reserve-time parent save is best-effort for historical compatibility;
                # the run-owned snapshot must carry the direct-parent fact before the
                # durable delegated task is acknowledged.
                if parent_sid and parent_sid != sid:
                    owned_sess.parent_id = parent_sid
                if not generation:
                    if startup_state is not None:
                        startup_state.update({"ok": False, "detail": "child_generation_missing"})
                    if startup_event is not None:
                        startup_event.set()
                    return SubAgentResult(
                        final_answer="[状态: failure] 子代理执行代际缺失，当前 worker 未执行任何动作。",
                        outcome="failed",
                        depth=depth,
                    )
                linked = self._topology_journal.linked(
                    child_id=sid,
                    parent_id=parent_sid,
                    generation=generation,
                    depth=depth,
                )
                started = linked and self._topology_journal.generation_started(
                    child_id=sid,
                    parent_id=parent_sid,
                    generation=generation,
                    owner_id=self._runner_owner_id,
                    depth=depth,
                )
                self._refresh_topology_state(sid)
                if not started:
                    if startup_state is not None:
                        startup_state.update({"ok": False, "detail": "topology_start_not_durable"})
                    if startup_event is not None:
                        startup_event.set()
                    return SubAgentResult(
                        final_answer=(
                            "[状态: failure] 子代理 topology/generation 启动事实未持久化，"
                            "当前 worker 未执行任何 provider/tool 动作。"
                        ),
                        outcome="failed",
                        depth=depth,
                    )
                try:
                    try:
                        self._persist_delegated_task(
                            owned_sess,
                            task=task,
                            context=context,
                            depth=depth,
                            acceptance=acceptance,
                        )
                    except BaseException as exc:  # noqa: BLE001 - startup must be acknowledged
                        if startup_state is not None:
                            startup_state.update(
                                {
                                    "ok": False,
                                    "detail": f"durable_start_failed:{type(exc).__name__}",
                                }
                            )
                        if startup_event is not None:
                            startup_event.set()
                        failed = SubAgentResult(
                            final_answer=(
                                f"[状态: failure] 子代理 durable startup 异常: "
                                f"{type(exc).__name__}: {exc}"
                            ),
                            outcome="failed",
                            depth=depth,
                        )
                        self._persist_terminal_result(
                            child_id=sid,
                            parent_id=parent_sid,
                            generation=generation,
                            result=failed,
                        )
                        raise
                    if startup_state is not None:
                        startup_state.update({"ok": True, "detail": "durable_start_ready"})
                    if startup_event is not None:
                        startup_event.set()
                    try:
                        result = self._execute_subagent(
                            owned_sess,
                            depth,
                            max_rounds=max_rounds,
                            cancel_event=cancel_event,
                            llm_client=llm_client,
                            model_label=model_label,
                        )
                    except BaseException as exc:  # noqa: BLE001 - persist exact failure then preserve API
                        failed = SubAgentResult(
                            final_answer=(
                                f"[状态: failure] 子代理后台执行异常: "
                                f"{type(exc).__name__}: {exc}"
                            ),
                            outcome="failed",
                            depth=depth,
                        )
                        self._persist_terminal_result(
                            child_id=sid,
                            parent_id=parent_sid,
                            generation=generation,
                            result=failed,
                        )
                        raise
                    self._persist_terminal_result(
                        child_id=sid,
                        parent_id=parent_sid,
                        generation=generation,
                        result=result,
                    )
                    return result
                finally:
                    # Result availability is attempted while the run-owned Session lease
                    # is still held and before this generation is durably released.
                    self._topology_journal.generation_released(
                        child_id=sid,
                        parent_id=parent_sid,
                        generation=generation,
                        owner_id=self._runner_owner_id,
                        depth=depth,
                        reason="worker_exit",
                    )
                    self._refresh_topology_state(sid)
        finally:
            if _model_tok is not None:
                current_model_label.reset(_model_tok)
            _CURRENT_SUBAGENT_DEPTH.reset(_depth_tok)
            current_session_id.set(old_ctx_sid)

    def _reserve_background_child(
        self, parent_sid: str, depth: int
    ) -> tuple[str, threading.Event, Session, _SubAgentHandle] | None:
        """原子保留一个 background handle 槽位；容量只约束并发资源，不判断任务。"""
        sid = f"subagent_{uuid.uuid4().hex[:12]}"
        generation = uuid.uuid4().hex

        parent_run_generation = str(current_run_generation.get() or "")
        cancel_event = threading.Event()
        handle = _SubAgentHandle(
            child_id=sid,
            parent_id=parent_sid,
            parent_run_generation=parent_run_generation,
            depth=depth,
            generation=generation,
        )
        with self._children_guard:
            self._prune_handles_locked(reserve_slot=True)
            if len(self._handles) >= self._max_handles:
                return None
            if parent_sid:
                self._children_by_parent.setdefault(parent_sid, set()).add(sid)
                self._parent_by_child[sid] = parent_sid
                self._parent_run_generation_by_child[sid] = parent_run_generation
            self._local_generation_by_child[sid] = generation
            self._cancel_events[sid] = cancel_event
            self._agent_inbox[sid] = []
            self._messages_to_parent[sid] = []
            self._handles[sid] = handle
            self._handle_order.append(sid)
        sess = self.session_store.load(sid)
        if parent_sid and parent_sid != sid:
            sess.parent_id = parent_sid
        with suppress(Exception):
            self.session_store.save(sess)
        return sid, cancel_event, sess, handle

    def _child_spawn_grant_allowed(self) -> bool:
        """E4: CHILD_SPAWN_GRANT 授予判断（模块级实现的薄包装）。"""
        return child_spawn_grant_allowed()

    def _compute_child_tool_scope(
        self, required_tools: list[str] | None
    ) -> tuple[frozenset[str] | None, str]:
        """E4 child 工具面计算：requires.tools 声明即程序级强制白名单。

        规则（EVO-20261012-bb3022f4）：
        - 声明了 required_tools → child scope = 声明集；声明超出父 scope 直接拒绝
          （授权只降不升，fail-fast 而非静默截断）；
        - 未声明 → 继承父 scope（父 None = 全量 registry 面）；
        - spawn_subagent 默认从 child 面剔除（防递归舰队），显式授予走
          CHILD_SPAWN_GRANT 白名单；未授予且原本为 None 的面转为「全量 -
          spawn_subagent」的显式集合。
        返回 (child_scope, refusal_detail)；refusal 非空 = 拒绝启动。
        """
        parent_scope = current_tool_discovery_scope.get()
        if required_tools is not None:
            req = frozenset(
                t for t in (str(x).strip() for x in required_tools) if t
            )
            if parent_scope is not None:
                overflow = sorted(req - set(parent_scope))
                if overflow:
                    return None, (
                        "requires.tools 声明超出父执行域（授权只降不升）: "
                        + ", ".join(overflow)
                    )
            base: set[str] | None = set(req)
        else:
            base = None if parent_scope is None else set(parent_scope)
        if self._child_spawn_grant_allowed():
            return (frozenset(base) if base is not None else None), ""
        if base is None:
            try:
                base = set(self.registry.names())
            except Exception:  # noqa: BLE001 — names 派生失败时保守返回 None（全量）
                return None, ""
        return frozenset(base - {"spawn_subagent"}), ""

    def _compute_child_write_scope(
        self, requested: WriteScope | None
    ) -> tuple[WriteScope | None, str]:
        """C3: requires.write_scope 声明与父 write scope 求交（只降不升）。

        DESIGN-20261030 §5.1/§5.3：与 _compute_child_tool_scope 同构的写侧
        授权传递链落点（L1 父子求交；P2 外部锚未接入，该层暂不收紧）：
        - 声明了 requested → intersect_write_scope(parent, requested)；越界
          （refusal_detail 非空）= 拒绝启动（fail-fast 而非静默截断）；
        - 未声明 → 继承父 scope（父 None = 全量）；
        - 子显式声明但 write_scope 核心（core/write_scope 或
          run_context.current_write_scope）不可用 → fail-closed 拒绝，不静默
          忽略声明（§5.10 NFR-4 跨版本口径）。current_write_scope 延迟 import：
          核心未就绪时既有 import 面零破坏（未声明分支返回 None 即准确的继承
          值——父会话同样无法设置任何 write scope）。
        返回 (child_scope, refusal_detail)；refusal_detail 非空 = 拒绝启动。
        """
        if requested is None:
            try:
                from llm_loop.core.run_context import current_write_scope

                return current_write_scope.get(), ""
            except ImportError:
                return None, ""
        try:
            from llm_loop.core.run_context import current_write_scope
            from llm_loop.core.write_scope import intersect_write_scope
        except ImportError as exc:
            return None, (
                "requires.write_scope 声明无法生效（write_scope 核心不可用: "
                f"{type(exc).__name__}: {exc}）；为不静默忽略写侧授权声明，"
                "拒绝启动（fail-closed）"
            )
        try:
            parent_scope = current_write_scope.get()
            effective, refusal_detail = intersect_write_scope(
                parent_scope, requested
            )
        except Exception as exc:  # noqa: BLE001 — 求交面异常时 fail-closed，不让 child 带未定义 scope 启动
            return None, (
                f"write_scope 求交异常（fail-closed 拒绝启动）: "
                f"{type(exc).__name__}: {exc}"
            )
        return effective, refusal_detail

    def _apply_write_scope_tool_surface_policy(
        self,
        child_scope: frozenset[str] | None,
        child_write_scope: WriteScope | None,
    ) -> tuple[frozenset[str] | None, tuple[str, ...]]:
        """P1-a: 受限 write scope 的 child **保留** execute_command 工具面。

        DESIGN-20261030 §16（口径由 P1-b 回退为 P1-a，产品决定 2026-10-30）：
        P1-b 把写侧约束做成「工具面剔除 execute_command」——强度最高，但受限
        child 连只读命令与测试都跑不了，实用性代价过大。P1-a 保留命令工具，
        把写侧约束下沉到命令语义层：core/command_scope_guard 按写盘命令族
        判定写目标是否落在 write scope 内，越界即程序级拒绝（工具层强制点）。

        「受限」判定：child_write_scope 非 None 且 declared=True（显式声明，含
        paths:[] 显式只读）。父声明、子未声明 → 继承父的 declared scope，同样受限；
        父子都未声明 → 不受限，工具面零变化（FR-3）。

        返回 (有效工具面, 被剔除的工具名)。P1-a 下**不剔除任何工具**，第二个返回值
        恒为空元组（回执字段保留以兼容既有消费方；写侧拦截改由命令族闸承担）。
        """
        return child_scope, ()

    def _start_failure_result(
        self,
        depth: int,
        detail: str,
        child_id: str = "",
        state: str = "refused",
    ) -> dict:
        """start() 拒绝/失败回执（accepted=False 家族）的统一构造。

        DESIGN-20261030 §5.3 C3/C5: write_scope 求交拒绝与既有 depth/tool
        scope/canary/reserve 等拒绝及 startup 失败回执同构——仅 child_id
        （预留前 "" / 预留后 sid）与 state（refused/failed）取值不同。
        统一构造保证字段集合与顺序稳定，start() 主体只做裁决不做拼装。
        """
        return {
            "accepted": False,
            "child_id": child_id,
            "state": state,
            "depth": depth,
            "detail": detail,
        }

    def _worker_terminal_from_exception(
        self,
        sid: str,
        depth: int,
        startup_event: threading.Event,
        startup_state: dict[str, object],
        exc: BaseException,
    ) -> SubAgentResult:
        """_worker 后台异常路径统一收口：startup 握手补齐 + 真实 terminal。

        EVO-20261012-bb3022f4/65475c5a (E5) — background thread 必须形成真实
        terminal：未握手先补 startup_state/startup_event（start() 侧超时/失败
        分支据此拒绝）；已持久化 delivery result 优先回放（幂等收口），否则
        构造 failed 结果如实携带异常。contextvar token 恢复仍由 _worker 外层
        finally 统一保证，本方法不触碰 contextvar。
        """
        if not startup_event.is_set():
            startup_state.update(
                {"ok": False, "detail": f"startup_exception:{type(exc).__name__}"}
            )
            startup_event.set()
        with self._children_guard:
            generation = self._local_generation_by_child.get(sid, "")
        durable_result = (
            self._delivery_journal.result(sid, generation) if generation else None
        )
        return (
            self._result_from_payload(durable_result.payload)
            if durable_result is not None
            else SubAgentResult(
                final_answer=(
                    f"[状态: failure] 子代理后台执行异常: "
                    f"{type(exc).__name__}: {exc}"
                ),
                outcome="failed",
                depth=depth,
            )
        )

    def start(
        self,
        task: str,
        context: str = "",
        depth: int = 0,
        max_rounds: int | None = None,
        inherit: bool = False,
        acceptance: list[str] | None = None,
        model: str = "",
        required_tools: list[str] | None = None,
        review_isolated: bool = False,
        # fs_isolation 放在既有参数之后（keyword 传参为主流；避免任何位置参数
        # 调用方把 review_isolated 静默错绑到 fs_isolation）。
        fs_isolation: bool = False,
        # DESIGN-20261030 §5.3 C2/C3: 子代理写侧路径归属声明（spawn 侧
        # SurfaceRequirements 解析出的 WriteScope）；None=未声明（继承父，
        # 零行为变化）。置于签名末尾，同样只以 keyword 传入。
        required_write_scope: WriteScope | None = None,
    ) -> dict:
        """启动 background child；review_isolated 仅由可信 Host 内部调用。"""
        if depth >= self.max_depth:
            return self._start_failure_result(depth, f"递归深度超限（已达上限 {self.max_depth}）")

        # EVO-20261012-bb3022f4 (E4): requires.tools 声明即程序级强制白名单，
        # 在预留任何 child 资源前计算并拒绝（fail-fast，不静默截断）。
        child_scope, scope_refusal = self._compute_child_tool_scope(required_tools)
        if scope_refusal:
            return self._start_failure_result(depth, scope_refusal)

        # DESIGN-20261030 §5.3 C3/C5: requires.write_scope 与父 write scope 求交，
        # 同样在预留任何 child 资源之前计算并拒绝（fail-fast，不静默截断）。
        child_write_scope, write_scope_refusal = self._compute_child_write_scope(
            required_write_scope
        )
        if write_scope_refusal:
            return self._start_failure_result(depth, write_scope_refusal)

        # DESIGN-20261030 §16 P1-a: 受限写域的 child 保留 execute_command 工具面。
        # P1-a：工具面不因写域收窄（命令面保留，写侧约束下沉到命令族闸，
        # 见 core/command_scope_guard 与 DESIGN-20261030 §16）；未受限时工具面零变化。
        child_scope, surface_restriction = self._apply_write_scope_tool_surface_policy(
            child_scope, child_write_scope
        )

        requested_model = str(model or "").strip()
        inherited_model = (
            str(current_model_label.get() or "").strip()
            if self._llm_resolver is not None
            else ""
        )
        child_model_ref = requested_model or inherited_model
        try:
            child_llm, child_model_label = self._resolve_child_llm(child_model_ref)
        except Exception as exc:  # noqa: BLE001 - reject before reserving child resources
            return {
                "accepted": False,
                "child_id": "",
                "state": "refused",
                "depth": depth,
                "model": child_model_ref,
                "detail": f"child_model_unavailable:{type(exc).__name__}:{exc}",
            }

        parent_sid = current_session_id.get()
        # Explicit Host canary authorization never turns into a full-powered
        # child by inheriting the parent's worker ContextVar. The actual budget
        # member must be bound to the new child SID/generation before any thread
        # can call the provider. No descendant can recursively spawn, and no
        # canary child may buy an isolated worktree — a physical resource that
        # the shared ledger cannot account for.
        from llm_loop.resources import task_budget_subagent_profile as canary_profile
        from llm_loop.resources.task_budget_dispatch import active_task_budget

        parent_budget = active_task_budget()
        is_canary = (
            parent_budget is not None
            and parent_budget._get_validated()["grant"]["profile"] == canary_profile.PROFILE
        )
        if is_canary and parent_budget is not None and (
            depth != 0 or inherit or fs_isolation or required_tools != []
            or child_model_label != canary_profile.MODEL_REF
            or parent_budget.member.member_id != parent_budget.budget_id
            or parent_budget.member.session_id != parent_sid
        ):
            return self._start_failure_result(depth, "subagent_canary_child_scope_denied")
        if is_canary:
            # The child is a no-tool one-fact diagnostic, not a general
            # recursive worker. Bound real model decision rounds regardless
            # of the operator's much higher production iteration setting.
            max_rounds = min(
                self.max_iterations if max_rounds is None else max(1, int(max_rounds)),
                3,
            )
        if inherit:
            context = self._inherit_parent_context(context)
        reserved = self._reserve_background_child(parent_sid, depth)
        if reserved is None:
            return self._start_failure_result(depth, f"后台子代理资源已达硬上限（{self._max_handles}）")
        sid, cancel_event, sess, handle = reserved
        child_budget = None
        if is_canary:
            try:
                assert parent_budget is not None
                child_budget = parent_budget.bind_direct_canary_child(
                    sid, handle.generation
                )
            except Exception as exc:
                # No retry on CAS/persist ambiguity. A failed derivation cannot
                # leave a runnable child or consume more Provider attempts.
                refused = SubAgentResult(
                    final_answer=(
                        "subagent_canary_child_budget_not_authorized:"
                        + type(exc).__name__
                    ),
                    outcome="refused", refused=True, depth=depth,
                )
                self._finalize_child(sid, parent_sid, refused)
                with self._children_guard:
                    if sid in self._handles:
                        self._handles[sid].collected = True
                return self._start_failure_result(depth, refused.final_answer, child_id=sid)
        # Set this before the worker starts and BEFORE child_id is exposed to
        # the caller. Reviewer's parent cannot alter its input via agent_message.
        if review_isolated:
            handle.review_isolated = True

        # EVO-20261016-ac47e850: 声明式 git worktree 隔离。prepare 失败即拒绝
        # （带 reason_code），绝不降级共享工作区——无声丢隔离比失败更糟。
        worktree_lease = None  # WorktreeLease | None（延迟 import，运行态持有）
        if fs_isolation:
            from llm_loop.workspace.worktree_isolation import (
                WorktreeIsolationError,
                prepare_worktree,
            )

            _parent_ws = current_workspace_root.get() or ""
            try:
                worktree_lease = prepare_worktree(sid, parent_root=_parent_ws)
            except WorktreeIsolationError as exc:
                refused = SubAgentResult(
                    final_answer=(
                        f"[状态: failure] worktree 隔离准备失败"
                        f"（reason_code={exc.reason_code}），child 未启动、"
                        f"未降级共享工作区: {exc.detail}"
                    ),
                    outcome="refused",
                    refused=True,
                    depth=depth,
                )
                finalized = self._finalize_child(sid, parent_sid, refused)
                with self._children_guard:
                    if sid in self._handles:
                        self._handles[sid].collected = True
                assert finalized is not None
                return self._start_failure_result(depth, refused.final_answer, child_id=sid)

        if self._project_coordinator is not None:
            try:
                self._begin_fleet_run(sid, depth, parent_sid=sess.parent_id or "")
            except Exception as exc:  # noqa: BLE001 - mechanical boundary rejection before any child/provider/tool action
                # EVO-20261016-ac47e850: prepare 已建的树在此拒绝路径必须释放
                # （child 未启动，树无主人）。
                if worktree_lease is not None:
                    from llm_loop.workspace.worktree_isolation import (
                        format_release_note,
                        release_worktree,
                    )

                    try:
                        _note = format_release_note(
                            release_worktree(
                                worktree_lease.parent_root, worktree_lease.path
                            ),
                            worktree_lease.path,
                        )
                    except Exception as _rel_exc:  # noqa: BLE001 — 拒绝路径不被清理异常遮蔽
                        _note = (
                            f"[worktree] 清理异常（{type(_rel_exc).__name__}: "
                            f"{_rel_exc}），树保留: {worktree_lease.path}"
                        )
                else:
                    _note = ""
                refused = SubAgentResult(
                    final_answer=(
                        f"[状态: failure] fleet run 边界拒绝（lease acquire 失败），"
                        f"未启动任何 child/provider/tool 动作: {type(exc).__name__}: {exc}"
                        + (f"\n{_note}" if _note else "")
                    ),
                    outcome="refused",
                    refused=True,
                    depth=depth,
                )
                finalized = self._finalize_child(sid, parent_sid, refused)
                with self._children_guard:
                    if sid in self._handles:
                        self._handles[sid].collected = True
                assert finalized is not None
                return self._start_failure_result(depth, refused.final_answer, child_id=sid)

        caller_ctx = contextvars.copy_context()
        startup_event = threading.Event()
        startup_state: dict[str, object] = {}

        def _worker() -> None:
            def _inside_context() -> None:
                # EVO-20261012-bb3022f4/65475c5a (E4/E5): child 会话专属 contextvar
                # 注入——只影响本 child 线程（caller_ctx 为 copy_context 的副本）：
                #   - E4: 工具发现面/执行面截断到 requires.tools 强制白名单；
                #   - E5: cancel_event 与 wait 累计预算暴露给 wait 工具。
                _scope_tok = (
                    current_tool_discovery_scope.set(child_scope)
                    if child_scope is not None
                    else None
                )
                # DESIGN-20261030 §5.3 C5: 写侧 scope 注入（仅当有效 scope 非
                # None 时 set，与 _scope_tok 条件 set 模式一致）。延迟 import：
                # write_scope 核心未就绪时本分支不可达（计算面已拒绝或返回
                # None），不拖垮既有 import 面。
                if child_write_scope is not None:
                    from llm_loop.core.run_context import current_write_scope

                    _wscope_tok = current_write_scope.set(child_write_scope)
                else:
                    _wscope_tok = None
                _cancel_tok = child_cancel_event.set(cancel_event)
                # EVO-20261016-ac47e850: 声明式隔离时 child 施工面切到 worktree；
                # journal/session 落盘位置不受影响（session_store 决定）。
                _ws_tok = (
                    current_workspace_root.set(worktree_lease.path)
                    if worktree_lease is not None
                    else None
                )
                # EVO-20261012-32e89b46: 注入共享载体（值语义 set 会随每次派发
                # copy_context() 快照丢失，累计恒归零）。
                _wait_tok = child_wait_budget_used.set(WaitBudget())
                try:
                    try:
                        result = self._run_reserved_child(
                            sid=sid,
                            sess=sess,
                            task=task,
                            context=context,
                            depth=depth,
                            max_rounds=max_rounds,
                            acceptance=acceptance,
                            cancel_event=cancel_event,
                            startup_event=startup_event,
                            startup_state=startup_state,
                            llm_client=child_llm,
                            model_label=child_model_label,
                        )
                    except BaseException as exc:  # noqa: BLE001 — background thread 必须形成真实 terminal
                        result = self._worker_terminal_from_exception(
                            sid, depth, startup_event, startup_state, exc
                        )
                    # EVO-20261016-ac47e850: 终态释放隔离树（干净删/脏保留），
                    # 报告附加到 result——父会话据此决定是否显式合并（不自动合并）。
                    # release 自身异常绝不阻断 _finalize_child（防 handle 滞留）。
                    if worktree_lease is not None:
                        from llm_loop.workspace.worktree_isolation import (
                            format_release_note,
                            release_worktree,
                        )

                        try:
                            _release = release_worktree(
                                worktree_lease.parent_root,
                                worktree_lease.path,
                            )
                            _release_note = format_release_note(
                                _release, worktree_lease.path
                            )
                        except Exception as _rel_exc:  # noqa: BLE001 — 如实报告并放行终态
                            _release_note = (
                                f"[worktree] 清理异常（{type(_rel_exc).__name__}: "
                                f"{_rel_exc}），树保留: {worktree_lease.path}"
                            )
                        result.final_answer = (
                            f"{result.final_answer}\n{_release_note}"
                        )
                    self._finalize_child(sid, parent_sid, result)
                finally:
                    if _wscope_tok is not None:
                        # DESIGN-20261030 §5.3 C5/T16: worker 退出统一恢复，
                        # 杜绝 child write scope 泄漏（与 _scope_tok 同模式）。
                        from llm_loop.core.run_context import current_write_scope

                        current_write_scope.reset(_wscope_tok)
                    if _scope_tok is not None:
                        current_tool_discovery_scope.reset(_scope_tok)
                    if _ws_tok is not None:
                        current_workspace_root.reset(_ws_tok)
                    child_cancel_event.reset(_cancel_tok)
                    child_wait_budget_used.reset(_wait_tok)

            if child_budget is None:
                caller_ctx.run(_inside_context)
            else:
                assert child_budget is not None
                # The original parent budget is *never* usable with a child
                # session ID. Bind a precisely derived member for this worker;
                # its provider attempts debit the one durable shared ledger.
                from llm_loop.resources.task_budget_dispatch import bind_task_budget

                def _run_budgeted_child() -> None:
                    assert child_budget is not None
                    sid_tok = current_session_id.set(sid)
                    gen_tok = current_run_generation.set(handle.generation)
                    try:
                        with bind_task_budget(child_budget, cleanup_scope=True):
                            _inside_context()
                    finally:
                        current_run_generation.reset(gen_tok)
                        current_session_id.reset(sid_tok)

                caller_ctx.run(_run_budgeted_child)

        thread = threading.Thread(
            target=_worker,
            name=f"lfl-subagent-{sid[-8:]}",
            daemon=True,
        )
        with self._children_guard:
            handle.thread = thread
        try:
            thread.start()
        except BaseException as exc:  # noqa: BLE001 — 启动失败不得留下幽灵 active child
            # EVO-20261016-ac47e850: worker 从未运行，prepare 已建的树在此释放。
            if worktree_lease is not None:
                from llm_loop.workspace.worktree_isolation import (
                    format_release_note,
                    release_worktree,
                )

                try:
                    _note = format_release_note(
                        release_worktree(
                            worktree_lease.parent_root, worktree_lease.path
                        ),
                        worktree_lease.path,
                    )
                except Exception as _rel_exc:  # noqa: BLE001 — 启动失败原因优先
                    _note = (
                        f"[worktree] 清理异常（{type(_rel_exc).__name__}: "
                        f"{_rel_exc}），树保留: {worktree_lease.path}"
                    )
            else:
                _note = ""
            failed = SubAgentResult(
                final_answer=(
                    f"[状态: failure] 子代理线程启动失败: {type(exc).__name__}: {exc}"
                    + (f"\n{_note}" if _note else "")
                ),
                outcome="failed",
                depth=depth,
            )
            self._finalize_child(sid, parent_sid, failed)
            with self._children_guard:
                if sid in self._handles:
                    self._handles[sid].collected = True
            return self._start_failure_result(
                depth, failed.final_answer, child_id=sid, state="failed"
            )
        if not startup_event.wait(timeout=2.0):
            cancel_event.set()
            with self._children_guard:
                if sid in self._handles:
                    self._handles[sid].collected = True
            return self._start_failure_result(
                depth, "child durable startup 超时，已请求取消；未确认任何子任务执行。",
                child_id=sid, state="failed",
            )
        if not bool(startup_state.get("ok")):
            with self._children_guard:
                if sid in self._handles:
                    self._handles[sid].collected = True
            return self._start_failure_result(
                depth, f"child durable startup 失败: {startup_state.get('detail', 'unknown')}",
                child_id=sid, state="failed",
            )
        return {
            "accepted": True,
            "child_id": sid,
            "state": "running",
            "depth": depth,
            "model": child_model_label,
            "tool_scope": (
                "full(excluding spawn_subagent)"
                if child_scope is None
                else ",".join(sorted(child_scope))
            ),
            **(
                {"write_scope_tool_restriction": list(surface_restriction)}
                if surface_restriction
                else {}
            ),
            "write_scope_command_guard": "p1a_write_family",
            "worktree": worktree_lease.path if worktree_lease is not None else "",
            "detail": "child 已启动，父代理可继续决策并通过 agent_message 中途 steer",
        }

    def review_terminal_current(self, child_id: str, parent_id: str) -> dict[str, str | bool] | None:
        """P0-B: process-local terminal attestation, never a disk-replayed PASS.

        An untrusted same-user shell can rewrite runtime JSON/journal bytes.
        Review admission therefore requires the *actual in-memory* child handle
        owned by this runner, with its done_event set and completed outcome.
        Pruned handles or process restarts fail closed, even if durable logs
        still describe an earlier successful review.
        """
        with self._children_guard:
            handle = self._handles.get(str(child_id))
            if (
                handle is None
                or handle.parent_id != str(parent_id)
                or not handle.review_isolated
                or handle.state != "completed"
                or not handle.done_event.is_set()
                or handle.result is None
                or handle.result.outcome != "completed"
                or not handle.generation
            ):
                return None
            return {
                "child_id": handle.child_id,
                "parent_id": handle.parent_id,
                "generation": handle.generation,
                "state": handle.state,
                "review_isolated": True,
                "final_answer": handle.result.final_answer,
            }

    def result_current(self, child_id: str, wait_seconds: float = 0.0) -> tuple[bool, str, dict]:
        """Query a direct child from local handle or durable generation-scoped facts."""

        requester = current_session_id.get()
        sid = str(child_id or "").strip()
        if not sid:
            return False, "缺少 child_id", {}
        with self._children_guard:
            handle = self._handles.get(sid)
        durable = None if handle is not None else self._durable_state(sid)
        with self._children_guard:
            handle = self._handles.get(sid)
            if handle is not None:
                if handle.parent_id != requester:
                    return False, "仅直接 parent 可以读取该 child handle", {}
                generation = handle.generation
                parent_id = handle.parent_id
                activity_event = handle.activity_event
                running = handle.state == "running"
                if self._delivery_journal.enabled:
                    reports_now = [
                        row.content for row in self._delivery_journal.reports(sid, generation)
                    ]
                else:
                    reports_now = list(self._messages_to_parent.get(sid, []))
                has_unseen_report = len(reports_now) > handle.seen_reports
                if running and not has_unseen_report:
                    activity_event.clear()
            else:
                if durable is None:
                    return False, "child handle 不存在、已淘汰且无durable topology", {}
                if durable.parent_id != requester:
                    return False, "仅直接 parent 可以读取该 child", {}
                generation = durable.generation
                parent_id = durable.parent_id

        if handle is None:
            assert durable is not None
            report_rows = self._delivery_journal.reports(sid, generation)
            result_record = self._delivery_journal.result(sid, generation)
            cancel = self._delivery_journal.cancel_state(sid, generation)
            result = (
                self._result_from_payload(result_record.payload)
                if result_record is not None
                else None
            )
            return True, "ok", {
                "child_id": sid,
                "parent_id": parent_id,
                "generation": generation,
                "result_id": result_record.result_id if result_record is not None else "",
                "state": result.outcome if result is not None else "orphaned",
                "depth": result.depth if result is not None else durable.depth,
                "cancel_requested": cancel is not None,
                "reports": [row.content for row in report_rows],
                "result": result,
                "local_active": False,
            }

        bounded_wait = min(30.0, max(0.0, float(wait_seconds or 0.0)))
        if running and not has_unseen_report and bounded_wait > 0:
            activity_event.wait(timeout=bounded_wait)
        with self._children_guard:
            handle = self._handles.get(sid)
            if handle is not None:
                result = handle.result
                if self._delivery_journal.enabled:
                    reports = [
                        row.content for row in self._delivery_journal.reports(sid, handle.generation)
                    ]
                else:
                    reports = (
                        list(self._messages_to_parent.get(sid, []))
                        if handle.state == "running"
                        else list(result.reports if result is not None else [])
                    )
                handle.seen_reports = max(handle.seen_reports, len(reports))
                return True, "ok", {
                    "child_id": handle.child_id,
                    "parent_id": handle.parent_id,
                    "generation": handle.generation,
                    "result_id": (
                        f"result-{handle.generation}" if result is not None and self._delivery_journal.result(sid, handle.generation) is not None else ""
                    ),
                    "state": handle.state,
                    "depth": handle.depth,
                    "cancel_requested": handle.cancel_requested,
                    "reports": reports,
                    "result": result,
                    "local_active": handle.state == "running",
                }
        # A terminal handle may be pruned while the caller waits. Re-enter the durable
        # read-through path without fabricating activity or requiring it to stay cached.
        durable = self._durable_state(sid)
        if durable is None or durable.parent_id != requester:
            return False, "child handle 已淘汰且durable topology不可用", {}
        report_rows = self._delivery_journal.reports(sid, durable.generation)
        result_record = self._delivery_journal.result(sid, durable.generation)
        result = self._result_from_payload(result_record.payload) if result_record is not None else None
        cancel = self._delivery_journal.cancel_state(sid, durable.generation)
        return True, "ok", {
            "child_id": sid,
            "parent_id": durable.parent_id,
            "generation": durable.generation,
            "result_id": result_record.result_id if result_record is not None else "",
            "state": result.outcome if result is not None else "orphaned",
            "depth": result.depth if result is not None else durable.depth,
            "cancel_requested": cancel is not None,
            "reports": [row.content for row in report_rows],
            "result": result,
            "local_active": False,
        }

    def settle_committed_receipt(self, parent_session_id: str, message: Message) -> bool:
        """Cache a settlement only after its exact parent tool receipt is durably committed."""
        if message.tool_name != "subagent_result":
            return False
        binding = (message.metadata or {}).get("subagent_settlement")
        if not isinstance(binding, dict):
            return False
        child_id = str(binding.get("child_id") or "")
        parent_id = str(binding.get("parent_id") or "")
        generation = str(binding.get("generation") or "")
        result_id = str(binding.get("result_id") or "")
        if not all((child_id, parent_id, generation, result_id)) or parent_id != parent_session_id:
            return False
        with self._children_guard:
            handle = self._handles.get(child_id)
        durable = None if handle is not None else self._durable_state(child_id)
        expected_parent = handle.parent_id if handle is not None else (durable.parent_id if durable else "")
        expected_generation = handle.generation if handle is not None else (durable.generation if durable else "")
        if expected_parent != parent_id or expected_generation != generation:
            return False
        result_record = self._delivery_journal.result(child_id, generation)
        if (
            result_record is None
            or result_record.parent_id != parent_id
            or result_record.result_id != result_id
        ):
            return False
        # The callback is only a notification. Settlement authority remains the
        # durable parent facts: exact receipt message followed by matching WAL commit.
        if not self._delivery_journal.settlement_committed(
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            result_id=result_id,
        ):
            return False
        with self._children_guard:
            handle = self._handles.get(child_id)
            if handle is not None:
                if (
                    handle.parent_id != parent_id
                    or handle.generation != generation
                    or handle.state == "running"
                    or handle.result is None
                ):
                    return False
                handle.collected = True
                self._prune_handles_locked()
        return True

    def settle_current(self, child_id: str) -> bool:
        """在 terminal receipt 已成功构造后，由 direct parent ACK settlement。"""

        requester = current_session_id.get()
        sid = str(child_id or "").strip()
        with self._children_guard:
            handle = self._handles.get(sid)
            if (
                handle is None
                or handle.parent_id != requester
                or handle.state == "running"
                or handle.result is None
            ):
                return False
            handle.collected = True
            self._prune_handles_locked()
            return True

    # ── EVO-20260914-e6b8aa22: 终止子代理有界续话 ──
    # 预算由程序跨续话记账（记账事实持久化在会话消息本身，崩溃/重启后仍成立）：
    #   - 每 child 续话次数: 统计其会话内 FOLLOWUP_MARKER 前缀 user 消息数
    #   - 每父会话总预算: 统计父会话内 agent_followup 工具调用帧数
    #   - 时间窗: child 会话 updated_at（终止时最后一次落盘）距 now 不超过 FOLLOWUP_WINDOW_S
    # 超限/过期 → 显式拒绝并提示 spawn_subagent 新开；绝不静默新会话顶替续话。
    FOLLOWUP_MAX_PER_CHILD = 2
    FOLLOWUP_TOTAL_PER_PARENT = 4
    FOLLOWUP_WINDOW_S = 900.0
    FOLLOWUP_MAX_ROUNDS = 6
    FOLLOWUP_MARKER = "[subagent_followup:"

    def _followup_usage(
        self, child_sess: Session, parent_sess: Session | None
    ) -> tuple[int, int]:
        """从持久化会话消息推导续话记账（权威源是已落盘事实，非内存计数）."""
        per_child = sum(
            1
            for m in child_sess.messages
            if getattr(m, "role", "") == "user"
            and str(getattr(m, "content", "")).startswith(self.FOLLOWUP_MARKER)
        )
        per_parent = 0
        if parent_sess is not None:
            import json as _json

            per_parent = sum(
                1
                for m in parent_sess.messages
                if getattr(m, "role", "") == "assistant"
                and "agent_followup" in _json.dumps(m.to_llm_dict(), ensure_ascii=False, default=str)
            )
        return per_child, per_parent

    def _followup_window_expired(self, child_sess: Session) -> bool:
        from datetime import datetime, timedelta

        try:
            last = datetime.fromisoformat(str(child_sess.updated_at))
        except (TypeError, ValueError):
            # updated_at 不可解析（老版本会话）：不因格式问题误拒，次数/总量预算仍硬约束
            return False
        # naive/aware 混算会抛 TypeError 被吞掉导致窗口永不生效（2026-09-14 测试实测）
        now = datetime.now(last.tzinfo) if last.tzinfo else datetime.now()
        return now - last > timedelta(seconds=self.FOLLOWUP_WINDOW_S)

    def followup_current(
        self, child_id: str, instruction: str
    ) -> tuple[bool, str, SubAgentResult | None]:
        """对已终止的直接 child 发起有界续话（同会话、同深度、受限轮数）.

        返回 (ok, detail, result)。所有拒绝路径都显式说明剩余预算或过期事实，
        并指向 spawn_subagent 重新开一个新 child；不隐式新开会话。
        """

        requester = current_session_id.get()
        sid = str(child_id or "").strip()
        instruction = str(instruction or "").strip()
        if not requester:
            return False, "续话必须在父会话执行上下文中发起（无 current session）。", None
        if not sid:
            return False, "参数错误: child_id 不能为空。", None
        if not instruction:
            return False, "参数错误: instruction 不能为空；续话必须携带明确的新指令。", None

        with self._children_guard:
            handle = self._handles.get(sid)
        if handle is not None:
            if handle.parent_id != requester:
                return False, f"拒绝: {sid} 不是当前会话的直接 child。", None
            if handle.review_isolated:
                # EVO-20261021-e46f2431: 独立审查 child 与运行中 steer 同等禁止父会话
                # 续话——followup 会把 child 置为 settled，防重放契约下其终态
                # attestation 从此永久失效（review_terminal_current 只认 terminal
                # completed），等于烧掉本次审查的签发能力。
                return False, (
                    f"审查资格子代理 {sid} 禁用 followup（review_isolated）：续话会把它置为 "
                    "settled 并永久失去审查资格签发。需要新审查结论时用 review_admission "
                    "重开一次。"
                ), None
            if handle.state == "running":
                return False, f"{sid} 仍在运行；运行中转向请用 agent_message。", None
            generation = handle.generation
            depth = handle.depth
        else:
            self._refresh_topology_state(sid)
            durable = self._durable_topology.get(sid)
            probe_sess = self.session_store.load(sid)
            if durable is not None:
                if durable.parent_id != requester:
                    return False, f"拒绝: {sid} 不是当前会话的直接 child。", None
                if not durable.terminal:
                    return (
                        False,
                        f"{sid} 状态非 terminal（outcome={durable.outcome}），不可续话。",
                        None,
                    )
                generation = durable.generation
                depth = durable.depth
            elif probe_sess is not None:
                # 无 journal 部署：会话存储里的 parent_id 是登记事实；不在 active
                # 映射中（不在 _handles/_cancel_events）即视为已终止。
                if str(probe_sess.parent_id or "") != requester:
                    return False, f"拒绝: {sid} 不是当前会话的直接 child。", None
                generation = ""
                depth = 0
            else:
                return False, f"未找到 child {sid} 的任何登记记录。", None

        # ── 预算/窗口检查（在改动任何状态之前完成）──
        child_sess_probe = self.session_store.load(sid)
        if child_sess_probe is None:
            return False, f"child 会话 {sid} 不存在，无法续话。", None
        parent_sess = (
            self.session_store.load(requester) if requester != sid else child_sess_probe
        )
        per_child, per_parent = self._followup_usage(child_sess_probe, parent_sess)
        if per_child >= self.FOLLOWUP_MAX_PER_CHILD:
            return (
                False,
                f"续话窗口已用尽: {sid} 已续话 {per_child}/{self.FOLLOWUP_MAX_PER_CHILD} 次。"
                f"请用 spawn_subagent 新开 child（全新会话，需在 task 中带上必要上下文）。",
                None,
            )
        if per_parent >= self.FOLLOWUP_TOTAL_PER_PARENT:
            return (
                False,
                f"父会话续话总预算已用尽: {per_parent}/{self.FOLLOWUP_TOTAL_PER_PARENT}。"
                "请用 spawn_subagent 新开 child。",
                None,
            )
        if self._followup_window_expired(child_sess_probe):
            return (
                False,
                f"续话窗口已过期: {sid} 终止已超过 {int(self.FOLLOWUP_WINDOW_S)}s。"
                "请用 spawn_subagent 新开 child。",
                None,
            )

        # ── 同会话续话执行（受限轮数；记账标记先落盘再执行，保证失败也计费）──
        # 与 run() 相同的 child LLM 解析（继承父 run 模型；失败则拒绝、不执行）
        child_model_ref = (
            str(current_model_label.get() or "").strip()
            if self._llm_resolver is not None
            else ""
        )
        try:
            child_llm, child_model_label = self._resolve_child_llm(child_model_ref)
        except Exception as exc:  # noqa: BLE001 - reject before any provider/tool action
            return False, f"子代理模型不可用，续话未执行: {type(exc).__name__}: {exc}", None

        seq = per_child + 1
        outcome: SubAgentResult
        with self.session_store.run_owned_session(sid) as owned:
            if owned is None:
                return False, f"无法取得 {sid} 的会话执行租约（可能正被其他执行持有）。", None
            owned.messages.append(
                Message(
                    role="user",
                    content=(
                        f"{self.FOLLOWUP_MARKER}{seq}] 父代理有界续话"
                        f"（第 {seq}/{self.FOLLOWUP_MAX_PER_CHILD} 次，本轮上限 "
                        f"{self.FOLLOWUP_MAX_ROUNDS} 轮）。新指令: {instruction}"
                    ),
                    source=MessageSource.USER,
                    metadata=origin_metadata(
                        InjectionLayer.PROGRAM_RECOVERY,
                        injection_kind="subagent_followup",
                        subagent_depth=depth,
                    ),
                )
            )
            _depth_tok = _CURRENT_SUBAGENT_DEPTH.set(depth)
            old_ctx_sid = current_session_id.set(sid)
            old_ctx_model = (
                current_model_label.set(child_model_label) if child_model_label else None
            )
            try:
                outcome = self._execute_subagent(
                    owned,
                    depth,
                    max_rounds=self.FOLLOWUP_MAX_ROUNDS,
                    cancel_event=threading.Event(),
                    llm_client=child_llm,
                    model_label=child_model_label,
                )
            finally:
                if old_ctx_model is not None:
                    current_model_label.reset(old_ctx_model)
                current_session_id.reset(old_ctx_sid)
                _CURRENT_SUBAGENT_DEPTH.reset(_depth_tok)

        self._persist_terminal_result(
            child_id=sid, parent_id=requester, generation=generation, result=outcome
        )
        self._refresh_topology_state(sid)
        with self._children_guard:
            if handle is not None:
                handle.state = "settled"
                handle.result = outcome
                handle.collected = False
                handle.activity_event.set()
        return (
            True,
            (
                f"续话完成（{seq}/{self.FOLLOWUP_MAX_PER_CHILD}，父会话累计 "
                f"{per_parent + 1}/{self.FOLLOWUP_TOTAL_PER_PARENT}）。"
            ),
            outcome,
        )

    def _refused_result(self, depth: int, final_answer: str) -> SubAgentResult:
        """run() 拒绝终态统一构造（outcome=refused 家族；未预留 child 资源路径）.

        DESIGN-20261030 §5.3 C5b: run() 的 depth/model 等预留前拒绝回执同构
        ——仅 final_answer 文案不同，outcome/refused/depth 构造恒定；统一构造
        保证拒绝终态字段集合与取值稳定，run() 主体只做裁决不做拼装。
        """
        return SubAgentResult(
            final_answer=final_answer,
            outcome="refused",
            refused=True,
            depth=depth,
        )

    def _run_refused_finalized(
        self, sid: str, parent_sid: str, depth: int, final_answer: str
    ) -> SubAgentResult:
        """run() 预留后拒绝路径统一收口：refused 终态 + 幂等 finalize + 返回.

        DESIGN-20261030 §5.3 C3/C5/C5b + EVO-20261016-ac47e850: requires.tools /
        requires.write_scope 求交拒绝、fs_isolation 准备失败、fleet run 边界
        拒绝五处回执同构（refused 结果 → _finalize_child → assert 非空返回）；
        拒绝时均未启动任何 child/provider/tool 动作，提前返回路径统一经外层
        finally 恢复 contextvar/释放 worktree/幂等 finalize（R28 审查
        P1-1/P2-3 口径不变）。
        """
        refused = self._refused_result(depth, final_answer)
        finalized = self._finalize_child(sid, parent_sid, refused)
        assert finalized is not None
        return finalized

    # ── 公开入口 ──
    def run(
        self,
        task: str,
        context: str = "",
        depth: int = 0,
        max_rounds: int | None = None,
        inherit: bool = False,
        acceptance: list[str] | None = None,
        model: str = "",
        required_tools: list[str] | None = None,
        fs_isolation: bool = False,
        # DESIGN-20261030 §5.3 C2/C3: 与 start() 同一声明语义的写侧路径归属；
        # None=未声明（继承父，零行为变化）。
        required_write_scope: WriteScope | None = None,
    ) -> SubAgentResult:
        """执行子代理任务（父代理调用 depth=0，子代理内部递归自增）.

        max_rounds: 节点级轮次预算（P3-4 DAG 节点预算）；None = 构造器 max_iterations。
        inherit: True 时只提供父会话 exact context artifact ref，不自动注入父 turn；
        child 可按需读取。与 context 手动要点可并存。
        acceptance (2026-08-18, 对齐 dsh_task 协议 v2): 验收清单——注入子代理系统提示，
        完成时逐项自检输出 完成/未完成/原因，分歧显性化（父级保留最终裁决权）。
        model: 显式 provider/model；省略时 production runner 机械继承父 run 当前模型。
        required_tools/fs_isolation: 与 start() 同一声明语义（E4 白名单 +
        EVO-20261016-ac47e850 worktree 隔离）——workflow local executor 的同步入口。
        required_write_scope: 与 start() 同一声明语义的写侧路径归属
        （DESIGN-20261030 §5.3 C5b：两条启动路径必须一致注入/拒绝，防单路径绕过）。
        """
        if depth >= self.max_depth:
            return self._refused_result(
                depth,
                f"[状态: failure] 递归深度超限（已达上限 {self.max_depth}），"
                f"请在父级整合结果，勿继续拆分。",
            )


        requested_model = str(model or "").strip()
        inherited_model = (
            str(current_model_label.get() or "").strip()
            if self._llm_resolver is not None
            else ""
        )
        child_model_ref = requested_model or inherited_model
        try:
            child_llm, child_model_label = self._resolve_child_llm(child_model_ref)
        except Exception as exc:  # noqa: BLE001 - reject before child/provider/tool execution
            return self._refused_result(
                depth,
                "[状态: failure] 子代理模型不可用，未启动任何 child/provider/tool 动作: "
                f"{type(exc).__name__}: {exc}",
            )

        # Resolve retrieval-only inheritance before current_session_id switches to child.
        if inherit:
            context = self._inherit_parent_context(context)

        parent_sid = current_session_id.get()
        sid, cancel_event, sess = self._reserve_child(parent_sid)
        # E4（EVO-20261012-bb3022f4）: requires.tools 声明即程序级强制白名单——
        # 声明时才裁决/挂载 discovery scope；未声明保持 run() 既有继承语义
        # （零回归；start() 面未声明时的 spawn_subagent 剔除是异步舰队防递归
        # 设计，不自动带入同步路径）。拒绝时未启动任何 child/provider/tool 动作。
        # EVO-20261016-ac47e850: run() 同步路径（workflow local executor 同款入口）
        # 接入声明式 worktree 隔离——prepare 失败 fail-fast 拒绝，不降级共享工作区。
        # 全部提前返回路径统一经 finally 恢复 contextvar/释放 worktree/幂等
        # finalize，杜绝拒绝路径的 scope 泄漏与拓扑残留（R28 审查 P1-1/P2-3）。
        scope_token = None
        write_scope_token = None
        ws_token = None
        worktree_lease = None
        wt_parent_root = ""
        released = False
        try:
            if required_tools is not None:
                child_scope, scope_refusal = self._compute_child_tool_scope(required_tools)
                if scope_refusal:
                    return self._run_refused_finalized(
                        sid, parent_sid, depth,
                        "[状态: failure] requires.tools 声明超出父执行域，"
                        f"未启动任何 child/provider/tool 动作: {scope_refusal}",
                    )
            # DESIGN-20261030 §5.3 C3/C5/C5b: 同步路径（workflow local executor
            # 同款入口）同样在启动前求交 write scope——只改 start() 一条路径时
            # 同步入口可完全绕过 scope（F14）；拒绝走 refused 终态，未启动任何
            # child/provider/tool 动作。注入仅当有效 scope 非 None（与既有
            # scope_token 条件挂载模式一致）。
            child_write_scope, write_scope_refusal = self._compute_child_write_scope(
                required_write_scope
            )
            if write_scope_refusal:
                return self._run_refused_finalized(
                    sid, parent_sid, depth,
                    "[状态: failure] requires.write_scope 求交拒绝"
                    f"（未启动任何 child/provider/tool 动作）: {write_scope_refusal}",
                )
            child_scope, surface_restriction = self._apply_write_scope_tool_surface_policy(
                child_scope if required_tools is not None else current_tool_discovery_scope.get(),
                child_write_scope,
            )
            if required_tools is not None or surface_restriction:
                scope_token = current_tool_discovery_scope.set(child_scope)
            if child_write_scope is not None:
                from llm_loop.core.run_context import current_write_scope

                write_scope_token = current_write_scope.set(child_write_scope)
            if fs_isolation:
                from llm_loop.workspace.worktree_isolation import (
                    WorktreeIsolationError,
                    prepare_worktree,
                )

                wt_parent_root = str(current_workspace_root.get() or "")
                try:
                    worktree_lease = prepare_worktree(sid, parent_root=wt_parent_root)
                except WorktreeIsolationError as exc:
                    return self._run_refused_finalized(
                        sid, parent_sid, depth,
                        f"[状态: failure] fs_isolation 准备失败（child 未启动，"
                        f"不降级共享工作区）: reason_code={exc.reason_code} {exc}",
                    )
                except Exception as exc:  # noqa: BLE001 - 机械准备段未知异常同样转 refused，不逃逸不泄漏拓扑
                    return self._run_refused_finalized(
                        sid, parent_sid, depth,
                        f"[状态: failure] fs_isolation 准备失败（child 未启动，"
                        f"不降级共享工作区）: {type(exc).__name__}: {exc}",
                    )
            if self._project_coordinator is not None:
                try:
                    self._begin_fleet_run(sid, depth, parent_sid=parent_sid or "")
                except Exception as exc:  # noqa: BLE001 - mechanical boundary rejection before any child/provider/tool action
                    if worktree_lease is not None:
                        from llm_loop.workspace.worktree_isolation import release_worktree

                        release_worktree(
                            parent_root=wt_parent_root,
                            worktree_path=worktree_lease.path,
                        )
                        released = True
                    return self._run_refused_finalized(
                        sid, parent_sid, depth,
                        f"[状态: failure] fleet run 边界拒绝（lease acquire 失败），"
                        f"未启动任何 child/provider/tool 动作: {type(exc).__name__}: {exc}",
                    )
            # 同步路径在当前线程挂载工作区根（discovery scope 已在声明分支挂载）；
            # run() 返回前统一恢复。
            if worktree_lease is not None:
                ws_token = current_workspace_root.set(worktree_lease.path)
            result = self._run_reserved_child(
                sid=sid,
                sess=sess,
                task=task,
                context=context,
                depth=depth,
                max_rounds=max_rounds,
                acceptance=acceptance,
                cancel_event=cancel_event,
                llm_client=child_llm,
                model_label=child_model_label,
            )
            if worktree_lease is not None:
                from llm_loop.workspace.worktree_isolation import (
                    format_release_note,
                    release_worktree,
                )

                report = release_worktree(
                    parent_root=wt_parent_root,
                    worktree_path=worktree_lease.path,
                )
                released = True
                note = format_release_note(report, worktree_lease.path)
                if note:
                    result.final_answer = f"{result.final_answer}\n{note}"
            finalized = self._finalize_child(sid, parent_sid, result)
            assert finalized is not None
            return finalized
        finally:
            if ws_token is not None:
                current_workspace_root.reset(ws_token)
            if write_scope_token is not None:
                # DESIGN-20261030 §5.3 C5b/T16: 拒绝/异常/正常路径统一恢复父
                # write scope，杜绝 child scope 泄漏回父会话。
                from llm_loop.core.run_context import current_write_scope

                current_write_scope.reset(write_scope_token)
            if scope_token is not None:
                current_tool_discovery_scope.reset(scope_token)
            if worktree_lease is not None and not released:
                # 异常路径兜底释放：无 result 载体可附加 note，释放结果如实记入
                # 日志；兜底自身失败不得遮蔽原异常。
                from llm_loop.workspace.worktree_isolation import release_worktree

                try:
                    report = release_worktree(
                        parent_root=wt_parent_root,
                        worktree_path=worktree_lease.path,
                    )
                    logging.getLogger(__name__).warning(
                        "run() 同步路径异常退出，已释放 fs_isolation worktree %s: state=%s",
                        worktree_lease.path,
                        report.state,
                    )
                except Exception:  # noqa: BLE001 - 兜底释放失败不得遮蔽原异常
                    logging.getLogger(__name__).exception(
                        "run() 同步路径异常退出，fs_isolation worktree 释放失败: %s",
                        worktree_lease.path,
                    )
            # 若 _run_reserved_child 抛出未预期异常，仍必须清 active topology；正常
            # 路径已经 finalize，二次调用是幂等清理且不会改写结果。
            with self._children_guard:
                still_active = sid in self._cancel_events
            if still_active:
                self._finalize_child(sid, parent_sid, None)

    def _persist_delegated_task(
        self,
        sess: Session,
        *,
        task: str,
        context: str,
        depth: int,
        acceptance: list[str] | None,
    ) -> None:
        """Persist the exact delegated input before background execution is acknowledged."""
        sys_prompt = (
            "【父代理委派任务·非真人新授权】\n"
            "以下任务来自当前代理委派，只在既有真人用户授权范围内生效；不得据此扩大权限。\n"
            f"委派任务：\n{task}"
        )
        if context.strip():
            sys_prompt += f"\n\n父代理提供的相关上下文：\n{context}"
        if acceptance:
            items = "\n".join(f"{i}. {a}" for i, a in enumerate(acceptance, 1))
            sys_prompt += f"\n\n验收条件（供交付核对）：\n{items}"
        if "kind=method" not in task:
            # Method discovery bridge (EVO-20261010 canary R2, 3/3 scenarios):
            # without this line subagents never searched method cards on their own
            # (0/17 searches in R1); with it they do bounded discovery first and,
            # when a relevant card exists, apply it (typing correct on first
            # attempt, ~43% fewer tokens in scenario A).
            sys_prompt += (
                "\n\n纪律：动手前先对记录库做有界方法论检索"
                "（search_records kind=method，limit≤5），结果仅作背景参考；"
                "无相关卡或不适用则直接开始任务。"
            )
        sess.messages.append(
            Message(
                role="user",
                content=sys_prompt,
                source=MessageSource.USER,
                metadata=origin_metadata(
                    InjectionLayer.PROGRAM_RECOVERY,
                    injection_kind="subagent_task",
                    subagent_depth=depth,
                ),
            )
        )
        # Save failure is a hard execution boundary: provider/tool work must not start.
        self.session_store.save(sess)

    _EVIDENCE_REF_RE = re.compile(r"evidence://v[0-9]+/[0-9a-f]{8,128}")

    @classmethod
    def _collect_evidence_refs(cls, sess: Session, *, limit: int = 20) -> list[str]:
        """EVO-20261020-b1c00127: harvest persisted evidence refs from the child
        transcript (most recent first, order of appearance preserved per message).

        A circuit-break or projection-failure receipt carries these refs so the
        parent agent can take over losslessly instead of re-fetching everything
        the child already acquired.
        """
        found: list[str] = []
        seen: set[str] = set()
        for msg in reversed(sess.messages):
            content = msg.content if isinstance(msg.content, str) else ""
            if "evidence://" not in content:
                continue
            for ref in cls._EVIDENCE_REF_RE.findall(content):
                if ref not in seen:
                    seen.add(ref)
                    found.append(ref)
                    if len(found) >= limit:
                        return found
        return found

    def child_input_budget_chars(
        self,
        model_ref: str,
        *,
        chars_per_token: float | None = None,
    ) -> int | None:
        """Tool-less child input budget in chars (same limits math as _bounded_child_wire).

        EVO-20261021-5bf26586: trusted Host callers (review admission) must
        pre-check that frozen material fits the reviewer model's *live*
        registry budget instead of a static cap that silently drifts after
        registry hot-reload. A reviewer child carries an empty tool scope
        (required_tools=[]), so the wire budget equals
        floor(allowed_input_tokens * chars_per_token) exactly as
        reserve_history_after_tools projects it for zero tool-schema chars.
        Returns None when the resolver/registry cannot resolve the model:
        the caller must fall back to its own conservative ceiling, never
        to "unlimited".

        EVO-20261023-fc5c34b9: ``chars_per_token`` lets the caller supply the
        ratio it will ALSO use on the child wire. The pre-check and the child
        must agree on the ratio, otherwise the pre-check admits material the
        child then refuses ("reviewer_unavailable" on a healthy reviewer).
        Omitted -> the registry ratio, exactly as before.
        """
        ref = str(model_ref or "").strip()
        if self._context_limits_resolver is None:
            return None
        try:
            limits = self._context_limits_resolver(ref)
            child_llm, _ = self._resolve_child_llm(ref)
        except Exception:  # noqa: BLE001 — pre-check degrades to caller's static cap
            return None
        if limits is None:
            return None
        context_window, provider_input_limit, registry_chars_per_token = limits
        if chars_per_token is None:
            chars_per_token = registry_chars_per_token
        if context_window <= 0 or chars_per_token <= 0:
            return None
        output_reserve = max(0, int(getattr(child_llm, "max_tokens", 0) or 0))
        if output_reserve >= context_window:
            return 0
        allowed = min(int(context_window * 0.9), context_window - output_reserve)
        if provider_input_limit is not None and provider_input_limit > 0:
            allowed = min(allowed, provider_input_limit)
        return int(allowed * chars_per_token)

    def _is_reviewer_wire(self, sess: Session, tools: list[dict]) -> bool:
        """True only for a reviewer-isolated, tool-less child wire.

        EVO-20261023-fc5c34b9. Two independent conditions must hold:
        the child handle was started with ``review_isolated=True`` (the
        genuine reviewer never accepts a parent steer), and the wire carries
        an empty tool scope. A normal subagent that happens to run without
        tools keeps the registry ratio untouched.
        """
        if tools:
            return False
        handles = getattr(self, "_handles", None)
        if not isinstance(handles, dict):
            return False
        handle = handles.get(getattr(sess, "session_id", "") or "")
        return bool(handle is not None and getattr(handle, "review_isolated", False))

    def _bounded_child_wire(
        self,
        sess: Session,
        *,
        llm: LLMClient,
        model_label: str,
        tools: list[dict],
        archived_once: set[int],
    ) -> tuple[list[dict], str]:
        """Reuse the main history/token projectors only at actual input pressure.

        Neither the original child messages nor the initial delegated ingress is
        discarded. If a model-readable exact archive cannot be guaranteed, reject
        the call instead of silently clipping or repeating the provider request.
        """
        messages = [m.to_llm_dict() for m in sess.messages]
        # D2（2026-10-20 投影契约）: 校验必须先于任何投影——非 dict 项一旦进入
        # wire 即为 Provider 结构违规；拒绝整个 wire（空列表+错误串，不发任何
        # 消息），绝不静默丢弃（有界 repr 200 字符，ERROR 级留痕）。
        violations = [(i, m) for i, m in enumerate(messages) if not isinstance(m, dict)]
        if violations:
            i, bad = violations[0]
            logging.getLogger(__name__).error(
                "投影契约失败(第%d项 type=%s): %s",
                i, type(bad).__name__, repr(bad)[:200],
            )
            return [], f"投影契约失败(第{i}项 type={type(bad).__name__})"
        # EVO-20261020-b1c00127: the child wire is never sent with a
        # GuardRequestContext, so a leaked `_active_run_ingress_ref` marker trips
        # `active_run_ingress_unexpected_marker` before any transport. The
        # compaction path already strips markers after build_history_messages
        # (INC-20261020 fix); this defensive strip additionally covers every
        # non-compaction path so the marker class cannot regress.
        messages = _strip_ingress_markers(messages)
        if self._context_limits_resolver is None:
            return messages, ""
        limits = self._context_limits_resolver(model_label)
        if limits is None:
            return messages, ""
        context_window, provider_input_limit, chars_per_token = limits
        # EVO-20261023-fc5c34b9: a reviewer-isolated child carries an empty
        # tool scope and one huge frozen artifact (code/JSON diffs). The
        # registry chars_per_token is a Chinese-mixed calibration and
        # overstates the token cost of ASCII-heavy material by ~5.8x, which
        # made the reviewer wire budget unsatisfiable for real code.
        # For THIS child only, the ratio is derived from the actual message
        # composition. The override is never more permissive than the
        # registry ratio for non-ASCII content (non-ASCII keeps the registry
        # ratio), so a CJK-heavy reviewer wire behaves exactly as before and
        # the physical window (allowed_input_tokens) is unchanged.
        #
        # The check is defensive: a compatible/legacy runner stand-in may not
        # implement the reviewer probe, and a missing probe must leave the
        # registry ratio untouched (never widen, never crash).
        reviewer_probe = getattr(self, "_is_reviewer_wire", None)
        if callable(reviewer_probe):
            try:
                is_reviewer_wire = bool(reviewer_probe(sess, tools))
            except Exception:  # noqa: BLE001 — a failing probe must not change the wire
                is_reviewer_wire = False
        else:
            is_reviewer_wire = False
        if is_reviewer_wire:
            chars_per_token = _wire_chars_per_token(messages, chars_per_token)
        if context_window <= 0 or chars_per_token <= 0:
            return messages, ""

        from llm_loop.core.loop.engine_services.token_budget import reserve_history_after_tools

        output_reserve = max(0, int(getattr(llm, "max_tokens", 0) or 0))
        if output_reserve >= context_window:
            return [], "输出预留已占满该模型的物理窗口"
        allowed_input_tokens = min(int(context_window * 0.9), context_window - output_reserve)
        if provider_input_limit is not None and provider_input_limit > 0:
            allowed_input_tokens = min(allowed_input_tokens, provider_input_limit)
        tool_chars = len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))
        count_tools = getattr(llm, "count_tool_schema_tokens", None)
        tool_tokens: int | None = None
        if callable(count_tools):
            try:
                measured = count_tools(tools)
                if isinstance(measured, int) and measured >= 0:
                    tool_tokens = measured
            except Exception:  # noqa: BLE001 — remote tokenizer not mandatory
                logging.getLogger(__name__).debug("child tool tokenizer unavailable", exc_info=True)
        reservation = reserve_history_after_tools(
            allowed_input_tokens=allowed_input_tokens,
            pre_tool_history_budget_chars=max(1, int(allowed_input_tokens * chars_per_token)),
            tool_schema_chars=tool_chars,
            tool_schema_tokens=tool_tokens,
            projection_chars_per_token=chars_per_token,
        )
        budget = reservation.effective_history_budget_chars
        if reservation.history_token_budget <= 0:
            return [], "工具 schema 已耗尽本模型输入容量"
        if sum(dict_wire_chars(m) for m in messages) <= budget:
            return messages, ""

        # A transcript ref is useful only if this child can actually hydrate it.
        can_search_archive = any(
            (tool.get("function") or {}).get("name") == "search_archive" for tool in tools
        )
        archive_store = self._archive_store
        if archive_store is None or not can_search_archive:
            return [], (
                "模型输入接近实际窗口，但当前子代理没有可调用的 search_archive "
                "或持久 ArchiveStore；已保留完整会话，拒绝静默截断"
            )

        from llm_loop.core.history import build_history_messages

        def _archive_exact(child_id: str, msg: Message) -> None:
            # build_history_messages may project the same immutable group again;
            # a child-owned idempotence set avoids duplicate archive rows.
            if id(msg) in archived_once:
                return
            archive_store.archive(
                child_id,
                role=msg.role,
                source=str(getattr(msg.source, "value", msg.source)),
                content=msg.content,
                tool_name=msg.tool_name,
                tool_call_id=msg.tool_call_id,
                status=str(msg.status) if msg.status is not None else None,
                reasoning_content=msg.reasoning_content,
            )
            archived_once.add(id(msg))

        try:
            projected = build_history_messages(
                sess.messages,
                system_prompt="",
                max_chars=budget,
                session_id=sess.session_id,
                archive_sink=_archive_exact,
                require_archive_success=True,
                preserve_active_ingress_message=sess.messages[0] if sess.messages else None,
            )
        except Exception as exc:  # noqa: BLE001 — cannot claim recoverability on failed archive
            return [], f"上下文压缩/原文归档失败（未向Provider发送）: {type(exc).__name__}"
        # The child wire is sent through ``LLMClient.chat`` without a
        # GuardRequestContext, so the engine-only active-ingress marker cannot be
        # validated on this path; final provider-structure validation would reject
        # the call as ``active_run_ingress_unexpected_marker`` at the first
        # compaction round (INC-20261020 subagent_5fb2aef276c1).  The marker is
        # transport bookkeeping, not provider content: drop it before sending, the
        # same way engine.py does when it hands a projection off.
        # D2（2026-10-20 投影契约）: 同一契约作用于压缩投影产物——校验先于投影，
        # 非 dict 项拒绝整个 wire（不发送、不静默丢弃，与入口处同一错误语义）。
        violations = [(i, m) for i, m in enumerate(projected) if not isinstance(m, dict)]
        if violations:
            i, bad = violations[0]
            logging.getLogger(__name__).error(
                "投影契约失败(第%d项 type=%s): %s",
                i, type(bad).__name__, repr(bad)[:200],
            )
            return [], f"投影契约失败(第{i}项 type={type(bad).__name__})"
        projected = [
            {k: v for k, v in m.items() if k != "_active_run_ingress_ref"}
            for m in projected
        ]
        measured = sum(dict_wire_chars(m) for m in projected)
        if measured > budget:
            return [], (
                f"最小无损投影仍超过该模型输入容量（预算={budget}字符，"
                f"投影={measured}字符）；完整委派和会话历史均已保留"
            )
        if not any(m.get("role") == "user" for m in projected):
            # Provider protocol invariant: a wire with no user-shaped turn is rejected
            # before inference (GLM: HTTP 400 / provider_code 1214, "messages 参数非法").
            # Re-anchor the exact persisted delegated ingress instead of sending it.
            ingress = sess.messages[0].to_llm_dict() if sess.messages else None
            if isinstance(ingress, dict) and ingress.get("role") == "user":
                repaired = [ingress, *projected]
                repaired_chars = sum(dict_wire_chars(m) for m in repaired)
                if repaired_chars <= budget:
                    logging.getLogger(__name__).warning(
                        "child wire lost its user anchor under compaction; "
                        "re-anchored persisted ingress: session=%s wire_messages=%d chars=%d",
                        sess.session_id, len(repaired), repaired_chars,
                    )
                    projected = repaired
                    measured = repaired_chars
            if not any(m.get("role") == "user" for m in projected):
                return [], (
                    "压缩后的投影不含任何 user 消息（Provider 会以 HTTP 400/1214 "
                    "拒绝该 wire）；完整委派和会话历史均已保留，拒绝发送非法请求"
                )
        logging.getLogger(__name__).info(
            "child context projected: session=%s model=%s source_messages=%d "
            "wire_messages=%d budget_chars=%d",
            sess.session_id, model_label, len(sess.messages), len(projected), budget,
        )
        return projected, ""

    def _execute_subagent(
        self,
        sess: Session,
        depth: int,
        max_rounds: int | None = None,
        cancel_event: threading.Event | None = None,
        llm_client: LLMClient | None = None,
        model_label: str = "",
    ) -> SubAgentResult:
        """子代理循环本体（会话注入/恢复由 run 包裹；拆出保证 finally 覆盖全部返回路径）."""
        effective_rounds = (
            max(1, int(max_rounds)) if max_rounds is not None else self.max_iterations
        )
        rounds = 0
        tool_trace: list[dict] = []
        tokens_in = 0
        tokens_out = 0
        truncated = False
        llm_error_count = 0
        last_llm_error = ""
        last_error_signature = ""
        same_error_streak = 0
        active_llm = llm_client or self.llm
        archived_once: set[int] = set()

        while rounds < effective_rounds:
            if cancel_event is not None and cancel_event.is_set():
                return SubAgentResult(
                    final_answer="[状态: cancelled] 子代理已按父会话停止请求取消，未继续执行后续动作。",
                    outcome="cancelled",
                    rounds=rounds,
                    tool_calls=tool_trace,
                    depth=depth,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
            rounds += 1
            # fleet slice 3: 每轮边界的租约心跳——只要子代理真实活着并在推进，
            # expires_at 就被机械延长。R1 起 renew 失败不再仅 fail-soft：权威
            # （TTL/supersede）一旦丢失即粘性围栏本 session 的全部副作用，
            # 子代理拒绝继续产生新动作并立即收口。
            self._renew_fleet_run(sess.session_id)
            if self._fleet_fence_lost(sess.session_id):
                return SubAgentResult(
                    final_answer=(
                        "[状态: refused] fleet lease 权威已失效（过期或被接管），"
                        "effect fence 已触发：本子代理停止产生新副作用并收口。"
                        "后继持有者可按接管事实继续。"
                    ),
                    outcome="refused",
                    rounds=rounds,
                    tool_calls=tool_trace,
                    depth=depth,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
            if rounds > 1:
                # 非首轮 LLM 决策前再扫一次，缩小消息恰好在上个 boundary 后到达
                # 的竞态窗口。首轮不注入，避免 task user 后连续 user wire。
                self._inject_pending_agent_messages(sess, sess.session_id)
            # ── LLM 决策 ──
            # Full lazy registry by default; an explicit parent discovery scope is
            # inherited through contextvars and therefore cannot be expanded by child.
            # lazy=True preserves executable JSON-schema structure while removing long
            # descriptions/examples, so capability is retained without paying full token cost.
            schemas = self.registry.schemas(lazy=True)
            from llm_loop.tools.eligibility import runtime_tool_health

            scope = current_tool_discovery_scope.get()
            sub_schemas = [
                schema
                for schema in schemas
                if scope is None or str(schema.get("name", "")) in scope
                if runtime_tool_health(str(schema.get("name", ""))).available
            ]
            # 2026-08-18 修复: 主循环经 _schema_to_param 包装 {type:"function", function:{...}}，
            # 子代理此前直传裸 schema（{name,description,parameters} 无 type）→ DeepSeek 400
            # "tools[0]: missing field type"（实证：子代理 09:31 起全部失败）。补齐同款包装。
            sub_schemas = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                for t in sub_schemas
            ]
            msgs, ingress_failure = self._bounded_child_wire(
                sess, llm=active_llm, model_label=model_label,
                tools=sub_schemas, archived_once=archived_once,
            )
            if ingress_failure:
                return SubAgentResult(
                    final_answer=f"[状态: failure] 子代理上下文预检: {ingress_failure}",
                    outcome="failed",
                    rounds=rounds,
                    tool_calls=tool_trace,
                    depth=depth,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
            _provider_call_coordinator = self.provider_call_coordinator
            _provider_call = (
                _provider_call_coordinator.open_shadow_call_for_client(
                    active_llm,
                    session_id=sess.session_id,
                    idempotency_key=f"subagent:{sess.session_id}:round:{rounds}",
                    owner_ref=f"subagent:{sess.session_id}:round:{rounds}",
                    execution_class=ExecutionClass.SUBAGENT,
                    service_priority=ServicePriority.P1_ACTIVE_TASK_AUXILIARY,
                    purpose=ProviderCallPurpose.SUBAGENT,
                )
                if _provider_call_coordinator is not None
                else None
            )
            try:
                resp = subagent_provider_chat(
                    self,
                    active_llm,
                    lambda _msgs=msgs, _schemas=sub_schemas: active_llm.chat(
                        _msgs, tools=_schemas
                    ),
                    {},
                    owner_ref=f"subagent:{sess.session_id}:round:{rounds}",
                    provider_call=_provider_call,
                    attempt_kind=ProviderAttemptKind.PRIMARY,
                    site_index=0,
                )
                if _provider_call_coordinator is not None:
                    _provider_call_coordinator.settle_shadow_call(
                        _provider_call, ProviderCallOutcome.SUCCESS
                    )
            except Exception as exc:  # noqa: BLE001 — 子代理 LLM 失败如实回传
                if _provider_call_coordinator is not None:
                    _provider_call_coordinator.settle_shadow_call(
                        _provider_call, ProviderCallOutcome.ERROR
                    )
                # LLM 调用失败时根本没有 assistant tool declaration，因此不能伪造
                # role=tool 错误帧；否则下一轮会形成 orphan tool protocol。失败事实
                # 留在本地 terminal outcome，不进入模型对话历史。
                llm_error_count += 1
                last_llm_error = f"{type(exc).__name__}: {exc}"
                # EVO-20261017-1d589ac3: a deterministic request rejection must not be
                # re-sent unchanged.  4xx (except timeout/early-hints/rate-limit) is a
                # property of this exact wire: retrying it burned a child's whole round
                # budget (489->491 identical 400s) and masked the cause as "truncated".
                if isinstance(exc, LLMHTTPError):
                    status_code = int(getattr(exc, "status_code", 0) or 0)
                    if 400 <= status_code < 500 and status_code not in (408, 425, 429):
                        return SubAgentResult(
                            final_answer=(
                                "[状态: failure] 子代理模型请求被 Provider 确定性拒绝"
                                f"（HTTP {status_code}，provider_code="
                                f"{getattr(exc, 'provider_code', None) or 'n/a'}）："
                                f"{str(exc)[:400]}。"
                                "同一 wire 不会因重试而改变，已停止重发；"
                                "子会话原始历史保持持久化。"
                            ),
                            outcome="failed",
                            rounds=rounds,
                            tool_calls=tool_trace,
                            depth=depth,
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                        )
                if isinstance(exc, LLMEmptyResponseError):
                    # Provider returned a real completed stream, possibly spending its
                    # entire reasoning/output allowance without a visible answer.
                    # Its usage is billable even though chat() raised and the child
                    # received no LLMResponse. Never re-send this unchanged wire.
                    tokens_in += max(0, int(exc.prompt_tokens))
                    tokens_out += max(0, int(exc.completion_tokens))
                    return SubAgentResult(
                        final_answer=(
                            "[状态: failure] 子代理模型未生成有效文本或工具动作；"
                            f"finish_reason={exc.finish_reason or 'unknown'}，"
                            f"已消耗输入 {exc.prompt_tokens} / 输出 {exc.completion_tokens} tokens"
                            "（其中推理消耗 "
                            f"{exc.reasoning_tokens if exc.reasoning_tokens is not None else 'unknown'}）。"
                            "请父代理据实际额度调整模型级输出预算或任务分工，不重复原样调用。"
                        ),
                        outcome="failed",
                        rounds=rounds,
                        tool_calls=tool_trace,
                        depth=depth,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
                if isinstance(exc, LLMError) and is_overflow_error(exc):
                    # An input-window overflow is deterministic for the same
                    # preserved messages. Return the exact failure to the parent;
                    # blindly continuing would burn remaining child rounds.
                    return SubAgentResult(
                        final_answer=(
                            "[状态: failure] 子代理模型输入超出该路由实际接收窗口；"
                            f"last_error={last_llm_error}。"
                            "当前子会话原始历史保持持久化，需先缩减输入投影或切换合适模型。"
                        ),
                        outcome="failed",
                        rounds=rounds,
                        tool_calls=tool_trace,
                        depth=depth,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
                if isinstance(exc, LLMProjectionError):
                    # EVO-20261020-b1c00127: a projection violation is a LOCAL wire
                    # defect raised before any transport or provider interaction.
                    # Replaying the identical wire replays the identical error
                    # (the 8/8 fleet failure burned three rounds per child on
                    # exactly this), and every provider would surface the same
                    # signature, so the cross-provider-identical case is judged
                    # runtime-side by construction. Fail fast once, with the
                    # violations and the evidence refs the child already produced.
                    violations = list(getattr(exc, "violations", ()) or ())
                    provider = str(getattr(exc, "provider", "") or "")
                    evidence_refs = self._collect_evidence_refs(sess)
                    evidence_note = (
                        "已采集证据 refs："
                        + "，".join(evidence_refs)
                        + "。父代理可据此无损接管。"
                        if evidence_refs
                        else "子会话未采集到 evidence refs。"
                    )
                    return SubAgentResult(
                        final_answer=(
                            "[状态: failure] 子代理请求投影违反机械 wire 不变量"
                            f"（violations={violations or 'n/a'}，provider={provider or 'n/a'}）："
                            f"{str(exc)[:300]}。"
                            "该错误在进入传输前本地抛出，对同一 wire 是确定性的，"
                            "换 provider 也会得到同一签名，故不做重放；"
                            + evidence_note
                            + "子会话原始历史保持持久化。"
                        ),
                        outcome="failed",
                        rounds=rounds,
                        tool_calls=tool_trace,
                        depth=depth,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
                signature = f"{type(exc).__name__}:{str(exc)[:200]}"
                if signature == last_error_signature:
                    same_error_streak += 1
                else:
                    last_error_signature = signature
                    same_error_streak = 1
                if same_error_streak >= 3:
                    # Same failure three times on an unchanged wire: transient retries
                    # no longer explain it, so stop instead of burning the round budget.
                    # EVO-20261020-b1c00127: carry the child's already-acquired
                    # evidence refs so the parent can take over losslessly.
                    evidence_refs = self._collect_evidence_refs(sess)
                    evidence_note = (
                        f"已采集证据 refs（{len(evidence_refs)} 个）："
                        + "，".join(evidence_refs[:10])
                        + "。父代理可据此无损接管。"
                        if evidence_refs
                        else ""
                    )
                    return SubAgentResult(
                        final_answer=(
                            "[状态: failure] 子代理连续 "
                            f"{same_error_streak} 次收到同一模型错误，"
                            f"已熔断停止重放：{last_llm_error[:400]}。"
                            + evidence_note
                            + "子会话原始历史保持持久化。"
                        ),
                        outcome="failed",
                        rounds=rounds,
                        tool_calls=tool_trace,
                        depth=depth,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
                continue
            tokens_in += resp.prompt_tokens
            tokens_out += resp.completion_tokens

            # Stop 可能发生在 LLM HTTP 调用期间；响应返回后先检查 cancel，再决定
            # 是否执行刚声明的工具，避免“用户已停止但副作用仍继续”。
            if cancel_event is not None and cancel_event.is_set():
                return SubAgentResult(
                    final_answer="[状态: cancelled] 子代理已按父会话停止请求取消，未执行停止后的模型动作。",
                    outcome="cancelled",
                    rounds=rounds,
                    tool_calls=tool_trace,
                    depth=depth,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )

            # 无工具调用 → 最终回答
            if not resp.tool_calls:
                answer = (resp.content or "").strip()
                stale_assistant = (
                    Message(
                        role="assistant",
                        content=answer,
                        source=MessageSource.USER,
                        reasoning_content=resp.reasoning_content,
                        model_used=model_label,
                        metadata=(
                            {"provider_replay": resp.provider_replay}
                            if resp.provider_replay
                            else {}
                        ),
                    )
                    if answer
                    else None
                )
                if self._inject_pending_agent_messages(
                    sess,
                    sess.session_id,
                    preceding_assistant=stale_assistant,
                ):
                    # 该“final”在新 steer 到达前生成，不能直接结算；下一轮基于
                    # 真实时序 assistant(old) -> agent_message 继续决策。
                    continue
                if not answer:
                    return SubAgentResult(
                        final_answer="[状态: failure] 子代理未返回工具调用，也未返回可交付的最终文本。",
                        outcome="failed",
                        rounds=rounds,
                        tool_calls=tool_trace,
                        depth=depth,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
                # durable child history 必须包含 terminal assistant；父级收到的 final_answer
                # 与子会话可审计/可恢复终态保持同一事实源。
                sess.messages.append(
                    Message(
                        role="assistant",
                        content=answer,
                        source=MessageSource.USER,
                        reasoning_content=resp.reasoning_content,
                        model_used=model_label,
                        metadata=(
                            {"provider_replay": resp.provider_replay}
                            if resp.provider_replay
                            else {}
                        ),
                    )
                )
                with suppress(Exception):
                    self.session_store.save(sess)
                return SubAgentResult(
                    final_answer=answer,
                    outcome="completed",
                    rounds=rounds,
                    tool_calls=tool_trace,
                    truncated=truncated,
                    depth=depth,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )

            # ── 执行工具（真实执行，复用 registry）──
            # 约束 C1 与主循环同构：assistant(tool_calls) 声明必须先进入子会话，
            # 后续 tool(result) 才有可回放的前置声明。旧实现只追加 tool receipt，
            # 下一轮形成 orphan tool 消息；provider 清洗后模型看不到上一轮已执行
            # 的动作，真实事故表现为同一 execute_command 连续重复到 8/8 轮耗尽。
            import json as _json

            assistant_decl = Message(
                role="assistant",
                content=resp.content or "",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": _json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in resp.tool_calls
                ],
                reasoning_content=resp.reasoning_content,
                model_used=model_label,
                metadata=(
                    {"provider_replay": resp.provider_replay}
                    if resp.provider_replay
                    else {}
                ),
            )
            sess.messages.append(assistant_decl)
            # Declaration must be durable before any tool can execute. SessionStore
            # backfills the matching message.appended event from this exact snapshot.
            self.session_store.save(sess)
            execution_ids: dict[str, str] = {}
            for tc in resp.tool_calls:
                call = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                execution_ids[call.id] = self._tool_journal.declared(
                    sess, call, round_no=rounds
                )

            from llm_loop.tools.registry import tool_result_to_message

            for tc in resp.tool_calls:
                call = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                execution_id = execution_ids.get(call.id, "")
                result_state_sha = ""
                executed = False
                # Explicit parent scope is an authorization boundary and must survive
                # hallucinated/unadvertised tool calls. With scope=None, registry/tool
                # implementations own callability and safety; child identity adds no penalty.

                scope = current_tool_discovery_scope.get()
                if not execution_id:
                    result = ToolResult(
                        status=ToolResultStatus.ERROR,
                        content=(
                            "execution_not_started=true; reason_code=wal_declaration_unavailable; "
                            "auto_reexecuted=false"
                        ),
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                elif scope is not None and call.name not in scope:
                    result = ToolResult(
                        status=ToolResultStatus.BLOCKED,
                        # EVO-20261014-459a8a1e: E1 工具白名单层，带码落 exception_log。
                        content=(
                            f"[状态: blocked] [E1_TOOL_WHITELIST] 工具 {call.name} 不在父执行域授权集合内。"
                        ),
                        tool_call_id=call.id,
                        tool_name=call.name,
                        error_type="E1_TOOL_WHITELIST",
                    )
                    # 该拒绝不经 registry.execute，显式走同一观察者管线落故障台账。
                    notify_external = getattr(self.registry, "notify_external_result", None)
                    if callable(notify_external):
                        notify_external(call.name, result)
                else:
                    started = self._tool_journal.started(
                        sess.session_id,
                        execution_id=execution_id,
                        round_no=rounds,
                        call=call,
                    )
                    if not started:
                        result = ToolResult(
                            status=ToolResultStatus.ERROR,
                            content=(
                                "execution_not_started=true; reason_code=wal_start_not_durable; "
                                "auto_reexecuted=false"
                            ),
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                    else:
                        executed = True
                        try:
                            # EVO-20261014 子代理 effect 代际隔离：worker 线程经
                            # copy_context 继承父 run 的 current_run_generation，
                            # binding 会带父代去查子会话的 run_generation_authority
                            # （子 sid 从未注册 → "" != 父代 → 全部 effect 工具被
                            # unauthorized，文案误导为 "run lease fenced"，磁盘
                            # lease 实则健康）。子代理会话不参与父 run-generation
                            # CAS；其 effect 权威由 R1 fleet lease fence 承担。
                            generation_token = current_run_generation.set("")
                            try:

                                with self._tool_journal.effect_context(
                                    session_id=sess.session_id,
                                    execution_id=execution_id,
                                    round_no=rounds,
                                    call=call,
                                    workspace_root=current_workspace_root.get(),
                                    lease_fence=self._fleet_lease_fence(sess.session_id),
                                ):
                                    result = self.registry.execute(call)
                            finally:
                                current_run_generation.reset(generation_token)
                        except Exception as exc:  # noqa: BLE001 — 如实回传
                            result = ToolResult(
                                status=ToolResultStatus.ERROR,
                                content=(
                                    "[状态: error] 子代理工具执行异常: "
                                    f"{type(exc).__name__}: {exc}"
                                ),
                                tool_call_id=call.id,
                                tool_name=call.name,
                            )

                tool_trace.append({"name": call.name, "status": result.status.value})
                tool_msg = tool_result_to_message(
                    result,
                    failure_guidance_enabled=False,
                    experience_guidance_enabled=True,
                    tool_guidance_mode=self.registry.tool_guidance_mode,
                )
                if executed and execution_id:
                    # Exact future receipt is staged immediately after execution; if
                    # the process dies before this point, started-but-unknown recovery
                    # explicitly forbids automatic re-execution.
                    result_state_sha = self._tool_journal.finished(
                        sess.session_id,
                        execution_id=execution_id,
                        round_no=rounds,
                        call=call,
                        tool_message=tool_msg,
                    )
                sess.messages.append(tool_msg)
                # The ordinary transcript receipt is durable before WAL settlement.
                # If save fails, the exact sidecar remains for later repair.
                self.session_store.save(sess)
                if execution_id:
                    self._tool_journal.receipt_committed(
                        sess.session_id,
                        execution_id=execution_id,
                        round_no=rounds,
                        tool_call_id=call.id,
                        tool_name=call.name,
                        result_state_sha256=result_state_sha,
                        tool_message=tool_msg,
                    )
                if cancel_event is not None and cancel_event.is_set():
                    return SubAgentResult(
                        final_answer="[状态: cancelled] 子代理在工具执行期间收到父会话停止请求，已停止后续轮次。",
                        outcome="cancelled",
                        rounds=rounds,
                        tool_calls=tool_trace,
                        depth=depth,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )

            # 当前 assistant(tool_calls)->tool(...) 已全部配对完成，才进入安全
            # step boundary。父消息从这里开始只影响下一轮，不打断原子工具动作。
            self._inject_pending_agent_messages(sess, sess.session_id)

        # 所有轮次均在 provider/LLM 层失败时属于 failed，不冒充“执行过但截断”。
        if llm_error_count == rounds and not tool_trace:
            answer = (
                "[状态: failure] 子代理 LLM 连续调用失败，未获得可执行动作或最终回答。"
                + (f" last_error={last_llm_error}" if last_llm_error else "")
            )
            with suppress(Exception):
                self.session_store.save(sess)
            return SubAgentResult(
                final_answer=answer,
                outcome="failed",
                rounds=rounds,
                tool_calls=tool_trace,
                depth=depth,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )

        # 轮数超限截断（如实标注）
        truncated = True
        answer = "（子代理已达轮数上限，结果未完整收敛——请父级基于已有工具反馈整合）"
        with suppress(Exception):
            self.session_store.save(sess)
        return SubAgentResult(
            final_answer=answer,
            outcome="truncated",
            rounds=rounds,
            tool_calls=tool_trace,
            truncated=truncated,
            depth=depth,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    # ── fork 继承（DSH 借鉴 022-A）──
    def _capture_parent_context_artifact(
        self, parent_sid: str, msgs: list[Message]
    ) -> tuple[str, int, int]:
        """Persist a mechanically complete parent storage transcript for child lookup.

        Private assistant reasoning/provider replay is deliberately excluded: this artifact
        is exact conversational/tool storage truth, not cross-agent reasoning replay. Long
        message content is split into bounded JSONL chunks so ``read_file(offset/limit)``
        can advance monotonically without re-truncating one giant line.
        """
        if self.artifact_store is None or not msgs:
            return "", 0, 0

        rows: list[dict[str, object]] = []
        for message_index, msg in enumerate(msgs):
            content = str(getattr(msg, "content", "") or "")
            chunks = [
                content[pos : pos + _PARENT_CONTEXT_ARTIFACT_CHUNK_CHARS]
                for pos in range(0, len(content), _PARENT_CONTEXT_ARTIFACT_CHUNK_CHARS)
            ] or [""]
            md = getattr(msg, "metadata", {}) or {}
            for chunk_index, chunk in enumerate(chunks):
                row: dict[str, object] = {
                    "message_index": message_index,
                    "role": str(getattr(msg, "role", "") or ""),
                    "source": str(getattr(getattr(msg, "source", None), "value", "") or ""),
                    "chunk_index": chunk_index,
                    "chunk_count": len(chunks),
                    "content": chunk,
                }
                if chunk_index == 0:
                    tool_call_id = str(getattr(msg, "tool_call_id", "") or "")
                    tool_name = str(getattr(msg, "tool_name", "") or "")
                    if tool_call_id:
                        row["tool_call_id"] = tool_call_id
                    if tool_name:
                        row["tool_name"] = tool_name
                    tool_calls = getattr(msg, "tool_calls", None)
                    if isinstance(tool_calls, list) and tool_calls:
                        row["tool_calls"] = tool_calls
                    attachments = md.get("attachments") if isinstance(md, dict) else None
                    if isinstance(attachments, list) and attachments:
                        row["attachments"] = attachments
                rows.append(row)
        manifest = {
            "kind": "subagent_parent_context",
            "parent_session_id": parent_sid,
            "message_count": len(msgs),
            "chunk_count": len(rows),
            "chunk_chars": _PARENT_CONTEXT_ARTIFACT_CHUNK_CHARS,
            "representation": "storage_transcript_without_private_reasoning",
        }
        text = "\n".join(
            [json.dumps(manifest, ensure_ascii=False, sort_keys=True)]
            + [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
        ) + "\n"
        payload = text.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        scope = workspace_base()
        canonical = (
            Path(scope)
            / ".lfl"
            / "continuity"
            / "subagent_parent_context"
            / f"{digest[:24]}.jsonl"
        )
        record = self.artifact_store.create(
            workspace_scope=scope,
            canonical_path=str(canonical),
            data=payload,
            owner_session_id=parent_sid,
            execution_id=f"subagent-parent-context:{digest[:24]}",
            tool_call_id="",
            tool_name="spawn_subagent",
            effect_kind="subagent_parent_context",
        )
        return record.ref, len(text), len(rows) + 1

    def _inherit_parent_context(self, context: str) -> str:
        """Expose exact parent context as retrieval-only; never auto-inline parent turns."""

        parent_sid = current_session_id.get()
        if not parent_sid:
            return context
        try:
            parent_sess = (
                self._parent_session_provider(parent_sid)
                if self._parent_session_provider is not None
                else None
            )
            if parent_sess is None:
                parent_sess = self.session_store.load(parent_sid)
            msgs = list(parent_sess.messages)
        except Exception:  # noqa: BLE001 — fail-open: 继承失败不阻断子代理
            return context
        if not msgs:
            return context
        try:
            exact_ref, exact_chars, exact_lines = self._capture_parent_context_artifact(
                parent_sid, msgs
            )
        except Exception:  # noqa: BLE001 — exact-ref aid is fail-open
            return context
        if not exact_ref:
            return context
        inherit_block = (
            "【fork 继承·父会话上下文引用（retrieval-only，不自动展开）】\n"
            f"exact_parent_context_ref={exact_ref} exact_chars={exact_chars} "
            f"exact_lines={exact_lines} "
            "representation=storage_transcript_without_private_reasoning "
            "retrieval_only=true inline_parent_messages=0\n"
            f"read_contract=read_file(path='{exact_ref}', offset=<line>, limit=<lines>)"
        )
        return f"{context}\n\n{inherit_block}" if context.strip() else inherit_block
