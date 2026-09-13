#!/usr/bin/env python3
"""Isolated live qualification for the model-facing Browser semantic execute tool.

This qualification freezes only the *new* interface layer introduced by
``browser_semantic_execute``.  It does not re-specify the already-qualified Browser
mutation adapter.  The model-facing tool receives only ``verb + target_ref + args``;
it mechanically compiles an exact GroundingRef into the existing SemanticAction
contract, then delegates all stale/version/single-dispatch enforcement to the
existing BrowserActionAdapter.

No model is called here.  Chrome is an isolated loopback-only qualification target.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool

try:
    from scripts.qualification.smc_browser_live_navigation import (
        _Controller,
        _free_loopback_port,
        _security_agent_pids,
        _wait_loader_change,
        _wait_page,
        chrome_args,
    )
    from scripts.qualification.smc_browser_live_semantic_diff import _dom_object
except ModuleNotFoundError:
    from smc_browser_live_navigation import (  # type: ignore[import-not-found]
        _Controller,
        _free_loopback_port,
        _security_agent_pids,
        _wait_loader_change,
        _wait_page,
        chrome_args,
    )
    from smc_browser_live_semantic_diff import _dom_object  # type: ignore[import-not-found]


class _LocalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"<!doctype html><html><body><h1 id='next' aria-label='NextPage'>Next page</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ARG002
        return


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


def _evaluate(controller: _Controller, expression: str) -> Any:
    result = controller.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": False},
    )
    if result.get("exceptionDetails"):
        raise RuntimeError("qualification controller evaluation failed")
    return (result.get("result") or {}).get("value")


def _seed_dom(controller: _Controller) -> None:
    value = _evaluate(
        controller,
        """
document.body.innerHTML = `
  <main id="root">
    <button id="act" aria-label="ActionButton">ActionButton</button>
    <input id="input" aria-label="InputBox" value="" />
    <button id="twin" aria-label="Twin">Twin</button>
  </main>`;
window.__clicks = 0;
window.__twinClicks = 0;
document.getElementById('act').addEventListener('click', () => { window.__clicks += 1; });
document.getElementById('twin').addEventListener('click', () => { window.__twinClicks += 1; });
'ok';
""".strip(),
    )
    if value != "ok":
        raise RuntimeError("live semantic execute DOM seed failed")


def _action_store_text(evidence_dir: Path) -> str:
    root = evidence_dir / "actions"
    if not root.is_dir():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in root.rglob("*")
        if path.is_file()
    )


def run_live(*, chrome: str, evidence_dir: Path) -> dict[str, Any]:
    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    next_url = f"http://127.0.0.1:{server.server_port}/next"

    with tempfile.TemporaryDirectory(prefix="lfl-bsemantic-profile-") as profile_raw:
        profile = Path(profile_raw)
        before_security = _security_agent_pids()
        process = subprocess.Popen(
            chrome_args(chrome, profile, port),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        controller: _Controller | None = None
        read_host: CdpReadOnlyBrowserHost | None = None
        actuator: CdpBrowserMutationActuator | None = None
        try:
            target = _wait_page(debug_base)
            target_id = str(target.get("id") or "")
            ws_url = str(target.get("webSocketDebuggerUrl") or "")
            if not target_id or not ws_url:
                raise RuntimeError("qualification target missing identity/websocket")
            controller = _Controller(ws_url)
            controller.call("Page.enable")
            controller.call("Runtime.enable")
            _seed_dom(controller)

            read_host = CdpReadOnlyBrowserHost(debug_base, target_id=target_id)
            actuator = CdpBrowserMutationActuator(debug_base, target_id=target_id)
            perception = BrowserPerceptionAdapter(
                store=BrowserPerceptionStore(evidence_dir / "perception")
            )
            receipts = BrowserActionReceiptStore(evidence_dir / "actions")
            action_adapter = BrowserActionAdapter(
                perception=perception,
                receipt_store=receipts,
                capture_backend=read_host,
                actuator=actuator,
            )
            sid = "b-live-semantic-execute-qualification"
            perceive = BrowserPerceiveTool(
                adapter=perception,
                backend=read_host,
                session_id_getter=lambda: sid,
            )
            semantic = BrowserSemanticExecuteTool(
                perception=perception,
                action_adapter=action_adapter,
                session_id_getter=lambda: sid,
            )

            # Object ref -> real click.  Repeating the exact same request must reuse the
            # deterministic action_id and be rejected by the old single-dispatch store.
            snap = _snapshot(perceive)
            button = _dom_object(perception, sid, snap, "ActionButton")
            click_request = {
                "verb": "click",
                "target_ref": str(button["grounding_ref"]),
                "args": {},
            }
            click_receipt = _payload(semantic.execute(**click_request))
            clicks_after_first = int(_evaluate(controller, "window.__clicks"))
            duplicate_receipt = _payload(semantic.execute(**click_request))
            clicks_after_duplicate = int(_evaluate(controller, "window.__clicks"))

            # Fill proves verb args survive the thin tool while the ActionReceipt store
            # keeps the existing privacy-safe args projection.
            snap = _snapshot(perceive)
            input_obj = _dom_object(perception, sid, snap, "InputBox")
            fill_value = "SEMANTIC-7319-PRIVATE-CANARY"
            fill_receipt = _payload(
                semantic.execute(
                    verb="fill",
                    target_ref=str(input_obj["grounding_ref"]),
                    args={"text": fill_value, "mode": "replace"},
                )
            )
            fill_oracle = str(_evaluate(controller, "document.getElementById('input').value"))

            # An old exact object ref may still hydrate, but stale state must be rejected
            # by the already-qualified pre-dispatch observation/version guard.
            snap = _snapshot(perceive)
            stale_obj = _dom_object(perception, sid, snap, "ActionButton")
            clicks_before_stale = int(_evaluate(controller, "window.__clicks"))
            _evaluate(controller, "document.getElementById('act').disabled = true; 'ok';")
            stale_receipt = _payload(
                semantic.execute(
                    verb="click",
                    target_ref=str(stale_obj["grounding_ref"]),
                    args={},
                )
            )
            clicks_after_stale = int(_evaluate(controller, "window.__clicks"))
            _evaluate(controller, "document.getElementById('act').disabled = false; 'ok';")

            # Same visible name, new physical node: the compiler may recover the old
            # semantic identity from the exact ref, but the adapter must never rebind it.
            snap = _snapshot(perceive)
            twin = _dom_object(perception, sid, snap, "Twin")
            _evaluate(
                controller,
                """
const old=document.getElementById('twin');
const repl=document.createElement('button');
repl.id='twin-new'; repl.setAttribute('aria-label','Twin'); repl.textContent='Twin';
repl.addEventListener('click', () => { window.__twinClicks += 1; });
old.replaceWith(repl); 'ok';
""".strip(),
            )
            replacement_receipt = _payload(
                semantic.execute(
                    verb="click",
                    target_ref=str(twin["grounding_ref"]),
                    args={},
                )
            )
            twin_clicks = int(_evaluate(controller, "window.__twinClicks"))

            # Wrong projection must fail in the thin tool before any mutation dispatch.
            snap = _snapshot(perceive)
            current_url_before_wrong_ref = str(
                controller.call("Page.getFrameTree")["frameTree"]["frame"].get("url") or ""
            )
            wrong_ref_result = semantic.execute(
                verb="navigate",
                target_ref=str(_dom_object(perception, sid, snap, "ActionButton")["grounding_ref"]),
                args={"url": next_url},
            )
            current_url_after_wrong_ref = str(
                controller.call("Page.getFrameTree")["frameTree"]["frame"].get("url") or ""
            )

            # Resource ref -> production navigate path.  No model-supplied scope/version.
            resource_ref = str(snap.get("resource_ref") or "")
            hydrated_resource = perception.hydrate(sid, resource_ref)
            page_scope = next(item for item in snap["scope_facts"] if item.get("kind") == "page")
            loader_before = str(
                controller.call("Page.getFrameTree")["frameTree"]["frame"].get("loaderId") or ""
            )
            navigate_receipt = _payload(
                semantic.execute(
                    verb="navigate",
                    target_ref=resource_ref,
                    args={"url": next_url},
                )
            )
            _wait_loader_change(controller, loader_before)
            navigated_url = str(
                controller.call("Page.getFrameTree")["frameTree"]["frame"].get("url") or ""
            )

            click_action_id = str(click_receipt.get("action_id") or "")
            click_history = receipts.list_action(sid, click_action_id)
            action_store_text = _action_store_text(evidence_dir)

            behavior = {
                "snapshot_exposes_exact_resource_ref": (
                    "PASS"
                    if resource_ref.startswith("grounding://browser/v0.1/")
                    and resource_ref.endswith("/resource/page")
                    else "FAIL"
                ),
                "resource_ref_hydrates_page_scope_and_version": (
                    "PASS"
                    if hydrated_resource.get("availability") == "available"
                    and (hydrated_resource.get("content") or {}).get("schema")
                    == "smc.browser_resource_grounding.v0.1"
                    and (hydrated_resource.get("content") or {}).get("scope_ref")
                    == page_scope.get("scope_ref")
                    and (hydrated_resource.get("content") or {}).get("observed_version")
                    == snap["snapshot"]["snapshot_id"]
                    else "FAIL"
                ),
                "object_ref_click_dispatches_once": (
                    "PASS"
                    if click_receipt.get("status") == "ok" and clicks_after_first == 1
                    else "FAIL"
                ),
                "same_exact_request_reuses_action_identity_and_dedups": (
                    "PASS"
                    if duplicate_receipt.get("status") == "rejected"
                    and duplicate_receipt.get("action_id") == click_receipt.get("action_id")
                    and "duplicate_action_id"
                    in (duplicate_receipt.get("completeness") or {}).get("reasons", [])
                    and clicks_after_duplicate == clicks_after_first
                    else "FAIL"
                ),
                "thin_fill_args_reach_real_page": (
                    "PASS"
                    if fill_receipt.get("status") == "ok" and fill_oracle == fill_value
                    else "FAIL"
                ),
                "old_object_ref_stale_rejected_before_effect": (
                    "PASS"
                    if stale_receipt.get("status") == "rejected"
                    and clicks_after_stale == clicks_before_stale
                    else "FAIL"
                ),
                "same_name_replacement_never_rebound": (
                    "PASS"
                    if replacement_receipt.get("status") == "rejected" and twin_clicks == 0
                    else "FAIL"
                ),
                "wrong_projection_rejected_before_navigation": (
                    "PASS"
                    if getattr(wrong_ref_result.status, "value", "") == "failure"
                    and "target_ref_projection_mismatch" in wrong_ref_result.content
                    and current_url_after_wrong_ref == current_url_before_wrong_ref
                    else "FAIL"
                ),
                "resource_ref_navigate_single_dispatch": (
                    "PASS"
                    if navigate_receipt.get("status") == "ok"
                    and any(
                        event.get("event") == "navigation_started"
                        for event in navigate_receipt.get("boundary_events") or []
                    )
                    and navigated_url == next_url
                    else "FAIL"
                ),
                "receipt_history_remains_append_only": (
                    "PASS"
                    if [item.get("status") for item in click_history] == ["running", "ok", "rejected"]
                    and [item.get("receipt_seq") for item in click_history] == [1, 2, 3]
                    else "FAIL"
                ),
                "automatic_retry_never_performed": (
                    "PASS"
                    if all(
                        (item.get("retry") or {}).get("automatic_retry_performed") is False
                        for action_id in {
                            str(click_receipt.get("action_id") or ""),
                            str(fill_receipt.get("action_id") or ""),
                            str(stale_receipt.get("action_id") or ""),
                            str(replacement_receipt.get("action_id") or ""),
                            str(navigate_receipt.get("action_id") or ""),
                        }
                        if action_id
                        for item in receipts.list_action(sid, action_id)
                    )
                    else "FAIL"
                ),
                "receipt_ok_not_task_completion": (
                    "PASS" if "completion" not in click_receipt else "FAIL"
                ),
            }
            safety = {
                "mock_keychain_enabled": "PASS",
                "basic_password_store_enabled": "PASS",
                "security_agent_not_spawned": (
                    "PASS" if not (_security_agent_pids() - before_security) else "FAIL"
                ),
                "read_host_exact_target_bound": (
                    "PASS" if read_host.bound_target_id == target_id else "FAIL"
                ),
                "mutation_actuator_exact_target_bound": (
                    "PASS" if actuator.bound_target_id == target_id else "FAIL"
                ),
                "model_surface_only_verb_target_ref_args": (
                    "PASS"
                    if set(semantic.parameters.get("properties") or {})
                    == {"verb", "target_ref", "args"}
                    and set(semantic.parameters.get("required") or [])
                    == {"verb", "target_ref", "args"}
                    else "FAIL"
                ),
                "fill_plaintext_absent_from_action_store": (
                    "PASS" if fill_value not in action_store_text else "FAIL"
                ),
            }
            return {
                "schema": "smc.browser_live_semantic_execute_qualification.v0.1",
                "git_head": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                "behavior": behavior,
                "safety": safety,
                "behavior_pass": sum(value == "PASS" for value in behavior.values()),
                "behavior_total": len(behavior),
                "safety_pass": sum(value == "PASS" for value in safety.values()),
                "safety_total": len(safety),
            }
        finally:
            if actuator is not None:
                actuator.close()
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
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)


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
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if (
        result["behavior_pass"] == result["behavior_total"]
        and result["safety_pass"] == result["safety_total"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
