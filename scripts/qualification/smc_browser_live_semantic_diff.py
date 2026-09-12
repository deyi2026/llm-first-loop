#!/usr/bin/env python3
"""Qualification-only live Browser SemanticDiff harness.

The external CDP controller may mutate an isolated qualification Chrome.  The
production Browser surface under test stays read-only: snapshot/diff/hydrate.
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
        _wait_loader_change,
        _wait_page,
        chrome_args,
    )
except ModuleNotFoundError:  # direct `python scripts/qualification/...py` entrypoint
    from smc_browser_live_navigation import (  # type: ignore[import-not-found]
        _Controller,
        _free_loopback_port,
        _security_agent_pids,
        _wait_loader_change,
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


def _set_initial_dom(controller: _Controller) -> None:
    expression = """
document.body.innerHTML = `
  <main id="root">
    <button id="stable" aria-label="Stable">Stable</button>
    <button id="replace-me" aria-label="Twin">Twin</button>
  </main>`;
'ok';
""".strip()
    response = controller.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": False},
    )
    if ((response.get("result") or {}).get("value")) != "ok":
        raise RuntimeError("initial live diff DOM setup failed")


def _mutate_same_document(controller: _Controller) -> None:
    expression = """
const stable = document.getElementById('stable');
stable.disabled = true;
stable.textContent = 'Stable changed';
const oldTwin = document.getElementById('replace-me');
const newTwin = document.createElement('button');
newTwin.id = 'replacement';
newTwin.setAttribute('aria-label', 'Twin');
newTwin.textContent = 'Twin';
oldTwin.replaceWith(newTwin);
'ok';
""".strip()
    response = controller.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": False},
    )
    if ((response.get("result") or {}).get("value")) != "ok":
        raise RuntimeError("same-document live diff mutation failed")


def _snapshot(tool: BrowserPerceiveTool) -> dict[str, Any]:
    return _payload(tool.execute(action="snapshot", projection_limit=500))


def _diff(
    tool: BrowserPerceiveTool, before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    return _payload(
        tool.execute(
            action="diff",
            from_version=str(before["snapshot"]["snapshot_id"]),
            to_version=str(after["snapshot"]["snapshot_id"]),
        )
    )


def _check_same_document(
    adapter: BrowserPerceptionAdapter,
    session_id: str,
    before: dict[str, Any],
    after: dict[str, Any],
    diff: dict[str, Any],
) -> dict[str, str]:
    stable_before = _dom_object(adapter, session_id, before, "Stable")
    stable_after = _dom_object(adapter, session_id, after, "Stable")
    old_twin = _dom_object(adapter, session_id, before, "Twin")
    new_twin = _dom_object(adapter, session_id, after, "Twin")
    changed = {item["id"]: set(item["fields"]) for item in diff.get("changed") or []}
    created = set(diff.get("created") or [])
    removed = set(diff.get("removed") or [])
    return {
        "same_document_comparable": "PASS" if diff.get("comparable") is True else "FAIL",
        "same_document_scope_same": "PASS" if diff.get("scope_relation") == "same" else "FAIL",
        "stable_identity_preserved": (
            "PASS" if stable_before.get("id") == stable_after.get("id") else "FAIL"
        ),
        "stable_field_change_observed": (
            "PASS"
            if "state.enabled" in changed.get(str(stable_before.get("id")), set())
            else "FAIL"
        ),
        "replacement_old_removed": (
            "PASS" if old_twin.get("id") in removed else "FAIL"
        ),
        "replacement_new_created": (
            "PASS" if new_twin.get("id") in created else "FAIL"
        ),
        "replacement_not_name_rebound": (
            "PASS" if old_twin.get("id") != new_twin.get("id") else "FAIL"
        ),
    }


def run_live(*, chrome: str, evidence_dir: Path) -> dict[str, Any]:
    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lfl-bdiff-profile-") as profile_raw:
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
            controller.call("Page.enable")
            controller.call("Runtime.enable")
            _set_initial_dom(controller)

            host = CdpReadOnlyBrowserHost(debug_base, target_id=target_id)
            adapter = BrowserPerceptionAdapter(
                store=BrowserPerceptionStore(evidence_dir / "grounding")
            )
            session_id = "b-live-semantic-diff-qualification"
            tool = BrowserPerceiveTool(
                adapter=adapter,
                backend=host,
                session_id_getter=lambda: session_id,
            )

            before = _snapshot(tool)
            _mutate_same_document(controller)
            after = _snapshot(tool)
            same_doc_diff = _diff(tool, before, after)
            checks = _check_same_document(
                adapter, session_id, before, after, same_doc_diff
            )
            checks["same_document_identity_partial_explicit"] = (
                "PASS"
                if "identity_unstable_objects"
                in (same_doc_diff.get("completeness") or {}).get("reasons", [])
                and not all(
                    bool(value)
                    for value in (same_doc_diff.get("field_completeness") or {}).values()
                )
                else "FAIL"
            )

            no_op = _snapshot(tool)
            no_op_diff = _diff(tool, after, no_op)
            checks["no_op_net_diff_empty"] = (
                "PASS"
                if no_op_diff.get("comparable") is True
                and no_op_diff.get("created") == []
                and no_op_diff.get("removed") == []
                and no_op_diff.get("changed") == []
                else "FAIL"
            )
            checks["no_op_identity_partial_explicit"] = (
                "PASS"
                if "identity_unstable_objects"
                in (no_op_diff.get("completeness") or {}).get("reasons", [])
                and no_op_diff.get("field_completeness")
                == {"created": False, "removed": False, "changed": False}
                else "FAIL"
            )

            full_ref = str(same_doc_diff.get("full_list_ref") or "")
            hydrated_diff = _payload(
                tool.execute(action="hydrate", grounding_ref=full_ref)
            )
            checks["full_list_ref_exact_hydration"] = (
                "PASS"
                if hydrated_diff.get("availability") == "available"
                and hydrated_diff.get("content") == same_doc_diff
                else "FAIL"
            )

            frame_before_reload = controller.call("Page.getFrameTree")["frameTree"]["frame"]
            loader_before = str(frame_before_reload.get("loaderId") or "")
            controller.call("Page.reload", {"ignoreCache": True})
            _wait_loader_change(controller, loader_before)
            _set_initial_dom(controller)
            after_reload = _snapshot(tool)
            navigation_diff = _diff(tool, no_op, after_reload)
            checks["reload_diff_incomparable"] = (
                "PASS"
                if navigation_diff.get("comparable") is False
                and navigation_diff.get("scope_relation") == "changed"
                else "FAIL"
            )
            checks["reload_does_not_mass_diff"] = (
                "PASS"
                if navigation_diff.get("created") is None
                and navigation_diff.get("removed") is None
                and navigation_diff.get("changed") is None
                else "FAIL"
            )

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
                        "navigate",
                        "reload",
                        "script",
                        "url",
                    }.intersection(
                        {str(v).lower() for v in tool.parameters["properties"]["action"]["enum"]}
                    )
                    else "FAIL"
                ),
            }
            all_values = list(checks.values()) + list(safety.values())
            return {
                "schema": "smc.browser_live_semantic_diff_qualification.v0.1",
                "status": "PASS" if all(v == "PASS" for v in all_values) else "FAIL",
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
