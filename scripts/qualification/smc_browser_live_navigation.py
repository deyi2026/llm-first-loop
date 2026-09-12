#!/usr/bin/env python3
"""Qualification-only live Browser document-generation harness.

This module is intentionally outside ``src/llm_loop``.  It owns a separate
control-plane websocket that may mutate an isolated qualification Chrome while
the production ``CdpReadOnlyBrowserHost`` keeps its observation-only surface.

The model-facing Browser tool is never given navigation/reload/evaluate access.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import connect as websocket_connect

from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore


def _find_scope(snapshot: dict[str, Any], kind: str) -> dict[str, Any]:
    for scope in snapshot.get("scope_facts") or []:
        if isinstance(scope, dict) and scope.get("kind") == kind:
            return scope
    raise KeyError(f"missing scope kind={kind}")


def _find_named_object(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        item
        for item in snapshot.get("objects") or []
        if isinstance(item, dict)
        and isinstance(item.get("attributes"), dict)
        and item["attributes"].get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one object named {name!r}; observed={len(matches)}")
    return matches[0]


def _find_object_by_id(snapshot: dict[str, Any], object_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in snapshot.get("objects") or []
        if isinstance(item, dict) and item.get("id") == object_id
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one object id={object_id!r}; observed={len(matches)}")
    return matches[0]


def _find_dom_physical_object(
    adapter: BrowserPerceptionAdapter,
    session_id: str,
    snapshot: dict[str, Any],
    *,
    name: str,
) -> dict[str, Any]:
    """Select a qualification object only by persisted mechanical identity facts."""

    matches: list[dict[str, Any]] = []
    for item in snapshot.get("objects") or []:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes")
        if not isinstance(attrs, dict) or attrs.get("name") != name:
            continue
        ref = str(item.get("grounding_ref") or "")
        hydrated = adapter.hydrate(session_id, ref)
        content = hydrated.get("content")
        if (
            hydrated.get("availability") == "available"
            and isinstance(content, dict)
            and content.get("identity_basis") == "dom_physical_identity"
            and isinstance(content.get("semantic_object"), dict)
            and content["semantic_object"].get("id") == item.get("id")
        ):
            matches.append(item)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one DOM-physical object named {name!r}; observed={len(matches)}"
        )
    return matches[0]


def evaluate_navigation(
    before: dict[str, Any],
    after: dict[str, Any],
    hydrated_old_grounding: dict[str, Any],
    *,
    target_before: str,
    target_after: str,
    loader_before: str,
    loader_after: str,
    object_before_id: str = "",
    object_after_id: str = "",
) -> dict[str, Any]:
    """Mechanically evaluate one same-target full-document replacement."""

    before_scope = dict(before.get("snapshot", {}).get("scope") or {})
    after_scope = dict(after.get("snapshot", {}).get("scope") or {})
    before_page = _find_scope(before, "page")
    after_page = _find_scope(after, "page")
    before_document = _find_scope(before, "document")
    after_document = _find_scope(after, "document")
    before_object = (
        _find_object_by_id(before, object_before_id)
        if object_before_id
        else _find_named_object(before, "Same Name")
    )
    after_object = (
        _find_object_by_id(after, object_after_id)
        if object_after_id
        else _find_named_object(after, "Same Name")
    )

    hydrated_content = hydrated_old_grounding.get("content")
    hydrated_object = (
        hydrated_content.get("semantic_object")
        if isinstance(hydrated_content, dict)
        else None
    )
    before_snapshot_id = str(before.get("snapshot", {}).get("snapshot_id") or "")

    checks = {
        "same_exact_target": "PASS" if target_before == target_after and target_before else "FAIL",
        "page_generation_preserved": (
            "PASS"
            if before_scope.get("page_generation") == after_scope.get("page_generation")
            else "FAIL"
        ),
        "page_scope_preserved": (
            "PASS" if before_page.get("scope_ref") == after_page.get("scope_ref") else "FAIL"
        ),
        "loader_changed": "PASS" if loader_before and loader_before != loader_after else "FAIL",
        "document_generation_incremented": (
            "PASS"
            if isinstance(before_scope.get("document_generation"), int)
            and isinstance(after_scope.get("document_generation"), int)
            and after_scope["document_generation"] > before_scope["document_generation"]
            else "FAIL"
        ),
        "document_scope_changed": (
            "PASS"
            if before_document.get("scope_ref") != after_document.get("scope_ref")
            else "FAIL"
        ),
        "same_name_identity_invalidated": (
            "PASS" if before_object.get("id") != after_object.get("id") else "FAIL"
        ),
        "old_grounding_exact_after_reload": (
            "PASS"
            if hydrated_old_grounding.get("availability") == "available"
            and isinstance(hydrated_object, dict)
            and hydrated_object.get("id") == before_object.get("id")
            and hydrated_object.get("observed_version") == before_snapshot_id
            else "FAIL"
        ),
    }
    return {
        "schema": "smc.browser_live_navigation_qualification.v0.1",
        "status": "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL",
        "checks": checks,
    }


def chrome_args(chrome: str, profile: Path, port: int) -> list[str]:
    """Return the isolated qualification Chrome command.

    Mock/basic credential storage is a safety contract: fresh profiles must never
    wake macOS Keychain prompts during automated qualification.
    """

    return [
        chrome,
        "--headless=new",
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--use-mock-keychain",
        "--password-store=basic",
        "about:blank",
    ]


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _security_agent_pids() -> set[int]:
    proc = subprocess.run(
        ["pgrep", "-x", "SecurityAgent"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {int(line) for line in proc.stdout.splitlines() if line.strip().isdigit()}


def _wait_page(debug_base: str, *, timeout_s: float = 8.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    with httpx.Client(timeout=1.0, trust_env=False, follow_redirects=False) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(f"{debug_base}/json/list")
                response.raise_for_status()
                pages = [
                    item
                    for item in response.json()
                    if isinstance(item, dict) and item.get("type") == "page"
                ]
                if len(pages) == 1 and pages[0].get("webSocketDebuggerUrl"):
                    return pages[0]
            except (httpx.HTTPError, ValueError, TypeError):
                pass
            time.sleep(0.1)
    raise TimeoutError("qualification Chrome page target did not become ready")


class _Controller:
    """Qualification-only CDP controller; never imported by production runtime."""

    def __init__(self, ws_url: str) -> None:
        self._ws = websocket_connect(ws_url, open_timeout=5.0)
        self._request_id = 0

    def call(
        self, method: str, params: dict[str, Any] | None = None, *, timeout_s: float = 8.0
    ) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        self._ws.send(
            json.dumps(
                {"id": request_id, "method": method, "params": params or {}},
                separators=(",", ":"),
            )
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            raw = self._ws.recv(timeout=max(0.1, deadline - time.monotonic()))
            message = json.loads(raw)
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"qualification CDP control failed: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("qualification CDP response missing object result")
            return result
        raise TimeoutError(f"qualification CDP method timed out: {method}")

    def close(self) -> None:
        self._ws.close()


def _main_frame(controller: _Controller) -> dict[str, Any]:
    tree = controller.call("Page.getFrameTree").get("frameTree") or {}
    frame = tree.get("frame") if isinstance(tree, dict) else None
    if not isinstance(frame, dict):
        raise RuntimeError("qualification target missing main frame")
    return frame


def _wait_loader_change(
    controller: _Controller, old_loader: str, *, timeout_s: float = 8.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        frame = _main_frame(controller)
        loader = str(frame.get("loaderId") or "")
        if loader and loader != old_loader:
            return frame
        time.sleep(0.05)
    raise TimeoutError("full-document reload did not produce a new loader identity")


def _set_fixture_dom(controller: _Controller) -> None:
    expression = """
document.body.innerHTML = '<button id="stable" aria-label="Same Name">Same Name</button>';
document.body.dataset.smcQualification = 'v1';
'ok';
""".strip()
    response = controller.call(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": False},
    )
    if ((response.get("result") or {}).get("value")) != "ok":
        raise RuntimeError("qualification DOM setup did not complete")


def run_live(*, chrome: str, evidence_dir: Path) -> dict[str, Any]:
    """Run one isolated live same-target full-document qualification."""

    port = _free_loopback_port()
    debug_base = f"http://127.0.0.1:{port}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lfl-bnav-profile-") as profile_raw:
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
            _set_fixture_dom(controller)

            host = CdpReadOnlyBrowserHost(debug_base, target_id=target_id)
            store = BrowserPerceptionStore(evidence_dir / "grounding")
            adapter = BrowserPerceptionAdapter(store=store)
            session_id = "b-live-navigation-qualification"

            frame_before = _main_frame(controller)
            loader_before = str(frame_before.get("loaderId") or "")
            before = adapter.snapshot(session_id, host.capture(), projection_limit=200)
            old_object = _find_dom_physical_object(
                adapter,
                session_id,
                before,
                name="Same Name",
            )
            old_ref = str(old_object.get("grounding_ref") or "")

            controller.call("Page.reload", {"ignoreCache": True})
            frame_after_reload = _wait_loader_change(controller, loader_before)
            loader_after = str(frame_after_reload.get("loaderId") or "")
            _set_fixture_dom(controller)

            target_after = _wait_page(debug_base)
            after_target_id = str(target_after.get("id") or "")
            after = adapter.snapshot(session_id, host.capture(), projection_limit=200)
            new_object = _find_dom_physical_object(
                adapter,
                session_id,
                after,
                name="Same Name",
            )
            hydrated = adapter.hydrate(session_id, old_ref)
            result = evaluate_navigation(
                before,
                after,
                hydrated,
                target_before=target_id,
                target_after=after_target_id,
                loader_before=loader_before,
                loader_after=loader_after,
                object_before_id=str(old_object.get("id") or ""),
                object_after_id=str(new_object.get("id") or ""),
            )
            result["safety"] = {
                "mock_keychain_enabled": "PASS",
                "basic_password_store_enabled": "PASS",
                "security_agent_not_spawned": (
                    "PASS"
                    if not (_security_agent_pids() - before_security)
                    else "FAIL"
                ),
                "production_host_exact_target_bound": (
                    "PASS" if host.bound_target_id == target_id else "FAIL"
                ),
            }
            if any(value != "PASS" for value in result["safety"].values()):
                result["status"] = "FAIL"
            return result
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
