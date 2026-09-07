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
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from llm_loop.core.loop.engine_services.tool_reachability import (
    RoundReachabilityRecorder,
    tool_schema_names,
)
from llm_loop.core.loop.tool_exec import (
    _EMPTY_SEARCH_REMIND_AT,
    _STAGNATION_REMIND_AT,
    _is_empty_search_result,
    _is_search_like_call,
    _json_dumps_args,
    _tool_args_summary,
    fingerprint_summary,
)
from llm_loop.core.message import (
    Message,
    MessageSource,
    ToolResult,
    ToolResultStatus,
)
from llm_loop.introspection.status import ToolHistoryItem
from llm_loop.llm.client import LLMResponse, StreamDelta, ToolRoundInfo
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
    ) -> None:
        """Bind the staged projection to one real provider request (fail-open)."""
        try:
            self._round_obs.ensure_attempt(
                kind=kind,
                attempt_index=attempt_index,
                model=model,
                provider=provider,
            )
        except Exception:  # noqa: BLE001 -- observability cannot block the run
            logger.debug("reachability attempt bind failed (fail-open)", exc_info=True)

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
            tool_msg = tool_result_to_message(
                result,
                failure_guidance_enabled=self._host.registry.failure_guidance_enabled,
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

        if not executable_calls:
            results = []
        else:
            from llm_loop.core.run_context import current_workspace_root

            effect_journal = self._host._tool_execution_journal()
            with effect_journal.effect_bindings(
                session_id=sess.session_id,
                execution_ids=execution_ids,
                round_no=rounds,
                calls=executable_calls,
                workspace_root=current_workspace_root.get(),
            ):
                try:
                    results = self._host.registry.execute_many(
                        executable_calls, on_result=persist_finished
                    )
                except TypeError as exc:
                    # Legacy duck-typed registries may reject the new kwarg before entering
                    # their method body; retrying that specific signature mismatch is safe.
                    if "on_result" not in str(exc):
                        raise
                    results = self._host.registry.execute_many(executable_calls)
                    for call, result in zip(executable_calls, results, strict=False):
                        persist_finished(call, result)
        by_id = {r.tool_call_id: r for r in results if r.tool_call_id}
        ordered = [
            pre_results.get(call.id) or by_id.get(call.id)
            for call in allowed_calls
        ]
        return [r for r in ordered if r is not None], wal_messages, wal_result_sha

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
        _execution_ids = (
            self._declare_tool_execution_wal(sess, _declared_calls, rounds)
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
                # P2-A Rule-first: every valid declaration reaches the normal execution/WAL
                # path. Repetition is observed after receipt; it is never a pre-execution gate.
                results, _wal_messages, _wal_result_sha = self._execute_allowed_with_wal(
                    sess, valid_calls, _execution_ids, rounds
                )
                # 对账不变量: 声明数 == 结果数（缺失 → 合成取消，防孤儿声明落盘）
                if len(results) != len(valid_calls):
                    executed_ids = {r.tool_call_id for r in results if r.tool_call_id}
                    missing = [tc for tc in valid_calls if tc.id not in executed_ids]
                    if missing:
                        self._synthesize_cancelled(
                            sess, missing, executed_ids=set(), round_index=rounds)
                        logger.warning(
                            "工具对账不变量缺失: 声明 %d 结果 %d（%d 条合成取消）",
                            len(valid_calls),
                            len(results),
                            len(missing),
                        )
                for tc, result in zip(valid_calls, results, strict=False):
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
                # EVO-20260903-ba25857b Phase 0: executed receipt facts + flush.
                try:
                    self._round_obs.record_executed(
                        [
                            {
                                "tool_call_id": r.tool_call_id,
                                "name": r.tool_name,
                                "status": getattr(getattr(r, "status", None), "value", ""),
                                "blocked": False,
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
        """Attach G6-v2 hard-boundary facts to their original visible producer.

        No dynamic prompt slot is created. The session's tool content stays unchanged;
        history projection renders these structured facts only for the current human turn.
        """
        try:
            from llm_loop.tools.eligibility import runtime_tool_health
            names = tuple(
                dict.fromkeys(
                    str(n)
                    for n in (getattr(result, "capability_requirements", ()) or ())
                    if str(n)
                )
            )
            if not names:
                return
            facts: list[dict[str, Any]] = []
            for name in names:
                health = runtime_tool_health(name)
                if health.available:
                    continue
                facts.append(
                    {
                        "tool_name": name,
                        "reason_code": str(health.reason_code or "runtime_unhealthy"),
                        "replacement": [str(x) for x in (health.preferred_next or ()) if str(x)],
                    }
                )
            if not facts:
                return
            metadata = tool_msg.metadata if isinstance(tool_msg.metadata, dict) else {}
            metadata["capability_unavailable"] = facts
            metadata["capability_boundary_turn_ref"] = self._host._run_state().current_turn_ref
            tool_msg.metadata = metadata
        except Exception:  # noqa: BLE001 — boundary facts must never block tool receipt
            logger.debug("capability boundary metadata attach failed (fail-open)", exc_info=True)

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
            tool_msg = tool_result_to_message(
                result, failure_guidance_enabled=self._host.registry.failure_guidance_enabled
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
                "tool_result_blocked"
                if result.status is ToolResultStatus.BLOCKED
                else "unauthorized"
                if result.status is ToolResultStatus.UNAUTHORIZED
                else None
            ),
        )

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

        P2-A: all declared arguments participate. Program code must not collapse
        different roots/depths/options into one semantic "same target" identity.
        """
        return f"{tc.name}|{_json_dumps_args(tc.arguments)}"

    def _track_tool_observation(self, tc, sess, tool_trace: list[dict], result=None) -> None:
        """Record exact repeated calls and consecutive empty search receipts.

        P2-A: telemetry only. It never blocks a call, writes a model message, persists
        a cross-run deny state, or terminates the run.
        """
        fp = self._stagnation_fingerprint(tc)
        state = self._host._run_state().stagnation_state
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
        from llm_loop.tools.eligibility import runtime_tool_health

        registered = tool_schema_names(tool_schemas)
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
