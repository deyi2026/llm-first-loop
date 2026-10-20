"""Opt-in headless Chrome touch/viewport E2E for isolated Web V2 (no real API writes).

Start candidate Vite on 127.0.0.1:5187; run from repo root with Python Playwright.
LFL_WEB_MOBILE_QA_URL and LFL_WEB_MOBILE_QA_DIR optionally select a
candidate URL and a dedicated local output directory; do not use production paths.
All /api/* traffic is fulfilled with synthetic fixtures before reaching a backend.
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(os.environ.get("LFL_WEB_MOBILE_QA_DIR", "data/web-v2-mobile-qa-20261017"))
ROOT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get("LFL_WEB_MOBILE_QA_URL", "http://127.0.0.1:5187/ui/v2/?session=qa-a")
SESSIONS = [
    dict(
        session_id=s,
        title=t,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        message_count=120,
        status="active",
        last_message_preview="qa",
        pinned=False,
        channel="web",
    )
    for s, t in [("qa-a", "会话甲"), ("qa-b", "会话乙"), ("qa-c", "会话丙")]
]
REPORT = []


def intercept(route):
    url = urlsplit(route.request.url)
    path = url.path
    data = None
    if path == "/api/v1/events":
        return route.fulfill(
            status=200, content_type="text/event-stream", body="event: connected\ndata: {}\n\n"
        )
    if path == "/api/v1/sessions":
        data = dict(sessions=SESSIONS, count=len(SESSIONS))
    elif path == "/api/v1/session/current":
        data = {"current": "qa-a"}
    elif path.startswith("/api/v1/sessions/") and path.endswith("/messages"):
        sid = path.split("/")[4]
        limit = int(parse_qs(url.query).get("limit", ["100"])[0])
        offset = int(parse_qs(url.query).get("offset", ["0"])[0])
        content = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"{sid} history item #{i}"}
            for i in range(120)
        ]
        count = len(content)
        data = {
            "session_id": sid,
            "total": count,
            "has_more": offset + limit < count,
            "messages": content[max(0, count - offset - limit) : count - offset],
        }
    elif path == "/api/v1/agents/tree":
        data = {"nodes": []}
    elif path == "/api/v1/workspaces":
        data = {"workspaces": [], "current": None}
    elif path == "/api/v1/chat/stream/status":
        data = {"running": False}
    elif path.startswith("/api/v1/chat/queue"):
        data = {"items": [], "count": 0, "queued": 0, "claimed": 0}
    elif path == "/api/v1/capabilities":
        data = {"capabilities": {}}
    elif path == "/api/v1/models":
        data = {"models": [], "current": None, "catalog": []}
    elif path == "/auth/status":
        data = {"authenticated": True, "browser_login": False}
    elif path == "/health":
        data = {"status": "ok"}
    elif path.startswith("/api/"):
        data = {}
    if data is not None:
        return route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(data, ensure_ascii=False),
        )
    return route.continue_()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    try:
        for width, height in [
            (320, 568),
            (375, 812),
            (390, 844),
            (430, 932),
            (768, 1024),
            (1366, 850),
        ]:
            mobile = width <= 900
            context = browser.new_context(
                viewport={"width": width, "height": height},
                is_mobile=mobile,
                has_touch=mobile,
                device_scale_factor=2 if mobile else 1,
            )
            page = context.new_page()
            page.route("**/*", intercept)
            errors = []
            page.on("pageerror", lambda err, errors=errors: errors.append(str(err)))
            try:
                page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
                page.locator("[data-testid=app-shell]").wait_for(timeout=20000)
                page.get_by_text("qa-a history item #119", exact=False).first.wait_for(
                    timeout=15000
                )
                viewport = page.evaluate(
                    "({w:innerWidth, doc:document.documentElement.scrollWidth, body:document.body.scrollWidth})"
                )
                check(viewport["doc"] <= viewport["w"] + 1, f"horizontal page overflow: {viewport}")
                if mobile:
                    panel_toggle = page.get_by_test_id("right-panel-toggle")
                    toggle_rect = panel_toggle.bounding_box()
                    check(
                        toggle_rect is not None and toggle_rect["x"] >= 0
                        and toggle_rect["x"] + toggle_rect["width"] <= width + 1,
                        f"right-panel entry missing or pushed outside viewport: {toggle_rect}",
                    )
                    check(
                        toggle_rect["x"] + toggle_rect["width"] >= width - 2,
                        f"mobile panel arrow not attached to right screen edge: {toggle_rect}",
                    )
                    check(
                        panel_toggle.inner_text().strip() == "◂"
                        and panel_toggle.get_attribute("aria-expanded") == "false",
                        "mobile panel missing the desktop-equivalent closed arrow",
                    )
                    check(
                        panel_toggle.evaluate("(e) => getComputedStyle(e).position") == "fixed",
                        "mobile arrow is not fixed to the phone viewport",
                    )
                    page.locator("[data-testid=topbar] button").first.click()
                    check(
                        page.locator("[data-testid=app-shell]").evaluate(
                            '(e)=>e.classList.contains("mobile-sidebar-open")'
                        ),
                        "sidebar did not open",
                    )
                    scrim = page.get_by_role("button", name="关闭会话侧栏")
                    check(scrim.count() == 1, "sidebar scrim must be accessible")
                    scrim_border = scrim.evaluate("(e)=>getComputedStyle(e).borderTopWidth")
                    check(
                        scrim_border == "0px",
                        f"mobile scrim has unwanted native button border {scrim_border}",
                    )
                    page.get_by_text("会话乙", exact=True).first.click()
                    page.get_by_text("qa-b history item #119", exact=False).first.wait_for(
                        timeout=15000
                    )
                    check(
                        not page.locator("[data-testid=app-shell]").evaluate(
                            '(e)=>e.classList.contains("mobile-sidebar-open")'
                        ),
                        "sidebar did not close on navigation",
                    )
                    page.locator("[data-testid=topbar] button").first.click()
                    page.keyboard.press("Escape")
                    check(
                        not page.locator("[data-testid=app-shell]").evaluate(
                            '(e)=>e.classList.contains("mobile-sidebar-open")'
                        ),
                        "Escape did not close sidebar",
                    )
                    panel_toggle.click()
                    check(
                        panel_toggle.inner_text().strip() == "▸"
                        and panel_toggle.get_attribute("aria-expanded") == "true",
                        "mobile panel missing the opened-state arrow",
                    )
                    check(
                        page.get_by_role("button", name="关闭右侧面板").count() == 1,
                        "panel scrim missing",
                    )
                    panel = page.locator('[data-testid="right-panel"]')
                    panel.wait_for(state="visible")
                    arrow_open = panel_toggle.bounding_box()
                    panel_open = panel.bounding_box()
                    check(
                        arrow_open is not None and panel_open is not None
                        and abs(arrow_open["x"] + arrow_open["width"] - panel_open["x"]) <= 2,
                        f"open arrow covers panel or is detached from its edge: arrow={arrow_open}, panel={panel_open}",
                    )
                    tab_boxes = panel.locator(".v2-panel-tabs > button").evaluate_all(
                        """(buttons) => buttons.map(node => ({
                           text: node.textContent?.trim(),
                           rect: node.getBoundingClientRect().toJSON(),
                           panel: node.closest('aside').getBoundingClientRect().toJSON()
                        }))"""
                    )
                    check(
                        bool(tab_boxes) and all(
                            item["rect"]["left"] >= item["panel"]["left"] - 1
                            and item["rect"]["right"] <= item["panel"]["right"] + 1
                            for item in tab_boxes
                        ),
                        f"right-panel tabs are clipped: {tab_boxes}",
                    )
                    panel.get_by_role("button", name="预览").click()
                    panel.get_by_role("button", name="设置").click()
                    if width in (320, 375, 390):
                        page.screenshot(path=str(ROOT / f"viewport-{width}-right-panel-open.png"))
                    panel_toggle.click()
                    page.locator("[data-testid=right-panel]").wait_for(state="detached", timeout=5000)
                    check(panel_toggle.inner_text().strip() == "◂", "arrow did not restore after closing")
                    panel_toggle.click()
                    page.keyboard.press("Escape")
                    check(
                        not page.locator("[data-testid=app-shell]").evaluate(
                            '(e)=>e.classList.contains("mobile-panel-open")'
                        ),
                        "Escape did not close panel",
                    )
                    panel_toggle.click()
                    panel.get_by_role("button", name="收起右侧面板").click()
                    page.locator("[data-testid=right-panel]").wait_for(state="detached", timeout=5000)
                else:
                    page.get_by_text("会话乙", exact=True).first.click()
                    page.get_by_text("qa-b history item #119", exact=False).first.wait_for(
                        timeout=15000
                    )
                scroll = page.locator("[data-testid=message-list]").evaluate(
                    "(e)=>({h:e.scrollHeight,v:e.clientHeight})"
                )
                check(scroll["h"] > scroll["v"], f"history is not scrollable {scroll}")
                page.locator("[data-testid=message-list]").evaluate("(e)=>e.scrollTop=0")
                page.wait_for_timeout(100)
                check(
                    page.locator("[data-testid=message-list]").evaluate("(e)=>e.scrollTop") == 0,
                    "message list cannot scroll to top",
                )
                check(not errors, f"JS page errors: {errors[:2]}")
                if width in [375, 390, 768, 1366]:
                    page.screenshot(path=str(ROOT / f"viewport-{width}.png"))
                REPORT.append(
                    {
                        "width": width,
                        "height": height,
                        "status": "PASS",
                        "overflow": viewport,
                        "scroll": scroll,
                    }
                )
                print(f"PASS {width}x{height}, scroll={scroll}", flush=True)
            except Exception as exc:
                with suppress(Exception):
                    page.screenshot(path=str(ROOT / f"FAIL-{width}.png"), timeout=2500)
                REPORT.append(
                    {"width": width, "height": height, "status": "FAIL", "detail": str(exc)[:900]}
                )
                print(f"FAIL {width}x{height}: {str(exc)[:350]}", flush=True)
            finally:
                context.close()
    finally:
        browser.close()
(ROOT / "report.json").write_text(
    json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("TOTAL", len(REPORT), "FAILURES", sum(r["status"] != "PASS" for r in REPORT))

if any(result["status"] != "PASS" for result in REPORT):
    raise SystemExit(1)
