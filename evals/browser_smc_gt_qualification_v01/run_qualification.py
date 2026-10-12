#!/usr/bin/env python3
"""First consumer of the shared SMC ground-truth fixture (qualification v01).

Every expectation is read from the fixture's ``/manifest`` at run time; the
server-side ``/state`` event log is the only effect oracle. The runner holds
no route-specific names, ids, or event shapes.

Not a model study: no worker, no provider, no frozen prompts. See
PROTOCOL.v1.md for the clause contracts and the runner-policy vs
fixture-expectation split.

Run:  python3 evals/browser_smc_gt_qualification_v01/run_qualification.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures"
sys.path.insert(0, str(FIXTURES))

from smc_ground_truth_server import GroundTruthServer  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SCHEMA = "smc.browser_gt_qualification_v01.plan"
FILL_VALUE = "qual-v01"
SCROLL_TOP = 300
SETTLE_MS = 400
WAIT_DELAY_MS = 250
RESULTS = HERE / "results"

# runner policy: expected-event kind -> canonical kind that performs it
_PRIMARY_KIND = {
    "click": "button",
    "hx_click": "button",
    "ready_click": "button",
    "fill": "input",
    "select": "select",
    "scroll": "region",
}


def _get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalized(page: Any) -> str:
    """page.content() with attribute quotes normalized to single quotes.

    Chromium serializes attributes with double quotes regardless of the
    source markup, while manifest markers are written with single quotes.
    """
    return page.content().replace('"', "'")


def _count_ok(actual: int, expected: Any) -> bool:
    if isinstance(expected, bool):
        return False
    if isinstance(expected, int):
        return actual == expected
    if isinstance(expected, str) and expected.startswith(">="):
        return actual >= int(expected[2:])
    return False


def _clause_family(route: str) -> str:
    if route == "/":
        return "index"
    if route.startswith("/unique/") or route.startswith("/htmx/"):
        return "dispatch"
    if route.startswith("/pollution/"):
        return "grounding_probe"
    if route.startswith("/ambiguous/"):
        return "halt"
    if route == "/wait/delayed-enable":
        return "wait_then_dispatch"
    if route == "/wait/delayed-appear":
        return "wait_observe"
    raise AssertionError(f"unmapped route family: {route}")


def _locator(page: Any, obj: dict[str, Any]) -> Any:
    kind, name = obj["kind"], obj["name"]
    if kind == "button":
        return page.get_by_role("button", name=name, exact=True)
    if kind == "region":
        return page.get_by_role("region", name=name, exact=True)
    if kind in ("input", "select", "div"):
        return page.locator(f"[aria-label='{name}']")
    raise AssertionError(f"unmapped canonical kind: {kind}")


def _grounding(page: Any, rec: dict[str, Any], obj: dict[str, Any]) -> bool:
    expected = obj.get("kind_name_matches", 1)
    actual = _locator(page, obj).count()
    if not _count_ok(actual, expected):
        rec["failures"].append(
            f"grounding {obj['kind']}+{obj['name']!r}: count {actual} vs {expected}")
        return False
    name_only = obj.get("name_only_matches")
    if name_only is not None:
        cdp = page.context.new_cdp_session(page)
        tree = cdp.send("Accessibility.getFullAXTree")
        raw = sum(1 for nd in tree["nodes"]
                  if (nd.get("name") or {}).get("value") == obj["name"])
        if not _count_ok(raw, name_only):
            rec["failures"].append(
                f"name-only pollution {obj['name']!r}: raw AX {raw} vs {name_only}")
            return False
    return True


def _act(page: Any, meta: dict[str, Any]) -> None:
    expected = meta.get("expected_events", [])
    if not expected:
        return  # halt / observe clauses: no mutation by contract
    primary = _PRIMARY_KIND[expected[0]["kind"]]
    for obj in meta["canonical_objects"]:
        if obj["kind"] != primary:
            continue
        loc = _locator(page, obj)
        if obj["kind"] == "button":
            loc.click()
        elif obj["kind"] == "input":
            loc.fill(FILL_VALUE)
        elif obj["kind"] == "select":
            options = loc.locator("option").all_inner_texts()
            loc.select_option(options[-1])
        elif obj["kind"] == "region":
            loc.evaluate(f"el => el.scrollTop = {SCROLL_TOP}")
            page.wait_for_timeout(SETTLE_MS)
    if primary != "button":
        for obj in meta["canonical_objects"]:
            if obj["kind"] == "button":
                _locator(page, obj).click()


def _assert_events(rec: dict[str, Any], events: list[dict], expected: list[dict]) -> None:
    actual_counts: dict[tuple, int] = {}
    for ev in events:
        key = (ev.get("kind"), ev.get("element_id"))
        actual_counts[key] = actual_counts.get(key, 0) + 1
    expected_counts: dict[tuple, Any] = {}
    for ev in expected:
        key = (ev["kind"], ev["element_id"])
        expected_counts[key] = ev["count"]
    for key, want in expected_counts.items():
        got = actual_counts.get(key, 0)
        if not _count_ok(got, want):
            rec["failures"].append(f"events {key}: {got} vs {want}")
    for key in actual_counts:
        if key not in expected_counts:
            rec["failures"].append(f"unexpected event {key}")


def _run_clause(page: Any, srv: GroundTruthServer, manifest: dict, route: str) -> dict:
    meta = manifest["routes"][route]
    family = _clause_family(route)
    rec: dict[str, Any] = {"route": route, "family": family, "failures": []}
    params = {"delay_ms": WAIT_DELAY_MS} if route.startswith("/wait/") else {}
    page.goto(srv.route_url(route, **params))
    # baseline BEFORE any interaction: action effects must land inside the
    # delta, and any load-time side effect must surface as unexpected.
    rec["baseline"] = _get_json(srv.url + "state")["count"]
    if family == "index":
        content = _normalized(page)
        if meta.get("marker") and meta["marker"] not in content:
            rec["failures"].append("index marker missing")
        hrefs = page.locator("a").evaluate_all(
            "els => els.map(e => e.getAttribute('href'))")
        for other in manifest["routes"]:
            if other != "/" and other not in hrefs:
                rec["failures"].append(f"index missing link to {other}")
    elif family == "wait_observe":
        for obj in meta["canonical_objects"]:
            _locator(page, obj).wait_for(state="visible", timeout=8_000)
        for obj in meta["canonical_objects"]:
            _grounding(page, rec, obj)
    else:
        for obj in meta["canonical_objects"]:
            _grounding(page, rec, obj)
        if not rec["failures"]:
            _act(page, meta)
    _assert_events(rec, _delta(srv, rec), meta.get("expected_events", []))
    rec["pass"] = not rec["failures"]
    return rec


def _delta(srv: GroundTruthServer, rec: dict) -> list[dict]:
    events = _get_json(srv.url + "state")["events"]
    return events[rec["baseline"]:]


def _run_navigate(page: Any, srv: GroundTruthServer, manifest: dict, nav: list[str]) -> dict:
    rec: dict[str, Any] = {
        "route": f"{nav[0]} -> {nav[1]}", "family": "navigate_pair", "failures": []}
    page.goto(srv.route_url(nav[0]))
    rec["baseline"] = _get_json(srv.url + "state")["count"]
    page.locator(f"a[href='{nav[1]}']").click()
    content = _normalized(page)
    marker = manifest["routes"][nav[1]].get("marker")
    if marker and marker not in content:
        rec["failures"].append(f"landing marker missing: {marker}")
    _assert_events(rec, _delta(srv, rec), [])
    rec["pass"] = not rec["failures"]
    return rec


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS / f"run_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    clauses: list[dict] = []
    final_state: dict = {}
    manifest: dict = {}
    with GroundTruthServer() as srv:
        manifest = _get_json(srv.url + "manifest")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            nav = [r for r in manifest["routes"] if r.startswith("/navigate/")]
            for route in manifest["routes"]:
                if route.startswith("/navigate/"):
                    continue
                clauses.append(_run_clause(page, srv, manifest, route))
            if len(nav) >= 2:
                clauses.append(_run_navigate(page, srv, manifest, nav))
            final_state = _get_json(srv.url + "state")
            browser.close()

    manifest_sha = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
    gate = "PASS" if all(c["pass"] for c in clauses) else "FAIL"
    summary = {
        "schema": SCHEMA,
        "fixture": manifest.get("fixture"),
        "manifest_sha256": manifest_sha,
        "gate": gate,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clauses": clauses,
        "final_state": final_state,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    for c in clauses:
        status = "PASS" if c["pass"] else "FAIL"
        print(f"{status} [{c['family']}] {c['route']}")
        for f in c["failures"]:
            print(f"      - {f}")
    print(f"QUALIFICATION {gate}: {sum(c['pass'] for c in clauses)}/{len(clauses)} clauses; receipt {out_dir / 'summary.json'}")
    return 0 if gate == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
