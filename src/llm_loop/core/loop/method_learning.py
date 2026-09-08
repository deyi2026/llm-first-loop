"""Method Learning post-run integration mixin.

Keeps Method observability/reflection out of LoopEngine's core five-stage loop. All behavior is
post-run, fail-open, and non-authoritative: it cannot rewrite the user-visible final answer.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from llm_loop.methods.reflection import reflect_after_run

if TYPE_CHECKING:
    from llm_loop.config import Settings
    from llm_loop.llm.client import LLMClient
    from llm_loop.llm.pool import ModelClientPool

logger = logging.getLogger(__name__)


class _MethodLearningMixin:
    """Post-run Method usage observation and optional self-distillation."""

    if TYPE_CHECKING:
        llm: LLMClient
        llm_pool: ModelClientPool | None
        settings: Settings

        def _event_append(
            self, session_id: str, event_type: str, payload: dict[str, Any]
        ) -> None: ...

    def _post_run_method_learning(
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
            self._event_append(
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
        """Run isolated post-task reflection when explicitly enabled."""
        try:
            corrections = getattr(self, "corrections", None)
            method_store = getattr(corrections, "method_store", None) if corrections is not None else None
            method_client = self.llm
            if self.llm_pool is not None and model_used and "/" in model_used:
                try:
                    method_client = self.llm_pool.get_client(model_used)
                except Exception:  # noqa: BLE001 - preserve original run result
                    logger.debug("Method reflection model resolve failed; fallback current client", exc_info=True)
            outcome = reflect_after_run(
                mode=getattr(self.settings, "method_reflection_mode", "off"),
                llm_client=method_client,
                store=method_store,
                session_id=session_id,
                messages=sess.messages,
                rounds=rounds,
                tool_trace=tool_trace,
                run_end_reason=run_end_reason,
                final_answer=final_answer,
                source_model=model_used or getattr(method_client, "model", ""),
                min_rounds=getattr(self.settings, "method_reflection_min_rounds", 6),
                min_tools=getattr(self.settings, "method_reflection_min_tools", 6),
                min_failures=getattr(self.settings, "method_reflection_min_failures", 2),
                timeout_s=getattr(self.settings, "method_reflection_timeout_s", 120.0),
            )
            self._event_append(
                session_id,
                "method.reflection",
                {
                    "attempted": outcome.attempted,
                    "triggered": outcome.triggered,
                    "saved_ref": outcome.saved_ref,
                    "teacher_fallback": outcome.used_teacher_fallback,
                    "reason": outcome.reason,
                    "model_used": model_used,
                },
            )
        except Exception:  # noqa: BLE001 - Method learning is fail-open and non-authoritative
            logger.debug("Method reflection failed-open", exc_info=True)
