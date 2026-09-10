"""Method Learning post-run integration service（组合，R9-P5-01：新逻辑不走继承）.

Keeps Method observability/reflection out of LoopEngine's core five-stage loop. All behavior is
post-run, fail-open, and non-authoritative: it cannot rewrite the user-visible final answer.
Engine wiring: LoopEngine 持有 MethodLearningService 实例（组合而非 Mixin 基类）。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from llm_loop.methods.learning_journal import learning_job_id

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MethodLearningService:
    """Post-run Method usage observation and optional self-distillation."""

    def __init__(self, engine: Any) -> None:
        # 组合：显式持有宿主 engine（不继承 LoopEngine，Mixin 列表只许退役）
        self._engine = engine

    def post_run(
        self,
        session_id: str,
        sess: Any,
        rounds: int,
        tool_trace: list[dict[str, Any]],
        run_end_reason: str,
        final_answer: str,
        model_used: str,
    ) -> None:
        self._observe_method_usage(
            session_id=session_id,
            tool_trace=tool_trace,
            run_end_reason=run_end_reason,
            rounds=rounds,
            model_used=model_used,
        )
        self._reflect_method_after_run(
            session_id=session_id,
            sess=sess,
            rounds=rounds,
            tool_trace=tool_trace,
            run_end_reason=run_end_reason,
            final_answer=final_answer,
            model_used=model_used,
        )

    def _observe_method_usage(
        self,
        *,
        session_id: str,
        tool_trace: list[dict[str, Any]],
        run_end_reason: str,
        rounds: int,
        model_used: str,
    ) -> None:
        """Record exact Method hydration without claiming semantic application."""
        try:
            loaded_refs: list[str] = []
            for row in tool_trace:
                if row.get("name") != "search_records":
                    continue
                raw_args = row.get("arguments")
                if not isinstance(raw_args, dict) or str(raw_args.get("kind", "")) != "method":
                    continue
                query = str(raw_args.get("query", "")).strip()
                if query.startswith("method:") and query not in loaded_refs:
                    loaded_refs.append(query)
            if not loaded_refs:
                return
            self._engine._event_append(
                session_id,
                "method.usage_observed",
                {
                    "method_refs": loaded_refs,
                    "application_proven": False,
                    "reason": run_end_reason,
                    "rounds": rounds,
                    "tool_calls": len(tool_trace),
                    "model_used": model_used,
                },
            )
        except Exception:  # noqa: BLE001 - observability never blocks the user result
            logger.debug("Method usage observation failed-open", exc_info=True)

    def _reflect_method_after_run(
        self,
        *,
        session_id: str,
        sess: Any,
        rounds: int,
        tool_trace: list[dict[str, Any]],
        run_end_reason: str,
        final_answer: str,
        model_used: str,
    ) -> None:
        """Enqueue-only: bind a Learning job to the exact completed episode.

        P0 invariant — this method never calls the model and never reads
        sess.messages. Input selection happens later, on the learning plane,
        against the episode's own material (episode:{sid}:{seq}:{digest}), so
        reflection of task C can no longer drag in the tail of tasks A/B.
        Fail-open: learning must never delay or break the user's final answer.
        """
        try:
            from llm_loop.methods.reflection import friction_facts, should_reflect

            mode = str(getattr(self._engine.settings, "method_reflection_mode", "off"))
            if mode == "off":
                return
            facts = friction_facts(rounds=rounds, tool_trace=tool_trace, run_end_reason=run_end_reason)
            triggered = should_reflect(
                facts=facts,
                min_rounds=getattr(self._engine.settings, "method_reflection_min_rounds", 6),
                min_tools=getattr(self._engine.settings, "method_reflection_min_tools", 6),
                min_failures=getattr(self._engine.settings, "method_reflection_min_failures", 2),
            )
            if not triggered:
                return
            journal = getattr(self._engine, "learning_journal", None)
            if journal is None:
                return
            episode = self._engine.episode_store.latest_episode(session_id)
            episode_ref = str(episode.get("ref")) if episode else ""
            if not episode_ref:
                # No durable episode for this turn: reflection has no lawful input.
                self._engine._event_append(
                    session_id, "method.reflection",
                    {"attempted": False, "triggered": True, "reason": "no_durable_episode", "model_used": model_used},
                )
                return
            job = journal.append(
                session_id=session_id,
                source_episode_ref=episode_ref,
                source_model=model_used or "",
                trigger_facts={**facts, "final_answer_chars": len(str(final_answer or ""))},
            )
            if job is None:
                # Episode already reached a terminal learning state: never re-learn.
                self._engine._event_append(
                    session_id,
                    "learning.enqueued",
                    {"learning_job_ref": f"learning:{learning_job_id(episode_ref)}", "source_episode_ref": episode_ref, "state": "skipped_terminal", "trigger_facts": facts},
                )
                return
            self._engine._event_append(
                session_id,
                "learning.enqueued",
                {
                    "learning_job_ref": f"learning:{job.job_id}",
                    "source_episode_ref": episode_ref,
                    "state": job.state,
                    "trigger_facts": facts,
                },
            )
        except Exception:  # noqa: BLE001 - Method learning is fail-open and non-authoritative
            logger.debug("Method reflection failed-open", exc_info=True)
