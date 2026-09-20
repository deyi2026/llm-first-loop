#!/usr/bin/env python3
"""P4-LIVE v0.2 crash/ambiguity rows V02-L17..V02-L20.

The rows run against a real isolated Browser fixture and production ActionRef/WAL /
receipt authorities. Fault injection occurs only at the frozen crash boundary. No model
request is made and no automatic replay is permitted.
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

from evals.smc_semantic_logic_p4_live.run_v02_live_rejections import Harness, _wait_ready
from evals.smc_semantic_logic_p4_live.run_v02_live_success import (
    _Controller,
    _evaluate,
    _free_loopback_port,
    _model_server_fact,
    _wal_attempt,
    chrome_args,
    fixture_server,
)
from llm_loop.core.message import ToolCall, ToolResult
from llm_loop.tools.p4_live_scope import p4_live_canary_tool_scope
from llm_loop.tools.registry import tool_result_to_message

ROWS = {
    "V02-L17": "crash_after_execution_prepare_before_browser_running",
    "V02-L18": "running_receipt_dispatch_ambiguity_no_replay",
    "V02-L19": "terminal_browser_receipt_outer_finished_missing_recover_exactly",
    "V02-L20": "transport_ambiguity_after_possible_effect_no_replay",
}


def _click_call(harness: Harness, label: str) -> ToolCall:
    return ToolCall(
        id=f"call-{label}",
        name="browser_semantic_click",
        arguments={"action_ref": harness.refs["click"]},
    )


def _recovery_fact(harness: Harness, execution_id: str) -> dict[str, Any]:
    decision = harness.correlator.classify(harness.sid, execution_id)
    sess = harness.sessions.load(harness.sid)
    recovered_count = harness.journal.recover(harness.sid, sess)
    recovered = [
        msg
        for msg in sess.messages
        if msg.role == "tool"
        and isinstance(msg.metadata, dict)
        and "tool_execution_recovery" in msg.metadata
    ]
    latest = recovered[-1] if recovered else None
    return {
        "classification": decision.state if decision is not None else None,
        "recovered_count": recovered_count,
        "recovered_status": latest.status.value if latest and latest.status else None,
        "recovered_content": latest.content if latest else None,
        "recovery_metadata": (
            dict(latest.metadata.get("tool_execution_recovery") or {}) if latest else None
        ),
    }


def _settle(harness: Harness, call: ToolCall, execution_id: str, result: ToolResult) -> bool:
    tool_msg = tool_result_to_message(
        result,
        failure_guidance_enabled=False,
        experience_guidance_enabled=False,
        tool_guidance_mode=harness.registry.tool_guidance_mode,
    )
    result_sha = harness.journal.finished(
        harness.sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        tool_message=tool_msg,
    )
    sess = harness.sessions.load(harness.sid)
    sess.messages.append(tool_msg)
    harness.sessions.save(sess)
    return harness.journal.receipt_committed(
        harness.sid,
        execution_id=execution_id,
        round_no=1,
        tool_call_id=call.id,
        tool_name=call.name,
        result_state_sha256=result_sha,
        tool_message=tool_msg,
    )


def run_row(row: str, output: Path) -> int:
    if row not in ROWS:
        raise SystemExit(f"unsupported recovery row: {row}")
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
            call = _click_call(harness, row.lower())
            facts: dict[str, Any] = {}
            execution_id = ""

            if row == "V02-L17":
                real_arm = harness.correlator.arm_receipt_cursor

                def crash_after_prepared(
                    session_id: str, exact_execution_id: str
                ) -> dict[str, Any]:
                    # PREPARED must already exist when this boundary is reached.
                    prepared = harness.bridge.load_exact(exact_execution_id)
                    facts["prepared_before_crash"] = bool(prepared)
                    raise SystemExit("v02-l17-stop-after-prepared")

                harness.correlator.arm_receipt_cursor = crash_after_prepared  # type: ignore[method-assign]
                try:
                    with (
                        p4_live_canary_tool_scope(),
                        _wal_attempt(
                            sessions=harness.sessions,
                            journal=harness.journal,
                            sid=harness.sid,
                            workspace=harness.workspace,
                            run_generation=harness.run_generation,
                            call=call,
                        ) as execution_id,
                    ):
                        harness.registry.execute(call)
                except SystemExit as exc:
                    facts["fault"] = str(exc)
                finally:
                    harness.correlator.arm_receipt_cursor = real_arm  # type: ignore[method-assign]
                if not execution_id:
                    raise RuntimeError("L17 missing outer execution id")
                prepared = harness.bridge.load_exact(execution_id)
                action_id = str(prepared.get("inner_action_id") or "")
                facts["receipt_statuses_before_recovery"] = [
                    item.get("status")
                    for item in harness.receipts.list_action(harness.sid, action_id)
                ]
                facts["recovery"] = _recovery_fact(harness, execution_id)
                passed = (
                    facts.get("prepared_before_crash") is True
                    and harness.actuator.dispatch_count == 0
                    and facts["receipt_statuses_before_recovery"] == []
                    and facts["recovery"]["classification"] == "prepared_before_browser_running"
                    and facts["recovery"]["recovered_count"] == 1
                    and facts["recovery"]["recovery_metadata"].get("auto_reexecuted") is False
                )

            elif row == "V02-L18":
                real_append = harness.receipts.append

                def append_then_crash(
                    session_id: str, action_id: str, receipt: dict[str, Any]
                ) -> dict[str, Any]:
                    persisted = real_append(session_id, action_id, receipt)
                    if receipt.get("status") == "running":
                        raise SystemExit("v02-l18-stop-after-running")
                    return persisted

                harness.receipts.append = append_then_crash  # type: ignore[method-assign]
                try:
                    with (
                        p4_live_canary_tool_scope(),
                        _wal_attempt(
                            sessions=harness.sessions,
                            journal=harness.journal,
                            sid=harness.sid,
                            workspace=harness.workspace,
                            run_generation=harness.run_generation,
                            call=call,
                        ) as execution_id,
                    ):
                        harness.registry.execute(call)
                except SystemExit as exc:
                    facts["fault"] = str(exc)
                finally:
                    harness.receipts.append = real_append  # type: ignore[method-assign]
                if not execution_id:
                    raise RuntimeError("L18 missing outer execution id")
                prepared = harness.bridge.load_exact(execution_id)
                action_id = str(prepared.get("inner_action_id") or "")
                facts["receipt_statuses_before_recovery"] = [
                    item.get("status")
                    for item in harness.receipts.list_action(harness.sid, action_id)
                ]
                facts["recovery"] = _recovery_fact(harness, execution_id)
                passed = (
                    harness.actuator.dispatch_count == 0
                    and facts["receipt_statuses_before_recovery"] == ["running"]
                    and facts["recovery"]["classification"] == "browser_running_outcome_unknown"
                    and facts["recovery"]["recovered_count"] == 1
                    and facts["recovery"]["recovery_metadata"].get("auto_reexecuted") is False
                )

            elif row == "V02-L19":
                with (
                    p4_live_canary_tool_scope(),
                    _wal_attempt(
                        sessions=harness.sessions,
                        journal=harness.journal,
                        sid=harness.sid,
                        workspace=harness.workspace,
                        run_generation=harness.run_generation,
                        call=call,
                    ) as execution_id,
                ):
                    result = harness.registry.execute(call)
                prepared = harness.bridge.load_exact(execution_id)
                action_id = str(prepared.get("inner_action_id") or "")
                facts["tool_status_before_crash"] = result.status.value
                facts["receipt_statuses_before_recovery"] = [
                    item.get("status")
                    for item in harness.receipts.list_action(harness.sid, action_id)
                ]
                facts["recovery"] = _recovery_fact(harness, execution_id)
                facts["clicks"] = int(_evaluate(controller, "window.__p4clicks || 0"))
                passed = (
                    result.status.value == "success"
                    and harness.actuator.dispatch_count == 1
                    and facts["clicks"] == 1
                    and facts["receipt_statuses_before_recovery"] == ["running", "ok"]
                    and facts["recovery"]["classification"] == "browser_terminal_exact"
                    and facts["recovery"]["recovered_count"] == 1
                    and facts["recovery"]["recovery_metadata"].get("auto_reexecuted") is False
                    and facts["recovery"]["recovery_metadata"].get("browser_receipt_status") == "ok"
                    and harness.actuator.dispatch_count == 1
                )

            else:  # V02-L20
                real_dispatch = harness.actuator.dispatch

                def dispatch_then_transport_error(
                    *, verb: str, physical_target: str | None, args: dict[str, Any]
                ) -> Any:
                    dispatched = real_dispatch(
                        verb=verb, physical_target=physical_target, args=args
                    )
                    if not dispatched.acknowledged:
                        raise RuntimeError("fixture dispatch unexpectedly unacknowledged")
                    raise ConnectionError("v02-l20-transport-lost-after-possible-effect")

                harness.actuator.dispatch = dispatch_then_transport_error  # type: ignore[method-assign]
                with (
                    p4_live_canary_tool_scope(),
                    _wal_attempt(
                        sessions=harness.sessions,
                        journal=harness.journal,
                        sid=harness.sid,
                        workspace=harness.workspace,
                        run_generation=harness.run_generation,
                        call=call,
                    ) as execution_id,
                ):
                    result = harness.registry.execute(call)
                    outer_committed = _settle(harness, call, execution_id, result)
                harness.actuator.dispatch = real_dispatch  # type: ignore[method-assign]
                prepared = harness.bridge.load_exact(execution_id)
                action_id = str(prepared.get("inner_action_id") or "")
                history = harness.receipts.list_action(harness.sid, action_id)
                facts["tool_status"] = result.status.value
                facts["tool_content"] = result.content
                facts["receipt_statuses"] = [item.get("status") for item in history]
                facts["terminal_completeness"] = (
                    dict(history[-1].get("completeness") or {}) if history else None
                )
                facts["terminal_retry"] = dict(history[-1].get("retry") or {}) if history else None
                facts["outer_receipt_committed"] = bool(outer_committed)
                facts["clicks"] = int(_evaluate(controller, "window.__p4clicks || 0"))
                # A terminal ambiguous failure is durable; a later recovery must not replay.
                sess = harness.sessions.load(harness.sid)
                recovered_again = harness.journal.recover(harness.sid, sess)
                facts["recovered_again"] = recovered_again
                passed = (
                    result.status.value == "failure"
                    and harness.actuator.dispatch_count == 1
                    and facts["clicks"] == 1
                    and facts["receipt_statuses"] == ["running", "failed"]
                    and "dispatch_outcome_ambiguous"
                    in list((facts["terminal_completeness"] or {}).get("reasons") or [])
                    and (facts["terminal_retry"] or {}).get("automatic_retry_performed") is False
                    and facts["outer_receipt_committed"] is True
                    and recovered_again == 0
                )

            evidence = {
                "schema": "smc.p4_live.v02.recovery_row.v0.2",
                "row": row,
                "condition": ROWS[row],
                "status": "PASS" if passed else "FAIL",
                "model_server": model_fact,
                "model_requests": 0,
                "browser_dispatches": harness.actuator.dispatch_count,
                "click_effects": int(_evaluate(controller, "window.__p4clicks || 0")),
                "automatic_replay_performed": False,
                "execution_id": execution_id,
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
