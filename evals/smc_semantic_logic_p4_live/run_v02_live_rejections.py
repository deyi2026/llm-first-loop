#!/usr/bin/env python3
"""P4-LIVE v0.2 real-Browser rejection rows V02-L06..V02-L16.

No model requests are made in this runner. It uses real Browser perception, real
ActionRef issuance/resolution, real execution binding/WAL and the real CDP actuator.
Each row injects exactly the frozen mechanical invalidity and proves zero unintended
physical dispatch; V02-L16 permits exactly the first intended dispatch and rejects the
exact duplicate without a second dispatch.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from evals.smc_semantic_logic_p4_live.run_v02_live_success import (
    _Controller,
    _CountingActuator,
    _evaluate,
    _find_ref,
    _free_loopback_port,
    _model_server_fact,
    _wal_attempt,
    chrome_args,
    fixture_server,
)
from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
from llm_loop.browser.action_ref import (
    ActionRefBindingStore,
    ActionRefIssueContext,
    ActionRefIssuer,
    ActionRefResolver,
)
from llm_loop.browser.action_ref_execution import ActionRefExecutionBridgeStore
from llm_loop.browser.action_ref_recovery import ActionRefCrashCorrelator
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.core.message import ToolCall, ToolResult
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import (
    ToolExecutionJournal,
    revoke_effect_binding_for_call,
)
from llm_loop.event_log.store import EventStore
from llm_loop.tools.builtin.browser_action_ref_kernel import ActionRefSemanticCompileBridge
from llm_loop.tools.builtin.browser_action_ref_mutation import (
    ActionRefMutationKernel,
    build_typed_action_ref_mutation_tools,
)
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.p4_live_scope import p4_live_canary_tool_scope
from llm_loop.tools.registry import ToolRegistry, tool_result_to_message

ROWS = {
    "V02-L06": "cross_session",
    "V02-L07": "cross_workspace",
    "V02-L08": "prior_run_generation",
    "V02-L09": "expired_binding",
    "V02-L10": "browser_runtime_restart",
    "V02-L11": "wrong_kind",
    "V02-L12": "integrity_corruption",
    "V02-L13": "stale_document_generation",
    "V02-L14": "target_replacement_before_first_use",
    "V02-L15": "effect_binding_absent_and_revoked",
    "V02-L16": "duplicate_exact_declaration_at_most_once",
}


class Harness:
    def __init__(
        self, root: Path, debug: str, target: dict[str, Any], controller: _Controller, base_url: str
    ) -> None:
        self.root = root
        self.debug = debug
        self.target_id = str(target["id"])
        self.controller = controller
        self.base_url = base_url
        self.clock = [1000.0]
        self.workspace = str(root.resolve())
        self.run_generation = "p4-live-v02-reject-run"
        self.events = EventStore(root / "events", enabled=True)
        self.sessions = SessionStore(root / "sessions", event_store=self.events)
        self.sid = self.sessions.create()
        self.pstore = BrowserPerceptionStore(
            root / "perception", retention_seconds=60, now_fn=lambda: self.clock[0]
        )
        self.bstore = ActionRefBindingStore(root / "action_refs", now_fn=lambda: self.clock[0])
        self.issuer = ActionRefIssuer(binding_store=self.bstore, perception_store=self.pstore)
        self.perception = BrowserPerceptionAdapter(
            store=self.pstore,
            action_ref_issuer=self.issuer,
            action_ref_context_getter=lambda: ActionRefIssueContext(
                workspace_scope=self.workspace,
                origin_run_generation=self.run_generation,
            ),
        )
        self.host = CdpReadOnlyBrowserHost(debug, target_id=self.target_id)
        self.projection = self.perception.snapshot(
            self.sid, self.host.capture(), projection_limit=300
        )
        snapshot_id = str((self.projection.get("snapshot") or {}).get("snapshot_id") or "")
        self.bundle = self.pstore.load_snapshot_bundle(self.sid, snapshot_id)
        self.refs = {
            "resource": str(self.projection.get("resource_action_ref") or ""),
            "click": _find_ref(self.projection, self.bundle, "ClickTarget", "button"),
            "fill": _find_ref(self.projection, self.bundle, "FillTarget", "textbox"),
            "select": _find_ref(self.projection, self.bundle, "SelectTarget", "combobox"),
            "scroll": _find_ref(self.projection, self.bundle, "ScrollTarget", "generic"),
        }
        self.receipts = BrowserActionReceiptStore(root / "browser_action")
        self.actuator = _CountingActuator(
            CdpBrowserMutationActuator(debug, target_id=self.target_id)
        )
        self.adapter = BrowserActionAdapter(
            perception=self.perception,
            receipt_store=self.receipts,
            capture_backend=self.host,
            actuator=self.actuator,
        )
        semantic = BrowserSemanticExecuteTool(
            perception=self.perception,
            action_adapter=self.adapter,
            session_id_getter=lambda: self.sid,
        )
        self.bridge = ActionRefExecutionBridgeStore(root / "audit" / "action_ref_execution")
        self.correlator = ActionRefCrashCorrelator(
            bridge_store=self.bridge,
            receipt_store=self.receipts,
        )
        kernel = ActionRefMutationKernel(
            resolver=ActionRefResolver(
                binding_store=self.bstore,
                perception_store=self.pstore,
            ),
            compiler=ActionRefSemanticCompileBridge(compiler=semantic),
            execution_bridge=self.bridge,
            crash_correlator=self.correlator,
            action_adapter=self.adapter,
        )
        self.registry = ToolRegistry()
        for tool in build_typed_action_ref_mutation_tools(kernel):
            self.registry.register(tool)
        self.journal = ToolExecutionJournal(
            event_store=self.events,
            result_root=root / "tool_execution",
            session_store=self.sessions,
            action_ref_recovery=self.correlator.recover_message,
        )

    def close(self) -> None:
        self.actuator.close()
        self.host.close()

    def call(
        self,
        *,
        label: str,
        tool_name: str = "browser_semantic_click",
        arguments: dict[str, Any] | None = None,
        sid: str | None = None,
        workspace: str | None = None,
        run_generation: str | None = None,
        revoke: bool = False,
        settle: bool = True,
    ) -> tuple[ToolResult, str | None]:
        call = ToolCall(
            id=f"call-{label}",
            name=tool_name,
            arguments=dict(arguments or {"action_ref": self.refs["click"]}),
        )
        owner_sid = sid or self.sid
        owner_workspace = workspace or self.workspace
        owner_run = run_generation or self.run_generation
        with (
            p4_live_canary_tool_scope(),
            _wal_attempt(
                sessions=self.sessions,
                journal=self.journal,
                sid=owner_sid,
                workspace=owner_workspace,
                run_generation=owner_run,
                call=call,
            ) as execution_id,
        ):
            if revoke and not revoke_effect_binding_for_call(call.id):
                raise RuntimeError("failed to revoke exact effect binding")
            result = self.registry.execute(call)
            if settle:
                tool_msg = tool_result_to_message(
                    result,
                    failure_guidance_enabled=False,
                    experience_guidance_enabled=False,
                    tool_guidance_mode=self.registry.tool_guidance_mode,
                )
                result_sha = self.journal.finished(
                    owner_sid,
                    execution_id=execution_id,
                    round_no=1,
                    call=call,
                    tool_message=tool_msg,
                )
                sess = self.sessions.load(owner_sid)
                sess.messages.append(tool_msg)
                self.sessions.save(sess)
                self.journal.receipt_committed(
                    owner_sid,
                    execution_id=execution_id,
                    round_no=1,
                    tool_call_id=call.id,
                    tool_name=call.name,
                    result_state_sha256=result_sha,
                    tool_message=tool_msg,
                )
            return result, execution_id


def _failure_fact(result: ToolResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "content": result.content,
        "error_type": result.error_type,
        "error_detail": result.error_detail,
    }


def _wait_ready(controller: _Controller) -> None:
    deadline = time.monotonic() + 5.0
    while _evaluate(controller, "document.readyState") != "complete":
        if time.monotonic() > deadline:
            raise RuntimeError("fixture readiness timeout")
        time.sleep(0.05)


def run_row(row: str, output: Path) -> int:
    if row not in ROWS:
        raise SystemExit(f"unsupported rejection row: {row}")
    model_fact = _model_server_fact()
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    with (
        fixture_server() as base_url,
        tempfile.TemporaryDirectory(prefix=f"lfl-{row.lower()}-profile-") as profile,
        tempfile.TemporaryDirectory(prefix=f"lfl-{row.lower()}-evidence-") as ev,
    ):
        port = _free_loopback_port()
        debug = f"http://127.0.0.1:{port}"
        args = chrome_args(chrome, Path(profile), port)
        args[-1] = base_url + "/fixture"
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        controller: _Controller | None = None
        harness: Harness | None = None
        try:
            from scripts.qualification.smc_browser_live_navigation import _wait_page

            target = _wait_page(debug)
            controller = _Controller(str(target["webSocketDebuggerUrl"]))
            controller.call("Page.enable")
            controller.call("Runtime.enable")
            _wait_ready(controller)
            harness = Harness(Path(ev), debug, target, controller, base_url)
            setup_mutations = 0
            facts: dict[str, Any] = {}

            if row == "V02-L06":
                other_sid = harness.sessions.create()
                result, _ = harness.call(label="cross-session", sid=other_sid)
                facts["result"] = _failure_fact(result)
            elif row == "V02-L07":
                other_workspace = harness.root / "other-workspace"
                other_workspace.mkdir()
                result, _ = harness.call(
                    label="cross-workspace", workspace=str(other_workspace.resolve())
                )
                facts["result"] = _failure_fact(result)
            elif row == "V02-L08":
                result, _ = harness.call(label="prior-run", run_generation="p4-live-v02-prior-run")
                facts["result"] = _failure_fact(result)
            elif row == "V02-L09":
                harness.clock[0] = 2000.0
                result, _ = harness.call(label="expired")
                facts["result"] = _failure_fact(result)
            elif row == "V02-L10":
                harness.pstore.runtime_nonce = "p4-live-v02-restarted-runtime"
                result, _ = harness.call(label="runtime-restart")
                facts["result"] = _failure_fact(result)
            elif row == "V02-L11":
                result, _ = harness.call(
                    label="wrong-kind",
                    tool_name="browser_semantic_navigate",
                    arguments={
                        "action_ref": harness.refs["click"],
                        "url": base_url + "/dest",
                    },
                )
                facts["result"] = _failure_fact(result)
            elif row == "V02-L12":
                path = harness.bstore.record_path(harness.refs["click"])
                raw = json.loads(path.read_text(encoding="utf-8"))
                raw["grounding_ref"] = "grounding://browser/v0.1/tampered"
                path.write_text(json.dumps(raw, sort_keys=True), encoding="utf-8")
                result, _ = harness.call(label="integrity-corruption")
                facts["result"] = _failure_fact(result)
            elif row == "V02-L13":
                controller.call("Page.navigate", {"url": base_url + "/dest"})
                setup_mutations += 1
                _wait_ready(controller)
                result, _ = harness.call(label="stale-document")
                facts["result"] = _failure_fact(result)
                facts["fixture_setup_navigation"] = True
            elif row == "V02-L14":
                # Replace the actuator's current target view before first ActionRef use.
                original = harness.target_id
                replacement = original + "-replacement"
                real_http_get = harness.actuator.inner._http_get_json  # noqa: SLF001

                def replacement_view(url: str) -> list[dict[str, Any]]:
                    pages = copy.deepcopy(real_http_get(url))
                    for page in pages:
                        if str(page.get("id") or "") == original:
                            page["id"] = replacement
                            page["webSocketDebuggerUrl"] = str(
                                page.get("webSocketDebuggerUrl") or ""
                            ).replace(original, replacement)
                    return pages

                harness.actuator.inner._configured_target_id = ""  # noqa: SLF001
                harness.actuator.inner._http_get_json = replacement_view  # noqa: SLF001
                result, _ = harness.call(label="target-replacement")
                facts["result"] = _failure_fact(result)
                facts["replacement_is_distinct"] = replacement != original
            elif row == "V02-L15":
                # First prove absent binding without constructing any outer WAL execution.
                direct = harness.registry.execute(
                    ToolCall(
                        id="call-effect-absent",
                        name="browser_semantic_click",
                        arguments={"action_ref": harness.refs["click"]},
                    )
                )
                revoked, _ = harness.call(label="effect-revoked", revoke=True)
                facts["absent"] = _failure_fact(direct)
                facts["revoked"] = _failure_fact(revoked)
            elif row == "V02-L16":
                first, first_execution = harness.call(label="duplicate-first")
                first_dispatches = harness.actuator.dispatch_count
                first_clicks = int(_evaluate(controller, "window.__p4clicks || 0"))
                second, second_execution = harness.call(label="duplicate-second")
                facts.update(
                    {
                        "first": _failure_fact(first),
                        "second": _failure_fact(second),
                        "first_execution_id": first_execution,
                        "second_execution_id": second_execution,
                        "first_dispatches": first_dispatches,
                        "first_clicks": first_clicks,
                    }
                )

            dispatches = harness.actuator.dispatch_count
            clicks = int(_evaluate(controller, "window.__p4clicks || 0"))
            if row == "V02-L16":
                passed = (
                    facts["first"]["status"] == "success"
                    and facts["second"]["status"] == "failure"
                    and dispatches == 1
                    and clicks == 1
                    and "duplicate_action_id" in str(facts["second"]["content"])
                )
            elif row == "V02-L15":
                passed = (
                    facts["absent"]["status"] == "failure"
                    and facts["revoked"]["status"] == "failure"
                    and dispatches == 0
                    and clicks == 0
                    and "action_ref_effect_binding_required" in str(facts["absent"]["content"])
                    and "action_ref_effect_binding_revoked" in str(facts["revoked"]["content"])
                )
            else:
                result_fact = facts["result"]
                passed = result_fact["status"] == "failure" and dispatches == 0 and clicks == 0

            evidence = {
                "schema": "smc.p4_live.v02.rejection_row.v0.2",
                "row": row,
                "condition": ROWS[row],
                "status": "PASS" if passed else "FAIL",
                "model_server": model_fact,
                "model_requests": 0,
                "browser_dispatches": dispatches,
                "click_effects": clicks,
                "fixture_setup_mutations": setup_mutations,
                "automatic_retry_performed": False,
                "facts": facts,
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2))
            return 0 if passed else 2
        finally:
            if harness is not None:
                with suppress(Exception):
                    harness.close()
            if controller is not None:
                controller.close()
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--row", required=True, choices=sorted(ROWS))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run_row(args.row, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
