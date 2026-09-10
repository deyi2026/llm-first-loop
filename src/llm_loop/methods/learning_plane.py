"""Learning Plane: durable queue consumer running ReflectionRuns off the task plane.

Power boundaries (by design, not by convention):

- Task plane owns the user session; this module never touches it.
- Foreground always wins: any active run (in-process registry or cross-process
  ``*.run.lock``) makes learning yield (requeue, never busy-wait).
- A ReflectionRun has no user channel, no normal agent tools, no hidden CoT.
  The model only receives one hydrated episode snapshot and returns a closed
  JSON schema; the single write path is MethodStore.save_candidate with
  runtime-derived provenance (real episode ref + learning job ref).
- Fail-open: any error marks the job failed and leaves the user plane untouched.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from llm_loop.methods.learning_journal import LearningJob, LearningJournal
from llm_loop.methods.reflection import reflect_on_episode
from llm_loop.resources.contracts import (
    AdmissionOutcome,
    AdmissionRequest,
    ExecutionClass,
    ResourceKey,
    ResourceScopeKind,
    ServicePriority,
)
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.resources.provider_calls import ProviderCallCoordinator

logger = logging.getLogger(__name__)



class LearningPlane:
    """Background consumer of the durable learning queue.

    Started once per process by the factory; the thread is a daemon so it never
    blocks shutdown. All state transitions go through LearningJournal, which
    makes post-crash reconciliation exact: a job whose terminal event is
    missing is simply re-run; a job that already produced a candidate is
    terminal and never reflected again.
    """

    def __init__(
        self,
        *,
        journal: LearningJournal,
        episode_store: Any,
        method_store: Any,
        engine: Any,
        model_resolver: Callable[[str], Any],
        resource_governor: ResourceGovernor,
        resource_target_resolver: Callable[[str], tuple[str, str]],
        provider_call_coordinator: ProviderCallCoordinator | None = None,
        poll_interval_s: float = 5.0,
        quiet_period_s: float = 15.0,
    ) -> None:
        self._journal = journal
        self._episode_store = episode_store
        self._method_store = method_store
        self._engine = engine
        self._model_resolver = model_resolver
        self._resource_governor = resource_governor
        self._resource_target_resolver = resource_target_resolver
        self._provider_call_coordinator = provider_call_coordinator
        self._poll_interval_s = max(1.0, float(poll_interval_s))
        self._quiet_period_s = max(0.0, float(quiet_period_s))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---------- lifecycle ----------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="lfl-learning-plane", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout_s)

    # ---------- admission ----------

    def foreground_busy(self) -> bool:
        """Compatibility view of the Governor's mechanical foreground barrier."""
        return self._resource_governor.higher_priority_active(
            ServicePriority.P3_BACKGROUND_LEARNING
        )

    def _resource_request(self, job: LearningJob) -> AdmissionRequest:
        """Build the Learning lease request, sharing a qualified local runtime key.

        RG-2 first asks the provider-call coordinator for a live local runtime
        resource. If no such fact exists (cloud, unknown local runtime, probe
        failure), the RG-1 process-local Learning lane remains the exact fallback.
        """
        provider_id, model_id = self._resource_target_resolver(job.source_model)
        request_id = f"learning:{job.job_id}:attempt:{job.attempt + 1}"
        owner_ref = f"learning:{job.job_id}"
        coordinator = self._provider_call_coordinator
        if coordinator is not None:
            try:
                client = self._model_resolver(job.source_model)
                shared = coordinator.build_request_for_client(
                    client,
                    execution_class=ExecutionClass.BACKGROUND_LEARNING,
                    service_priority=ServicePriority.P3_BACKGROUND_LEARNING,
                    owner_ref=owner_ref,
                    provider_id=provider_id,
                    model_id=model_id,
                    request_id=request_id,
                )
            except Exception:  # noqa: BLE001 - preserve the RG-1 fallback lane
                shared = None
            if shared is not None:
                return shared

        key = ResourceKey(
            provider_id=provider_id,
            scope_kind=ResourceScopeKind.RUNTIME,
            scope_id=f"rg1-learning-process:{model_id}",
        )
        self._resource_governor.set_concurrency_limit(key, 1)
        return AdmissionRequest(
            request_id=request_id,
            owner_ref=owner_ref,
            execution_class=ExecutionClass.BACKGROUND_LEARNING,
            service_priority=ServicePriority.P3_BACKGROUND_LEARNING,
            provider_id=provider_id,
            model_id=model_id,
            resource_keys=(key,),
            submitted_at=time.time(),
        )

    def _quiet_elapsed(self, job: LearningJob) -> bool:
        try:
            created = float(job.created_at or 0)
        except (TypeError, ValueError):
            created = 0.0
        if created <= 0:
            return True
        return (time.time() - created) >= self._quiet_period_s

    # ---------- worker loop ----------

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                jobs = self._journal.runnable_jobs()
            except Exception:  # noqa: BLE001
                jobs = []
            if not jobs:
                self._stop.wait(self._poll_interval_s)
                continue
            progressed = False
            for job in jobs:
                if self._stop.is_set():
                    return
                try:
                    progressed = self._try_execute(job) or progressed
                except Exception:  # noqa: BLE001 - learning is fail-open
                    logger.warning("learning job %s crashed fail-open", job.job_id, exc_info=True)
                    try:
                        self._journal.mark_failed(job.job_id, "worker_exception")
                    except Exception:  # noqa: BLE001
                        logger.warning("learning job %s mark_failed failed", job.job_id, exc_info=True)
            if not progressed:
                self._stop.wait(self._poll_interval_s)

    def _try_execute(self, job: LearningJob) -> bool:
        if self.foreground_busy():
            return False  # foreground wins; leave queued, no busy-wait
        if not self._quiet_elapsed(job):
            return False
        try:
            request = self._resource_request(job)
        except Exception:  # noqa: BLE001 - unresolved target yields without consuming an attempt
            logger.warning("learning job %s resource target unavailable", job.job_id, exc_info=True)
            return False

        decision = self._resource_governor.try_acquire(request)
        if decision.outcome is not AdmissionOutcome.ADMITTED or decision.lease is None:
            return False
        lease = decision.lease
        try:
            try:
                self._journal.mark_admitted(job.job_id)
            except Exception:  # noqa: BLE001
                return False
            if self.foreground_busy():  # re-check between admission and start
                self._journal.mark_requeued(job.job_id, "foreground_arrived")
                return False
            self._journal.mark_started(job.job_id)
            if self.foreground_busy():  # last check before spending the model slot
                self._journal.mark_requeued(job.job_id, "foreground_arrived")
                return False
            entry = self._episode_store.get(job.session_id, job.source_episode_ref)
            if entry is None:
                self._journal.mark_failed(job.job_id, "episode_not_found")
                return True
            settings = getattr(self._engine, "settings", None)
            timeout_s = float(getattr(settings, "method_reflection_timeout_s", 120.0) or 120.0)
            client = self._model_resolver(job.source_model)
            final_answer = ""
            for row in reversed(entry.get("messages") or []):
                if str(row.get("role")) == "assistant":
                    final_answer = str(row.get("content") or "")
                    break
            outcome = reflect_on_episode(
                llm_client=client,
                store=self._method_store,
                episode_entry=entry,
                trigger_facts=dict(job.trigger_facts or {}),
                tool_trace=[],
                run_end_reason=str((job.trigger_facts or {}).get("run_end_reason", "")),
                final_answer=final_answer,
                timeout_s=timeout_s,
            )
            if outcome.candidate_payload is not None:  # reason == schema_ok
                try:
                    record = self._method_store.save_candidate(
                        name=str(outcome.candidate_payload.get("name", "")),
                        description=str(outcome.candidate_payload.get("description", "")),
                        body=str(outcome.candidate_payload.get("body", "")),
                        source_model=job.source_model,
                        source_episode_refs=[job.source_episode_ref],
                        evidence_refs=[f"learning:{job.job_id}"],
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "learning job %s candidate save failed", job.job_id, exc_info=True
                    )
                    self._journal.mark_failed(job.job_id, "candidate_save_failed")
                    return True
                self._journal.mark_saved(job.job_id, record.method_ref)
                return True
            if not outcome.attempted:
                # structural: disabled / core method missing / empty material — terminal "none"
                self._journal.mark_none(job.job_id, outcome.reason or "not_attempted")
                return True
            if outcome.reason == "reflection_call_failed":
                self._journal.mark_failed(job.job_id, outcome.reason)
                return True
            # model returned decision=none, non-JSON, or schema-invalid payload
            self._journal.mark_none(job.job_id, outcome.reason[:200] or "no_candidate")
            return True
        finally:
            self._resource_governor.release(lease)
