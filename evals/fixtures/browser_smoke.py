"""Browser-level smoke for the shared SMC ground truth fixture.

Complements the in-file HTTP self-check (``python3 evals/fixtures/smc_ground_truth_server.py``).
This one drives a real headless Chromium through every route family and
asserts against the server-side ``/state`` event log. Element names come from
``/manifest`` (data-driven, no hardcoded DOM expectations).

Requires: playwright (``pip install playwright`` + browser binaries).
Run:  python3 evals/fixtures/browser_smoke.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smc_ground_truth_server import GroundTruthServer  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

CHECKS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    line = ("PASS" if cond else "FAIL") + " " + name
    if detail and not cond:
        line += f" :: {detail}"
    CHECKS.append(line)
    return cond


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _events(state: dict, kind: str | None = None, element_id: str | None = None) -> list[dict]:
    return [e for e in state["events"]
            if (kind is None or e.get("kind") == kind)
            and (element_id is None or e.get("element_id") == element_id)]


def _cname(manifest: dict, route: str, idx: int = 0) -> str:
    return manifest["routes"][route]["canonical_objects"][idx]["name"]


def main() -> int:
    with GroundTruthServer() as srv:
        manifest = _get_json(srv.url + "manifest")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()

            # 1. unique click -> exactly one click event
            page.goto(srv.route_url("/unique/click"))
            page.get_by_role("button", name=_cname(manifest, "/unique/click")).click()
            check("unique click: exactly 1 event",
                  len(_events(_get_json(srv.url + "state"), "click", "run-check")) == 1)

            # 2. unique fill -> fill event carries the value
            page.goto(srv.route_url("/unique/fill"))
            page.get_by_label(_cname(manifest, "/unique/fill", 0), exact=True).fill("PC-42")
            page.get_by_role("button", name=_cname(manifest, "/unique/fill", 1)).click()
            ev = _events(_get_json(srv.url + "state"), "fill", "code")
            check("unique fill: 1 event, value carried",
                  len(ev) == 1 and ev[0].get("value") == "PC-42")

            # 3. unique select -> select event carries the option
            page.goto(srv.route_url("/unique/select"))
            page.get_by_label(_cname(manifest, "/unique/select"), exact=True).select_option("west")
            page.get_by_role("button", name="Save region").click()
            ev = _events(_get_json(srv.url + "state"), "select", "region")
            check("unique select: 1 event, option carried",
                  len(ev) == 1 and ev[0].get("value") == "west")

            # 4. scroll -> debounced scroll event with scrollTop
            page.goto(srv.route_url("/unique/scroll"))
            page.locator("#scroll-area").evaluate("el => el.scrollTop = 300")
            page.wait_for_timeout(400)
            ev = _events(_get_json(srv.url + "state"), "scroll", "scroll-area")
            check("unique scroll: >=1 event, scrollTop>0",
                  len(ev) >= 1 and ev[0].get("scrollTop", 0) > 0)

            # 5. pollution: raw AX object graph carries >= 2 same-name nodes
            #    (button + StaticText/InlineTextBox children), so name-only
            #    matching is polluted while kind+name resolves to one button.
            #    Note: aria_snapshot() folds the text into the button name
            #    (count == 1), so count the CDP full AX tree instead.
            page.goto(srv.route_url("/pollution/button-text-child"))
            name = _cname(manifest, "/pollution/button-text-child")
            try:
                cdp = page.context.new_cdp_session(page)
                tree = cdp.send("Accessibility.getFullAXTree")
                count = sum(
                    1 for n in tree["nodes"]
                    if (n.get("name") or {}).get("value") == name
                )
            except Exception:
                count = page.locator("body").aria_snapshot().count(name)
            check("pollution: raw AX occurrences >= 2 (name-only polluted)",
                  count >= 2, f"got {count}")

            # 6. ambiguity: kind+name matches exactly 2, no dispatch
            before = _get_json(srv.url + "state")["count"]
            page.goto(srv.route_url("/ambiguous/two-buttons"))
            n = page.get_by_role("button", name=_cname(manifest, "/ambiguous/two-buttons"),
                                 exact=True).count()
            check("ambiguous: kind+name matches == 2",
                  n == 2, f"got {n}")
            check("ambiguous: zero side effect (state unchanged)",
                  _get_json(srv.url + "state")["count"] == before)

            # 7. delayed enable: actionability wait -> ready_click, no early_click
            page.goto(srv.route_url("/wait/delayed-enable", delay_ms=400))
            page.get_by_role("button", name=_cname(manifest, "/wait/delayed-enable")).click(timeout=15_000)
            page.wait_for_timeout(200)
            st = _get_json(srv.url + "state")
            check("delayed enable: ready_click once, no early_click",
                  len(_events(st, "ready_click", "run-check")) == 1
                  and not _events(st, "early_click"))

            # 8. delayed appear: object absent at load becomes visible
            page.goto(srv.route_url("/wait/delayed-appear", delay_ms=300))
            page.get_by_label(_cname(manifest, "/wait/delayed-appear"), exact=True).wait_for(state="visible", timeout=5_000)
            check("delayed appear: target visible after delay",
                  page.locator("#target").is_visible())

            # 9. navigate a -> b via link
            page.goto(srv.route_url("/navigate/page-a"))
            page.get_by_role("link", name="Go to page B").click()
            check("navigate: a -> b marker", page.locator("[data-page='b']").count() == 1)

            # 10. htmx shim: hx-* click reports hx_click + swaps receipt
            page.goto(srv.route_url("/htmx/click"))
            page.get_by_role("button", name=_cname(manifest, "/htmx/click")).click()
            page.wait_for_timeout(300)
            ev = _events(_get_json(srv.url + "state"), "hx_click", "hx-commit")
            check("htmx shim: 1 hx_click + receipt swap",
                  len(ev) == 1 and "Hx submitted" in page.locator("#receipt").inner_text())

            browser.close()

    fails = [c for c in CHECKS if c.startswith("FAIL")]
    for line in CHECKS:
        print(line)
    print(f"BROWSER SMOKE: {len(CHECKS) - len(fails)}/{len(CHECKS)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
