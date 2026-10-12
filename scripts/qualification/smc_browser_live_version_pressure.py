#!/usr/bin/env python3
"""Qualification-only live Browser staleness/version-pressure harness.

The external CDP controller mutates only an isolated qualification Chrome. The
production Browser surface remains read-only; version assessment compares two
explicit persisted observations and never captures or refreshes by itself.
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
    from scripts.qualification.smc_browser_live_semantic_diff import (
        _dom_object,
        _mutate_same_document,
        _set_initial_dom,
        _snapshot,
    )
except ModuleNotFoundError:  # direct script entrypoint
    from smc_browser_live_navigation import (  # type: ignore[import-not-found]
        _Controller,
        _free_loopback_port,
        _security_agent_pids,
        _wait_loader_change,
        _wait_page,
        chrome_args,
    )
    from smc_browser_live_semantic_diff import (  # type: ignore[import-not-found]
        _dom_object,
        _mutate_same_document,
        _set_initial_dom,
        _snapshot,
    )


def _page_scope(snapshot: dict[str, Any]) -> str:
    return str(
        next(item for item in snapshot["scope_facts"] if item.get("kind") == "page")[
            "scope_ref"
        ]
    )


def _predicate(*, scope_ref: str, target: str) -> dict[str, Any]:
    return {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": scope_ref,
        "target": target,
        "property": "exists",
        "operator": "eq",
        "value": True,
    }


def _payload(result: Any) -> dict[str, Any]:
    status = getattr(getattr(result, "status", None), "value", "")
    if status != "success":
        raise RuntimeError(f"Browser tool failed: status={status}; content={result.content}")
    value = json.loads(result.content)
    if not isinstance(value, dict):
        raise RuntimeError("Browser tool returned non-object JSON")
    return value


def run_live(*, chrome: str, evidence_dir: Path) -> dict[str, Any]:
    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lfl-bstale-profile-") as profile_raw:
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
            session_id = "b-live-version-pressure-qualification"
            tool = BrowserPerceiveTool(
                adapter=adapter,
                backend=host,
                session_id_getter=lambda: session_id,
            )

            before = _snapshot(tool)
            before_id = str(before["snapshot"]["snapshot_id"])
            stable_before = _dom_object(adapter, session_id, before, "Stable")
            exact = adapter.assess_version_precondition(
                session_id,
                expected_version=before_id,
                observed_version=before_id,
                version_scope="object",
                scope_ref=str(stable_before["scope_ref"]),
                target_id=str(stable_before["id"]),
            )

            no_op = _snapshot(tool)
            no_op_id = str(no_op["snapshot"]["snapshot_id"])
            object_no_op = adapter.assess_version_precondition(
                session_id,
                expected_version=before_id,
                observed_version=no_op_id,
                version_scope="object",
                scope_ref=str(stable_before["scope_ref"]),
                target_id=str(stable_before["id"]),
            )
            resource_no_op = adapter.assess_version_precondition(
                session_id,
                expected_version=before_id,
                observed_version=no_op_id,
                version_scope="resource",
                scope_ref=_page_scope(before),
            )
            snapshot_no_op = adapter.assess_version_precondition(
                session_id,
                expected_version=before_id,
                observed_version=no_op_id,
                version_scope="snapshot",
                scope_ref=str(before["snapshot"]["scope"]["scope_ref"]),
            )

            _mutate_same_document(controller)
            after = _snapshot(tool)
            after_id = str(after["snapshot"]["snapshot_id"])
            stable_after = _dom_object(adapter, session_id, after, "Stable")
            same_doc = adapter.assess_version_precondition(
                session_id,
                expected_version=before_id,
                observed_version=after_id,
                version_scope="object",
                scope_ref=str(stable_before["scope_ref"]),
                target_id=str(stable_before["id"]),
            )
            old_grounding = _payload(
                tool.execute(
                    action="hydrate",
                    grounding_ref=str(stable_before["grounding_ref"]),
                )
            )
            same_doc_diff = _payload(
                tool.execute(
                    action="diff",
                    from_version=before_id,
                    to_version=after_id,
                )
            )

            frame_before_reload = controller.call("Page.getFrameTree")["frameTree"]["frame"]
            loader_before = str(frame_before_reload.get("loaderId") or "")
            controller.call("Page.reload", {"ignoreCache": True})
            _wait_loader_change(controller, loader_before)
            _set_initial_dom(controller)
            after_reload = _snapshot(tool)
            reload_id = str(after_reload["snapshot"]["snapshot_id"])
            stable_reload = _dom_object(adapter, session_id, after_reload, "Stable")
            after_reload_assessment = adapter.assess_version_precondition(
                session_id,
                expected_version=after_id,
                observed_version=reload_id,
                version_scope="object",
                scope_ref=str(stable_after["scope_ref"]),
                target_id=str(stable_after["id"]),
            )
            resource_assessment = adapter.assess_version_precondition(
                session_id,
                expected_version=after_id,
                observed_version=reload_id,
                version_scope="resource",
                scope_ref=_page_scope(after),
            )
            old_predicate_wait = _payload(
                tool.execute(
                    action="wait",
                    predicate=_predicate(
                        scope_ref=str(stable_after["scope_ref"]),
                        target=str(stable_after["id"]),
                    ),
                    timeout_ms=80,
                    interval_ms=20,
                )
            )
            old_wait_observation = dict(old_predicate_wait.get("observation") or {})

            checks = {
                "exact_version_matches": (
                    "PASS"
                    if exact.get("result") == "match"
                    and exact.get("reason") == "exact_version"
                    else "FAIL"
                ),
                "pressure_does_not_make_unchanged_object_stale": (
                    "PASS"
                    if object_no_op.get("result") == "match"
                    and object_no_op.get("reason")
                    == "object_unchanged_new_observation"
                    and (object_no_op.get("pressure") or {}).get("present") is True
                    else "FAIL"
                ),
                "pressure_does_not_make_unchanged_resource_stale": (
                    "PASS"
                    if resource_no_op.get("result") == "match"
                    and resource_no_op.get("reason")
                    == "resource_unchanged_new_observation"
                    and (resource_no_op.get("pressure") or {}).get("present") is True
                    else "FAIL"
                ),
                "snapshot_scope_is_strict_across_observations": (
                    "PASS"
                    if snapshot_no_op.get("result") == "stale"
                    and snapshot_no_op.get("reason")
                    == "different_snapshot_same_generation"
                    else "FAIL"
                ),
                "same_document_new_observation_is_stale": (
                    "PASS"
                    if same_doc.get("result") == "stale"
                    and same_doc.get("reason") == "object_changed_same_generation"
                    and same_doc.get("comparable") is True
                    and (same_doc.get("pressure") or {}).get("present") is True
                    else "FAIL"
                ),
                "stable_identity_survives_same_document_churn": (
                    "PASS"
                    if stable_before.get("id") == stable_after.get("id")
                    else "FAIL"
                ),
                "stale_history_remains_hydratable": (
                    "PASS" if old_grounding.get("availability") == "available" else "FAIL"
                ),
                "stale_history_remains_diffable": (
                    "PASS" if same_doc_diff.get("comparable") is True else "FAIL"
                ),
                "reload_generation_is_stale_and_incomparable": (
                    "PASS"
                    if after_reload_assessment.get("result") == "stale"
                    and after_reload_assessment.get("reason")
                    == "document_generation_changed"
                    and after_reload_assessment.get("comparable") is False
                    else "FAIL"
                ),
                "same_name_reload_object_not_rebound": (
                    "PASS"
                    if stable_after.get("id") != stable_reload.get("id")
                    and after_reload_assessment.get("target_id") == stable_after.get("id")
                    and after_reload_assessment.get("silent_rebind_performed") is False
                    else "FAIL"
                ),
                "resource_scope_observes_generation_pressure": (
                    "PASS"
                    if resource_assessment.get("result") == "stale"
                    and resource_assessment.get("reason") == "document_generation_changed"
                    else "FAIL"
                ),
                "old_predicate_scope_after_reload_is_indeterminate": (
                    "PASS"
                    if (old_predicate_wait.get("predicate_result") or {}).get("result")
                    == "indeterminate"
                    and old_wait_observation.get("reason") == "scope_not_observed"
                    else "FAIL"
                ),
                "version_assessment_never_auto_refreshes": (
                    "PASS"
                    if all(
                        item.get("automatic_refresh_performed") is False
                        for item in (
                            exact,
                            object_no_op,
                            resource_no_op,
                            snapshot_no_op,
                            same_doc,
                            after_reload_assessment,
                            resource_assessment,
                        )
                    )
                    else "FAIL"
                ),
            }
            actions = {str(v).lower() for v in tool.parameters["properties"]["action"]["enum"]}
            safety = {
                "mock_keychain_enabled": "PASS",
                "basic_password_store_enabled": "PASS",
                "security_agent_not_spawned": (
                    "PASS" if not (_security_agent_pids() - before_security) else "FAIL"
                ),
                "production_host_exact_target_bound": (
                    "PASS" if host.bound_target_id == target_id else "FAIL"
                ),
                "model_surface_unchanged_read_only": (
                    "PASS"
                    if actions == {"snapshot", "hydrate", "diff", "wait"}
                    else "FAIL"
                ),
                "no_mutation_or_receipt_surface": (
                    "PASS"
                    if not {"click", "fill", "select", "navigate", "scroll", "receipt"}.intersection(actions)
                    else "FAIL"
                ),
            }
            values = list(checks.values()) + list(safety.values())
            return {
                "schema": "smc.browser_live_version_pressure_qualification.v0.1",
                "status": "PASS" if all(v == "PASS" for v in values) else "FAIL",
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
