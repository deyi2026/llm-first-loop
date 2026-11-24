"""Opt-in isolated Chrome qualification for long history viewport rendering.

All API requests are synthetic; no real Run, write, or production browser.
Start candidate Vite on loopback port 5197 with --strictPort.
"""
from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

BASE = os.environ.get("LFL_HISTORY_QA_URL", "http://127.0.0.1:5197/ui/v2/?session=qa-history")
ORIGIN = urlsplit(BASE)
assert ORIGIN.hostname == "127.0.0.1" and ORIGIN.port == 5197
TOTAL = 350
SID = "qa-history"


def intercept(route):
    url = urlsplit(route.request.url)
    if (url.scheme, url.netloc) != (ORIGIN.scheme, ORIGIN.netloc):
        return route.abort()
    path = url.path
    data = None
    if path == "/api/v1/events":
        return route.fulfill(status=200, content_type="text/event-stream", body="event: connected\ndata: {}\n\n")
    if path == "/api/v1/sessions":
        data = {"sessions": [{"session_id": SID, "title": "QA history", "created_at": "2026-01-01T00:00:00Z",
                              "updated_at": "2026-01-01T00:00:00Z", "message_count": TOTAL,
                              "status": "active", "last_message_preview": "QA", "channel": "web"}], "count": 1}
    elif path == "/api/v1/session/current":
        data = {"current": SID}
    elif path == f"/api/v1/sessions/{SID}/messages":
        q = parse_qs(url.query)
        limit, offset = int(q.get("limit", ["50"])[0]), int(q.get("offset", ["0"])[0])
        end = max(0, TOTAL - offset)
        start = max(0, end - limit)
        data = {"session_id": SID, "total": TOTAL, "has_more": start > 0, "revision": "qa-stable",
                "messages": [{"index": i, "role": "user" if i % 2 == 0 else "assistant",
                              "content": f"QA row {i:04d}\n\n" + ("**text** and `code` " * (1 + i % 9))}
                             for i in range(start, end)]}
    elif path == "/api/v1/chat/stream/status":
        data = {"running": False}
    elif path.startswith("/api/v1/chat/queue"):
        data = {"items": [], "count": 0, "queued": 0, "claimed": 0}
    elif path == "/api/v1/capabilities":
        data = {"capabilities": {}}
    elif path == "/api/v1/coordination/board":
        data = {"channel": None, "lanes": [], "overlaps": [], "degraded": [], "deployment": {"in_sync": True}}
    elif path == "/api/v1/workspaces":
        data = {"workspaces": [], "current": None}
    elif path == "/api/v1/agents/tree":
        data = {"nodes": []}
    elif path == "/api/v1/models":
        data = {"models": [], "current": None, "catalog": []}
    elif path == "/auth/status":
        data = {"authenticated": True, "browser_login": False}
    elif path == "/health":
        data = {"status": "ok"}
    elif path.startswith("/api/"):
        data = {}
    if data is not None:
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
    return route.continue_()


def settle(page):
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    try:
        for width, height in [(1366, 850), (390, 844)]:
            context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=width < 900, has_touch=width < 900)
            page = context.new_page()
            page.route("**/*", intercept)
            errors = []
            page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
            page.goto(BASE, wait_until="domcontentloaded")
            rows = page.locator(".v2-message-list > [data-history-row=true]")
            rows.last.wait_for()
            assert rows.count() == 50
            counts = [50]
            for count in range(100, TOTAL + 1, 50):
                button = page.get_by_role("button", name="↑ 加载更早")
                button.click()
                page.wait_for_function("(n) => document.querySelectorAll('.v2-message-list > [data-history-row=true]').length === n", arg=count)
                settle(page)
                counts.append(count)
            assert rows.count() == TOTAL
            assert rows.evaluate_all("els => els.every((el,i) => el.textContent.includes('QA row '+String(i).padStart(4,'0')))")
            assert page.locator(".v2-long-history").count() == 1
            assert page.evaluate("CSS.supports('content-visibility', 'auto')")
            list_node = page.get_by_test_id("message-list")
            page.locator(".v2-scroll-bottom").click()
            page.wait_for_timeout(350)
            settle(page)
            stats = list_node.evaluate("""el => {
                const rows = [...el.querySelectorAll(':scope > [data-history-row=true]')];
                const box = el.getBoundingClientRect();
                const last = rows.at(-1).getBoundingClientRect();
                return {rows:rows.length, skipped:rows.filter(r => !r.firstElementChild.checkVisibility({contentVisibilityAuto:true})).length,
                        lastVisible:last.top < box.bottom && last.bottom > box.top,
                        css:getComputedStyle(rows[0]).contentVisibility,
                        overflow:document.documentElement.scrollWidth > innerWidth + 1};
            }""")
            assert stats["skipped"] > 0 and stats["lastVisible"] and stats["css"] == "auto" and not stats["overflow"], stats
            # Native rendering must reveal the exact old row when navigated to,
            # without deleting any DOM history or submitting a message.
            rows.first.scroll_into_view_if_needed()
            settle(page)
            assert rows.first.evaluate("el => el.firstElementChild.checkVisibility({contentVisibilityAuto:true})")
            assert "QA row 0000" in rows.first.inner_text()
            assert rows.count() == TOTAL and not errors, errors
            page.locator(".v2-scroll-bottom").click()
            page.wait_for_timeout(350)
            settle(page)
            assert rows.last.evaluate("el => {const box=el.parentElement.getBoundingClientRect();const row=el.getBoundingClientRect();return row.top < box.bottom && row.bottom > box.top;}")
            print(json.dumps({"viewport": [width,height], "pages":counts, **stats, "first_row_revealed":True, "page_errors":len(errors)}))
            context.close()
    finally:
        browser.close()
