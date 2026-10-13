"""ToolCycleService——工具执行循环职责面（R9-P5-02 / B5-W3-01）.

_ToolExecMixin（10 法，tool_exec.py:138-486）+ _ToolEligibilityMixin（1 法，
tool_eligibility.py）逐字平移：宿主面（events/routing mixin + settings/status/
registry/session + 停滞态 per-session 桶）经 ``self._host``；
域内互调与运行态保持 self；
module 级辅助 _json_dumps_args 等留驻 tool_exec.py（REQ-REF-06 re-export 不变）。
等价证明：生成管线 AST 反替自证 + 提交门禁 PROBE 隔离树 ci_gate 全绿。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (service 模式: self 属性来自 host 注入面，pyright 无法静态解析，沿 mixin 原口径文件级关闭这两条)

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from llm_loop.core.loop.engine_services.convergence_boundary import (
    ConvergenceFacts,
    evaluate_convergence_boundary,
)
from llm_loop.core.loop.engine_services.convergence_receipt import (
    MirrorFacts,
    QueuePressureFacts,
    VitalsFacts,
    mirror_budget_chars,
    render_convergence_receipt_addendum,
)
from llm_loop.core.loop.engine_services.tool_reachability import (
    RoundReachabilityRecorder,
    tool_schema_names,
)
from llm_loop.core.loop.tool_exec import (
    _EMPTY_SEARCH_REMIND_AT,
    _STAGNATION_REMIND_AT,
    _canonical_json_dumps_args,
    _is_empty_search_result,
    _is_search_like_call,
    _json_dumps_args,
    _tool_args_summary,
    fingerprint_summary,
)
from llm_loop.core.message import (
    Message,
    MessageSource,
    RecoverabilityStatus,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from llm_loop.core.run_context import current_workspace_root
from llm_loop.introspection.status import ToolHistoryItem
from llm_loop.llm.client import LLMResponse, StreamDelta, ToolResultInfo, ToolRoundInfo
from llm_loop.runtime.tool_octet import record_tool_octet
from llm_loop.tools.registry import tool_result_to_message

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)

class ToolCycleService:
    # legacy 字段名 stagnation_state 仅承载事实观测；P2-A 后无 breaker authority。

    def __init__(self, host: LoopEngine) -> None:
        self._host = host
        # EVO-20260903-ba25857b Phase 0: 工具可达性每轮观测（纯观测面，fail-open）
        self._round_obs = RoundReachabilityRecorder()
        # G5 对抗复审：rule_review/called-last 已迁入 per-session _RunState；
        # ToolCycleService 不持有跨 session 的能力可用性计数。
        # MR-1: 本轮 structured unavailable 模型可见通知缓存（enforce 生成、
        # provider 轮次消费即弃——不进 sess.messages，不回流历史，硬约束④）

    def _reachability_begin_attempt(
        self,
        *,
        kind: str,
        attempt_index: int = 0,
        model: str = "",
        provider: str = "",
    ) -> str:
        """Bind the staged projection to one real provider request (fail-open)."""
        try:
            return self._round_obs.ensure_attempt(
                kind=kind,
                attempt_index=attempt_index,
                model=model,
                provider=provider,
            )
        except Exception:  # noqa: BLE001 -- observability cannot block the run
            logger.debug("reachability attempt bind failed (fail-open)", exc_info=True)
            return ""

    def _reachability_record_response(self, resp: LLMResponse | None) -> None:
        """Record one provider response emission, including explicit no-tool responses."""
        if resp is None:
            return
        try:
            self._round_obs.record_emission(
                [
                    {
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "raw_arguments": _json_dumps_args(tc.arguments),
                        "arguments": tc.arguments,
                        "valid": bool(tc.id),
                    }
                    for tc in (resp.tool_calls or [])
                ]
            )
        except Exception:  # noqa: BLE001 -- observability cannot block the run
            logger.debug("reachability response emission failed (fail-open)", exc_info=True)

    def _reachability_finalize(self, outcome: str) -> None:
        """Finalize the active/staged reachability record exactly once (fail-open)."""
        try:
            self._round_obs.finalize(outcome)
        except Exception:  # noqa: BLE001 -- observability cannot block the run
            logger.debug("reachability attempt finalize failed (fail-open)", exc_info=True)

    def _declare_tool_execution_wal(self, sess, declared_calls, rounds: int) -> dict[str, str]:
        execution_ids: dict[str, str] = {}
        for tc, _pair_id in declared_calls:
            if not tc.id:
                continue
            try:
                execution_ids[tc.id] = self._host._tool_execution_declared(
                    sess, tc, round_no=rounds
                )
            except Exception:  # noqa: BLE001 — WAL declaration must not corrupt pairing
                logger.warning("tool execution declared WAL failed (fail-open)", exc_info=True)
        return execution_ids

    def _continuity_reuse_result(self, call) -> ToolResult | None:
        """Short-circuit an exact repeated durable read when source identity is unchanged.

        Only read_evidence (immutable ref/range) and read_file (stat/artifact version
        verified) participate.  Search/network/control tools are intentionally excluded.
        """

        if call.name not in {"read_file", "read_evidence"} or not isinstance(call.arguments, dict):
            return None
        try:
            from llm_loop.core.longrun_continuity import (
                canonical_read_key,
                file_version_still_matches,
            )

            key = canonical_read_key(call.name, call.arguments)
            cached = self._host._run_state().longrun_read_cache.get(key)
            if not isinstance(cached, dict):
                return None
            version = str(cached.get("source_version_token") or "")
            if call.name == "read_file" and not file_version_still_matches(
                call.arguments, version
            ):
                return None
            evidence_ref = str(cached.get("evidence_ref") or "")
            artifact_ref = str(cached.get("artifact_ref") or "")
            facts = [
                "exact_read_reused=true",
                f"tool={call.name}",
                "source_execution_performed=false",
            ]
            if version:
                facts.append(f"source_version_token={version}")
            if evidence_ref:
                facts.append(f"evidence_ref={evidence_ref}")
            if artifact_ref:
                facts.append(f"snapshot_ref={artifact_ref}")
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="[longrun_continuity_reuse] " + "; ".join(facts),
                tool_call_id=call.id,
                tool_name=call.name,
                recoverability_status=(
                    RecoverabilityStatus.RECORDED
                    if evidence_ref
                    else RecoverabilityStatus.NOT_CONFIGURED
                ),
                evidence_ref=evidence_ref or None,
                evidence_representation="ref_only" if evidence_ref else None,
                evidence_projection_complete=False if evidence_ref else None,
                evidence_source_version_token=version or None,
                source_resolution_mode="longrun_continuity",
                source_execution_performed=False,
                short_circuit_kind="longrun_duplicate_read",
            )
        except Exception:  # noqa: BLE001 — cache optimization fail-open to physical read
            logger.debug("longrun continuity read reuse failed", exc_info=True)
            return None

    def _remember_continuity_read(self, call, result: ToolResult) -> None:
        """Record exact successful read facts for same-run/cross-overflow reuse."""

        if (
            call.name not in {"read_file", "read_evidence"}
            or not isinstance(call.arguments, dict)
            or result.status is not ToolResultStatus.SUCCESS
            or result.short_circuit_kind == "longrun_duplicate_read"
        ):
            return
        try:
            from llm_loop.core.longrun_continuity import canonical_read_key

            version = str(result.evidence_source_version_token or "")
            if not version and isinstance(result.evidence_origin_facts, dict):
                version = str(result.evidence_origin_facts.get("source_version_token") or "")
            artifact_ref = ""
            for fact in result.artifact_facts or ():
                if isinstance(fact, dict) and fact.get("ref"):
                    artifact_ref = str(fact.get("ref"))
                    break
            key = canonical_read_key(call.name, call.arguments)
            self._host._run_state().longrun_read_cache[key] = {
                "tool": call.name,
                "arguments": dict(call.arguments),
                "evidence_ref": str(result.evidence_ref or ""),
                "source_version_token": version,
                "artifact_ref": artifact_ref,
            }
        except Exception:  # noqa: BLE001 — observability/cache must not alter tool truth
            logger.debug("longrun continuity read remember failed", exc_info=True)

    def _execute_allowed_with_wal(
        self,
        sess,
        allowed_calls,
        execution_ids: dict[str, str],
        rounds: int,
    ):
        """Execute allowed calls while durably staging exact receipts before history append."""
        wal_messages: dict[str, Message] = {}
        wal_result_sha: dict[str, str] = {}
        executable_calls = []
        pre_results: dict[str, ToolResult] = {}
        for call in allowed_calls:
            execution_id = execution_ids.get(call.id, "")
            if not execution_id:
                pre_results[call.id] = ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=(
                        "execution_not_started=true; reason_code=wal_declaration_unavailable; "
                        "auto_reexecuted=false"
                    ),
                    tool_call_id=call.id,
                    tool_name=call.name,
                )
                continue
            try:
                started = self._host._tool_execution_started(
                    sess.session_id,
                    execution_id=execution_id,
                    round_no=rounds,
                    call=call,
                )
            except Exception:  # noqa: BLE001 — normal receipt path remains authority
                logger.warning("tool execution started WAL failed (fail-open)", exc_info=True)
                started = False
            if not started:
                pre_results[call.id] = ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=(
                        "execution_not_started=true; reason_code=wal_start_not_durable; "
                        "auto_reexecuted=false"
                    ),
                    tool_call_id=call.id,
                    tool_name=call.name,
                )
                continue
            executable_calls.append(call)

        def persist_finished(call, result) -> None:
            execution_id = execution_ids.get(call.id, "")
            if not execution_id:
                return
            # R2（antidrift_impl 批1，执行期修正 EX-2）: 回执消息唯一常态构造点在
            # persist_finished 预构造（journal 与 EventStore 解耦，execution_id 总是
            # 分配——_record_single_receipt 的 prebuilt 分支因此是常态而非仅 WAL
            # 重放）。三件套附加必须在此、tool_msg 构造前落在 result.content 上，
            # 保证 journal/WAL 持久化的即最终形态。None 分支的调用保留为防御路径
            # （两路互斥：execution_id 存在 ⇔ prebuilt 存在）。
            self._attach_convergence_receipt_facts(sess, call, result)
            self._remember_continuity_read(call, result)
            tool_msg = tool_result_to_message(
                result,
                failure_guidance_enabled=self._host.registry.failure_guidance_enabled,
                tool_guidance_mode=self._host.registry.tool_guidance_mode,
            )
            self._attach_capability_boundary_metadata(tool_msg, result)
            wal_messages[call.id] = tool_msg
            wal_result_sha[call.id] = self._host._tool_execution_finished(
                sess.session_id,
                execution_id=execution_id,
                round_no=rounds,
                call=call,
                tool_message=tool_msg,
            )

        continuity_results: list[ToolResult] = []
        physical_calls = []
        for call in executable_calls:
            reused = self._continuity_reuse_result(call)
            if reused is not None:
                continuity_results.append(reused)
                persist_finished(call, reused)
            else:
                physical_calls.append(call)

        gap_skipped: list[ToolCall] = []
        if not physical_calls:
            results = list(continuity_results)
        else:

            effect_journal = self._host._tool_execution_journal()
            with effect_journal.effect_bindings(
                session_id=sess.session_id,
                execution_ids=execution_ids,
                round_no=rounds,
                calls=physical_calls,
                workspace_root=current_workspace_root.get(),
            ):
                physical_results, gap_skipped = self._execute_segments_with_gap_check(
                    sess, physical_calls, persist_finished
                )
            # Phase4 M1：skipped 回执合成与消费点后移至 _execute_tools 回执落盘
            # 之后（审查 P2-1/P2-5：消除"声明+skip 已落盘而已执行回执未落盘"的
            # 中段崩溃孤儿窗口，并使消息序为 声明→已执行回执→skip→插话）。
            results = [*continuity_results, *physical_results]
        by_id = {r.tool_call_id: r for r in results if r.tool_call_id}
        ordered = [
            pre_results.get(call.id) or by_id.get(call.id)
            for call in allowed_calls
        ]
        return (
            [r for r in ordered if r is not None],
            wal_messages,
            wal_result_sha,
            gap_skipped,
        )

    def _execute_tools(
        self,
        resp: LLMResponse,
        sess,
        rounds: int,
        tool_trace: list[dict],
    ) -> Iterator[StreamDelta]:
        """行动：执行工具（tool_calls），move 自 engine.py:492-553（生成器保持外泄次序）."""
        self._host._phase("action.tool_loop")
        # C1 pairing: persist the model declaration before tool receipts. Provider
        # tool_call_id is normally authoritative. If a malformed provider response omits
        # an id, create a local pairing id *only for history repair*, never execute that
        # call, and pair it with a factual blocked tool receipt. This keeps the next
        # provider request structurally valid without injecting a program system prompt.
        _declared_calls = [
            (tc, tc.id or f"lfl-missing-id-r{rounds}-{idx + 1}")
            for idx, tc in enumerate(resp.tool_calls)
        ]
        _assistant_decl_durable = True
        if _declared_calls:
            assistant_decl = Message(
                role="assistant",
                content=resp.content or "",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": pair_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": _json_dumps_args(tc.arguments),
                        },
                    }
                    for tc, pair_id in _declared_calls
                ],
                reasoning_content=resp.reasoning_content,
                metadata=(
                    {"provider_replay": resp.provider_replay}
                    if resp.provider_replay
                    else {}
                ),
            )
            sess.messages.append(assistant_decl)
            _assistant_event = self._host._append_message_event(sess, assistant_decl)
            _event_store = getattr(self._host, "_event_store", None)
            _wal_active = _event_store is not None and getattr(_event_store, "enabled", False)
            _assistant_decl_durable = (not _wal_active) or _assistant_event is not None
        # Convergence observations never revoke ordinary tool authority.  Every concrete
        # provider declaration follows the normal WAL/execution path; there is no
        # convergence meta-router fence in front of the real tool.
        _wal_declared_calls = list(_declared_calls)
        _execution_ids = (
            self._declare_tool_execution_wal(sess, _wal_declared_calls, rounds)
            if _assistant_decl_durable
            else {}
        )
        for tc, pair_id in _declared_calls:
            if tc.id:
                continue
            msg = Message(
                role="tool",
                content=(
                    f"[协议回执] executed=false; reason_code=missing_tool_call_id; "
                    f"tool={tc.name}; provider_call_id=missing"
                ),
                tool_call_id=pair_id,
                tool_name=tc.name,
                source=MessageSource.SYSTEM,
                status=ToolResultStatus.BLOCKED,
                metadata={
                    "protocol_repair": {
                        "reason_code": "missing_tool_call_id",
                        "synthetic_pairing_id": pair_id,
                        "executed": False,
                    }
                },
            )
            sess.messages.append(msg)
            self._host._append_message_event(sess, msg)
            self._host._record_action(
                "action.tool_loop", "missing_tool_call_id", f"{tc.name};pair={pair_id};executed=0"
            )
            record_tool_octet(
                session_id=sess.session_id,
                round_index=rounds,
                tool_call_id=pair_id,
                tool_name=tc.name,
                args=tc.arguments if isinstance(tc.arguments, dict) else {},
                status="blocked",
                duration_ms=None,
                result_content=None,
                reason_code="missing_tool_call_id",
            )

        # EVO-20260810-750e985a: 工具并发控制（只读并行/修改串行/按声明顺序回写）
        valid_calls = [tc for tc in resp.tool_calls if tc.id]
        if valid_calls:
            # HARNESS-01(2026-08-14): 中断时孤儿 tool_calls 合成回执——assistant 声明
            # （带 tool_calls）先入历史、yield 流式进展后才 execute_many；若客户端在 yield
            # 阶段断流（GeneratorExit），历史留下"有声明无回执"孤儿 → 严格 FC 协议下下次
            # 请求直接 400。兜底：中断时对未执行声明写合成"已取消"回执并立即保存会话
            # （声明数 = 结果数 + 取消数 对账不变量成立，任何保存时机历史自洽）。
            try:
                # P2-1: 工具轮次进展外泄（fail-open，yield 异常不阻断主循环）
                for tc in valid_calls:
                    # H-UI: 工具调用开始（实时状态条）
                    self._host._notify_action(
                        "tool_call",
                        tool_name=tc.name,
                        args_summary=_tool_args_summary(tc.arguments),
                    )
                    try:
                        yield StreamDelta(
                            text="",
                            tool_round=ToolRoundInfo(
                                tool_name=tc.name,
                                round_index=rounds,
                                args_summary=_tool_args_summary(tc.arguments),
                                tool_call_id=tc.id,
                            ),
                        )
                    except GeneratorExit:
                        # 客户端断流：全部声明未执行 → 合成取消回执 + 落盘（防孤儿）
                        self._synthesize_cancelled(
                            sess, valid_calls,
                            executed_ids=set(), round_index=rounds)
                        try:
                            self._host.session.save(sess)
                        except Exception:  # noqa: BLE001 — 保存失败 fail-open
                            logger.warning("中断路径会话保存失败（fail-open）", exc_info=True)
                        self._reachability_finalize("client_disconnect")
                        raise  # 正常生成器关闭语义（重新抛 GeneratorExit）
                    except Exception:  # noqa: BLE001 — fail-open
                        logger.warning("tool_round yield 失败（fail-open）", exc_info=True)
                runner = getattr(self._host, "runner", None)
                if runner is not None and runner.enabled and runner.is_cancelled(sess.session_id):
                    self._synthesize_cancelled(
                        sess, valid_calls, executed_ids=set(), round_index=rounds)
                    self._reachability_finalize("cancelled_tools")
                    return
                # A convergence observation is not an execution fence.  If the model
                # names a concrete tool, execute that tool under the normal registry/WAL
                # safety layers instead of forcing a convergence_decide detour.
                allowed_results, _wal_messages, _wal_result_sha, _gap_skipped = (
                    self._execute_allowed_with_wal(
                        sess, valid_calls, _execution_ids, rounds
                    )
                )
                results = list(allowed_results)
                # 对账不变量: 声明数 == 结果数 + 间隙跳过数（缺失 → 合成取消，
                # 防孤儿声明落盘）。gap_skipped 的回执已由
                # _synthesize_skipped_for_interjection 直写（消息+octet），不进
                # 结果列表（status=None 无法走 _record_single_receipt 的五态路径）。
                if len(results) + len(_gap_skipped) != len(valid_calls):
                    executed_ids = {r.tool_call_id for r in results if r.tool_call_id}
                    skipped_ids = {tc.id for tc in _gap_skipped}
                    missing = [
                        tc
                        for tc in valid_calls
                        if tc.id not in executed_ids and tc.id not in skipped_ids
                    ]
                    if missing:
                        self._synthesize_cancelled(
                            sess, missing, executed_ids=set(), round_index=rounds)
                        logger.warning(
                            "工具对账不变量缺失: 声明 %d 结果 %d（%d 条合成取消）",
                            len(valid_calls),
                            len(results),
                            len(missing),
                        )
                # Phase4 M1: 按 id 配对（gap_skipped 造成的中位缺失不再错位配对；
                # 无跳过时与原 zip 位置配对等价——ordered 保持 allowed_calls 序）。
                _results_by_id = {r.tool_call_id: r for r in results if r.tool_call_id}
                recorded_results: list[tuple[Any, Any]] = []
                for tc in valid_calls:
                    result = _results_by_id.get(tc.id)
                    if result is None:
                        continue
                    self._record_single_receipt(
                        sess,
                        tc,
                        result,
                        tool_trace,
                        round_index=rounds,
                        prebuilt_tool_msg=_wal_messages.get(tc.id),
                        wal_execution_id=_execution_ids.get(tc.id, ""),
                        wal_result_sha=_wal_result_sha.get(tc.id, ""),
                    )
                    recorded_results.append((tc, result))

                # ``tool_result`` introduces a new post-execution yield point. Persist the
                # complete execution batch before exposing any UI terminal event so a client
                # disconnect at that yield cannot skip the normal loop-end session save and
                # leave JSON-read recovery behind the already-executed tools. Event/WAL facts
                # remain authoritative where enabled; this snapshot is the no-event-log fence.
                try:
                    self._host.session.save(sess)
                except Exception:  # noqa: BLE001 — UI observability must not block tool semantics
                    logger.warning(
                        "tool_result 前会话快照持久化失败（fail-open）", exc_info=True
                    )

                if _gap_skipped:
                    # Phase4 M1 间隙收割（§4.2 CK-A 尾段）：已执行回执落盘后，
                    # 剩余未开始调用逐条回执 skipped_for_interjection → 轮内直接
                    # 进入消费点 → 下一轮派发。时序后移消除无 WAL 部署的孤儿
                    # 窗口（审查 P2-1）并固定消息序（P2-5）。
                    self._synthesize_skipped_for_interjection(
                        sess, _gap_skipped, round_index=rounds
                    )
                    self._consume_gap_interjections(sess)
                # Phase4 M3 分桶戳记（§7）：本轮回执是否含在途打断标注（度量用）。
                self._host._run_state().last_receipt_interrupted = any(
                    getattr(result, "interrupted_for_interjection", False)
                    for _tc, result in recorded_results
                )

                # UI terminal facts are emitted only after every receipt in this execution
                # batch has been recorded and the batch persistence boundary was attempted.
                for tc, result in recorded_results:
                    yield StreamDelta(
                        text="",
                        tool_result=ToolResultInfo(
                            tool_name=tc.name,
                            tool_call_id=tc.id,
                            status=result.status.value,
                            duration_ms=result.duration_ms,
                            result_chars=len(result.content or ""),
                        ),
                    )
                # EVO-20260903-ba25857b Phase 0: executed receipt facts + flush.
                try:
                    self._round_obs.record_executed(
                        [
                            {
                                "tool_call_id": r.tool_call_id,
                                "name": r.tool_name,
                                "status": getattr(getattr(r, "status", None), "value", ""),
                                "blocked": r.status is ToolResultStatus.BLOCKED,
                            }
                            for r in results
                        ]
                    )
                    self._round_obs.finalize("tool_response")
                except Exception:  # noqa: BLE001 — observability must not block the run
                    logger.debug(
                        "reachability executed/finalize failed (fail-open)", exc_info=True
                    )
            # 注：唯一中断点 = tool_round yield（内层 except GeneratorExit 已合成+落盘+重抛）；
            # execute_many 后无 yield（同步阻塞），不重复外层兜底（防重复合成）
            except GeneratorExit:
                raise
        else:
            self._reachability_finalize("tool_declarations_invalid")

    def _attach_capability_boundary_metadata(self, tool_msg: Message, result) -> None:
        """Attach current-turn mechanical capability facts to their visible producer.

        This layer reports only verified availability/boundary facts.  It does not
        render recovery strategy, select the next action, or create a dynamic prompt
        slot.  History projection keeps the facts visible only for the current human
        turn; durable tool content remains unchanged.
        """
        try:
            from llm_loop.skills.loader import find_skill
            from llm_loop.tools.eligibility import runtime_tool_health

            required_tools = tuple(
                dict.fromkeys(
                    str(n)
                    for n in (getattr(result, "capability_requirements", ()) or ())
                    if str(n)
                )
            )
            unavailable: list[dict[str, Any]] = []
            for name in required_tools:
                health = runtime_tool_health(name)
                if health.available:
                    continue
                unavailable.append(
                    {
                        "tool_name": name,
                        "reason_code": str(health.reason_code or "runtime_unhealthy"),
                        "replacement": [str(x) for x in (health.preferred_next or ()) if str(x)],
                    }
                )

            available: list[dict[str, str]] = []
            advice = getattr(result, "recovery_advice", None)
            preferred_skill = str(getattr(advice, "preferred_skill", "") or "").strip()
            if preferred_skill:
                settings = getattr(self._host, "settings", None)
                skills_dir = str(getattr(settings, "skills_dir", "") or "").strip() or None
                if find_skill(skills_dir, preferred_skill) is not None:
                    available.append(
                        {
                            "kind": "skill",
                            "name": preferred_skill,
                            "loader": "skill_load",
                        }
                    )

            if not unavailable and not available:
                return
            metadata = tool_msg.metadata if isinstance(tool_msg.metadata, dict) else {}
            if unavailable:
                metadata["capability_unavailable"] = unavailable
            if available:
                metadata["capability_available"] = available
            metadata["capability_boundary_turn_ref"] = self._host._run_state().current_turn_ref
            tool_msg.metadata = metadata
        except Exception:  # noqa: BLE001 — boundary facts must never block tool receipt
            logger.debug("capability boundary metadata attach failed (fail-open)", exc_info=True)

    def _attach_convergence_receipt_facts(self, sess, tc, result) -> None:
        """R2（antidrift_impl 批1）: convergence_decide SUCCESS 回执附加三件套事实段.

        回执侧附加，与放行/拦截语义正交（_track_tool_observation 只认 name+status，
        不解析 content）；镜像累积=continue 且 unresolved 非空时在附加之后 append
        （第 N+1 次回执镜像恰含前 N 次）。组装器抛错 fail-open 回退现状回执
        （对齐 capability metadata fail-open 先例）。WAL 恢复重放（prebuilt_tool_msg）
        分支不经此处。
        """
        try:
            if tc.name != "convergence_decide":
                return
            if result.status is not ToolResultStatus.SUCCESS:
                return
            bucket = self._host._run_state()
            started = float(getattr(bucket, "vitals_started_monotonic", 0.0) or 0.0)
            vitals = VitalsFacts(
                rounds=int(getattr(bucket, "vitals_rounds", 0) or 0),
                wall_clock_s=(time.monotonic() - started) if started > 0 else 0.0,
                tokens_in=int(getattr(bucket, "vitals_tokens_in", 0) or 0),
                tokens_out=int(getattr(bucket, "vitals_tokens_out", 0) or 0),
                usage_available=started > 0,
                unavailable_reason="run_vitals_unavailable",
            )
            probe = getattr(self._host, "interjection_pressure_probe", None)
            if probe is None:
                queue_pressure = QueuePressureFacts(unavailable_reason="no_queue_binding")
            else:
                try:
                    snapshot = probe(sess.session_id)
                except Exception:  # noqa: BLE001 — probe 读失败如实标注，不冒充
                    snapshot = None
                if not isinstance(snapshot, dict):
                    queue_pressure = QueuePressureFacts(
                        unavailable_reason="queue_read_failed"
                    )
                else:
                    queue_pressure = QueuePressureFacts(
                        count=int(snapshot.get("count", 0) or 0),
                        oldest_enqueued_at=snapshot.get("oldest_enqueued_at"),
                    )
            addendum = render_convergence_receipt_addendum(
                vitals,
                MirrorFacts(entries=list(bucket.convergence_history)),
                queue_pressure,
                budget_chars=mirror_budget_chars(),
            )
            result.content = f"{result.content}\n\n{addendum}"
            arguments = tc.arguments if isinstance(tc.arguments, dict) else {}
            unresolved = str(arguments.get("unresolved") or "").strip()
            decision = str(arguments.get("decision") or "").strip().lower()
            if decision == "continue" and unresolved:
                bucket.convergence_history.append(unresolved)
        except Exception:  # noqa: BLE001 — R2 三件套附加必须不阻断回执（fail-open）
            logger.debug(
                "convergence receipt addendum attach failed (fail-open)", exc_info=True
            )

    def _record_single_receipt(
        self,
        sess,
        tc,
        result,
        tool_trace: list[dict],
        *,
        round_index: int,
        prebuilt_tool_msg: Message | None = None,
        wal_execution_id: str = "",
        wal_result_sha: str = "",
    ) -> None:
        """单个放行调用的回执落盘（自 _execute_tools 回执处理段抽取，行为逐字平移）.

        T1.3（spec 5.3.1-5a）: tool_trace 补执行口径（tool_loop）指纹摘要字段，
        与决策侧 llm_decide 分列可辨，两口径同源 fingerprint_summary 防漂移。
        """
        tool_trace.append(
            {
                "id": tc.id,
                "name": tc.name,
                "arguments": tc.arguments,
                "status": result.status.value,  # GPT 审计批次4: 证据有效性门
                "fp_summary": fingerprint_summary(self._stagnation_fingerprint(tc)),
            }
        )
        self._record_tool_history(result)
        # H-UI: 工具结果（实时状态条）
        self._host._notify_action(
            "tool_result", tool_name=tc.name, status=result.status.value
        )
        tool_msg = prebuilt_tool_msg
        if tool_msg is None:
            # R2（antidrift_impl 批1）: 非重放路径回执附加三件套（fail-open；
            # prebuilt_tool_msg=WAL 恢复已提交回执重放，不附加）
            self._attach_convergence_receipt_facts(sess, tc, result)
            tool_msg = tool_result_to_message(
                result,
                failure_guidance_enabled=self._host.registry.failure_guidance_enabled,
                tool_guidance_mode=self._host.registry.tool_guidance_mode,
            )
            self._attach_capability_boundary_metadata(tool_msg, result)
        sess.messages.append(tool_msg)
        # D1: tool 回执消息事件（fail-open）
        _message_event = self._host._append_message_event(sess, tool_msg)
        if wal_execution_id and _message_event is not None:
            self._host._tool_execution_receipt_committed(
                sess.session_id,
                execution_id=wal_execution_id,
                round_no=round_index,
                tool_call_id=tc.id,
                tool_name=tc.name,
                result_state_sha256=wal_result_sha,
                tool_message=tool_msg,
            )
        # EVO-20260814-aab7eb0b P2: 运行中停滞指纹追踪（evaluator.py:271 同构指纹）
        # EVO-20260823-9bb27899: 传 result 供搜索类工具空结果计数
        self._track_tool_observation(tc, sess, tool_trace, result=result)
        # M2-G2.1: tool_octet terminal 观测（receipt 配对完成后恰好一次；fail-open，
        # M4-R0 冻结映射：status 原值透传，BLOCKED/UNAUTHORIZED 带 reason_code）
        record_tool_octet(
            session_id=sess.session_id,
            round_index=round_index,
            tool_call_id=tc.id,
            tool_name=tc.name,
            args=tc.arguments if isinstance(tc.arguments, dict) else {},
            status=result.status.value,
            duration_ms=result.duration_ms,
            result_content=result.content,
            reason_code=(
                # Phase4 M2 CK-C：在途打断标注优先（§4.2 回执规范）
                result.interrupt_reason_code
                if getattr(result, "interrupted_for_interjection", False)
                and result.interrupt_reason_code
                else "tool_result_blocked"
                if result.status is ToolResultStatus.BLOCKED
                else "unauthorized"
                if result.status is ToolResultStatus.UNAUTHORIZED
                else None
            ),
        )

    def _gap_interjections_pending(self, sess) -> bool:
        """Phase4 M1 间隙检查点谓词：mailbox 真值 peek（CK-A；§4.4 fail-open）.

        runner 未启用/属性缺失 → False（无收割路径）；peek 异常 → 保守降级
        False（不收割不阻断，退化为轮首/终答边界消费）。
        """
        runner = getattr(self._host, "runner", None)
        if runner is None or not getattr(runner, "enabled", False):
            return False
        try:
            return bool(runner.interjections_pending(sess.session_id))
        except Exception:  # noqa: BLE001 — §4.4 peek 失败保守降级
            logger.warning(
                "interjections_pending peek failed (fail-open, no harvest)", exc_info=True
            )
            return False

    def _execute_segments_with_gap_check(
        self, sess, physical_calls, persist_finished
    ) -> tuple[list[ToolResult], list[ToolCall]]:
        """Segmented execution with Phase4 M1 gap checkpoints (§4.2 CK-A 尾段).

        物理序与 registry.execute_many 单批语义一致：只读并行批在前、变更调用
        串行在后（同 ``_READONLY_TOOLS`` 分类）。间隙检查点仅在"无在途工具"
        的物理边界：序列头（派发前）与每段之间——只读批内部为并发在途，不插
        检查。peek 非空 → 停止派发剩余段并返回待跳过清单（由调用方合成
        skipped_for_interjection 回执并进入消费点）。
        """
        readonly_names = getattr(self._host.registry, "_READONLY_TOOLS", frozenset())
        readonly_seg = [c for c in physical_calls if c.name in readonly_names]
        mutating = [c for c in physical_calls if c.name not in readonly_names]
        segments: list[list[ToolCall]] = []
        if readonly_seg:
            segments.append(readonly_seg)
        segments.extend([c] for c in mutating)
        executed: list[ToolResult] = []
        for idx, seg in enumerate(segments):
            # 每个物理边界（含序列头——覆盖 LLM 调用期间到达的轮间隙插话）
            # 均为无在途工具时刻，执行间隙检查。
            if self._gap_interjections_pending(sess):
                remaining: list[ToolCall] = []
                for later in segments[idx:]:
                    remaining.extend(later)
                return executed, remaining
            try:
                seg_results = self._host.registry.execute_many(
                    seg, on_result=persist_finished
                )
            except TypeError as exc:
                # Legacy duck-typed registries may reject the new kwarg before entering
                # their method body; retrying that specific signature mismatch is safe.
                if "on_result" not in str(exc):
                    raise
                seg_results = self._host.registry.execute_many(seg)
                for call, result in zip(seg, seg_results, strict=False):
                    persist_finished(call, result)
            executed.extend(seg_results)
        return executed, []

    def _synthesize_skipped_for_interjection(
        self, sess, skipped_calls: list[ToolCall], *, round_index: int
    ) -> None:
        """M1 间隙收割：剩余未开始调用逐条回执 skipped_for_interjection.

        形态对齐 _synthesize_cancelled（Message 无 status、octet 如实 duration/
        result 双 null、随会话落盘）；差异仅在事实：调用未开始、因间隙收割
        跳过、无副作用。声明数=结果数+取消数+跳过数对账成立。
        """
        for tc in skipped_calls:
            content = (
                f"[序列间隙收割] 工具 '{tc.name}' 在派发前跳过"
                f"（skipped_for_interjection=true; reason_code=skipped_for_interjection; "
                f"auto_reexecuted=false）：收到用户新插话，序列在间隙点收割，"
                f"该调用未开始、无副作用；请基于新输入重新规划。"
            )
            skip_msg = Message(
                role="tool",
                content=content,
                tool_call_id=tc.id,
                tool_name=tc.name,
                source=MessageSource.SYSTEM,
            )
            sess.messages.append(skip_msg)
            self._host._append_message_event(sess, skip_msg)
            self._host._record_action(
                "action.tool_loop", "skipped_for_interjection", tc.name
            )
            record_tool_octet(
                session_id=sess.session_id,
                round_index=round_index,
                tool_call_id=tc.id,
                tool_name=tc.name,
                args=tc.arguments if isinstance(tc.arguments, dict) else {},
                status="skipped",
                duration_ms=None,
                result_content=None,
                reason_code="skipped_for_interjection",
            )

    def _consume_gap_interjections(self, sess) -> int:
        """M1 间隙收割：轮内直接进入消费点（轮首消费逻辑提前复用，§4.2）.

        take→ingress 守卫→持久化→ack 链路与 _consume_live_interjections 同源
        （含行级持久化失败的回插+传播恢复，见其 docstring）；user_text 对齐经
        run_state.interject_harvest_user_texts 暂存，由下一轮轮首合并。
        延迟导入避免 engine↔service 环引。
        """
        from llm_loop.core.loop.engine_services.interjection_consume import (
            _consume_live_interjections,
        )

        accepted = _consume_live_interjections(
            self._host, sess.session_id, sess, via="gap_harvest"
        )
        if accepted:
            self._host._run_state().interject_harvest_user_texts.extend(accepted)
            self._host._record_action(
                "tool_cycle.gap_harvest",
                "interjection_consumed",
                f"accepted={len(accepted)}",
            )
        return len(accepted)

    def _synthesize_cancelled(self, sess, calls, *,
                              executed_ids: set[str], round_index: int) -> None:
        """HARNESS-01: 对未执行声明写合成取消回执（防孤儿 tool_calls → 下轮 400）.

        消息如实标注"声明后中断未执行"，status 不设（非五态结果，不伪造成功/失败）；
        随会话落盘，任何保存时机下声明数 = 结果数 + 取消数 对账成立。
        """
        for tc in calls:
            if tc.id in executed_ids:
                continue
            cancel_msg = Message(
                role="tool",
                content=(
                    f"[执行中断] 工具 '{tc.name}' 声明后循环中断（客户端断流/引擎终止），"
                    f"该调用未执行、无副作用。"
                ),
                tool_call_id=tc.id,
                tool_name=tc.name,
                source=MessageSource.SYSTEM,
            )
            sess.messages.append(cancel_msg)
            self._host._append_message_event(sess, cancel_msg)
            self._host._record_action("action.tool_loop", "cancelled", tc.name)
            # M2-G2.3: tool_octet cancelled 观测（合成路径 duration/result 双 null；fail-open）
            record_tool_octet(
                session_id=sess.session_id,
                round_index=round_index,
                tool_call_id=tc.id,
                tool_name=tc.name,
                args=tc.arguments if isinstance(tc.arguments, dict) else {},
                status="cancelled",
                duration_ms=None,
                result_content=None,
                reason_code="cancelled",
            )

    def _stagnation_fingerprint(self, tc) -> str:
        """Exact call fingerprint for factual telemetry only.

        P2-A: all declared arguments participate. JSON object key order is canonicalized
        recursively because it is not semantic; list order, values, types, and tool name
        remain identity-bearing. Program code must not collapse different roots/depths/options
        into one semantic "same target" identity.
        """
        return f"{tc.name}|{_canonical_json_dumps_args(tc.arguments)}"

    def _track_tool_observation(self, tc, sess, tool_trace: list[dict], result=None) -> None:
        """Record exact repeated calls and consecutive empty search receipts.

        P2-A: telemetry only. It never blocks a call, writes a model message, persists
        a cross-run deny state, or terminates the run.
        """
        bucket = self._host._run_state()
        state = bucket.stagnation_state
        if (
            tc.name == "convergence_decide"
            and result is not None
            and result.status is ToolResultStatus.SUCCESS
        ):
            # Legacy/manual compatibility only; factory no longer registers this tool.
            bucket.convergence_boundary_pending = False
            bucket.convergence_boundary_evidence = {}
            bucket.stagnation_state = {
                "fp": None,
                "count": 0,
                "reminded": False,
                "empty_count": 0,
                "empty_reminded": False,
            }
            self._host._record_action(
                "convergence.observation", "legacy_decision_seen", "prompt_chars=0"
            )
            return

        # A real direct tool call is itself evidence that the model has a concrete next
        # action.  Release the one-round observation latch without changing callability.
        if bucket.convergence_boundary_pending:
            bucket.convergence_boundary_pending = False
            bucket.convergence_boundary_evidence = {}
            self._host._record_action(
                "convergence.observation", "direct_tool_continued", f"tool={tc.name}; prompt_chars=0"
            )

        fp = self._stagnation_fingerprint(tc)
        # ① 精确完整调用指纹连续计数；不同参数就是不同事实。
        if state["fp"] == fp:
            state["count"] += 1
        else:
            state["fp"] = fp
            state["count"] = 1
            state["reminded"] = False

        if state["count"] >= _STAGNATION_REMIND_AT and not state["reminded"]:
            state["reminded"] = True
            self._host._record_action(
                "tool.repeat_observed",
                "observed",
                f"tool={tc.name}; exact_call_count={state['count']}; prompt_chars=0",
            )
        # ② 搜索类调用连续空结果计数；空结果只是一条回执事实，不代表目标不存在。
        if _is_search_like_call(tc) and _is_empty_search_result(result):
            state["empty_count"] = state.get("empty_count", 0) + 1
        else:
            state["empty_count"] = 0
            state["empty_reminded"] = False
        if state.get("empty_count", 0) >= _EMPTY_SEARCH_REMIND_AT and not state.get(
            "empty_reminded", False
        ):
            state["empty_reminded"] = True
            self._host._record_action(
                "tool.empty_search_observed",
                "observed",
                f"tool={tc.name}; consecutive_empty={state['empty_count']}; prompt_chars=0",
            )

    def _goal_frontier_counts(self, session_id: str) -> tuple[int | None, int | None]:
        """Return strict-session active-goal task totals, or unknown on any read failure."""
        corrections = getattr(self._host, "corrections", None)
        audit_dir = getattr(corrections, "audit_dir", None) if corrections is not None else None
        if not audit_dir:
            return None, None
        try:
            from llm_loop.introspection.goal import GoalStore
            from llm_loop.introspection.task_store import TaskStore

            goal = GoalStore(audit_dir).get(
                prefer_session_id=session_id,
                strict_session=True,
            )
            if not goal or str(goal.get("status") or "") != "active":
                return None, None
            goal_id = str(goal.get("id") or "")
            if not goal_id:
                return None, None
            frontier = TaskStore(audit_dir).compute_frontier(goal_id)
            return int(frontier.get("total", 0)), int(frontier.get("open_count", 0))
        except Exception:  # noqa: BLE001 — optional observability must fail open
            logger.debug("convergence goal-frontier probe failed", exc_info=True)
            return None, None

    def _maybe_arm_convergence_boundary(self, sess, rounds: int) -> None:
        """Record one ephemeral convergence observation from mechanical facts only.

        The latch is telemetry, not routing authority: it never changes the provider tool
        surface and never blocks a direct real-tool declaration.
        """
        bucket = self._host._run_state()
        if bucket.convergence_boundary_pending:
            return
        try:
            obligations = self._host.registry.async_obligations(sess.session_id)
        except Exception:  # noqa: BLE001 — unknown lifecycle state must not affect tools
            return
        state = bucket.stagnation_state or {}
        breakdown = bucket.last_breakdown or {}
        ratio = breakdown.get("ratio") if isinstance(breakdown, dict) else None
        try:
            ratio_value = float(ratio) if ratio is not None else None
        except (TypeError, ValueError):
            ratio_value = None
        total_tasks, open_tasks = self._goal_frontier_counts(sess.session_id)
        facts = ConvergenceFacts(
            rounds=int(rounds or 0),
            repeated_exact_call_count=int(state.get("count", 0) or 0),
            consecutive_empty_searches=int(state.get("empty_count", 0) or 0),
            context_ratio=ratio_value,
            goal_task_total=total_tasks,
            goal_open_tasks=open_tasks,
            outstanding_async_obligations=len(obligations or ()),
        )
        verdict = evaluate_convergence_boundary(facts)
        if not verdict.arm:
            return
        bucket.convergence_boundary_pending = True
        bucket.convergence_boundary_evidence = {
            "round": facts.rounds,
            "reasons": list(verdict.reasons),
            "repeat_count": facts.repeated_exact_call_count,
            "empty_search_count": facts.consecutive_empty_searches,
            "context_ratio": facts.context_ratio,
            "goal_task_total": facts.goal_task_total,
            "goal_open_tasks": facts.goal_open_tasks,
            "outstanding_async_obligations": facts.outstanding_async_obligations,
        }
        self._host._record_action(
            "convergence.observation",
            "observed",
            f"reasons={','.join(verdict.reasons)}; direct_tools_remain_callable=true; prompt_chars=0",
        )

    def _schema_to_param(self, t: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }

    def _resp_summary(self, resp: LLMResponse) -> str:
        if resp.tool_calls:
            # 决策侧（llm_decide 口径）记录精确调用指纹的有界摘要；
            # 摘要仅用于审计展示，不作为跨 run 身份键或阻断依据。
            # 消费点 engine.py llm_decide 事件 detail 自动变富，零改动
            parts = [
                f"{t.name}{{{fingerprint_summary(self._stagnation_fingerprint(t))}}}"
                for t in resp.tool_calls
            ]
            return "tool_calls=" + "; ".join(parts)
        return f"content={resp.content[:80] if resp.content else '(空)'}"

    def _record_tool_history(self, result: ToolResult) -> None:
        if self._host.status:
            self._host.status.record_tool_history(
                ToolHistoryItem(
                    name=result.tool_name,
                    arguments={},
                    status=result.status,
                    summary=result.content[:120],
                    duration_ms=result.duration_ms,
                )
            )


    def _record_current_provider_callable(self, schemas) -> None:
        """Record the exact current provider surface for schema-introspection truth."""
        try:
            self._host._run_state().current_provider_callable_tools = {
                str(row.get("name", ""))
                for row in (schemas or ())
                if isinstance(row, dict) and row.get("name")
            }
        except Exception:  # noqa: BLE001 — introspection fact cannot block the run
            logger.debug("current provider callable surface record failed", exc_info=True)


    def _project_tool_schemas_for_round(
        self,
        tool_schemas: list[dict],
        *,
        planned_label: str,
        user_text: str,
        session_messages: list[Any],
        advance_state_round: bool = True,
        logical_round: int | None = None,
    ) -> list[dict]:
        """Expose the stable registered surface minus mechanically unavailable tools.

        P1-B retires CORE/keyword/protocol/recovery selection, promotion TTL state, and
        capability-requirement selection/audit. ``planned_label``/``user_text``/
        ``session_messages`` remain in the compatibility signature but have zero authority
        over callability. ``advance_state_round`` is likewise retained for retry callers.
        """
        del planned_label, user_text, session_messages, advance_state_round
        from llm_loop.resources.task_budget_dispatch import active_task_budget
        from llm_loop.tools.eligibility import runtime_tool_health

        budget = active_task_budget()
        if budget is not None:
            snapshot = budget._get_validated()
            allowed = snapshot["grant"]["capabilities"]["allowed_tools"]
            if snapshot["grant"]["limits"]["tool_invocations"] == 0:
                tool_schemas = []
            elif allowed is not None:
                tool_schemas = [
                    schema for schema in tool_schemas
                    if any(name in allowed for name in tool_schema_names([schema]))
                ]
        registered = tool_schema_names(tool_schemas)
        # convergence_decide is retired from provider routing.  Even if an embedding or
        # compatibility registry supplies it, hide only that meta-tool and leave every
        # ordinary healthy tool directly callable.
        tool_schemas = [
            schema
            for schema in tool_schemas
            if str(schema.get("name", "") or "") != "convergence_decide"
        ]
        effective: list[dict] = []
        quarantined: list[str] = []
        for schema in tool_schemas:
            name = str(schema.get("name", "") or "")
            if name and not runtime_tool_health(name).available:
                quarantined.append(name)
                continue
            effective.append(schema)

        try:
            self._round_obs.begin_round(
                session_id=(
                    str(self._host._run_state_mgr.bound_session_id() or "")
                    if callable(getattr(getattr(self._host, "_run_state_mgr", None), "bound_session_id", None))
                    else ""
                ),
                round_no=int(logical_round or 0),
            )
            self._round_obs.record_projection(
                registered=registered,
                candidate=registered,
                final_callable=tool_schema_names(effective),
                quarantined=quarantined,
            )
        except Exception:  # noqa: BLE001 — reachability observability cannot block a run
            logger.debug("stable tool-surface observability failed (fail-open)", exc_info=True)

        self._last_tool_eligibility = {
            "mode": "stable_runtime_health",
            "applied": bool(quarantined),
            "original_count": len(tool_schemas),
            "visible_count": len(effective),
            "quarantined_names": list(quarantined),
        }
        self._record_current_provider_callable(effective)
        return effective
