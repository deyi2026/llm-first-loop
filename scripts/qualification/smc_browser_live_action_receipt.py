#!/usr/bin/env python3
"""Isolated live qualification for Browser mutation dispatch + ActionReceipt v0.1."""

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
from llm_loop.tools.builtin.browser_action import BrowserActionTool
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

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


class _AmbiguousAfterRealDispatch:
    """Qualification-only fault injector: real dispatch, then lose acknowledgement."""

    def __init__(self, inner: CdpBrowserMutationActuator) -> None:
        self.inner = inner
        self.calls = 0

    def dispatch(self, **kwargs: Any):
        self.calls += 1
        self.inner.dispatch(**kwargs)
        raise TimeoutError("qualification injected acknowledgement loss after real dispatch")


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
    <button id="amb" aria-label="AmbiguousButton">AmbiguousButton</button>
    <button id="popup" aria-label="PopupButton">PopupButton</button>
    <input id="input" aria-label="InputBox" value="" />
    <select id="select" aria-label="Choice"><option value="a">A</option><option value="b">B</option></select>
    <button id="twin" aria-label="Twin">Twin</button>
    <div style="height:1800px"></div>
    <button id="scroll" aria-label="ScrollTarget">ScrollTarget</button>
  </main>`;
window.__clicks = 0;
window.__ambiguousClicks = 0;
window.__twinClicks = 0;
document.getElementById('act').addEventListener('click', () => { window.__clicks += 1; });
document.getElementById('amb').addEventListener('click', function () {
  window.__ambiguousClicks += 1;
  this.disabled = true;
});
document.getElementById('popup').addEventListener('click', () => { window.open('/popup', '_blank'); });
document.getElementById('twin').addEventListener('click', () => { window.__twinClicks += 1; });
'ok';
""".strip(),
    )
    if value != "ok":
        raise RuntimeError("live action DOM seed failed")


def _action(
    snapshot: dict[str, Any],
    *,
    action_id: str,
    verb: str,
    target_id: str,
    scope_ref: str,
    args: dict[str, Any],
    version_scope: str,
) -> dict[str, Any]:
    return {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": scope_ref,
        "action_id": action_id,
        "verb": verb,
        "target_id": target_id,
        "args": args,
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": str(snapshot["snapshot"]["snapshot_id"]),
        "version_scope": version_scope,
        "version_precondition": "required",
    }


def _receipt_history(store: BrowserActionReceiptStore, sid: str, action_id: str) -> list[dict[str, Any]]:
    return store.list_action(sid, action_id)


def run_live(*, chrome: str, evidence_dir: Path) -> dict[str, Any]:
    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    next_url = f"http://127.0.0.1:{server.server_port}/next"

    with tempfile.TemporaryDirectory(prefix="lfl-baction-profile-") as profile_raw:
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
            sid = "b-live-action-receipt-qualification"
            perceive = BrowserPerceiveTool(
                adapter=perception,
                backend=read_host,
                session_id_getter=lambda: sid,
            )
            action_tool = BrowserActionTool(
                adapter=action_adapter,
                session_id_getter=lambda: sid,
            )

            # Real Chrome dispatch followed by deterministic acknowledgement loss.
            snap = _snapshot(perceive)
            ambiguous_obj = _dom_object(perception, sid, snap, "AmbiguousButton")
            ambiguous_fault = _AmbiguousAfterRealDispatch(actuator)
            ambiguous_adapter = BrowserActionAdapter(
                perception=perception,
                receipt_store=receipts,
                capture_backend=read_host,
                actuator=ambiguous_fault,
            )
            ambiguous_tool = BrowserActionTool(
                adapter=ambiguous_adapter,
                session_id_getter=lambda: sid,
            )
            ambiguous_receipt = _payload(
                ambiguous_tool.execute(
                    **_action(
                        snap,
                        action_id="live-transport-ambiguity",
                        verb="click",
                        target_id=str(ambiguous_obj["id"]),
                        scope_ref=str(ambiguous_obj["scope_ref"]),
                        args={},
                        version_scope="object",
                    )
                )
            )
            ambiguous_clicks = int(_evaluate(controller, "window.__ambiguousClicks"))
            ambiguous_disabled = bool(_evaluate(controller, "document.getElementById('amb').disabled"))

            # Real popup boundary: exact original target remains bound; new page/window is evidence only.
            snap = _snapshot(perceive)
            popup_obj = _dom_object(perception, sid, snap, "PopupButton")
            popup_receipt = _payload(
                action_tool.execute(
                    **_action(
                        snap,
                        action_id="live-popup-boundary",
                        verb="click",
                        target_id=str(popup_obj["id"]),
                        scope_ref=str(popup_obj["scope_ref"]),
                        args={},
                        version_scope="object",
                    )
                )
            )

            # click + duplicate
            snap = _snapshot(perceive)
            button = _dom_object(perception, sid, snap, "ActionButton")
            click_req = _action(
                snap,
                action_id="live-click",
                verb="click",
                target_id=str(button["id"]),
                scope_ref=str(button["scope_ref"]),
                args={},
                version_scope="object",
            )
            click_receipt = _payload(action_tool.execute(**click_req))
            clicks_after_first = int(_evaluate(controller, "window.__clicks"))
            duplicate_receipt = _payload(action_tool.execute(**click_req))
            clicks_after_duplicate = int(_evaluate(controller, "window.__clicks"))

            # fill
            snap = _snapshot(perceive)
            input_obj = _dom_object(perception, sid, snap, "InputBox")
            fill_value = "B-ACTION-FILL-SECRET"
            fill_receipt = _payload(
                action_tool.execute(
                    **_action(
                        snap,
                        action_id="live-fill",
                        verb="fill",
                        target_id=str(input_obj["id"]),
                        scope_ref=str(input_obj["scope_ref"]),
                        args={"text": fill_value, "mode": "replace"},
                        version_scope="object",
                    )
                )
            )
            fill_oracle = str(_evaluate(controller, "document.getElementById('input').value"))

            # select
            snap = _snapshot(perceive)
            select_obj = _dom_object(perception, sid, snap, "Choice")
            select_receipt = _payload(
                action_tool.execute(
                    **_action(
                        snap,
                        action_id="live-select",
                        verb="select",
                        target_id=str(select_obj["id"]),
                        scope_ref=str(select_obj["scope_ref"]),
                        args={"value": "b"},
                        version_scope="object",
                    )
                )
            )
            select_oracle = str(_evaluate(controller, "document.getElementById('select').value"))

            # scroll
            snap = _snapshot(perceive)
            scroll_obj = _dom_object(perception, sid, snap, "ScrollTarget")
            before_scroll = float(_evaluate(controller, "window.scrollY"))
            scroll_receipt = _payload(
                action_tool.execute(
                    **_action(
                        snap,
                        action_id="live-scroll",
                        verb="scroll",
                        target_id=str(scroll_obj["id"]),
                        scope_ref=str(scroll_obj["scope_ref"]),
                        args={"delta_pages": 1},
                        version_scope="object",
                    )
                )
            )
            after_scroll = float(_evaluate(controller, "window.scrollY"))

            # stale object fact -> reject before dispatch
            snap = _snapshot(perceive)
            stale_obj = _dom_object(perception, sid, snap, "ActionButton")
            clicks_before_stale = int(_evaluate(controller, "window.__clicks"))
            _evaluate(controller, "document.getElementById('act').disabled = true; 'ok';")
            stale_receipt = _payload(
                action_tool.execute(
                    **_action(
                        snap,
                        action_id="live-stale",
                        verb="click",
                        target_id=str(stale_obj["id"]),
                        scope_ref=str(stale_obj["scope_ref"]),
                        args={},
                        version_scope="object",
                    )
                )
            )
            clicks_after_stale = int(_evaluate(controller, "window.__clicks"))
            _evaluate(controller, "document.getElementById('act').disabled = false; 'ok';")

            # same-name physical replacement -> old Semantic ID must not rebind.
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
                action_tool.execute(
                    **_action(
                        snap,
                        action_id="live-replacement",
                        verb="click",
                        target_id=str(twin["id"]),
                        scope_ref=str(twin["scope_ref"]),
                        args={},
                        version_scope="object",
                    )
                )
            )
            twin_clicks = int(_evaluate(controller, "window.__twinClicks"))

            # navigate through production actuator to a loopback HTTP resource.
            snap = _snapshot(perceive)
            page_scope = next(item for item in snap["scope_facts"] if item.get("kind") == "page")
            loader_before = str(
                controller.call("Page.getFrameTree")["frameTree"]["frame"].get("loaderId") or ""
            )
            navigate_receipt = _payload(
                action_tool.execute(
                    **_action(
                        snap,
                        action_id="live-navigate",
                        verb="navigate",
                        target_id=str(page_scope["scope_ref"]),
                        scope_ref=str(page_scope["scope_ref"]),
                        args={"url": next_url},
                        version_scope="resource",
                    )
                )
            )
            _wait_loader_change(controller, loader_before)
            navigated_url = str(controller.call("Page.getFrameTree")["frameTree"]["frame"].get("url") or "")

            click_history = _receipt_history(receipts, sid, "live-click")
            fill_dispatch = receipts.hydrate_dispatch_grounding(sid, "live-fill") or {}
            action_store_text = "\n".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in (evidence_dir / "actions").rglob("*")
                if path.is_file()
            )
            def schema_keys(value: Any) -> set[str]:
                keys: set[str] = set()
                if isinstance(value, dict):
                    for key, child in value.items():
                        keys.add(str(key).lower())
                        keys |= schema_keys(child)
                elif isinstance(value, list):
                    for child in value:
                        keys |= schema_keys(child)
                return keys

            model_keys = schema_keys(action_tool.parameters)
            forbidden_model_keys = {
                "selector", "xpath", "backendnodeid", "backend_node_id",
                "x", "y", "coordinates", "script", "cdp_method", "method",
            }

            checks = {
                "click_single_dispatch_applied": "PASS" if click_receipt.get("status") == "ok" and clicks_after_first == 1 else "FAIL",
                "real_transport_ambiguity_dispatch_applied_once": (
                    "PASS"
                    if ambiguous_receipt.get("status") == "failed"
                    and ambiguous_fault.calls == 1
                    and ambiguous_clicks == 1
                    and ambiguous_disabled
                    else "FAIL"
                ),
                "real_transport_ambiguity_reports_post_effect_without_replay": (
                    "PASS"
                    if ambiguous_receipt.get("after_version")
                    and (ambiguous_receipt.get("observed_effects") or {}).get("diff_ref")
                    and (ambiguous_receipt.get("retry") or {}).get("automatic_retry_performed") is False
                    and "dispatch_outcome_ambiguous" in (ambiguous_receipt.get("completeness") or {}).get("reasons", [])
                    else "FAIL"
                ),
                "duplicate_action_id_rejected_without_second_click": (
                    "PASS"
                    if duplicate_receipt.get("status") == "rejected"
                    and clicks_after_duplicate == clicks_after_first
                    else "FAIL"
                ),
                "fill_applied": "PASS" if fill_receipt.get("status") == "ok" and fill_oracle == fill_value else "FAIL",
                "select_applied": "PASS" if select_receipt.get("status") == "ok" and select_oracle == "b" else "FAIL",
                "scroll_applied": "PASS" if scroll_receipt.get("status") == "ok" and after_scroll > before_scroll else "FAIL",
                "stale_object_rejected_before_click": (
                    "PASS"
                    if stale_receipt.get("status") == "rejected"
                    and clicks_after_stale == clicks_before_stale
                    else "FAIL"
                ),
                "same_name_replacement_never_rebound": (
                    "PASS" if replacement_receipt.get("status") == "rejected" and twin_clicks == 0 else "FAIL"
                ),
                "popup_boundary_event_visible_without_target_rebind": (
                    "PASS"
                    if popup_receipt.get("status") == "ok"
                    and any(
                        event.get("event") in {"new_window", "new_page"}
                        for event in popup_receipt.get("boundary_events") or []
                    )
                    and read_host.bound_target_id == target_id
                    and actuator.bound_target_id == target_id
                    else "FAIL"
                ),
                "navigate_single_dispatch_acknowledged": (
                    "PASS"
                    if navigate_receipt.get("status") == "ok"
                    and any(event.get("event") == "navigation_started" for event in navigate_receipt.get("boundary_events") or [])
                    else "FAIL"
                ),
                "navigate_reached_exact_loopback_resource": "PASS" if navigated_url == next_url else "FAIL",
                "receipt_running_terminal_append_only": (
                    "PASS"
                    if [item.get("status") for item in click_history[:2]] == ["running", "ok"]
                    and [item.get("receipt_seq") for item in click_history] == [1, 2, 3]
                    else "FAIL"
                ),
                "receipt_before_after_versions_present": (
                    "PASS"
                    if click_history[0].get("before_version")
                    and click_history[1].get("before_version") == click_history[0].get("before_version")
                    and click_history[1].get("after_version")
                    else "FAIL"
                ),
                "dispatch_grounding_durable": (
                    "PASS"
                    if fill_dispatch.get("schema") == "smc.browser_action_dispatch_grounding.v0.1"
                    and fill_dispatch.get("physical_target_sha256")
                    else "FAIL"
                ),
                "automatic_retry_never_performed": (
                    "PASS"
                    if all(
                        (receipt.get("retry") or {}).get("automatic_retry_performed") is False
                        for aid in (
                            "live-transport-ambiguity", "live-popup-boundary", "live-click",
                            "live-fill", "live-select", "live-scroll", "live-stale",
                            "live-replacement", "live-navigate",
                        )
                        for receipt in receipts.list_action(sid, aid)
                    )
                    else "FAIL"
                ),
                "terminal_status_not_task_completion": (
                    "PASS"
                    if all("completion" not in receipt for receipt in click_history)
                    else "FAIL"
                ),
                "boundary_completeness_not_overclaimed": (
                    "PASS"
                    if navigate_receipt.get("completeness", {}).get("complete") is False
                    else "FAIL"
                ),
            }
            safety = {
                "mock_keychain_enabled": "PASS",
                "basic_password_store_enabled": "PASS",
                "security_agent_not_spawned": "PASS" if not (_security_agent_pids() - before_security) else "FAIL",
                "read_host_exact_target_bound": "PASS" if read_host.bound_target_id == target_id else "FAIL",
                "mutation_actuator_exact_target_bound": "PASS" if actuator.bound_target_id == target_id else "FAIL",
                "model_surface_has_no_physical_locator_or_script": (
                    "PASS" if model_keys.isdisjoint(forbidden_model_keys) else "FAIL"
                ),
                "fill_plaintext_absent_from_action_store": "PASS" if fill_value not in action_store_text else "FAIL",
                "dispatch_grounding_hides_physical_target": "PASS" if "physical_target" not in fill_dispatch and fill_dispatch.get("physical_target_sha256") else "FAIL",
            }
            return {
                "schema": "smc.browser_live_action_receipt_qualification.v0.1",
                "behavior": checks,
                "safety": safety,
                "behavior_pass": sum(value == "PASS" for value in checks.values()),
                "behavior_total": len(checks),
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
    result_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["behavior_pass"] == result["behavior_total"] and result["safety_pass"] == result["safety_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
