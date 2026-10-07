"""FR-2 post-dispatch settle wait — real-browser E2E (M4).

Same doctrine as the M3 guard E2E: page-side predicates (rAF race, option
visibility polling) and their CDP plumbing (Runtime.callFunctionOn +
awaitPromise + returnByValue) are only proven by a real Chromium round trip;
mock-layer tests would only restate our own assumptions.
"""

import re
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
)
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore

from tests.integration.test_browser_semantic_guard_e2e import _attest_dedicated

PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>settle-e2e</title></head>
<body>
  <button id="btn" name="Plain">Plain</button>
  <input id="combo" name="Country" role="combobox" aria-controls="pop" aria-expanded="false">
  <div id="pop" role="listbox" style="display:none">
    <div role="option" name="Alpha">Alpha</div>
    <div role="option" name="Beta">Beta</div>
  </div>
  <input id="slow" name="City" role="combobox" aria-controls="slowpop" aria-expanded="false">
  <div id="slowpop" role="listbox" style="display:none">
    <div role="option" name="Late">Late</div>
  </div>
<script>
  const show = (input, pop, delay) => input.addEventListener('click', () => {
    setTimeout(() => {
      pop.style.display = 'block';
      input.setAttribute('aria-expanded', 'true');
    }, delay);
  });
  show(document.getElementById('combo'), document.getElementById('pop'), 120);
  show(document.getElementById('slow'), document.getElementById('slowpop'), 240);
</script>
</body></html>
"""


@pytest.fixture(scope="module")
def env():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        pytest.skip("playwright not installed")
    import glob
    import platform

    candidates = []
    if platform.system() == "Darwin":
        candidates = glob.glob(
            "/Applications/Chromium.app/Contents/MacOS/Chromium"
        ) or glob.glob("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    chromium = candidates[0] if candidates else "chromium"
    import tempfile

    pw = sync_playwright().start()
    profile = tempfile.mkdtemp(prefix="lfl-settle-e2e-")
    proc = subprocess.Popen(
        [chromium, "--headless=new", f"--user-data-dir={profile}",
         "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    ws_url = None
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        line = proc.stderr.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = re.search(r"DevTools listening on (ws://\S+)", line)
        if m:
            ws_url = m.group(1)
            break
    if ws_url is None:  # pragma: no cover
        proc.terminate()
        pytest.skip("chromium did not expose a DevTools endpoint")
    port = int(re.match(r"ws://[^:]+:(\d+)/", ws_url).group(1))
    browser = pw.chromium.connect_over_cdp(ws_url)
    page = None
    for ctx in browser.contexts:
        if ctx.pages:
            page = ctx.pages[0]
            break
    if page is None:  # pragma: no cover
        page = browser.contexts[0].new_page()
    ns = SimpleNamespace(page=page, base=f"http://127.0.0.1:{port}", _pw=pw, _proc=proc)
    try:
        yield ns
    finally:
        browser.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
        pw.stop()


@pytest.fixture(scope="module")
def page_html(tmp_path_factory: Path) -> Path:
    p = tmp_path_factory.mktemp("settle-e2e-page") / "page.html"
    p.write_text(PAGE_HTML, encoding="utf-8")
    return p


def _stack(tmp_path: Path, env: SimpleNamespace, page_html: Path, *, settle_enabled: bool):
    host = CdpReadOnlyBrowserHost(env.base, attest_fn=_attest_dedicated)
    actuator = CdpBrowserMutationActuator(env.base, attest_fn=_attest_dedicated)
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "receipts"),
        capture_backend=host,
        actuator=actuator,
        guard_collector=host.collect_guard_observation,
        guard_enabled=True,
        settle_enabled=settle_enabled,
    )
    env.page.goto(page_html.as_uri())
    env.page.wait_for_load_state("load")
    return SimpleNamespace(host=host, actuator=actuator, perception=perception, action=action, page=env.page)


def _click(first: dict, name: str, action_id: str) -> dict:
    target = next(
        obj for obj in first["objects"]
        if obj.get("attributes", {}).get("name") == name
    )
    return {
        "schema": "smc.semantic_action.v0.1", "domain": "browser",
        "scope_ref": target["scope_ref"], "action_id": action_id,
        "verb": "click", "target_id": target["id"], "args": {},
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate", "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object", "version_precondition": "required",
    }


def _input_expanded(st, session_id: str, result: dict, input_name: str) -> bool:
    """First-valid-observation probe via the projected state surface.

    Real-CDP capture projects no state.visible today (fixture captures do);
    the popup's post-click state is observable through state.expanded on the
    combobox input, which IS a projected field. Recorded as a real finding:
    do not "fix" this by faking visible fields in tests.
    """
    bundle = st.perception.store.load_snapshot_bundle(session_id, result["after_version"])
    objects = bundle.get("objects") or []
    for obj in objects:
        if (obj.get("attributes") or {}).get("name") == input_name:
            return bool(obj.get("state", {}).get("expanded"))
    raise AssertionError(f"input {input_name!r} not projected in after bundle")


def test_e6_plain_click_settles_on_raf_baseline_within_cap(tmp_path: Path, env, page_html) -> None:
    st = _stack(tmp_path, env, page_html, settle_enabled=True)
    first = st.perception.snapshot("s1", st.host.capture())
    result = st.action.execute("s1", _click(first, "Plain", "e6"))
    assert result["status"] == "ok"
    wait = result["wait"]
    assert wait["schema"] == "smc.browser_wait_verdict.v0.1"
    assert wait["mode"] == "raf_baseline"
    assert wait["cap_ms"] == 50
    assert wait["settled_by"] in {"raf", "cap"}  # race semantics: first branch wins
    assert (wait["settled_by"] == "raf") == (wait["verdict"] == "settled")
    assert 0 <= wait["elapsed_ms"] <= 80  # one settle round trip, hard bounded


def test_e7_combobox_settle_lands_first_valid_observation_one_cycle_earlier(tmp_path: Path, env, page_html) -> None:
    # Control arm: settle off -> immediate post-capture races the 120ms popup
    st_off = _stack(tmp_path, env, page_html, settle_enabled=False)
    first = st_off.perception.snapshot("s2", st_off.host.capture())
    off = st_off.action.execute("s2", _click(first, "Country", "e7-off"))
    assert off["status"] == "ok"
    assert "wait" not in off
    # pre-FR-2: capture races the 120ms popup, so the first observation
    # still shows the combobox collapsed; the model must poll again later.
    assert _input_expanded(st_off, "s2", off, "Country") is False

    # Treatment arm: settle on -> predicate waits out the 120ms render
    st_on = _stack(tmp_path, env, page_html, settle_enabled=True)
    first = st_on.perception.snapshot("s3", st_on.host.capture())
    on = st_on.action.execute("s3", _click(first, "Country", "e7-on"))
    assert on["status"] == "ok"
    assert on["wait"]["mode"] == "combobox_options"
    assert on["wait"]["verdict"] == "settled"
    assert on["wait"]["settled_by"] == "options"
    assert on["wait"]["visible_options"] >= 1
    assert on["wait"]["elapsed_ms"] <= 200
    # first valid observation already settled: the after bundle carries the
    # opened popup state, one polling cycle earlier than the control arm.
    assert _input_expanded(st_on, "s3", on, "Country") is True


def test_e8_combobox_timeout_is_honest_single_dispatch_no_retry(tmp_path: Path, env, page_html) -> None:
    st = _stack(tmp_path, env, page_html, settle_enabled=True)
    first = st.perception.snapshot("s4", st.host.capture())
    result = st.action.execute("s4", _click(first, "City", "e8"))
    assert result["status"] == "ok"  # timeout is honest, not a failure
    wait = result["wait"]
    assert wait["mode"] == "combobox_options"
    assert wait["verdict"] == "timeout"
    assert wait["settled"] is False
    assert wait["settled_by"] == "cap"
    assert wait["elapsed_ms"] >= 190  # really waited out the 200ms cap
    assert result["retry"]["attempt_count"] == 1  # single dispatch, never retried


def test_e9_settle_disabled_receipt_has_no_wait_field(tmp_path: Path, env, page_html) -> None:
    st = _stack(tmp_path, env, page_html, settle_enabled=False)
    first = st.perception.snapshot("s5", st.host.capture())
    result = st.action.execute("s5", _click(first, "Plain", "e9"))
    assert result["status"] == "ok"
    assert "wait" not in result
