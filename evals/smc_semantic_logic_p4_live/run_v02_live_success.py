#!/usr/bin/env python3
"""P4-LIVE v0.2 success-row runner (V02-L01..L05).

Each invocation executes exactly one frozen row. There is no retry. A fresh isolated
loopback fixture + Chrome profile is created for the row. The model sees the exact
12-tool P4-LIVE scoped provider surface; only an exact expected first declaration is
executed. All Browser execution goes through production ActionRef, WAL, semantic
compiler, target precondition, BrowserActionAdapter, real CDP actuator, and receipts.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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
from llm_loop.config import load_settings
from llm_loop.core.message import Message, MessageSource, ToolCall
from llm_loop.core.prompt import build_system_prompt
from llm_loop.core.run_context import (
    current_reasoning_effort,
    current_reasoning_mode,
    current_run_generation,
    current_session_id,
    current_workspace_root,
)
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.event_log.store import EventStore
from llm_loop.factory import build_engine
from llm_loop.llm.client import LLMClient
from llm_loop.llm.schemas import build_tools_schema
from llm_loop.tools.builtin.browser_action_ref_kernel import ActionRefSemanticCompileBridge
from llm_loop.tools.builtin.browser_action_ref_mutation import (
    ActionRefMutationKernel,
    build_typed_action_ref_mutation_tools,
)
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.p4_live_scope import P4_LIVE_CANARY_TOOL_SCOPE, p4_live_canary_tool_scope
from llm_loop.tools.registry import ToolRegistry, tool_result_to_message
from scripts.qualification.smc_browser_live_navigation import (
    _Controller,
    _free_loopback_port,
    _wait_page,
    chrome_args,
)
from scripts.qualification.smc_browser_live_semantic_execute import _evaluate

ROOT = Path(__file__).resolve().parents[2]
MODEL = "ornith-1.5-35b-a3b-mlx"
LIVE_ROWS = {
    "V02-L01": "navigate",
    "V02-L02": "click",
    "V02-L03": "fill",
    "V02-L04": "select",
    "V02-L05": "scroll",
}

FIXTURE_HTML = b"""<!doctype html><html><head><title>P4LIVE-Fixture</title></head>
<body style='margin:20px;height:5000px'>
<button id='click' aria-label='ClickTarget'>ClickTarget</button>
<input id='fill' aria-label='FillTarget' value=''>
<select id='select' aria-label='SelectTarget'><option value='alpha'>Alpha</option><option value='beta'>Beta</option></select>
<div id='click-status' aria-label='ClickStatus'>clicks:0</div>
<div style='height:1800px'></div><div id='scroll' aria-label='ScrollTarget'>ScrollTarget</div><div style='height:1800px'></div>
<script>
window.__p4clicks=0;
document.getElementById('click').addEventListener('click',()=>{window.__p4clicks++;document.getElementById('click-status').textContent='clicks:'+window.__p4clicks;});
</script></body></html>"""
DEST_HTML = b"<!doctype html><html><head><title>P4LIVE-Destination</title></head><body><h1>P4LIVE-Destination</h1></body></html>"


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = DEST_HTML if self.path.startswith("/dest") else FIXTURE_HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: Any) -> None:
        return None


@contextmanager
def fixture_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@dataclass
class _CountingActuator:
    inner: CdpBrowserMutationActuator
    bind_count: int = 0
    dispatch_count: int = 0

    def bind_observed_target(self, expected_target_id_sha256: str) -> None:
        self.bind_count += 1
        self.inner.bind_observed_target(expected_target_id_sha256)

    def dispatch(self, *, verb: str, physical_target: str | None, args: dict[str, Any]):
        self.dispatch_count += 1
        return self.inner.dispatch(verb=verb, physical_target=physical_target, args=args)

    def close(self) -> None:
        self.inner.close()


def _model_server_fact() -> dict[str, Any]:
    matches = []
    for line in subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines():
        parts = line.strip().split()
        if (
            len(parts) > 4
            and Path(parts[1]).name.lower() in {"python", "python3"}
            and parts[2:4] == ["-m", "mlx_lm.server"]
            and "--port" in parts
            and parts[parts.index("--port") + 1] == "8901"
        ):
            matches.append(parts)
    if len(matches) != 1:
        raise RuntimeError(f"expected one mlx_lm.server on 8901, observed={len(matches)}")
    parts = matches[0]
    model = parts[parts.index("--model") + 1] if "--model" in parts else ""
    fact = {
        "count": 1,
        "model_basename": Path(model).name,
        "prompt_concurrency_1": "--prompt-concurrency" in parts
        and parts[parts.index("--prompt-concurrency") + 1] == "1",
        "decode_concurrency_1": "--decode-concurrency" in parts
        and parts[parts.index("--decode-concurrency") + 1] == "1",
    }
    if (
        fact["model_basename"] != "Ornith-1.5-35B-A3B-MLX"
        or not fact["prompt_concurrency_1"]
        or not fact["decode_concurrency_1"]
    ):
        raise RuntimeError(f"8901 identity drift: {fact}")
    clients = subprocess.run(
        ["lsof", "-nP", "-iTCP:8901"], check=False, capture_output=True, text=True
    ).stdout.splitlines()[1:]
    fact["established_client_count"] = len([x for x in clients if "LISTEN" not in x])
    if fact["established_client_count"] != 0:
        raise RuntimeError("8901 has established competing client")
    return fact


def _find_ref(
    projection: dict[str, Any],
    bundle: dict[str, Any],
    name: str,
    role: str,
) -> str:
    object_grounding = bundle.get("object_grounding") or {}
    private_identity = (bundle.get("private_capture") or {}).get("identity") or {}
    candidates: list[tuple[str, str]] = []
    for item in projection.get("objects") or []:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes") or {}
        object_id = str(item.get("id") or "")
        grounding = object_grounding.get(object_id) if isinstance(object_grounding, dict) else None
        identity = private_identity.get(object_id) if isinstance(private_identity, dict) else None
        if not isinstance(grounding, dict) or not isinstance(identity, dict):
            continue
        if (
            isinstance(attrs, dict)
            and attrs.get("name") == name
            and attrs.get("role") == role
            and item.get("action_ref")
            and grounding.get("identity_basis") == "dom_physical_identity"
            and identity.get("stable") is True
            and identity.get("source") == "dom"
            and str(identity.get("physical_id") or "").startswith("dom:")
        ):
            candidates.append((str(identity["physical_id"]), str(item["action_ref"])))
    physical_ids = {physical_id for physical_id, _ in candidates}
    refs = {action_ref for _, action_ref in candidates}
    if len(physical_ids) != 1 or len(refs) != 1:
        raise RuntimeError(
            f"exact stable DOM ActionRef unavailable for {name}/{role}: "
            f"candidates={len(candidates)} physical_ids={sorted(physical_ids)} refs={len(refs)}"
        )
    return next(iter(refs))


def _provider_wire(debug: str, target_id: str, temp_root: Path) -> list[dict[str, Any]]:
    env = dict(os.environ)
    env.update(
        {
            "LLM_API_KEY": "local-key",
            "LLM_BASE_URL": "http://localhost:8901/v1",
            "LLM_MODEL": "cognilocal/ornith-1.5-35b-a3b-mlx",
            "LFL_BROWSER_PERCEPTION_CDP_URL": debug,
            "LFL_BROWSER_PERCEPTION_TARGET_ID": target_id,
            "LFL_BROWSER_ACTION_ENABLED": "1",
            "LFL_BROWSER_ACTION_REF_ENABLED": "1",
            "LFL_BROWSER_ACTION_REF_MUTATION_ENABLED": "1",
            "LFL_DATA_ROOT": str(temp_root / "factory-data"),
        }
    )
    engine = build_engine(load_settings(env))
    with p4_live_canary_tool_scope():
        names = set(engine.registry.names_for_current_scope())
        if names != set(P4_LIVE_CANARY_TOOL_SCOPE):
            raise RuntimeError(f"provider scope drift: {sorted(names)}")
        return build_tools_schema(engine.registry.schemas_for_current_scope(lazy=True))


def _client() -> LLMClient:
    return LLMClient(
        api_key="local-key",
        base_url="http://localhost:8901/v1",
        model=MODEL,
        timeout_s=1800,
        max_tokens=16000,
        temperature=0.0,
        top_p=1.0,
        top_k=0,
        min_p=0.0,
        provider="cognilocal",
        wire_protocol="openai",
        reasoning_capable=True,
        reasoning_control="chat_template",
        guard_enabled=False,
    )


def _expected(row: str, refs: dict[str, str], base_url: str) -> tuple[str, dict[str, Any], str]:
    if row == "V02-L01":
        args = {"action_ref": refs["resource"], "url": base_url + "/dest"}
        prompt = f"只声明下一步 Browser semantic action。已完成观察，resource ActionRef={refs['resource']}。请导航到 {base_url}/dest。不要再次感知、等待或查询 schema，不要调用其他工具。"
        return "browser_semantic_navigate", args, prompt
    if row == "V02-L02":
        args = {"action_ref": refs["click"]}
        prompt = f"只声明下一步 Browser semantic action。已完成观察，ClickTarget ActionRef={refs['click']}。请点击一次。不要再次感知、等待或查询 schema，不要调用其他工具。"
        return "browser_semantic_click", args, prompt
    if row == "V02-L03":
        args = {"action_ref": refs["fill"], "text": "AB-7319", "mode": "replace"}
        prompt = f"只声明下一步 Browser semantic action。已完成观察，FillTarget ActionRef={refs['fill']}。请用 replace 模式填入 AB-7319。不要再次感知、等待或查询 schema，不要调用其他工具。"
        return "browser_semantic_fill", args, prompt
    if row == "V02-L04":
        args = {"action_ref": refs["select"], "value": "beta"}
        prompt = f"只声明下一步 Browser semantic action。已完成观察，SelectTarget ActionRef={refs['select']}。请选择 value=beta。不要再次感知、等待或查询 schema，不要调用其他工具。"
        return "browser_semantic_select", args, prompt
    args = {"action_ref": refs["scroll"], "delta_pages": 1}
    prompt = f"只声明下一步 Browser semantic action。已完成观察，ScrollTarget ActionRef={refs['scroll']}。请向下滚动 1 页。不要再次感知、等待或查询 schema，不要调用其他工具。"
    return "browser_semantic_scroll", args, prompt


def _normalize_call(call: Any) -> tuple[str, dict[str, Any], str]:
    name = str(getattr(call, "name", "") or "")
    args = getattr(call, "arguments", {})
    if isinstance(args, str):
        args = json.loads(args)
    if not isinstance(args, dict):
        raise RuntimeError("tool arguments are not object")
    return name, dict(args), str(getattr(call, "id", "") or getattr(call, "tool_call_id", "") or "")


@contextmanager
def _wal_attempt(
    *,
    sessions: SessionStore,
    journal: ToolExecutionJournal,
    sid: str,
    workspace: str,
    run_generation: str,
    call: ToolCall,
) -> Iterator[str]:
    st = current_session_id.set(sid)
    wt = current_workspace_root.set(workspace)
    rt = current_run_generation.set(run_generation)
    sv = sessions._activate_run_save_token(sid, run_generation=run_generation)  # noqa: SLF001
    try:
        sess = sessions.load(sid)
        sess.messages.append(
            Message(
                role="assistant",
                content="",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, sort_keys=True),
                        },
                    }
                ],
            )
        )
        sessions.save(sess)
        execution_id = journal.declared(sess, call, round_no=1)
        if not execution_id or not journal.started(
            sid, execution_id=execution_id, round_no=1, call=call
        ):
            raise RuntimeError("outer WAL declaration/start failed")
        with journal.effect_context(
            session_id=sid,
            execution_id=execution_id,
            round_no=1,
            call=call,
            workspace_root=workspace,
        ):
            yield execution_id
    finally:
        sessions._deactivate_run_save_token(sid, sv)  # noqa: SLF001
        current_run_generation.reset(rt)
        current_workspace_root.reset(wt)
        current_session_id.reset(st)


def _effect(controller: _Controller, row: str) -> dict[str, Any]:
    if row == "V02-L01":
        return {
            "title": _evaluate(controller, "document.title"),
            "url": _evaluate(controller, "location.href"),
        }
    if row == "V02-L02":
        return {"clicks": int(_evaluate(controller, "window.__p4clicks || 0"))}
    if row == "V02-L03":
        return {"value": _evaluate(controller, "document.getElementById('fill').value")}
    if row == "V02-L04":
        return {"value": _evaluate(controller, "document.getElementById('select').value")}
    return {"scroll_y": float(_evaluate(controller, "window.scrollY"))}


def _effect_ok(row: str, effect: dict[str, Any], base_url: str) -> bool:
    if row == "V02-L01":
        return effect["title"] == "P4LIVE-Destination" and effect["url"] == base_url + "/dest"
    if row == "V02-L02":
        return effect["clicks"] == 1
    if row == "V02-L03":
        return effect["value"] == "AB-7319"
    if row == "V02-L04":
        return effect["value"] == "beta"
    return effect["scroll_y"] > 0


def run_row(row: str, output: Path, *, dry_run: bool = False) -> int:
    if row not in LIVE_ROWS:
        raise SystemExit(f"unsupported success row: {row}")
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
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        controller = host = None
        actuator = None
        client = None
        try:
            target = _wait_page(debug)
            target_id = str(target.get("id") or "")
            ws_url = str(target.get("webSocketDebuggerUrl") or "")
            if not target_id or not ws_url:
                raise RuntimeError("explicit Browser target unavailable")
            controller = _Controller(ws_url)
            controller.call("Page.enable")
            controller.call("Runtime.enable")
            # Ensure fixture finished loading before the one authoritative perception snapshot.
            deadline = time.monotonic() + 5
            while _evaluate(controller, "document.readyState") != "complete":
                if time.monotonic() > deadline:
                    raise RuntimeError("fixture load timeout")
                time.sleep(0.05)
            root = Path(ev)
            workspace = str(root.resolve())
            run_generation = f"p4-live-v02-{row.lower()}-run"
            events = EventStore(root / "events", enabled=True)
            sessions = SessionStore(root / "sessions", event_store=events)
            sid = sessions.create()
            pstore = BrowserPerceptionStore(root / "perception", retention_seconds=300)
            bstore = ActionRefBindingStore(root / "action_refs")
            issuer = ActionRefIssuer(binding_store=bstore, perception_store=pstore)
            perception = BrowserPerceptionAdapter(
                store=pstore,
                action_ref_issuer=issuer,
                action_ref_context_getter=lambda: ActionRefIssueContext(
                    workspace_scope=workspace, origin_run_generation=run_generation
                ),
            )
            host = CdpReadOnlyBrowserHost(debug, target_id=target_id)
            projection = perception.snapshot(sid, host.capture(), projection_limit=300)
            snapshot_id = str((projection.get("snapshot") or {}).get("snapshot_id") or "")
            bundle = pstore.load_snapshot_bundle(sid, snapshot_id)
            refs = {
                "resource": str(projection.get("resource_action_ref") or ""),
                "click": _find_ref(projection, bundle, "ClickTarget", "button"),
                "fill": _find_ref(projection, bundle, "FillTarget", "textbox"),
                "select": _find_ref(projection, bundle, "SelectTarget", "combobox"),
                "scroll": _find_ref(projection, bundle, "ScrollTarget", "generic"),
            }
            if not all(refs.values()):
                raise RuntimeError("incomplete ActionRef projection")
            wire = _provider_wire(debug, target_id, root)
            expected_name, expected_args, prompt = _expected(row, refs, base_url)
            if dry_run:
                result = {
                    "schema": "smc.p4_live.v02.success_row.v0.2",
                    "row": row,
                    "status": "DRY_RUN_PASS",
                    "target_id_nonempty": bool(target_id),
                    "provider_tool_count": len(wire),
                    "refs_present": {k: bool(v) for k, v in refs.items()},
                    "expected_tool": expected_name,
                    "model_requests": 0,
                    "browser_dispatches": 0,
                }
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
                print(json.dumps(result, sort_keys=True, indent=2))
                return 0
            receipts = BrowserActionReceiptStore(root / "browser_action")
            actuator = _CountingActuator(CdpBrowserMutationActuator(debug, target_id=target_id))
            adapter = BrowserActionAdapter(
                perception=perception,
                receipt_store=receipts,
                capture_backend=host,
                actuator=actuator,
            )
            semantic = BrowserSemanticExecuteTool(
                perception=perception, action_adapter=adapter, session_id_getter=lambda: sid
            )
            bridge = ActionRefExecutionBridgeStore(root / "audit" / "action_ref_execution")
            correlator = ActionRefCrashCorrelator(bridge_store=bridge, receipt_store=receipts)
            kernel = ActionRefMutationKernel(
                resolver=ActionRefResolver(binding_store=bstore, perception_store=pstore),
                compiler=ActionRefSemanticCompileBridge(compiler=semantic),
                execution_bridge=bridge,
                crash_correlator=correlator,
                action_adapter=adapter,
            )
            registry = ToolRegistry()
            for tool in build_typed_action_ref_mutation_tools(kernel):
                registry.register(tool)
            client = _client()
            mt = current_reasoning_mode.set("on")
            et = current_reasoning_effort.set("medium")
            started = time.monotonic()
            try:
                response = client.chat(
                    [
                        {"role": "system", "content": build_system_prompt()},
                        {"role": "user", "content": prompt},
                    ],
                    wire,
                    timeout_s=1800,
                )
            finally:
                current_reasoning_effort.reset(et)
                current_reasoning_mode.reset(mt)
            calls = list(response.tool_calls)
            actual = []
            for c in calls:
                n, a, cid = _normalize_call(c)
                actual.append({"name": n, "arguments": a, "id": cid})
            base = {
                "schema": "smc.p4_live.v02.success_row.v0.2",
                "row": row,
                "model_server": model_fact,
                "target_id": target_id,
                "expected": {"name": expected_name, "arguments": expected_args},
                "actual": actual,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "model_requests": 1,
                "model_wall_s": round(time.monotonic() - started, 3),
            }
            if (
                len(actual) != 1
                or actual[0]["name"] != expected_name
                or actual[0]["arguments"] != expected_args
            ):
                base.update(
                    {
                        "status": "FAIL_DECLARATION",
                        "browser_dispatches": 0,
                        "physical_effect": _effect(controller, row),
                    }
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(base, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
                )
                print(json.dumps(base, ensure_ascii=False, sort_keys=True, indent=2))
                return 2
            call = ToolCall(
                id=actual[0]["id"] or f"{row.lower()}-call",
                name=expected_name,
                arguments=expected_args,
            )
            journal = ToolExecutionJournal(
                event_store=events,
                result_root=root / "tool_execution",
                session_store=sessions,
                action_ref_recovery=correlator.recover_message,
            )
            with (
                p4_live_canary_tool_scope(),
                _wal_attempt(
                    sessions=sessions,
                    journal=journal,
                    sid=sid,
                    workspace=workspace,
                    run_generation=run_generation,
                    call=call,
                ) as execution_id,
            ):
                result = registry.execute(call)
                tool_msg = tool_result_to_message(
                    result,
                    failure_guidance_enabled=False,
                    experience_guidance_enabled=False,
                    tool_guidance_mode=registry.tool_guidance_mode,
                )
                result_sha = journal.finished(
                    sid, execution_id=execution_id, round_no=1, call=call, tool_message=tool_msg
                )
                sess = sessions.load(sid)
                sess.messages.append(tool_msg)
                sessions.save(sess)
                committed = journal.receipt_committed(
                    sid,
                    execution_id=execution_id,
                    round_no=1,
                    tool_call_id=call.id,
                    tool_name=call.name,
                    result_state_sha256=result_sha,
                    tool_message=tool_msg,
                )
            prepared = bridge.load_exact(execution_id)
            action_id = str(prepared.get("inner_action_id") or "")
            history = receipts.list_action(sid, action_id)
            effect = _effect(controller, row)
            success = (
                result.status.value == "success"
                and actuator.dispatch_count == 1
                and [x.get("status") for x in history] == ["running", "ok"]
                and _effect_ok(row, effect, base_url)
                and bool(committed)
            )
            base.update(
                {
                    "status": "PASS" if success else "FAIL_EXECUTION",
                    "tool_status": result.status.value,
                    "tool_content": result.content,
                    "execution_id": execution_id,
                    "execution_bridge_id": prepared.get("bridge_id"),
                    "inner_action_id": action_id,
                    "grounding_ref": prepared.get("grounding_ref"),
                    "browser_target_id_sha256": prepared.get("browser_target_id_sha256"),
                    "receipt_statuses": [x.get("status") for x in history],
                    "receipt_seqs": [x.get("receipt_seq") for x in history],
                    "bind_count": actuator.bind_count,
                    "browser_dispatches": actuator.dispatch_count,
                    "physical_effect": effect,
                    "physical_effect_ok": _effect_ok(row, effect, base_url),
                    "outer_receipt_committed": bool(committed),
                    "automatic_retry_performed": False,
                }
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(base, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            print(json.dumps(base, ensure_ascii=False, sort_keys=True, indent=2))
            return 0 if success else 3
        finally:
            if client is not None:
                client.close()
            if actuator is not None:
                with suppress(Exception):
                    actuator.close()
            if host is not None:
                host.close()
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
    p = argparse.ArgumentParser()
    p.add_argument("--row", required=True, choices=sorted(LIVE_ROWS))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    return run_row(a.row, a.output, dry_run=a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
