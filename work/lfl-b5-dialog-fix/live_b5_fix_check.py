"""B5 dialog lifecycle fix - live verification on the product tool path.

Runs against the real Chrome for Testing CDP endpoint (127.0.0.1:9229) with
self-created targets (/json/new -> /json/close); user tabs are never touched.

Three flows, all via the PRODUCT layers (browser_perceive / browser_operate,
perception adapter, action adapter, CDP hosts from this worktree):

  A (click)   snapshot -> browser_operate click (opens alert) ->
              browser_operate dialog accept -> snapshot (t1 readable) ->
              raw host capture clean (no capture_channel_degraded).
  B (auto)    page opens alert by itself (setTimeout, no click) ->
              browser_operate dialog accept must succeed via the R3 self-heal
              (blind handle) instead of dialog_not_open -> snapshot t1 -> capture.
  C (neg)     plain page: dialog accept -> dialog_not_open, then snapshot on
              the same target still clean (zero side effect, no drop).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PAGES = HERE / "pages"
OUT = HERE / "out"
CDP = "http://127.0.0.1:9229"
PORT = 8799
SESSION = "live-b5-fix"

results: dict[str, Any] = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "flows": {}}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _http_json(path: str, method: str = "GET") -> Any:
    req = urllib.request.Request(f"{CDP}{path}", method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def new_target(url: str | None = None) -> str:
    # NOTE (task009-proven): /json/new?url=... does NOT actually load the page
    # on this Chrome instance (the tab stays about:blank; see SMC-BROWSER-
    # PHASE1 notes). Create the tab empty and navigate via the PRODUCT
    # browser_operate do=navigate verb instead (Page.navigate under the hood).
    path = "/json/new" if url is None else "/json/new?" + urllib.parse.quote(url, safe=":/?=&%")
    info = _http_json(path, method="PUT")
    return str(info["id"])


def close_target(tid: str) -> None:
    try:
        _http_json(f"/json/close/{tid}")
    except Exception as exc:  # noqa: BLE001
        log(f"WARN close {tid}: {exc}")


def wait_ready(tid: str, url_part: str, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for page in _http_json("/json/list"):
            if str(page.get("id")) == tid and url_part in str(page.get("url") or ""):
                return
        time.sleep(0.2)
    raise RuntimeError(f"target {tid} never became ready for {url_part}")


def attest_dedicated(url: str):  # noqa: ANN001, ANN202
    from llm_loop.browser.attestation import AttestationVerdict

    return AttestationVerdict(
        verdict="dedicated",
        user_data_dir="/tmp/attest-stub-profile",
        argv_sha256="stub" * 16,
        argv=(),
        detail="live b5 fix harness",
    )


class Stack:
    """Product tool stack bound to ONE explicit target (worktree code)."""

    def __init__(self, target_id: str, root: Path) -> None:
        from llm_loop.browser.action import (
            BrowserActionAdapter,
            BrowserActionReceiptStore,
        )
        from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
        from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
        from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
        from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
        from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
        from llm_loop.tools.builtin.browser_semantic_operation import (
            BrowserSemanticOperationReceiptStore,
            BrowserSemanticOperationTool,
        )

        self.host = CdpReadOnlyBrowserHost(CDP, target_id=target_id, attest_fn=attest_dedicated)
        self.actuator = CdpBrowserMutationActuator(CDP, target_id=target_id, attest_fn=attest_dedicated)
        self.perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(root / "perception"))
        self.receipt_store = BrowserSemanticOperationReceiptStore(root / "operation_receipts")
        action = BrowserActionAdapter(
            perception=self.perception,
            receipt_store=BrowserActionReceiptStore(root / "actions"),
            capture_backend=self.host,
            actuator=self.actuator,
        )
        execute = BrowserSemanticExecuteTool(
            perception=self.perception, action_adapter=action, session_id_getter=lambda: SESSION
        )
        self.operate = BrowserSemanticOperationTool(
            perception=self.perception,
            capture_backend=self.host,
            semantic_execute=execute,
            receipt_store=self.receipt_store,
            session_id_getter=lambda: SESSION,
        )
        self.perceive = BrowserPerceiveTool(
            adapter=self.perception, backend=self.host, session_id_getter=lambda: SESSION
        )

    # -- helpers -----------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        result = self.perceive.execute(action="snapshot")
        assert result.status.value == "success", result.content[:2000]
        return json.loads(result.content)

    def operate_raw(self, **kwargs: Any) -> dict[str, Any]:
        result = self.operate.execute(**kwargs)
        try:
            payload = json.loads(result.content)
        except json.JSONDecodeError:
            # failure paths return plain-text diagnostics, not JSON
            log(f"OPERATE NON-JSON [{kwargs}]: {result.content[:1500]}")
            return {"_tool_status": result.status.value, "_raw": result.content[:4000]}
        if isinstance(payload, dict):
            payload.setdefault("_tool_status", result.status.value)
        return payload

    def full_receipt(self, compact: dict[str, Any]) -> dict[str, Any]:
        hydrated = self.receipt_store.hydrate(SESSION, str(compact["receipt_ref"]))
        assert str(hydrated.get("availability")) == "available", hydrated
        return dict(hydrated["content"])


def _obj_text(obj: dict[str, Any]) -> str:
    """Snapshot objects carry text/name under ``attributes`` (DOM) or as the
    AX name of InlineTextBox nodes - both must be consulted."""
    attrs = obj.get("attributes")
    if isinstance(attrs, dict):
        for key in ("text", "name"):
            value = attrs.get(key)
            if isinstance(value, str) and value.strip():
                return value
    for key in ("text", "name"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def find_mirror(snapshot: dict[str, Any], prefix: str) -> str | None:
    for obj in snapshot.get("objects", []):
        text = _obj_text(obj)
        if text.startswith(prefix + ":"):
            return text
    return None


def _page_url(snapshot: dict[str, Any]) -> str:
    for item in snapshot.get("scope_facts") or []:
        if isinstance(item, dict) and item.get("kind") == "page":
            return str(item.get("url") or "")
    return ""


def read_resume_state(stack: "Stack") -> dict[str, Any]:
    """Read the page-resume mirrors; re-read once after 300ms (the accept
    ack can beat the page's continuation by a frame)."""
    snap = stack.snapshot()
    state = {
        "page_url": _page_url(snap),
        "t0": find_mirror(snap, "t0"),
        "t1": find_mirror(snap, "t1"),
    }
    if state["t1"] in (None, "t1:pending"):
        time.sleep(0.3)
        snap = stack.snapshot()
        state = {
            "page_url": _page_url(snap),
            "t0": find_mirror(snap, "t0"),
            "t1": find_mirror(snap, "t1"),
        }
    return state


def dialog_opened_in(action_receipt: dict[str, Any]) -> bool:
    for event in action_receipt.get("boundary_events") or []:
        if str(event.get("event")) == "dialog_opened":
            return True
    return False


def _navigate(stack: "Stack", tid: str, page: str, evidence: dict[str, Any]) -> "Stack":
    # cache-buster: Chrome heuristically caches these static URLs (a rerun
    # served a STALE page with zero GETs, proven in out/live_run.log); a
    # per-run query forces a fresh fetch.
    nav = stack.operate_raw(do="navigate", url=f"http://127.0.0.1:{PORT}/{page}?run={int(time.time())}")
    evidence["navigate"] = {"status": nav.get("status"), "halt_reason": nav.get("halt_reason")}
    assert nav.get("status") == "completed", json.dumps(nav)[:2000]
    wait_ready(tid, page)
    return stack


def flow_click() -> dict[str, Any]:
    tid = new_target()
    log(f"A click: target {tid}")
    evidence: dict[str, Any] = {"target_id": tid}
    results["flows"]["A_click"] = evidence  # progressive: survives assert failures
    try:
        stack = _navigate(Stack(tid, OUT / "flow_a"), tid, "dialog_click.html", evidence)
        snap1 = stack.snapshot()
        evidence["snapshot1_objects"] = len(snap1.get("objects", []))

        t0 = time.monotonic()
        click = stack.operate_raw(do="click", target={"kind": "button", "name": "lfl-alert-btn"})
        evidence["click_compact"] = click
        evidence["click_elapsed_s"] = round(time.monotonic() - t0, 2)
        full = stack.full_receipt(click)
        clause = full["clauses"][0]
        action_receipt = clause["action_receipt"]
        evidence["click_action_status"] = action_receipt.get("status")
        evidence["click_boundary_events"] = action_receipt.get("boundary_events")
        evidence["click_post_capture"] = action_receipt.get("post_capture")
        evidence["click_completeness_reasons"] = (action_receipt.get("completeness") or {}).get("reasons")
        assert action_receipt.get("status") == "ok", json.dumps(action_receipt)[:2000]
        assert dialog_opened_in(action_receipt), "no dialog_opened boundary event"
        assert action_receipt.get("post_capture") == {"skipped": True, "reason": "dialog_open"}, (
            "post-capture was not skipped for the dialog click"
        )
        assert stack.actuator._dialog_open is True
        assert stack.actuator._session is not None, "mutation session dropped after dialog click"

        accept = stack.operate_raw(do="dialog", action="accept")
        evidence["dialog_accept_compact"] = accept
        assert accept.get("status") == "completed", json.dumps(accept)[:2000]
        evidence["dialog_open_after_accept"] = stack.actuator._dialog_open

        resumed = read_resume_state(stack)
        evidence["resume_state"] = resumed
        assert resumed["t1"] not in (None, "t1:pending"), f"page did not resume after accept: {resumed}"
        assert resumed["t0"] not in (None, "t0:pending"), f"handler never entered (no t0): {resumed}"

        raw = stack.host.capture()
        evidence["final_capture_keys"] = sorted(raw.keys())[:8]
        evidence["final_capture_ok"] = True
        evidence["mutation_session_alive"] = stack.actuator._session is not None
        evidence["observation_session_alive"] = stack.host._session is not None
    finally:
        close_target(tid)
    return evidence


def flow_auto() -> dict[str, Any]:
    tid = new_target()
    log(f"B auto: target {tid}")
    evidence: dict[str, Any] = {"target_id": tid}
    results["flows"]["B_auto"] = evidence  # progressive: survives assert failures
    try:
        stack = _navigate(Stack(tid, OUT / "flow_b"), tid, "dialog_auto.html", evidence)
        # observe the page BEFORE its self-timer fires (3s), so the session
        # has a persisted world - then the page opens the dialog BY ITSELF:
        # no click, no tool action of any kind.
        snap = stack.snapshot()
        evidence["pre_dialog_snapshot_objects"] = len(snap.get("objects", []))
        time.sleep(3.6)
        evidence["dialog_open_before"] = stack.actuator._dialog_open  # must be False

        # R5 data point (NOT fixed this round): browser_perceive snapshot on a
        # dialog-frozen page - how long it takes and how it fails.
        t0 = time.monotonic()
        try:
            frozen = stack.perceive.execute(action="snapshot")
            evidence["frozen_perceive_elapsed_s"] = round(time.monotonic() - t0, 1)
            evidence["frozen_perceive_status"] = frozen.status.value
            evidence["frozen_perceive_excerpt"] = frozen.content[:220]
        except Exception as exc:  # noqa: BLE001 - the failure IS the data point
            evidence["frozen_perceive_elapsed_s"] = round(time.monotonic() - t0, 1)
            evidence["frozen_perceive_status"] = "raised"
            evidence["frozen_perceive_excerpt"] = f"{type(exc).__name__}: {str(exc)[:180]}"

        t0 = time.monotonic()
        accept = stack.operate_raw(do="dialog", action="accept")
        evidence["dialog_accept_elapsed_s"] = round(time.monotonic() - t0, 1)
        evidence["dialog_accept_compact"] = accept
        full = stack.full_receipt(accept)
        action_receipt = full["clauses"][0]["action_receipt"]
        evidence["dialog_action_status"] = action_receipt.get("status")
        assert accept.get("status") == "completed", json.dumps(accept)[:2000]
        assert action_receipt.get("status") == "ok", json.dumps(action_receipt)[:2000]

        resumed = read_resume_state(stack)
        evidence["resume_state"] = resumed
        assert resumed["t1"] not in (None, "t1:pending"), f"page did not resume after blind handle: {resumed}"
        assert resumed["t0"] not in (None, "t0:pending"), f"page timer never ran (no t0): {resumed}"

        stack.host.capture()
        evidence["final_capture_ok"] = True
        evidence["mutation_session_alive"] = stack.actuator._session is not None
    finally:
        close_target(tid)
    return evidence


def flow_negative() -> dict[str, Any]:
    tid = new_target()
    log(f"C negative: target {tid}")
    evidence: dict[str, Any] = {"target_id": tid}
    results["flows"]["C_negative"] = evidence  # progressive: survives assert failures
    try:
        stack = _navigate(Stack(tid, OUT / "flow_c"), tid, "plain.html", evidence)

        accept = stack.operate_raw(do="dialog", action="accept")
        evidence["dialog_accept_compact"] = accept
        full = stack.full_receipt(accept)
        action_receipt = full["clauses"][0]["action_receipt"]
        evidence["dialog_action_status"] = action_receipt.get("status")
        evidence["dialog_action_retry_reason"] = (action_receipt.get("retry") or {}).get("reason")
        assert accept.get("status") == "halted", json.dumps(accept)[:2000]
        assert evidence["dialog_action_retry_reason"] == "dialog_not_open", json.dumps(action_receipt)[:2000]

        snap = stack.snapshot()
        evidence["snapshot_after_reject_objects"] = len(snap.get("objects", []))
        evidence["page_url_after_reject"] = _page_url(snap)
        mirror = find_mirror(snap, "t1")
        assert mirror == "t1:none", f"plain page changed? {mirror}"
        stack.host.capture()
        evidence["final_capture_ok"] = True
        evidence["mutation_session_alive"] = stack.actuator._session is not None
        evidence["observation_session_alive"] = stack.host._session is not None
    finally:
        close_target(tid)
    return evidence


def main() -> int:
    import functools

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(PAGES))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"static pages served on 127.0.0.1:{PORT}")
    try:
        results["flows"]["A_click"] = flow_click()
        log("A click flow PASS")
        results["flows"]["B_auto"] = flow_auto()
        log("B auto flow PASS")
        results["flows"]["C_negative"] = flow_negative()
        log("C negative flow PASS")
        results["verdict"] = "PASS"
        return 0
    except AssertionError as exc:
        results["verdict"] = "FAIL"
        results["failure"] = str(exc)
        log(f"FAIL: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - harness/transport faults land as evidence too
        results["verdict"] = "FAIL"
        results["failure"] = f"{type(exc).__name__}: {exc}"
        log(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    finally:
        results["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        (OUT / "live_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
        server.shutdown()
        log(f"evidence -> {OUT / 'live_result.json'}")


if __name__ == "__main__":
    sys.exit(main())
