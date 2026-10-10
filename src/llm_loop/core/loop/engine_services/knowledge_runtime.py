"""Run-local knowledge consumption and feedback observation.

This service never executes a tool, mutates a Method/Experience, calls a model,
or settles provider/tool outcomes. It only sees already-persisted tool receipts
and may prepare a transient REFERENCE for the NEXT provider decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from contextlib import suppress
from typing import Any

_FAILURES = frozenset({"failure", "error", "timeout"})
_HIGH_RISK = re.compile(
    r"(deploy|publish|release|production|rm\s+-|delete|chmod|sudo|"
    r"生产|发布|部署|删除|清理目录|权限|密钥|转账|付款|发邮件|推送远程)",
    re.IGNORECASE,
)
_LOW_RISK = re.compile(
    r"(test|pytest|read|inspect|diagnos|investigat|check|repair|debug|"
    r"测试|读取|排查|检查|修复|分析|检索|复核|诊断|日志|代码)",
    re.IGNORECASE,
)


def _risk_for(query: str) -> str:
    # Risk inference only selects whether to offer low-authority advice,
    # never decides whether the tool is permitted to execute.
    if _HIGH_RISK.search(query) or not _LOW_RISK.search(query):
        return "high"
    return "low"


class KnowledgeRun:
    """Single-run isolated observer; keyed observations survive in EventStore."""

    def __init__(
        self,
        *,
        advisor: Any,
        session_id: str,
        run_ref: str,
        event_append: Callable[[str, str, dict[str, Any]], object],
        canary_sessions: frozenset[str] = frozenset(),
    ) -> None:
        self.advisor = advisor
        self.session_id = session_id
        self.run_ref = run_ref
        self.event_append = event_append
        self.canary_sessions = canary_sessions
        self._keys: set[str] = set()
        self._observed_call_ids: set[str] = set()
        self._first_failure: tuple[str, str] | None = None
        self._first_failure_prompted = False
        self._hydrated_refs: set[str] = set()
        self._prepared_references: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._finished = False

    def _emit(self, kind: str, key: str, payload: dict[str, Any]) -> None:
        with suppress(Exception):
            self.event_append(self.session_id, kind, {
                "knowledge_event_key": key,
                "run_ref": self.run_ref,
                **payload,
            })

    def observe_receipts(self, trace: list[dict], tool_messages: list[Any]) -> None:
        """Only accept a trace row with its actual paired tool message."""
        paired = {
            str(getattr(m, "tool_call_id", "") or ""): m
            for m in tool_messages
            if getattr(m, "role", "") == "tool" and getattr(m, "tool_call_id", None)
        }
        for row in trace:
            call_id = str(row.get("id") or "")
            if not call_id or call_id in self._observed_call_ids:
                continue
            message = paired.get(call_id)
            status = str(row.get("status") or "")
            actual_status = getattr(getattr(message, "status", None), "value", None)
            if message is None or actual_status != status:
                continue
            name = str(row.get("name") or "")
            if str(getattr(message, "tool_name", "") or "") != name:
                continue
            self._observed_call_ids.add(call_id)
            args = row.get("arguments")
            args = args if isinstance(args, dict) else {}
            binding = hashlib.sha256(
                f"{self.run_ref}\0{call_id}\0{status}".encode()
            ).hexdigest()[:24]
            if status in _FAILURES and self._first_failure is None:
                self._first_failure = (call_id, name)
                self._emit("knowledge.failure_observed", binding, {
                    "call_id": call_id, "tool": name, "status": status,
                    "root_cause": "not_evaluated", "replay_allowed": False,
                })
            if status != "success":
                continue
            if name == "search_records":
                ref = str(args.get("query") or "")
                kind = str(args.get("kind") or "")
                content = str(getattr(message, "content", "") or "").removeprefix(f"[状态: {status}] ")
                # A successful search_records call can also mean ZERO matches.
                # An exact-looking query alone does not prove hydration.
                hydrated = (
                    content.startswith("[search_records] 命中 ")
                    and (
                        (
                            kind == "method" and ref.startswith("method:")
                            and "--- exact Method ---" in content
                            and ref in content
                        )
                        or (
                            kind in {"experience", "lesson"}
                            and ref.startswith("experience:")
                            and f"\nexperience_ref={ref}\n" in content
                            and "\nbody=" in content
                        )
                    )
                )
                if hydrated:
                    self._hydrated_refs.add(ref)
                    self._emit("knowledge.hydration_observed", binding, {
                        "call_id": call_id, "kind": kind, "ref": ref,
                        "adoption": "not_evaluated",
                    })
            elif name == "method_manage" and args.get("action") == "record_use":
                self._emit("knowledge.method_declaration", binding, {
                    "call_id": call_id, "ref": str(args.get("method_ref") or ""),
                    "decision": str(args.get("use_decision") or ""),
                    "task_benefit": "not_evaluated",
                    "hydration_observed": str(args.get("method_ref") or "") in self._hydrated_refs,
                })
            elif name == "refine_experience" and args.get("action") == "record_use":
                content = str(getattr(message, "content", "") or "").removeprefix(f"[状态: {status}] ")
                if not content.startswith("[refine_experience] use declaration\n"):
                    continue
                try:
                    declaration = json.loads(content.split("\n", 1)[1])
                except (ValueError, IndexError):
                    continue
                if (
                    not isinstance(declaration, dict)
                    or declaration.get("schema") != "experience-use/v1"
                    or declaration.get("ref") != args.get("experience_id")
                    or declaration.get("decision") != args.get("use_decision")
                    or declaration.get("decision") not in {"applied", "adapted", "not_applicable", "rejected"}
                ):
                    continue
                ref = str(declaration["ref"])
                self._emit("knowledge.experience_declaration", binding, {
                    "call_id": call_id, "ref": ref, "decision": declaration["decision"],
                    "record_kind": declaration.get("record_kind"),
                    "verification_state": declaration.get("verification_state"),
                    "document_projection_sha256": declaration.get("document_projection_sha256"),
                    "hydration_observed": ref in self._hydrated_refs,
                    "authority": "model_declared", "task_benefit": "not_evaluated",
                })
            elif name == "save_experience":
                kind = str(args.get("record_kind") or "")
                state = str(args.get("verification_state") or "")
                if kind not in {"lesson", "experience"}:
                    continue
                # Store-side typed uncertainty / conflict cannot count as a
                # confirmed new record, regardless of legacy wrapper status.
                content = str(getattr(message, "content", "") or "").removeprefix(f"[状态: {status}] ")
                confirm = re.search(
                    r"\[save_experience\] 已沉淀 \S+ "
                    r"experience_ref=(experience:EXPERIENCE-[A-Za-z0-9-]+) "
                    r"status=active record_kind=(lesson|experience) "
                    r"verification_state=(verified|unverified|disproven)",
                    content,
                )
                if confirm is None or (kind, state) != (
                    confirm.group(2), confirm.group(3)
                ):
                    self._emit("knowledge.learning_unconfirmed", binding, {
                        "call_id": call_id, "record_kind": kind,
                        "outcome": "no_exact_confirmed_save_ref",
                    })
                    continue
                # A successful save tool receipt is evidence of a save, not that
                # its model-authored root cause or claimed benefit is correct.
                self._emit("knowledge.learning_saved", binding, {
                    "call_id": call_id, "ref": confirm.group(1), "record_kind": kind,
                    "verification_state": state,
                    "first_failed_call_id": (
                        self._first_failure[0] if self._first_failure else ""
                    ),
                    "independently_validated": False,
                })
            elif self._first_failure is not None:
                self._emit("knowledge.followup_tool_observed", binding, {
                    "call_id": call_id, "tool": name, "status": status,
                    "first_failed_call_id": self._first_failure[0],
                    "recovery_proven": False,
                })

    def before_provider(
        self,
        *,
        query: str,
        round_no: int,
        trace: list[dict],
        tool_messages: list[Any],
        available_history_chars: int,
    ) -> tuple[str, tuple[str, ...]]:
        """Return a transient REFERENCE and source refs for this ONE next decision."""
        if getattr(self.advisor, "mode", "off") == "off":
            return "", ()
        self.observe_receipts(trace, tool_messages)
        trigger = ""
        frontier = ""
        lookup = query
        if round_no == 1 and len(query.strip()) >= 12:
            trigger, frontier = "task_start", "first_decision"
        elif self._first_failure is not None and not self._first_failure_prompted:
            call_id, name = self._first_failure
            trigger, frontier = "first_failure", f"failed:{call_id}"
            lookup = f"{query[:175]} {name} failure"
            self._first_failure_prompted = True
        if not trigger:
            return "", ()
        try:
            discovery = self.advisor.discover(
                query=lookup, trigger=trigger, session_id=self.session_id,
                run_ref=self.run_ref, frontier=frontier, risk=_risk_for(query),
            )
        except Exception:
            return "", ()
        if discovery.key in self._keys:
            return "", ()
        self._keys.add(discovery.key)
        self._emit("knowledge.discovery", discovery.key, discovery.telemetry())
        refs = tuple(h.ref for h in discovery.hints)
        eligible = (
            self.advisor.mode == "canary"
            and self.session_id in self.canary_sessions
            and _risk_for(query) == "low"
            and available_history_chars >= len(discovery.reference) + 500
        )
        if not eligible or not refs:
            return "", refs
        self._emit("knowledge.reference_prepared", discovery.key, {
            "refs": list(refs), "reference_chars": len(discovery.reference),
            "provider_delivery": "not_confirmed",
        })
        self._prepared_references[discovery.key] = (discovery.reference, refs)
        return discovery.reference, refs


    def provider_reference_facts(self, payload: Any) -> list[dict[str, Any]]:
        """Match exact prepared bytes in final OpenAI payload; no delivery claim."""
        if not isinstance(payload, dict) or self.advisor.mode != "canary":
            return []
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return []  # other wire representations remain honestly unobserved
        contents = [
            str(row["content"]) for row in messages
            if isinstance(row, dict) and row.get("role") == "user"
            and isinstance(row.get("content"), str)
        ]
        return [
            {
                "knowledge_event_key": key, "run_ref": self.run_ref,
                "refs": list(refs), "reference_chars": len(reference),
                "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
            }
            for key, (reference, refs) in self._prepared_references.items()
            if any(content.endswith(reference) for content in contents)
        ]

    def finish(
        self, *, trace: list[dict], tool_messages: list[Any], reason: str,
        rounds: int, tokens_in: int, tokens_out: int, duration_ms: int,
        model_used: str, run_incomplete: bool,
    ) -> None:
        """Observe terminal receipts and runtime outcome, never score task success."""
        if self._finished or self.advisor.mode == "off":
            return
        self.observe_receipts(trace, tool_messages)
        self._finished = True
        self._emit("knowledge.run_outcome", "terminal", {
            "reason": reason, "rounds": rounds, "tokens_in": tokens_in,
            "tokens_out": tokens_out, "duration_ms": duration_ms,
            "model_used": model_used, "run_incomplete": run_incomplete,
            "task_benefit": "not_evaluated",
            "hydrated_refs": sorted(self._hydrated_refs),
        })


def _paired_tool_trace(messages: list[Any], turn_index: int) -> tuple[list[dict], list[Any]]:
    """Project only actual assistant declarations paired with tool receipts.

    No unverified model text, tool status guesses, or cross-turn rows participate.
    """
    declared: dict[str, tuple[str, dict]] = {}
    trace: list[dict] = []
    receipts: list[Any] = []
    seen: set[str] = set()
    for message in messages[max(0, turn_index + 1):]:
        if getattr(message, "role", "") == "assistant":
            for call in getattr(message, "tool_calls", None) or []:
                if not isinstance(call, dict):
                    continue
                call_id = str(call.get("id") or "")
                function = call.get("function")
                if not call_id or not isinstance(function, dict):
                    continue
                args = function.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (TypeError, ValueError):
                        args = {}
                declared[call_id] = (
                    str(function.get("name") or ""),
                    args if isinstance(args, dict) else {},
                )
        if getattr(message, "role", "") != "tool":
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        if call_id in seen or call_id not in declared:
            continue
        status = str(getattr(getattr(message, "status", None), "value", "") or "")
        if not status:
            continue
        name, args = declared[call_id]
        if str(getattr(message, "tool_name", "") or "") != name:
            continue
        seen.add(call_id)
        trace.append({"id": call_id, "name": name, "status": status, "arguments": args})
        receipts.append(message)
    return trace, receipts


def project_execution_knowledge(
    host: Any,
    sess: Any,
    built: list[dict[str, Any]],
    *,
    logical_round: int | None,
    history_budget: int,
) -> list[dict[str, Any]]:
    """Thin opt-in tail after the normal builder, before the physical LLM call.

    Neither persisted Session messages nor tool schemas/permissions are changed.
    The correction registry owns the installed search adapter (no new Kernel→
    knowledge store import). A new human turn creates a new per-session ledger.
    """
    runtime_config = getattr(getattr(host, "settings", None), "tool_runtime", None)
    mode = str(getattr(runtime_config, "knowledge_advisor_mode", "off") or "off")
    if mode == "off" or logical_round is None or logical_round <= 0:
        return built
    try:
        state = host._run_state()
        turn_index = getattr(state, "current_turn_ref", None)
        ingress = getattr(state, "active_run_ingress_message", None)
        if not isinstance(turn_index, int) or ingress is None:
            return built
        sid = str(getattr(sess, "session_id", "") or "")
        # A re-admitted run of the same persisted turn is a distinct execution
        # generation. Never borrow the prior run's dedupe keys or failure latch.
        from llm_loop.core.run_context import current_run_generation

        generation = str(current_run_generation.get() or "")
        run_ref = (
            f"{sid}:turn:{turn_index}:run:{generation}" if generation
            else f"{sid}:turn:{turn_index}"
        )
        tracker = getattr(state, "knowledge_runtime", None)
        if tracker is None or getattr(state, "knowledge_turn_identity", "") != run_ref:
            registry = getattr(host, "corrections", None)
            factory = getattr(registry, "build_knowledge_advisor", None)
            advisor = factory(mode) if callable(factory) else None
            if advisor is None:
                return built
            md = getattr(ingress, "metadata", None) or {}
            # A Web ingress credential plus an exact session allowlist are both
            # required. Other surfaces may collect SHADOW observations, not wire.
            # Persisted metadata ALONE is not an authorization proof: only the
            # currently bound signed ingress token can establish this is a live
            # human Web turn and not CLI/Feishu/delegated/replayed user-like text.
            from llm_loop.core.trace_leak.ingress_token import (
                current_ingress_session_id,
                current_ingress_token,
                is_whitelisted,
            )

            token = current_ingress_token.get()
            web_authenticated = (
                token is not None
                and is_whitelisted(token)
                and getattr(token, "channel", "") == "web"
                and getattr(token, "entry", "") == "web"
                and not bool(getattr(token, "delegated", False))
                and current_ingress_session_id.get() == sid
                and isinstance(md, dict)
                and md.get("ingress_channel") == "web"
                and md.get("ingress_entry") == "web"
                and md.get("origin_layer") == "user_instruction"
                and not bool(md.get("program_origin", False))
            )
            raw_allowlist = str(
                getattr(runtime_config, "knowledge_advisor_sessions", "") or ""
            )
            allowed = (
                frozenset(s.strip() for s in raw_allowlist.split(",") if s.strip())
                if web_authenticated
                else frozenset()
            )
            tracker = KnowledgeRun(
                advisor=advisor, session_id=sid, run_ref=run_ref,
                event_append=host._event_append, canary_sessions=allowed,
            )
            state.knowledge_runtime = tracker
            state.knowledge_turn_identity = run_ref
        trace, receipts = _paired_tool_trace(list(getattr(sess, "messages", []) or []), turn_index)
        budget = max(0, int(history_budget)) - sum(
            len(str(row.get("content") or "")) for row in built
        )
        reference, _ = tracker.before_provider(
            query=str(getattr(ingress, "content", "") or ""),
            round_no=logical_round, trace=trace, tool_messages=receipts,
            available_history_chars=budget,
        )
        if not reference:
            return built
        # GLM 1210: two consecutive tail user messages can be rejected by the
        # provider. Merge at the *transient wire projection* only, preserving
        # the original user text/marker as the exact prefix and a visibly
        # lower-authority REFERENCE appendix as the suffix. Session/EventStore
        # and the original built list/dicts remain byte-for-byte untouched.
        if built and built[-1].get("role") == "user":
            original_content = built[-1].get("content")
            if not isinstance(original_content, str):
                return built
            joined = dict(built[-1])
            joined["content"] = original_content + "\n\n" + reference
            return [*built[:-1], joined]
        return [*built, {"role": "user", "content": reference}]
    except Exception:
        return built  # Reference failure must not change actual tool/provider truth.
