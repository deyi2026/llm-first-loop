"""Explicit, one-shot, budget-bound LFL M1 FX05 qualification runner.

Not a production entrypoint. Each invocation creates a *new* session/root and
uses existing TaskBudgetExecution provider/tool dispatch reservations. It never
reactivates a historical grant. No Web switch, global env override or second
budget store implementation is installed.

The pre-send context-byte bound is a conservative additional upper bound,
not an assertion that LFL knows the provider's proprietary tokenizer.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from llm_loop.core.run_context import (
    current_reasoning_effort,
    current_reasoning_mode,
    current_run_generation,
    current_tool_discovery_scope,
    current_write_scope,
)
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.core.write_scope import WriteScope
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    BudgetPhase,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import (
    TaskBudgetExecution,
    active_task_budget,
    bind_task_budget,
    exact_workspace_scope,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore
from llm_loop.resources.task_budget_transport_context import (
    IsolatedTransportProfile,
    bind_authorized_provider_proxy,
    bind_isolated_provider_transport,
    qualify_loopback_provider_proxy,
)

MODEL = "glm/glm-5.3"
PROFILE = "m1-t1-fx05-bounded-cli-v2"
# 3 attempted sends * (2*55k input-byte projection + 8k overhead +
# 6k max output) <= 372k conservative token-equivalent units.
ATTEMPTS = 3
MAX_JSON_BYTES = 55_000
MAX_OUTPUT_TOKENS = 6_000
MODEL_TOTAL_TOKEN_CEILING = 400_000
MAX_TOOLS = 8
MAX_RUNTIME_SECONDS = 1800
TARGET_PATH = "t1-sandbox/outputs/fx05-draft.md"
_PRE_SEND_ENVELOPE: ContextVar[tuple[int, int, int] | None] = ContextVar(
    "m1_fx05_exact_pre_send_envelope", default=None
)


class FX05BudgetExecution(TaskBudgetExecution):
    """Reuse the production CAS/dispatch gate with conservative pre-send charge.

    Physical attempts reserve a worst-case proxy before a single HTTP byte
    can leave. Usage unknown is still an unknown obligation, not refunded.
    """

    def reserve(self, kind: BudgetDimension, *, tool_id: str = "") -> str:
        if kind != BudgetDimension.PHYSICAL_ATTEMPTS:
            return super().reserve(kind, tool_id=tool_id)
        self._get_validated()
        envelope = _PRE_SEND_ENVELOPE.get()
        if envelope is None:
            raise TaskBudgetDeniedError("m1_physical_send_without_bound_envelope")
        input_limit, output_limit, payload_bytes = envelope
        reservation_id = "dispatch-" + uuid.uuid4().hex
        self._cas_mutate(
            "reserve",
            member=self.member,
            reservation_id=reservation_id,
            kind=kind,
            measures={
                BudgetDimension.INPUT_TOKENS: input_limit,
                BudgetDimension.OUTPUT_TOKENS: output_limit,
                BudgetDimension.PAYLOAD_BYTES: payload_bytes,
            },
        )
        self._cas_mutate("mark_dispatched", reservation_id=reservation_id)
        return reservation_id


def _install_fail_closed_transport_guard() -> dict[str, int]:
    """No physical provider send without one explicit active M1 root."""
    from llm_loop.llm.client import LLMClient

    origin = LLMClient._transport_attempt_scope
    observe = LLMClient._observe_transport_usage
    counters = {"attempts": 0, "usage_reports": 0, "tokens_in": 0, "tokens_out": 0}
    current: dict[str, int | None] = {"in": None, "out": None}

    def on_usage(self: LLMClient, usage: dict[str, Any], *, model_id: str) -> None:
        if active_task_budget() is None:
            raise TaskBudgetDeniedError("m1_unbound_provider_usage")
        value_in = usage.get("prompt_tokens")
        value_out = usage.get("completion_tokens")
        if type(value_in) is int and value_in >= 0:
            current["in"] = value_in
        if type(value_out) is int and value_out >= 0:
            current["out"] = value_out
        return observe(self, usage, model_id=model_id)

    @contextmanager
    def bounded(
        self: LLMClient,
        *,
        model_id: str,
        target_url: str = "",
        transport_retry_index: int = 0,
        prepared: Mapping[str, Any] | None = None,
    ):
        budget = active_task_budget()
        if budget is None or budget.store.read(budget.budget_id)["grant"]["profile"] != PROFILE:
            raise TaskBudgetDeniedError("m1_explicit_budget_binding_required")
        if not isinstance(budget, FX05BudgetExecution):
            raise TaskBudgetDeniedError("m1_uninstrumented_budget_execution")
        if counters["attempts"] != counters["usage_reports"]:
            raise TaskBudgetDeniedError("m1_previous_provider_usage_unknown")
        endpoint = urlsplit(target_url)
        if (
            self.provider != "glm" or model_id != "glm-5.3"
            or endpoint.scheme != "https" or endpoint.hostname != "open.bigmodel.cn"
            or endpoint.username is not None or endpoint.password is not None
            or endpoint.query or endpoint.fragment or not endpoint.path.startswith("/api/")
        ):
            raise TaskBudgetDeniedError("m1_provider_endpoint_unqualified")
        size = prepared.get("projected_bytes") if isinstance(prepared, dict) else None
        controls = prepared.get("controls") if isinstance(prepared, dict) else None
        output_limit = controls.get("max_tokens") if isinstance(controls, dict) else None
        if (
            type(size) is not int or size <= 0 or size > MAX_JSON_BYTES
            or type(output_limit) is not int
            or output_limit <= 0 or output_limit > MAX_OUTPUT_TOKENS
        ):
            raise TaskBudgetDeniedError("m1_payload_or_output_bound_unqualified")
        current["in"], current["out"] = None, None
        # This is a deliberately over-conservative token-equivalent *proxy*.
        # Exact GLM token accounting remains the provider's observed usage.
        token = _PRE_SEND_ENVELOPE.set((2 * size + 8_000, output_limit, size))
        try:
            with origin(
                self,
                model_id=model_id,
                target_url=target_url,
                transport_retry_index=transport_retry_index,
                prepared=prepared,
            ):
                counters["attempts"] += 1
                yield
            if current["in"] is None or current["out"] is None:
                raise TaskBudgetDeniedError("m1_provider_usage_missing")
            counters["usage_reports"] += 1
            if int(current["in"]) > 2 * size + 8_000 or int(current["out"]) > output_limit:
                raise TaskBudgetDeniedError("m1_provider_usage_exceeded_reserved_proxy")
            counters["tokens_in"] += int(current["in"])
            counters["tokens_out"] += int(current["out"])
            if counters["tokens_in"] + counters["tokens_out"] > MODEL_TOTAL_TOKEN_CEILING:
                raise TaskBudgetDeniedError("m1_actual_token_budget_exceeded")
        finally:
            _PRE_SEND_ENVELOPE.reset(token)

    LLMClient._transport_attempt_scope = bounded  # explicit isolated-process scope
    LLMClient._observe_transport_usage = on_usage
    return counters


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--smoke", action="store_true", help="one tiny direct GLM request under the same CAS gate")
    mode.add_argument("--execute", action="store_true", help="run the one-shot FX05 task under the same CAS gate")
    parser.add_argument("--proxy", default="", help="optional explicit local HTTP proxy, e.g. http://127.0.0.1:6152")
    args = parser.parse_args()
    if not args.probe and not args.smoke and args.prompt_file is None:
        parser.error("--prompt-file required unless --probe")
    root = Path(__file__).resolve().parents[1]
    from llm_loop.config import load_settings
    from llm_loop.runtime.resolver import apply_to_environ, legacy_env_snapshot, resolve_effective

    resolved = resolve_effective("web")
    # Factory's provider registry still reads process-local environment;
    # inject the same resolved snapshot without modifying host configuration.
    apply_to_environ(resolved)
    settings = load_settings(legacy_env_snapshot(resolved))
    # Preserve the Mac's authoritative model registry BEFORE changing data_dir
    # to an isolated test runtime. Otherwise the isolated root has no
    # providers.local.json and silently synthesizes a DeepSeek-backed alias
    # named "glm/glm-5.3" (model-label spoofing).
    from llm_loop.llm.providers import load_registry

    trusted_registry = load_registry(settings)
    if trusted_registry.degraded or trusted_registry.resolve(MODEL) != ("glm", "glm-5.3"):
        raise TaskBudgetDeniedError("m1_glm_registry_not_qualified")
    settings = dataclasses.replace(
        settings,
        data_dir=str(root / "data" / "m1-budgeted-run"),
        llm_model=MODEL,
        llm_max_tokens=MAX_OUTPUT_TOKENS,
        llm_timeout_s=180.0,
        history_max_chars=50_000,
        max_iterations=ATTEMPTS,
        llm_retry_disconnect=0,
        runner_background=False,
    )
    from llm_loop.factory import build_engine

    engine = build_engine(settings, workspace_root=str(root))
    pool = engine.llm_pool
    if pool is None:
        engine.close()
        raise TaskBudgetDeniedError("m1_model_pool_unavailable")
    pool.replace_registry(trusted_registry)
    pool.set_default_model(MODEL)
    pool.model_fallbacks_raw = ""
    routed_client, resolved_provider, resolved_model = pool.get_resolved_client(MODEL)
    if (
        resolved_provider != "glm" or resolved_model != "glm-5.3"
        or getattr(routed_client, "provider", None) != "glm"
        or getattr(routed_client, "model", None) != "glm-5.3"
    ):
        engine.close()
        raise TaskBudgetDeniedError("m1_glm_routing_identity_mismatch")
    # Per-model registry defaults may be larger than the frozen output quota.
    # This is a process-local instance only; no change to production config.
    routed_client.max_tokens = 128 if args.smoke else min(
        int(routed_client.max_tokens or MAX_OUTPUT_TOKENS), MAX_OUTPUT_TOKENS
    )
    routed_client.timeout_s = 45.0 if args.smoke else 60.0
    if args.smoke:
        routed_client.retry_disconnect = 0
    session_id = engine.session.create()
    generation = uuid.uuid4().hex
    root_id = "m1fx05-" + uuid.uuid4().hex
    scope = exact_workspace_scope(str(root))
    grant = TaskBudgetGrant(
        budget_id=root_id,
        issuer="user-approved-host-controller",
        authority_source="user-2026-11-13-m1-fx05-regrant",
        workspace_scope=scope,
        session_id=session_id,
        human_turn_ref="approved-fx05-" + generation,
        surface="cli-test_harness",
        profile=PROFILE,
        policy_version="m1-t1-budgeted-cli-v2",
        deadline_epoch_s=time.time() + MAX_RUNTIME_SECONDS,
        limits=TaskBudgetLimits(
            physical_attempts=ATTEMPTS,
            tool_invocations=MAX_TOOLS,
            input_tokens=MODEL_TOTAL_TOKEN_CEILING,
            output_tokens=MODEL_TOTAL_TOKEN_CEILING,
            payload_bytes=2 * 1024 * 1024,
        ),
        capabilities=TaskBudgetCapabilities(
            allowed_tools=frozenset({"read_file", "edit_file", "get_tool_schema"}),
            allow_wake=False,
            allow_subagents=False,
        ),
        provider_identity="glm",
        exact_model_ref="glm-5.3",
    )
    store = TaskBudgetStore(root / "data" / "m1-budgeted-run" / "budgets")
    row = store.issue_root(grant, root_run_generation=generation, ingress_kind="cli", reject_duplicate=True)
    row = store.activate(root_id, expected_revision=row["revision"])
    assert row["phase"] == BudgetPhase.ACTIVE
    member = TaskBudgetMember.from_dict(row["members"][root_id])
    execution = FX05BudgetExecution(store=store, budget_id=root_id, member=member)
    counters = _install_fail_closed_transport_guard()
    print(json.dumps({"event": "admitted", "session_id": session_id, "budget_id": root_id, "generation": generation, "model": MODEL, "profile": PROFILE}), flush=True)

    scope_token = current_write_scope.set(WriteScope(paths=(TARGET_PATH,)))
    discovery_token = current_tool_discovery_scope.set(
        frozenset({"read_file", "edit_file", "get_tool_schema"})
    )
    generation_token = current_run_generation.set(generation)
    exit_code = 0
    try:
        # Without the existing I5-D isolated worker, budgeted_transport_timeout
        # deliberately falls back to a 1s socket timeout. Bind the qualified
        # per-attempt worker so Stop can terminate/reap the exact HTTP process;
        # this is what makes the existing <=60s IO timeout safe for real GLM.
        with (
            bind_task_budget(execution),
            bind_isolated_provider_transport(IsolatedTransportProfile(verify=True)),
        ):
            if args.probe:
                # Deliberately attempt no provider send. The actual Registry and
                # HTTP hooks must still be tested by subsequent qualification.
                execution.assert_tool_allowed("read_file")
                try:
                    execution.assert_tool_allowed("execute_command")
                except TaskBudgetDeniedError:
                    print(json.dumps({"event": "probe", "shell_denied": True}), flush=True)
                else:
                    raise AssertionError("shell unexpectedly admitted")
            elif args.smoke:
                proxy = qualify_loopback_provider_proxy(args.proxy or None)
                if args.proxy and proxy is None:
                    raise TaskBudgetDeniedError("m1_smoke_proxy_must_be_explicit_loopback_http")
                mode_token = current_reasoning_mode.set("off")
                effort_token = current_reasoning_effort.set("low")
                started = time.monotonic()
                response = None
                try:
                    with bind_authorized_provider_proxy(proxy), bind_isolated_provider_transport(
                        IsolatedTransportProfile(verify=True, proxy=proxy)
                    ):
                        iterator = routed_client._stream_openai(
                            [{"role": "user", "content": "Reply with exactly OK."}],
                            [],
                            timeout_s=45.0,
                            model="glm-5.3",
                        )
                        try:
                            while True:
                                try:
                                    next(iterator)
                                except StopIteration as stop:
                                    response = stop.value
                                    break
                        finally:
                            close_iterator = getattr(iterator, "close", None)
                            if callable(close_iterator):
                                close_iterator()
                finally:
                    current_reasoning_effort.reset(effort_token)
                    current_reasoning_mode.reset(mode_token)
                elapsed = round(time.monotonic() - started, 3)
                if (
                    response is None or not getattr(response, "content", "")
                    or counters["attempts"] != counters["usage_reports"]
                    or counters["tokens_in"] <= 0 or counters["tokens_out"] <= 0
                ):
                    exit_code = 3
                print(json.dumps({
                    "event": "smoke_terminal",
                    "provider": resolved_provider,
                    "model": resolved_model,
                    "proxy": "explicit_loopback" if proxy else "direct",
                    "elapsed_s": elapsed,
                    "response_chars": len(getattr(response, "content", "") or ""),
                    "finish_reason": getattr(response, "finish_reason", ""),
                    "usage_in": counters["tokens_in"],
                    "usage_out": counters["tokens_out"],
                    "physical_attempts": counters["attempts"],
                    "usage_reports": counters["usage_reports"],
                }), flush=True)
            else:
                prompt = args.prompt_file.read_text(encoding="utf-8")
                proxy = qualify_loopback_provider_proxy(args.proxy or None)
                if args.proxy and proxy is None:
                    raise TaskBudgetDeniedError("m1_run_proxy_must_be_explicit_loopback_http")
                # The full FX05 attempt uses the same isolated, one-request
                # worker proven by both smoke paths. No shared httpx pool or
                # ambient system-proxy discovery can strand this Run.
                with bind_authorized_provider_proxy(proxy), bind_isolated_provider_transport(
                    IsolatedTransportProfile(verify=True, proxy=proxy)
                ):
                    result = engine.run(
                        session_id,
                        prompt,
                        model=MODEL,
                        reasoning_mode="off",
                        reasoning_effort="low",
                        ingress=issue_ingress("cli"),
                    )
                if (
                    result.model_used != MODEL or result.run_incomplete
                    or counters["attempts"] != counters["usage_reports"]
                    or counters["tokens_in"] + counters["tokens_out"] > MODEL_TOTAL_TOKEN_CEILING
                ):
                    exit_code = 3
                print(json.dumps({
                    "event": "terminal", "model_used": result.model_used,
                    "run_incomplete": result.run_incomplete,
                    "rounds": result.rounds, "tools": len(result.tool_calls),
                    "provider_usage_in": counters["tokens_in"],
                    "provider_usage_out": counters["tokens_out"],
                    "physical_attempts": counters["attempts"],
                    "provider_usage_reports": counters["usage_reports"],
                    "result_tokens_in": result.tokens_in,
                    "result_tokens_out": result.tokens_out,
                    "session_id": session_id,
                }), flush=True)
    except Exception as exc:
        print(json.dumps({
            "event": "error",
            "type": type(exc).__name__,
            "reason": getattr(exc, "reason", ""),
        }), flush=True)
        exit_code = 3
    finally:
        # Terminal Run never leaves a reusable ACTIVE grant, even on error.
        try:
            execution.seal_at_run_end(reason="m1_cli_run_end")
        finally:
            current_run_generation.reset(generation_token)
            current_tool_discovery_scope.reset(discovery_token)
            current_write_scope.reset(scope_token)
            engine.close()
        state = store.read(root_id)
        print(json.dumps({
            "event": "sealed", "phase": state["phase"],
            "revision": state["revision"], "reservations": len(state["reservations"]),
            "budget_id": root_id,
        }), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
