"""M3 E2E: real Chromium + real CDP for the FR-1 semantic guard.

Unlike the fake-based unit tests (test_browser_semantic_guard_v01.py), these
cases drive a genuine headless Chromium: the guard probe JS runs on the real
DOM (DOM.resolveNode + Runtime.callFunctionOn), elementFromPoint has a real
layout to hit, and the actuator actually dispatches the click. Covers:

  E1 guard pass exempting a snapshot-level version mismatch (ad rotation
     outside the target neighborhood must NOT block a click)
  E2 neighborhood change inside the form -> guard reject, zero execution
  E3 overlay occlusion -> guard_occluded reject (this.click() would have
     succeeded anyway; only the guard stops it)
  E4 detached node between snapshot and dispatch -> guard_detach
  E5 sensitive password value never lands in the persisted bundle (FR-6)

Skipped automatically when playwright/chromium is unavailable.
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.perception import (
    SENSITIVE_VALUE_SENTINEL,
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
)

try:
    from playwright.sync_api import Browser, sync_playwright
except ImportError:  # pragma: no cover
    pytest.skip("playwright not installed", allow_module_level=True)

pytestmark = pytest.mark.browser_e2e

PAGE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Guard E2E</title></head><body>
<main>
<form id="login" aria-label="Sign-in form">
  <input type="text" aria-label="Username" name="username">
  <input type="password" aria-label="Password" name="password">
  <button type="button" id="signin" aria-label="Sign in">Sign in</button>
</form>
<div id="ad" data-region="promo">Ad slot A</div>
</main>
<script>
window.__clicked = 0;
window.__adTicker = null;
document.getElementById('signin').addEventListener('click', function () {
  window.__clicked += 1;
});
window.startAd = function () {
  var i = 0;
  window.__adTicker = setInterval(function () {
    i += 1;
    document.getElementById('ad').textContent = 'Ad slot ' + (i % 7);
  }, 40);
};
</script>
</body></html>"""


def _attest_dedicated(base_url: str):  # noqa: ANN001, ANN202 - e2e stub
    from llm_loop.browser.attestation import AttestationVerdict

    return AttestationVerdict(
        verdict="dedicated",
        user_data_dir="/tmp/lfl-e2e-profile",
        argv_sha256="e2e" * 16,
        argv=(),  # type: ignore[arg-type]
        detail="e2e stub",
    )


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SimpleNamespace]:
    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.executable_path
        except Exception:  # pragma: no cover
            pytest.skip("chromium binary not installed")
        if not Path(chromium).is_file():
            pytest.skip("playwright chromium binary not installed; browser E2E unverified")
        profile = tmp_path_factory.mktemp("e2e-profile")
        proc = subprocess.Popen(
            [
                chromium,
                "--headless=new",
                f"--user-data-dir={profile}",
                "--remote-debugging-port=0",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        ws_url = None
        browser: Browser | None = None
        stderr_pipe = proc.stderr
        assert stderr_pipe is not None
        try:
            # stderr.readline() is unbounded even inside a time.monotonic()
            # loop: Chromium can remain alive without emitting a newline.
            # Poll bytes with a real deadline, preserving the existing
            # skip-on-no-CDP policy without hanging full CI indefinitely.
            deadline = time.monotonic() + 15.0
            stderr_bytes = bytearray()
            while proc.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                ready, _, _ = select.select([stderr_pipe], [], [], remaining)
                if not ready:
                    break
                chunk = os.read(stderr_pipe.fileno(), 4096)
                if not chunk:
                    break
                stderr_bytes.extend(chunk)
                found = re.search(rb"DevTools listening on (ws://\S+)", stderr_bytes)
                if found is not None:
                    ws_url = found.group(1).decode("ascii")
                    break
            if ws_url is None:  # pragma: no cover
                pytest.skip("chromium did not expose a DevTools endpoint within 15s")
            port_match = re.match(r"ws://[^:]+:(\d+)/", ws_url)
            assert port_match is not None
            port = int(port_match.group(1))
            browser = pw.chromium.connect_over_cdp(ws_url, timeout=10_000)
            page = None
            for ctx in browser.contexts:
                if ctx.pages:
                    page = ctx.pages[0]
                    break
            if page is None:  # pragma: no cover
                page = browser.contexts[0].new_page()
            ns = SimpleNamespace(page=page, base=f"http://127.0.0.1:{port}")
            yield ns
        finally:
            if browser is not None:
                browser.close()
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()
                proc.wait(timeout=5)
            stderr_pipe.close()


@pytest.fixture()
def stack(tmp_path: Path, env: SimpleNamespace, page_html: Path) -> SimpleNamespace:
    host = CdpReadOnlyBrowserHost(env.base, attest_fn=_attest_dedicated)
    actuator = CdpBrowserMutationActuator(env.base, attest_fn=_attest_dedicated)
    perception = BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "perception")
    )
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "receipts"),
        capture_backend=host,
        actuator=actuator,
        guard_collector=host.collect_guard_observation,
        guard_enabled=True,
    )
    env.page.goto(page_html.as_uri())
    env.page.wait_for_load_state("load")
    return SimpleNamespace(
        host=host, actuator=actuator, perception=perception, action=action, page=env.page
    )


@pytest.fixture(scope="module")
def page_html(tmp_path_factory: pytest.TempPathFactory) -> Path:
    p = tmp_path_factory.mktemp("e2e-page") / "page.html"
    p.write_text(PAGE_HTML, encoding="utf-8")
    return p


def _find(snapshot: dict, kind: str, name: str) -> dict:
    return next(
        obj
        for obj in snapshot["objects"]
        if obj.get("kind") == kind
        and obj.get("attributes", {}).get("name") == name
    )


def _click_action(snapshot: dict, target: dict) -> dict:
    return {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "action_id": "act-e2e-1",
        "verb": "click",
        "target_id": target["id"],
        "args": {},
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": snapshot["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }


def _snapshot(stack) -> dict:
    return stack.perception.snapshot("s1", stack.host.capture())


def test_e1_guard_pass_exempts_version_mismatch(stack) -> None:
    first = _snapshot(stack)
    signin = _find(first, "button", "Sign in")
    # Real-world "comparable but not equal" churn: ad rotation outside the
    # form, an unrelated input value change, and the target gaining focus
    # (state.focused flips -> object scope reports stale) while the guard's
    # semantic payload (tag/name/role/text), the form neighborhood and the
    # document URL all stay identical. Without the guard this dispatch would
    # be rejected as version stale; with it, the mismatch is exempted.
    stack.page.evaluate("startAd()")
    stack.page.fill('[aria-label="Username"]', "alice")
    stack.page.evaluate("document.getElementById('signin').focus()")
    time.sleep(0.25)  # let the ad ticker rewrite the promo text a few times

    result = stack.action.execute("s1", _click_action(first, signin))

    assert result["status"] == "ok", json.dumps(result, ensure_ascii=False)[:600]
    assert result["guard"]["verdict"] == "pass"
    # the exemption must be visible on the persisted receipt, not just implied
    assert result["guard"]["exempted"] is True
    assert result["guard"]["exemption_reason"] == "version_mismatch_semantics_stable"
    assert stack.page.evaluate("window.__clicked") == 1


def test_e2_neighborhood_change_is_rejected_without_execution(stack) -> None:
    first = _snapshot(stack)
    signin = _find(first, "button", "Sign in")
    stack.page.evaluate(
        "var i=document.createElement('input');"
        "i.type='text';i.setAttribute('aria-label','One-time code');"
        "document.getElementById('login').appendChild(i);"
    )

    result = stack.action.execute("s1", _click_action(first, signin))

    assert result["status"] == "rejected"
    assert result["guard"]["verdict"] == "reject"
    assert result["guard"]["mismatched_layer"] == "neighborhood"
    assert stack.page.evaluate("window.__clicked") == 0


def test_e3_overlay_occlusion_is_rejected(stack) -> None:
    first = _snapshot(stack)
    signin = _find(first, "button", "Sign in")
    stack.page.evaluate(
        "var o=document.createElement('div');o.textContent='x';"
        "o.style.cssText='position:fixed;inset:0;background:#fff;z-index:9999';"
        "document.body.appendChild(o);"
    )

    result = stack.action.execute("s1", _click_action(first, signin))

    assert result["status"] == "rejected"
    assert result["guard"]["reason"] == "guard_occluded"
    assert stack.page.evaluate("window.__clicked") == 0


def test_e4_detached_node_is_rejected(stack) -> None:
    first = _snapshot(stack)
    signin = _find(first, "button", "Sign in")
    stack.page.evaluate("document.getElementById('signin').remove()")

    result = stack.action.execute("s1", _click_action(first, signin))

    assert result["status"] == "rejected"
    assert result["guard"]["reason"] == "guard_detach"
    assert stack.page.evaluate("window.__clicked") == 0


def test_e5_password_value_never_persists_in_plaintext(
    stack, tmp_path: Path
) -> None:
    stack.page.fill('[aria-label="Password"]', "s3cret-token-e2e")
    snap = _snapshot(stack)

    pw = _find(snap, "input", "Password")
    assert pw["attributes"].get("value_text") == SENSITIVE_VALUE_SENTINEL

    bundle_dir = tmp_path / "perception" / "snapshots"
    blob = "".join(p.read_text(encoding="utf-8") for p in bundle_dir.glob("*.json"))
    assert "s3cret-token-e2e" not in blob
    assert SENSITIVE_VALUE_SENTINEL in blob
