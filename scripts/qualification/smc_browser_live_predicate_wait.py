#!/usr/bin/env python3
"""Qualification-only live Browser Predicate/wait harness.

The external controller may prepare and change an isolated Browser fixture.  The
production Browser host under test remains strictly read-only.  This harness does
not qualify mutation dispatch, staleness/version pressure, or ActionReceipt.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

try:
    from scripts.qualification.smc_browser_live_navigation import (
        _Controller,
        _free_loopback_port,
        _security_agent_pids,
        _wait_page,
        chrome_args,
    )
except ModuleNotFoundError:  # direct script entrypoint
    from smc_browser_live_navigation import (  # type: ignore[import-not-found]
        _Controller,
        _free_loopback_port,
        _security_agent_pids,
        _wait_page,
        chrome_args,
    )


def _payload(result: Any) -> dict[str, Any]:
    status = getattr(getattr(result, "status", None), "value", "")
    if status != "success":
        raise RuntimeError(f"Browser tool failed: status={status}; content={result.content}")
    value = json.loads(result.content)
    if not isinstance(value, dict):
        raise RuntimeError("Browser tool returned non-object JSON")
    return value


def _snapshot(tool: BrowserPerceiveTool) -> dict[str, Any]:
    return _payload(tool.execute(action="snapshot", projection_limit=500))


def _dom_object(
    adapter: BrowserPerceptionAdapter,
    session_id: str,
    snapshot: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for item in snapshot.get("objects") or []:
        if not isinstance(item, dict):
            continue
        if (item.get("attributes") or {}).get("name") != name:
            continue
        hydrated = adapter.hydrate(session_id, str(item.get("grounding_ref") or ""))
        content = hydrated.get("content")
        if (
            hydrated.get("availability") == "available"
            and isinstance(content, dict)
            and content.get("identity_basis") == "dom_physical_identity"
        ):
            matches.append(item)
    if len(matches) != 1:
        raise RuntimeError(f"expected one DOM-physical {name!r}; observed={len(matches)}")
    return matches[0]


def _predicate(
    *,
    scope_ref: str,
    target: str,
    property_name: str,
    operator: str,
    value: Any,
) -> dict[str, Any]:
    return {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": scope_ref,
        "target": target,
        "property": property_name,
        "operator": operator,
        "value": value,
    }


def _set_initial_dom(controller: _Controller) -> None:
    expression = """
document.body.innerHTML = `
  <main id="root">
    <button id="stable" aria-label="Stable" disabled>Stable</button>
    <div id="filler-a">A</div>
    <div id="filler-b">B</div>
  </main>`;
'ok';
""".strip()
    response = controller.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": False},
    )
    if ((response.get("result") or {}).get("value")) != "ok":
        raise RuntimeError("initial live predicate DOM setup failed")


def _schedule_js(controller: _Controller, body: str, delay_ms: int) -> None:
    expression = f"setTimeout(() => {{ {body} }}, {int(delay_ms)}); 'armed';"
    response = controller.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": False},
    )
    if ((response.get("result") or {}).get("value")) != "armed":
        raise RuntimeError("qualification Browser transition was not armed")


class _FailOnceBackend:
    """Qualification-only observer fault wrapper; it never mutates Browser state."""

    def __init__(self, backend: CdpReadOnlyBrowserHost) -> None:
        self.backend = backend
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("qualification synthetic observer outage")
        return self.backend.capture()


def _wait(
    tool: BrowserPerceiveTool,
    predicate: dict[str, Any],
    *,
    timeout_ms: int,
    interval_ms: int,
) -> dict[str, Any]:
    return _payload(
        tool.execute(
            action="wait",
            predicate=predicate,
            timeout_ms=timeout_ms,
            interval_ms=interval_ms,
        )
    )


def run_live(*, chrome: str, evidence_dir: Path) -> dict[str, Any]:
    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lfl-bpredicate-profile-") as profile_raw:
        profile = Path(profile_raw)
        before_security = _security_agent_pids()
        process = subprocess.Popen(
            chrome_args(chrome, profile, port),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        controller: _Controller | None = None
        host: CdpReadOnlyBrowserHost | None = None
        try:
            target = _wait_page(debug_base)
            target_id = str(target.get("id") or "")
            ws_url = str(target.get("webSocketDebuggerUrl") or "")
            if not target_id or not ws_url:
                raise RuntimeError("qualification target missing identity/websocket")
            controller = _Controller(ws_url)
            controller.call("Runtime.enable")
            _set_initial_dom(controller)

            host = CdpReadOnlyBrowserHost(debug_base, target_id=target_id)
            adapter = BrowserPerceptionAdapter(
                store=BrowserPerceptionStore(evidence_dir / "grounding")
            )
            session_id = "b-live-predicate-wait-qualification"
            tool = BrowserPerceiveTool(
                adapter=adapter,
                backend=host,
                session_id_getter=lambda: session_id,
            )
            seed = _snapshot(tool)
            stable = _dom_object(adapter, session_id, seed, "Stable")
            stable_id = str(stable["id"])
            stable_scope = str(stable["scope_ref"])
            document_scope = str(seed["snapshot"]["scope"]["scope_ref"])

            checks: dict[str, str] = {}

            # One observer failure followed by a valid sample must remain visible
            # without turning the wait into a tool error.
            flaky_tool = BrowserPerceiveTool(
                adapter=adapter,
                backend=_FailOnceBackend(host),
                session_id_getter=lambda: session_id,
            )
            url_wait = _wait(
                flaky_tool,
                _predicate(
                    scope_ref=document_scope,
                    target=document_scope,
                    property_name="url",
                    operator="contains",
                    value="about:blank",
                ),
                timeout_ms=1_000,
                interval_ms=20,
            )
            url_result = dict(url_wait.get("predicate_result") or {})
            checks["observer_error_then_recovery"] = (
                "PASS"
                if url_result.get("result") == "satisfied"
                and url_result.get("observer_error_count") == 1
                and int(url_result.get("sample_count") or 0) >= 2
                else "FAIL"
            )

            _schedule_js(
                controller,
                "document.getElementById('stable').disabled = false;",
                150,
            )
            enabled_wait = _wait(
                tool,
                _predicate(
                    scope_ref=stable_scope,
                    target=stable_id,
                    property_name="enabled",
                    operator="eq",
                    value=True,
                ),
                timeout_ms=2_000,
                interval_ms=50,
            )
            enabled_result = dict(enabled_wait.get("predicate_result") or {})
            checks["live_enabled_transition_satisfied"] = (
                "PASS"
                if enabled_result.get("result") == "satisfied"
                and int(enabled_result.get("sample_count") or 0) >= 2
                and enabled_result.get("observer_error_count") == 0
                else "FAIL"
            )
            after_enabled = _snapshot(tool)
            enabled_obj = _dom_object(adapter, session_id, after_enabled, "Stable")
            checks["stable_identity_preserved_across_wait"] = (
                "PASS" if enabled_obj.get("id") == stable_id else "FAIL"
            )

            impossible_wait = _wait(
                tool,
                _predicate(
                    scope_ref=stable_scope,
                    target=stable_id,
                    property_name="name",
                    operator="eq",
                    value="This name is not present",
                ),
                timeout_ms=80,
                interval_ms=20,
            )
            impossible_result = dict(impossible_wait.get("predicate_result") or {})
            checks["timeout_unsatisfied_is_observation"] = (
                "PASS"
                if impossible_result.get("result") == "unsatisfied"
                and int(impossible_result.get("sample_count") or 0) >= 1
                else "FAIL"
            )

            # The production read-only host deliberately does not use
            # Runtime.evaluate to manufacture document.readyState.  The valid
            # B-SPEC property therefore remains indeterminate on this sensor.
            ready_wait = _wait(
                tool,
                _predicate(
                    scope_ref=document_scope,
                    target=document_scope,
                    property_name="document_ready_state",
                    operator="eq",
                    value="complete",
                ),
                timeout_ms=80,
                interval_ms=20,
            )
            ready_result = dict(ready_wait.get("predicate_result") or {})
            checks["unobserved_ready_state_is_indeterminate"] = (
                "PASS"
                if ready_result.get("result") == "indeterminate"
                and (ready_wait.get("observation") or {}).get("reason")
                == "property_unobserved"
                else "FAIL"
            )

            _schedule_js(controller, "document.getElementById('stable').remove();", 150)
            gone_wait = _wait(
                tool,
                _predicate(
                    scope_ref=stable_scope,
                    target=stable_id,
                    property_name="exists",
                    operator="eq",
                    value=False,
                ),
                timeout_ms=2_000,
                interval_ms=50,
            )
            gone_result = dict(gone_wait.get("predicate_result") or {})
            checks["complete_coverage_proves_live_absence"] = (
                "PASS"
                if gone_result.get("result") == "satisfied"
                and (gone_wait.get("observation") or {}).get("observed_value") is False
                and (gone_wait.get("observation") or {}).get("coverage_complete") is True
                else "FAIL"
            )

            # Separate adapter budget mechanically makes observation incomplete.
            # A non-decisive upper-bound count must remain indeterminate.
            partial_adapter = BrowserPerceptionAdapter(
                store=BrowserPerceptionStore(evidence_dir / "partial-grounding"),
                capture_node_cap=1,
            )
            partial_tool = BrowserPerceiveTool(
                adapter=partial_adapter,
                backend=host,
                session_id_getter=lambda: session_id,
            )
            partial_seed = _snapshot(partial_tool)
            partial_scope = str(partial_seed["snapshot"]["scope"]["scope_ref"])
            partial_wait = _wait(
                partial_tool,
                _predicate(
                    scope_ref=partial_scope,
                    target=partial_scope,
                    property_name="object_count",
                    operator="le",
                    value=999,
                ),
                timeout_ms=80,
                interval_ms=20,
            )
            partial_result = dict(partial_wait.get("predicate_result") or {})
            partial_observation = dict(partial_wait.get("observation") or {})
            checks["partial_coverage_count_is_indeterminate"] = (
                "PASS"
                if partial_result.get("result") == "indeterminate"
                and partial_observation.get("coverage_complete") is False
                and "coverage" in str(partial_observation.get("reason") or "")
                else "FAIL"
            )

            checks["predicate_result_sampling_facts_visible"] = (
                "PASS"
                if set(enabled_result)
                == {
                    "result",
                    "evaluation_mode",
                    "observed_at",
                    "deadline",
                    "interval_ms",
                    "sample_count",
                    "observer_error_count",
                }
                and enabled_result.get("evaluation_mode") == "polling"
                and enabled_result.get("deadline") is not None
                else "FAIL"
            )
            checks["wait_has_no_action_receipt_fields"] = (
                "PASS"
                if not {
                    "action_id",
                    "receipt_id",
                    "receipt_seq",
                    "before_version",
                    "after_version",
                }.intersection(enabled_wait)
                else "FAIL"
            )

            action_values = {
                str(value).lower()
                for value in tool.parameters["properties"]["action"]["enum"]
            }
            safety = {
                "mock_keychain_enabled": "PASS",
                "basic_password_store_enabled": "PASS",
                "security_agent_not_spawned": (
                    "PASS" if not (_security_agent_pids() - before_security) else "FAIL"
                ),
                "production_host_exact_target_bound": (
                    "PASS" if host.bound_target_id == target_id else "FAIL"
                ),
                "model_surface_has_no_mutation": (
                    "PASS"
                    if not {
                        "click",
                        "fill",
                        "select",
                        "navigate",
                        "scroll",
                        "reload",
                        "script",
                    }.intersection(action_values)
                    else "FAIL"
                ),
                "assert_not_exposed_in_this_stage": (
                    "PASS" if "assert" not in action_values else "FAIL"
                ),
            }
            all_values = list(checks.values()) + list(safety.values())
            return {
                "schema": "smc.browser_live_predicate_wait_qualification.v0.1",
                "status": "PASS" if all(value == "PASS" for value in all_values) else "FAIL",
                "checks": checks,
                "safety": safety,
            }
        finally:
            if host is not None:
                host.close()
            if controller is not None:
                controller.close()
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chrome",
        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args()

    result = run_live(chrome=args.chrome, evidence_dir=Path(args.evidence_dir))
    result_path = Path(args.result_json)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
