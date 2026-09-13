#!/usr/bin/env python3
"""Isolated real-Chrome qualification for bounded Browser semantic operation v0.1."""

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

from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import BrowserSemanticOperationTool

try:
    from scripts.qualification.smc_browser_live_navigation import (
        _Controller,
        _free_loopback_port,
        _security_agent_pids,
        _wait_page,
        chrome_args,
    )
    from scripts.qualification.smc_browser_live_semantic_execute import _evaluate
except ModuleNotFoundError:
    from smc_browser_live_navigation import (  # type: ignore[import-not-found]
        _Controller,
        _free_loopback_port,
        _security_agent_pids,
        _wait_page,
        chrome_args,
    )
    from smc_browser_live_semantic_execute import _evaluate  # type: ignore[import-not-found]


def _payload(result: Any) -> dict[str, Any]:
    status = getattr(getattr(result, "status", None), "value", "")
    if status != "success":
        raise RuntimeError(f"operation failed: {status}: {result.content}")
    value = json.loads(result.content)
    if not isinstance(value, dict):
        raise RuntimeError("operation returned non-object")
    return value


def _seed(controller: _Controller) -> None:
    value = _evaluate(
        controller,
        """
document.body.innerHTML = `
 <button id="act" aria-label="ActionButton">ActionButton</button>
 <button id="gate" aria-label="GateButton" disabled>GateButton</button>`;
window.__clicks=0; window.__gateClicks=0;
document.getElementById('act').onclick=()=>{window.__clicks+=1};
document.getElementById('gate').onclick=()=>{window.__gateClicks+=1};
'ok';
""".strip(),
    )
    if value != "ok":
        raise RuntimeError("seed failed")


def run_live(*, chrome: str, evidence_dir: Path) -> dict[str, Any]:
    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lfl-bop-profile-") as profile_raw:
        process = subprocess.Popen(
            chrome_args(chrome, Path(profile_raw), port),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        controller: _Controller | None = None
        read_host: CdpReadOnlyBrowserHost | None = None
        before_security = _security_agent_pids()
        try:
            target = _wait_page(debug_base)
            target_id = str(target.get("id") or "")
            ws_url = str(target.get("webSocketDebuggerUrl") or "")
            if not target_id or not ws_url:
                raise RuntimeError("target missing")
            controller = _Controller(ws_url)
            controller.call("Page.enable")
            controller.call("Runtime.enable")
            _seed(controller)

            read_host = CdpReadOnlyBrowserHost(debug_base, target_id=target_id)
            perception = BrowserPerceptionAdapter(
                store=BrowserPerceptionStore(evidence_dir / "perception")
            )
            action = BrowserActionAdapter(
                perception=perception,
                receipt_store=BrowserActionReceiptStore(evidence_dir / "actions"),
                capture_backend=read_host,
                actuator=CdpBrowserMutationActuator(debug_base, target_id=target_id),
            )
            sid = "b-live-bounded-operation"
            semantic = BrowserSemanticExecuteTool(
                perception=perception,
                action_adapter=action,
                session_id_getter=lambda: sid,
            )
            operation = BrowserSemanticOperationTool(
                perception=perception,
                capture_backend=read_host,
                semantic_execute=semantic,
                session_id_getter=lambda: sid,
            )

            first = _payload(operation.execute(clauses=[{
                "kind": "mutate", "verb": "click",
                "target": {"kind": "object", "identity": {"kind": "button", "name": "ActionButton"}},
                "args": {},
            }]))
            click_count = int(_evaluate(controller, "window.__clicks"))

            _evaluate(controller, """
const c=document.createElement('button'); c.id='act2'; c.setAttribute('aria-label','ActionButton');
c.textContent='ActionButton'; c.onclick=()=>{window.__clicks+=10}; document.body.appendChild(c); 'ok';
""".strip())
            ambiguous = _payload(operation.execute(clauses=[{
                "kind": "mutate", "verb": "click",
                "target": {"kind": "object", "identity": {"kind": "button", "name": "ActionButton"}},
                "args": {},
            }]))
            click_after_ambiguous = int(_evaluate(controller, "window.__clicks"))
            _evaluate(controller, "document.getElementById('act2').remove(); 'ok';")

            _evaluate(controller, "setTimeout(()=>{document.getElementById('gate').disabled=false},250); 'ok';")
            waited = _payload(operation.execute(clauses=[
                {
                    "kind": "wait",
                    "target": {"kind": "object", "identity": {"kind": "button", "name": "GateButton"}},
                    "property": "enabled", "operator": "eq", "value": True,
                    "timeout_ms": 2000, "interval_ms": 100,
                },
                {
                    "kind": "mutate", "verb": "click",
                    "target": {"kind": "object", "identity": {"kind": "button", "name": "GateButton"}},
                    "args": {},
                },
            ]))
            gate_count = int(_evaluate(controller, "window.__gateClicks"))

            after_security = _security_agent_pids()
            behavior = {
                "exact_unique_dispatches_once": "PASS" if click_count == 1 and first["execution_status"] == "clauses_exhausted" else "FAIL",
                "ambiguous_exact_identity_halts_without_dispatch": "PASS" if ambiguous["execution_status"] == "halted" and ambiguous["halt_reason"].startswith("exact_identity_match_count:") and click_after_ambiguous == 1 else "FAIL",
                "typed_wait_then_single_dispatch": "PASS" if waited["execution_status"] == "clauses_exhausted" and waited["clauses"][0]["predicate_result"]["result"] == "satisfied" and gate_count == 1 else "FAIL",
                "receipt_never_claims_task_completion": "PASS" if first["task_completion"] == waited["task_completion"] == "not_evaluated" else "FAIL",
                "automatic_retry_disabled": "PASS" if first["retry"]["automatic_retry_performed"] is False and waited["retry"]["automatic_retry_performed"] is False else "FAIL",
            }
            safety = {
                "security_agent_not_spawned": "PASS" if not (after_security - before_security) else "FAIL",
                "closed_identity_fields": "PASS" if set(BrowserSemanticOperationTool._IDENTITY_SCHEMA["properties"]) == {"kind", "role", "name"} and BrowserSemanticOperationTool._IDENTITY_SCHEMA["additionalProperties"] is False else "FAIL",
            }
            return {
                "schema": "smc.browser_live_bounded_semantic_operation.v0.1",
                "behavior": behavior,
                "behavior_pass": sum(v == "PASS" for v in behavior.values()),
                "behavior_total": len(behavior),
                "safety": safety,
                "safety_pass": sum(v == "PASS" for v in safety.values()),
                "safety_total": len(safety),
            }
        finally:
            if read_host is not None:
                read_host.close()
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
    parser.add_argument("--chrome", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--result-json", required=True)
    args = parser.parse_args()
    result = run_live(chrome=args.chrome, evidence_dir=Path(args.evidence_dir))
    path = Path(args.result_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["behavior_pass"] == result["behavior_total"] and result["safety_pass"] == result["safety_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
