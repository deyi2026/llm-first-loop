"""RunFinalizer——run 收尾段：记忆沉淀/持久化/UI 事件/audit/LoopResult 组装（R9 Phase 5 T6-A）.

B5-W4-01 迁入：engine._run_stream_inner 尾段 210 行装配为 finalize 门面 +
两个步骤方法（core 红线 200 约束下的内部职责切分，组内语句逐字平移、
组间数据流显式参数化）：

- persist_and_settle(...) -> tuple[str, str]：编排门面——_persist_turn（记忆沉淀 → origin 判定 →
  program.final audit → 助手消息持久化（PROGRAM_FINAL 占位协议）→ episode
  index → session persist（recovery note））→ _settle_run_end（缓存健康 →
  事件滚动/done 通知 → memory_stats 落盘 → run.end KPI 事件 → 长回答落盘）；
  回传 (final_answer, _run_end_reason)。LoopResult 组装留在 engine 委托块——
  本模块不持 engine 运行时回边（沿 engine<->build 断环先例，保持 runtime 环
  空态锚定）
- _persist_turn(...) -> tuple[str, str]：持久化半程；回传
  (final_answer, _run_end_reason)——session_save_failed 路径的段内再赋值
- _settle_run_end(...) -> str：事件与统计半程；回传 final_answer——
  cache_health/_persist_long_answer 的段内再赋值

语句逐字平移，``self.`` → ``self._host.``（宿主 = LoopEngine；AST 反替
自证逐语句 dump 全等）。行为零变化。规划签名 finalize(run_state) 让位现实
（17 平铺局部无拆装成本，kwargs 保原名）——RunState 对象化（W4-03）后统一
收窄签名（挂账复核）。

LoopResult 运行时延迟 import（engine→本模块顶部反向 import 会循环；run 时
engine 已加载完毕，sys.modules 缓存命中零开销）。

宿主依赖（engine 持有）：_remember / extractor / _event_append /
_append_message_event / episode_store / _session_payload / session /
_session_lifecycle / _record_program_fault / _termination / memory /
_memory_payload / _kpi_snapshot / _post_run_cache_health /
_check_event_rotate / _notify_action / _phase / _persist_long_answer /
_run_state().current_turn_ref（per-session 桶）
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (host 属性来自 LoopEngine 混入体系，pyright 无法静态解析，文件级关闭这两条；
#   沿 recovery_controller.py 既有豁免口径)

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING, Any

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_eligibility import PROGRAM_FINAL_PROTOCOL_BOUNDARY

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)


class RunFinalizer:
    """run 收尾职责面（memory/persistence/UI event/audit → LoopResult）."""

    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _index_truncated_run(
        self, *, session_id: str, run_end_reason: str, rounds: int, run_end_seq: int
    ) -> None:
        """B2(EVO-20260902-41898b20): 非 completed 终态 → truncated.jsonl 一行.

        数据源 = host._last_interrupted（B1 cancelled/llm_error 时写入；其余程序
        终态无半截产物，尾段如实置空）。幂等键 (session_id, run_end_seq)；
        存储未注入时静默跳过（无索引面即无义务）。
        """
        store = getattr(self._host, "episode_store", None)
        if store is None:
            return
        info = getattr(self._host, "_last_interrupted", None) or {}
        created = store.index_truncated_run(
            session_id,
            run_end_reason=run_end_reason,
            error_digest=str(info.get("error_digest") or ""),
            last_round=int(info.get("round") or rounds or 0),
            run_end_seq=run_end_seq,
            text_tail=str(info.get("text_tail") or ""),
            reasoning_tail=str(info.get("reasoning_tail") or ""),
            partial_chars=int(info.get("partial_chars") or 0),
            partial_sha256=str(info.get("partial_sha256") or ""),
            artifact_ref=str(info.get("artifact_ref") or ""),
        )
        if created:
            logger.info(
                "truncated episode 已索引: sid=%s reason=%s run_end_seq=%s",
                session_id,
                run_end_reason,
                run_end_seq,
            )

    def persist_and_settle(
        self,
        *,
        sess: Any,
        session_id: str,
        final_answer: str,
        _run_end_reason: str,
        _cancel_reason: str,
        resp: Any | None,
        rounds: int,
        tool_trace: list[dict],
        tokens_in: int,
        tokens_out: int,
        tokens_cache_hit: int,
        llm_ms_total: float,
        ttft_first_ms: float | None,
        model_used: str,
        truncation_noted: bool,
        verification_note: str | None,
        _run_started_at: float,
    ) -> tuple[str, str]:
        final_answer, _run_end_reason = self._persist_turn(
            sess=sess,
            session_id=session_id,
            final_answer=final_answer,
            _run_end_reason=_run_end_reason,
            resp=resp,
            rounds=rounds,
            model_used=model_used,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cache_hit=tokens_cache_hit,
            llm_ms_total=llm_ms_total,
            ttft_first_ms=ttft_first_ms,
        )
        final_answer = self._settle_run_end(
            sess=sess,
            session_id=session_id,
            final_answer=final_answer,
            _run_end_reason=_run_end_reason,
            _cancel_reason=_cancel_reason,
            rounds=rounds,
            model_used=model_used,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cache_hit=tokens_cache_hit,
            truncation_noted=truncation_noted,
            provider_truncated=bool(resp is not None and resp.truncated),
            _run_started_at=_run_started_at,
        )
        return final_answer, _run_end_reason

    def _persist_turn(
        self,
        *,
        sess: Any,
        session_id: str,
        final_answer: str,
        _run_end_reason: str,
        resp: Any | None,
        rounds: int,
        model_used: str,
        tokens_in: int,
        tokens_out: int,
        tokens_cache_hit: int,
        llm_ms_total: float,
        ttft_first_ms: float | None,
    ) -> tuple[str, str]:

        # ── 记住：沉淀记忆（不阻塞回答输出，FR-LOOP-03）──
        self._host._phase("remember")
        self._host._remember(final_answer, session_id, sess)
        # T33: 独立记忆提取定期触发（异步，不阻塞回答输出 DFX-PERF-04）
        if self._host.extractor is not None:
            try:
                self._host.extractor.maybe_trigger(session_id)
            except Exception:
                logger.warning("独立提取触发失败（fail-open）", exc_info=True)

        # P0-B1（2026-08-28 批准）: 程序反馈语义分离——错误/熔断/守卫/耗尽类文本
        # source=SYSTEM（非模型产出的如实标注；防下轮模型误读"assistant 已回答过"，
        # 并作为 extractor 过滤/投影标记的判定依据）。正常回答保持 USER 不变
        # （M51/M52 token 统计依赖零破坏）。
        from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES

        # GPT 审计批次2: answer_origin 单一真相源——run_end_reason 显式信号优先，
        # prefix 仅 legacy 兜底（老消息无 metadata/未覆盖出口）
        _answer_origin = "model" if _run_end_reason == "completed" else "program"
        _pf_source = (
            MessageSource.SYSTEM
            if _answer_origin == "program"
            or final_answer.startswith(PROGRAM_FEEDBACK_PREFIXES)
            else MessageSource.USER
        )
        _episode_resolution_candidate = bool(
            _answer_origin == "model"
            and _run_end_reason == "completed"
            and final_answer.strip()
            and resp is not None
            and not resp.truncated
        )
        _origin_metadata = {
            "answer_origin": _answer_origin,
            "run_end_reason": _run_end_reason,
            # R8.5: this dedicated bit is stronger than run_end_reason=completed.
            # Provider-truncated/empty/program answers never become automatically
            # retireable, and legacy messages lacking the bit remain fail-open.
            "episode_resolution_candidate": _episode_resolution_candidate,
        }
        # A provider token-limit stop is a real model partial, not a completed answer.
        # Preserve the exact model bytes in the normal assistant row, but mark the row
        # as unfinished so the next human ingress can rebuild one-shot continuity from
        # durable storage. This is runtime truth only; no continuation instruction is
        # persisted into conversational history.
        if _answer_origin == "model" and resp is not None and resp.truncated:
            _reasoning_full = str(getattr(resp, "reasoning_content", "") or "")
            _partial_sha = hashlib.sha256(
                (str(final_answer or "") + _reasoning_full).encode("utf-8", "replace")
            ).hexdigest()
            _artifact_ref = ""
            try:
                _artifact_ref = self._host._capture_truncation_artifact(
                    session_id,
                    reason="provider_truncated",
                    round_no=rounds,
                    provider=str(getattr(resp, "provider", "") or ""),
                    model=model_used,
                    text_full=str(final_answer or ""),
                    reasoning_full=_reasoning_full,
                    partial_sha256=_partial_sha,
                    provider_replay=(
                        resp.provider_replay if isinstance(resp.provider_replay, dict) else None
                    ),
                    tool_call_drafts=None,
                )
            except Exception:  # noqa: BLE001 — full assistant row remains durable fallback
                logger.warning(
                    "provider truncation exact artifact 写入失败；保留会话全文",
                    exc_info=True,
                )
            _origin_metadata = {
                **_origin_metadata,
                "llm_interrupted": True,
                "provider_truncated": True,
                "provider_finish_reason": str(getattr(resp, "finish_reason", "") or ""),
                "interrupted_provider": str(getattr(resp, "provider", "") or ""),
                "interrupted_model": model_used,
                "partial_sha256": _partial_sha,
                "truncation_artifact_ref": _artifact_ref,
            }
            self._host._last_interrupted = {
                "round": int(rounds or 0),
                "reason": "provider_truncated",
                "error_digest": "",
                "text_tail": str(final_answer or ""),
                "reasoning_tail": _reasoning_full,
                "partial_chars": len(str(final_answer or "")) + len(_reasoning_full),
                "partial_sha256": _partial_sha,
                "artifact_ref": _artifact_ref,
            }
        # R8.24-B B-3.2/B-D7（E19）: 程序终态全文不再进入 sess.messages——存储面
        # 只保留 role-shape 协议占位（B-D11 PROTOCOL_ONLY：与 build 链
        # PROGRAM_FINAL 替换同源常量，字节稳定），全文经 LoopResult（UI）与
        # program.final 事件（audit）交付；下轮模型可见面零程序通知正文。
        _program_final = _answer_origin == "program" and bool(final_answer)
        if _program_final:
            _origin_metadata = {
                **_origin_metadata,
                "program_final_placeholder": True,
            }
            try:
                self._host._event_append(
                    session_id,
                    "program.final",
                    {
                        "session_id": session_id,
                        "reason": _run_end_reason,
                        "answer_origin": "program",
                        "full_text": final_answer,
                    },
                )
            except Exception:  # noqa: BLE001 — audit 交付失败 fail-open（UI 轨不受影响）
                logger.debug("program.final 事件写入失败（fail-open）")
        _persist_content = (
            PROGRAM_FINAL_PROTOCOL_BOUNDARY if _program_final else final_answer
        )
        if resp is not None and resp.provider_replay and _answer_origin == "model":
            _origin_metadata = {
                **_origin_metadata,
                "provider_replay": resp.provider_replay,
            }
        sess.messages.append(
            Message(
                role="assistant",
                content=_persist_content,
                source=_pf_source,
                metadata=_origin_metadata,
                # M51/M52: 模型 + 本轮 run token 消耗持久化（web/feishu 页脚数据源）
                model_used=model_used,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_cache_hit=tokens_cache_hit,
                llm_ms=llm_ms_total,
                ttft_ms=ttft_first_ms or 0.0,
            )
            if final_answer
            else Message(
                role="assistant",
                content="",
                source=_pf_source,
                metadata={**_origin_metadata, "empty_output": True},
            )
        )
        # M20 THK-04: 最终回答轮 assistant 消息也回传思考链（官方"后续所有请求"语义，防下一轮 400）
        # GPT 审计批次2 双保险: 程序反馈（answer_origin != model）不携带任何 reasoning
        if final_answer and resp is not None and resp.reasoning_content and _answer_origin == "model":
            last = sess.messages[-1]
            last.reasoning_content = resp.reasoning_content
        # D1: 最终回答消息事件（fail-open）
        self._host._append_message_event(sess, sess.messages[-1])
        # R8.5: durable index first, retirement metadata second.  If the index
        # write fails, no resolved_episode_ref is attached and future provider
        # views keep the episode visible (fail-open, information-preserving).
        try:
            from llm_loop.core.episode_history import index_current_completed_episode

            index_current_completed_episode(
                self._host.episode_store,
                sess,
                turn_ref=self._host._run_state().current_turn_ref,
                final_answer_index=len(sess.messages) - 1,
            )
        except Exception:  # noqa: BLE001 — indexing failure must not corrupt delivery
            logger.warning("resolved episode 当前轮索引失败（fail-open，不退休）", exc_info=True)
        # R8.8: round-exhaustion lifecycle is consumed by producer identity before
        # persistence.  The previous post-save marker was lost on reload even when
        # classification was correct, allowing the decision prompt to resurrect.
        try:
            for m in sess.messages:
                if m.role != "system":
                    continue
                md = dict(m.metadata or {})
                if md.get("injection_kind") == "round_exhaustion_decision" and not md.get("consumed"):
                    md["consumed"] = True
                    m.metadata = md
        except Exception:  # noqa: BLE001 — consumption audit must not block delivery
            logger.warning("耗尽消息消费标记异常（fail-open）", exc_info=True)
        # T39: 会话保存异常 → 如实标注 + 不抛穿（程序故障不影响 AI 发挥）
        try:
            self._host.session.save(sess)
        except Exception as exc:  # noqa: BLE001
            logger.warning("会话保存失败（fail-open）: %s", exc)
            self._host._record_program_fault("session_persist")
            recovery_note = self._host._session_lifecycle._persist_with_recovery_note(
                target_type="session",
                source_id=sess.session_id,
                write_fn=lambda: self._host.session.save(sess),
                payload=self._host._session_payload(sess),
                trigger_point="loop_end_save",
            )
            extra = f" {recovery_note}" if recovery_note else ""
            _run_end_reason = "session_save_failed"
            final_answer = (
                f"{final_answer}\n\n[程序异常] 会话保存失败（{type(exc).__name__}: {exc}）。"
                f"本次回答仍有效，但历史可能未持久化。{extra}"
            )

        return final_answer, _run_end_reason

    def _settle_run_end(
        self,
        *,
        sess: Any,
        session_id: str,
        final_answer: str,
        _run_end_reason: str,
        _cancel_reason: str,
        rounds: int,
        model_used: str,
        tokens_in: int,
        tokens_out: int,
        tokens_cache_hit: int,
        truncation_noted: bool,
        provider_truncated: bool,
        _run_started_at: float,
    ) -> str:
        self._host._phase("done")
        # EVO-20260817-72fcd94a L3: 缓存健康闭环（fail-open；实现在 _BuildMixin）
        final_answer = self._host._post_run_cache_health(
            final_answer, sess, tokens_in, tokens_cache_hit, model_used
        )
        # P1-1(2026-08-15): run 末事件日志滚动检查钩子（大小/天数触发；fail-open 不阻断）
        self._host._check_event_rotate(session_id)
        # H-UI: 循环结束（状态条可收尾）
        self._host._notify_action("done")

        # P0-1: 记忆访问统计（decay_score/access_count/last_access_at）落盘——
        # search() 仅更新内存，此处每轮 run 完成批量持久化（低频，避免每轮检索全量写盘）
        try:
            if self._host.memory is not None:
                self._host.memory.flush()
        except Exception as exc:  # noqa: BLE001 — 统计落盘失败不阻断 run
            logger.warning("记忆统计落盘失败（fail-open）: %s", exc)
            recovery_note = self._host._session_lifecycle._persist_with_recovery_note(
                target_type="memory_stats",
                source_id="memory",
                write_fn=lambda: self._host.memory.flush() if self._host.memory is not None else None,
                payload=self._host._memory_payload(),
                trigger_point="memory_flush",
            )
            if recovery_note:
                logger.warning("记忆统计恢复通道: %s", recovery_note)

        # DSH 借鉴(2026-08-17): run 生命周期结束事件（对齐 DSH turn/end reason）——
        # 统一出口落盘，结束原因/轮数/token 汇总/耗时一次可查（fail-open 不阻断）
        _run_end_event = None
        try:
            _run_end_event = self._host._event_append(
                session_id,
                "run.end",
                {
                    "session_id": session_id,
                    "reason": _run_end_reason,
                    "cancel_reason": _cancel_reason,
                    "rounds": rounds,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cache_hit": tokens_cache_hit,
                    "duration_ms": int((time.monotonic() - _run_started_at) * 1000),
                    "model_used": model_used,
                    "truncated": truncation_noted,
                    "answer_preview": (final_answer or "")[:200],
                    **self._host._kpi_snapshot(),
                },
            )
        except Exception:  # noqa: BLE001 — run.end 失败 fail-open（不影响返回）
            logger.debug("run.end 事件写入失败（fail-open）")

        if _run_end_reason == "completed":
            try:
                self._host._clear_inflight_native_state(session_id)
            except Exception:  # noqa: BLE001 — stale sidecar cleanup must not affect answer
                logger.debug("in-flight native state 清理失败（fail-open）", exc_info=True)

        # B2(EVO-20260902-41898b20): 一切非 completed 终态（cancelled/llm_error/
        # overflow/guard_blocked/legacy_stagnation/breaker_context_pressure/…）→ truncated
        # 索引行（独立文件、非退休型、幂等键=(session_id, run_end 事件 seq)），
        # 修复"中断 run 在 episode 检索面结构性不可见"。completed 不写；fail-open
        # 不阻断收尾（存档见 run.end 事件）。
        if _run_end_reason != "completed" or provider_truncated:
            try:
                _index_reason = (
                    "provider_truncated"
                    if _run_end_reason == "completed" and provider_truncated
                    else _run_end_reason
                )
                self._index_truncated_run(
                    session_id=session_id,
                    run_end_reason=_index_reason,
                    rounds=rounds,
                    run_end_seq=int(getattr(_run_end_event, "seq", 0) or 0),
                )
            except Exception:  # noqa: BLE001 — 索引失败不阻断 run 返回
                logger.warning("truncated episode 索引失败（fail-open，不阻断收尾）", exc_info=True)

        # EVO-20260820-5bf342ae ②: 长回答落盘（实现抽 events.py _persist_long_answer,
        # 防 engine 膨胀守卫 1136——2026-08-21 内联版触顶后抽取）
        final_answer = self._host._persist_long_answer(session_id, final_answer or "")
        return final_answer
