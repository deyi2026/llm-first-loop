"""Read-only browser scroll qualification for Web V2 (requires Python Playwright).

Run against a local candidate or live Web V2 URL:
  python scripts/qualification/web_v2_scroll_qualification.py --url http://127.0.0.1:8976/ui/v2/

All stateful API methods are blocked in this disposable browser context. Long
suggestions, archives, service identities and escalation records are intercepted
with fixtures; this cannot approve, reject, restart or edit real workspace data.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from playwright.async_api import Page, async_playwright


def fixtures() -> dict[str, object]:
    sessions = [
        {
            "session_id": f"scroll-qa-{i}",
            "title": f"滚动验收会话 {i}",
            "message_count": 120,
            "channel": "web",
            "status": "active",
            "pinned": False,
            "created_at": "2026-10-13T00:00:00Z",
            "updated_at": "2026-10-13T00:00:00Z",
            "last_message_preview": "只读测试历史",
        }
        for i in range(3)
    ]
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"只读测试消息 {i}"}
        for i in range(120)
    ]
    suggestions = [
        {
            "id": f"EVO-SCROLL-{i:03d}",
            "content": ("可阅读的演进方案内容。" * 18) + str(i),
            "impact_hint": "webui/src/App.tsx",
            "status": "pending_review",
            "priority": "P1",
            "requires_human": True,
            "ts": "2026-10-13T00:00:00+08:00",
        }
        for i in range(70)
    ]
    archived = [
        {
            "session_id": f"archive-scroll-{i}",
            "title": f"归档会话 {i}",
            "message_count": i + 1,
            "channel": "web",
            "status": "archived",
            "updated_at": "2026-10-13T00:00:00+08:00",
        }
        for i in range(90)
    ]
    services = {
        "deployment": {
            "generation": 255,
            "git_head": "c" * 40,
            "code_root": "/example/" + "very-long-identity-path/" * 28,
        },
        "services": {
            name: {
                "restart_required": False,
                "live": {
                    "manifest_present": True,
                    "pid": 100,
                    "pid_alive": True,
                    "git_head": "c" * 40,
                },
                "stable": {
                    "generation": 255,
                    "git_head": "c" * 40,
                    "matches_desired_generation": True,
                    "succeeded_at": "2026-10-13T00:00:00+08:00",
                },
                "reasons": [],
            }
            for name in ("web", "feishu", "learning", "reviewer", "worker", "tools", "cache", "data")
        },
        "server_tz_offset_minutes": 480,
    }
    escalations = {
        "pending_count": 0,  # no global pending-approval modal
        "requests": [
            {
                "id": f"esc-scroll-{i}",
                "status": "consumed",
                "tool_name": "read_file",
                "command": ("read-only command with long arguments " * 8) + str(i),
                "justification": "可审计的只读请求",
                "session_id": "fixture-only",
                "created_at": "2026-10-13T00:00:00+08:00",
                "decided_at": "2026-10-13T00:00:00+08:00",
                "decided_by": "test",
                "decision_note": "",
            }
            for i in range(40)
        ],
    }
    detail = {
        **suggestions[0],
        "content": "长篇演进建议明细和证据。\n" * 220,
        "scope": "web-only",
        "evidence": "独立验证材料。\n" * 25,
        "impact_files": [f"docs/review-{i}.md" for i in range(35)],
    }
    return {
        "sessions": {"sessions": sessions, "count": len(sessions)},
        "current": {"current": "scroll-qa-0"},
        "messages": {"session_id": "scroll-qa-0", "total": len(messages), "has_more": False, "messages": messages},
        "suggestions": {"suggestions": suggestions},
        "services": services,
        "archive": {"sessions": archived, "count": len(archived)},
        "escalations": escalations,
        "detail": detail,
        "diff": {"actions": [{"kind": "read-only", "description": "详细改动 " * 80}] * 10},
    }


async def scroll_check(page: Page, selector: str, label: str) -> dict[str, object]:
    # Short-height layout intentionally uses a single outer sidebar scrollport,
    # so wheel/keyboard access is still practical after its chrome consumes most
    # of the viewport; don't incorrectly require the nested list to scroll.
    if page.viewport_size["height"] <= 520 and label in {
        "evolution-list", "escalation", "archives", "file-tree",
    }:
        selector = ".v2-sidebar"
    element = page.locator(selector).first
    await element.wait_for(state="attached")
    await element.evaluate("(node) => { node.scrollTop = 0 }")
    before = await element.evaluate(
        "(node) => ({client:node.clientHeight, content:node.scrollHeight,"
        "overflow:getComputedStyle(node).overflowY})"
    )
    assert before["content"] - before["client"] > 50, f"{label}: overflow fixture is not present: {before}"
    await element.hover()
    await page.mouse.wheel(0, 420)
    await page.wait_for_timeout(200)
    after = await element.evaluate("(node) => node.scrollTop")
    assert after > 0, f"{label}: wheel could not scroll: {before}"
    return {"view": label, "client": before["client"], "content": before["content"], "scrollTop": after}


async def services_layout_check(page: Page) -> dict[str, object]:
    """Catch a distinct failure: a KPI two-column grid applied to service cards.

    A scrollable parent alone does not ensure useful card widths. The screenshot
    incident had web/learning in ~110px columns and feishu across the rest.
    Check computed geometry and the ability to reach the final card as well.
    """
    result = await page.evaluate(
        """() => {
          const view = document.querySelector('[data-testid="services-panel"]');
          const grid = view?.querySelector('.v2-services-grid');
          const cards = [...(grid?.querySelectorAll('[data-testid^="service-card-"]') ?? [])];
          const box = (node) => { const rect = node.getBoundingClientRect(); return {
            x:rect.x, y:rect.y, width:rect.width, right:rect.right, bottom:rect.bottom
          }; };
          return {
            view: view ? {...box(view), clientHeight:view.clientHeight, scrollHeight:view.scrollHeight} : null,
            grid: grid ? {...box(grid), clientWidth:grid.clientWidth,
              scrollWidth:grid.scrollWidth, columns:getComputedStyle(grid).gridTemplateColumns} : null,
            cards: cards.map((card) => ({name:card.dataset.testid, ...box(card)}))
          };
        }"""
    )
    assert result["grid"] is not None, f"service identity uses wrong grid class: {result}"
    assert len(result["cards"]) >= 3, f"service card data missing: {result}"
    grid = result["grid"]
    assert grid["scrollWidth"] <= grid["clientWidth"] + 3, f"service grid extends horizontally: {result}"
    for card in result["cards"]:
        assert card["width"] >= 220, f"service card too narrow: {card}"
        assert card["right"] <= grid["right"] + 3, f"service card outside grid: {card}"
    widths = [round(card["width"]) for card in result["cards"]]
    assert max(widths) - min(widths) <= 2, f"unequal service cards: {widths}"
    view = page.get_by_test_id("services-panel")
    await view.evaluate("(node) => { node.scrollTop = node.scrollHeight }")
    last_visible = await view.evaluate(
        """(node) => {
          const card = node.querySelector('[data-testid="service-card-data"]');
          return !!card && card.getBoundingClientRect().bottom <=
            node.getBoundingClientRect().bottom + 3;
        }"""
    )
    assert last_visible, "final service card is inaccessible at the bottom of the scrollport"
    return {"view": "service-grid", "cardWidth": widths[0], "cardCount": len(widths),
            "columns": grid["columns"], "lastCardReachable": last_visible}


async def run_viewport(browser: object, url: str, width: int, height: int) -> list[dict[str, object]]:
    page = await browser.new_page(viewport={"width": width, "height": height})
    data = fixtures()
    async def no_mutation(route: object) -> None:
        if route.request.method != "GET":
            await route.fulfill(status=403, json={"detail": "qualification is read-only"})
        else:
            # This is a disposable, fully fixture-backed context, not a live
            # backend smoke test. Unknown endpoints never reach production.
            await route.fulfill(status=200, json={})

    await page.route("**/api/**", no_mutation)
    def fixture_response(body: object):
        async def respond(route: object) -> None:
            await route.fulfill(status=200, json=body)
        return respond

    for pattern, key in (
        ("**/api/v1/sessions", "sessions"),
        ("**/api/v1/sessions?*", "sessions"),
        ("**/api/v1/session/current", "current"),
        ("**/api/v1/sessions/*/messages*", "messages"),
        ("**/api/v1/evolution/list?*", "suggestions"),
        ("**/api/v1/evolution/detail?*", "detail"),
        ("**/api/v1/evolution/diff?*", "diff"),
        ("**/api/v1/services/status", "services"),
        ("**/api/v1/sessions?include_archived=true", "archive"),
        ("**/api/v1/escalation/list?*", "escalations"),
    ):
        await page.route(pattern, fixture_response(data[key]))

    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    assert response and response.status == 200, "Web V2 page unreachable"
    await page.get_by_test_id("topbar").wait_for()
    await page.wait_for_timeout(500)
    mobile = width <= 900
    menu = page.get_by_test_id("topbar").locator("button").first
    results: list[dict[str, object]] = []

    if mobile:
        await menu.click()
        assert await page.locator(".v2-shell.mobile-sidebar-open").count() == 1
    await page.get_by_test_id("tab-evo").click()
    await page.locator('[data-testid^="evo-view-"]').first.wait_for(timeout=10000)
    results.append(await scroll_check(page, ".v2-evo-body", "evolution-list"))

    # Review the detail and safety-confirm dialogs; never click '确定' or make
    # any approval POST. This checks independent modal scroll containers.
    await page.locator(".v2-evo-body").evaluate("(node) => { node.scrollTop = 0 }")
    await page.locator('[data-testid^="evo-view-"]').first.click()
    await page.get_by_test_id("evo-detail-content").wait_for(timeout=10000)
    results.append(await scroll_check(page, ".v2-evo-detail-scroll", "evolution-detail"))
    await page.get_by_test_id("evo-detail-approve").click()
    confirmation = page.get_by_test_id("evo-confirm-modal").locator(".v2-evo-modal-box")
    await confirmation.wait_for()
    dimensions = await confirmation.evaluate(
        "(node) => ({client:node.clientHeight,content:node.scrollHeight,"
        "viewport:window.innerHeight,overflow:getComputedStyle(node).overflowY})"
    )
    assert dimensions["client"] <= dimensions["viewport"] and dimensions["overflow"] == "auto", (
        f"approval confirmation is clipped: {dimensions}"
    )
    if dimensions["content"] > dimensions["client"] + 30:
        results.append(await scroll_check(page, '[data-testid="evo-confirm-modal"] .v2-evo-modal-box', "approval-confirm"))
    await page.get_by_test_id("evo-confirm-modal").get_by_role("button", name="取消").click()
    await page.get_by_role("button", name="关闭演进建议详情").click()

    await page.get_by_test_id("tab-esc").click()
    await page.locator('[data-testid="escalation-panel"] .v2-evo-item').first.wait_for(timeout=10000)
    results.append(await scroll_check(page, '[data-testid="escalation-panel"] .v2-evo-body', "escalation"))

    await page.get_by_test_id("tab-archived").click()
    await page.get_by_test_id("archived-item").first.wait_for(timeout=10000)
    results.append(await scroll_check(page, ".v2-archived-list", "archives"))

    await page.get_by_test_id("tab-files").click()
    files = page.locator(".v2-tree-body")
    await files.wait_for()
    await files.evaluate(
        "(node) => {const fixture=document.createElement('div');"
        "fixture.style.height='2100px';fixture.style.flex='none';"
        "fixture.textContent='read-only overflow fixture';node.appendChild(fixture)}"
    )
    results.append(await scroll_check(page, ".v2-tree-body", "file-tree"))

    await page.get_by_test_id("services-entry").click()
    if mobile:
        assert await page.locator(".v2-shell.mobile-sidebar-open").count() == 0, (
            "main-view navigation left the sidebar covering the page"
        )
    await page.get_by_test_id("service-card-web").wait_for(timeout=10000)
    results.append(await scroll_check(page, '[data-testid="services-panel"]', "service-identities"))
    results.append(await services_layout_check(page))

    if mobile:
        await menu.click()
    await page.get_by_test_id("learning-entry").click()
    if mobile:
        assert await page.locator(".v2-shell.mobile-sidebar-open").count() == 0
    learning = page.locator(".v2-learning-view")
    await learning.wait_for()
    await learning.evaluate(
        "(node) => {const fixture=document.createElement('div');"
        "fixture.style.height='2100px';fixture.style.flex='none';"
        "fixture.textContent='read-only overflow fixture';node.appendChild(fixture)}"
    )
    results.append(await scroll_check(page, ".v2-learning-view", "learning"))

    if mobile:
        await menu.click()
    await page.get_by_test_id("knowledge-entry").click()
    if mobile:
        assert await page.locator(".v2-shell.mobile-sidebar-open").count() == 0
    knowledge = page.locator(".v2-learning-view")
    await knowledge.wait_for()
    await knowledge.evaluate(
        "(node) => {const fixture=document.createElement('div');"
        "fixture.style.height='2100px';fixture.style.flex='none';node.appendChild(fixture)}"
    )
    results.append(await scroll_check(page, ".v2-learning-view", "knowledge"))

    if mobile:
        await page.get_by_test_id("topbar").get_by_role("button", name="右侧面板", exact=True).click()
    elif await page.get_by_test_id("panel-body").count() == 0:
        await page.get_by_role("button", name="右侧面板", exact=True).click()
    settings = page.get_by_test_id("panel-body")
    await settings.wait_for()
    await settings.evaluate(
        "(node) => {const fixture=document.createElement('div');"
        "fixture.style.height='2100px';fixture.style.flex='none';node.appendChild(fixture)}"
    )
    results.append(await scroll_check(page, ".v2-panel-body", "right-settings"))
    if mobile:
        await page.get_by_test_id("panel-collapse-btn").click()
        assert await page.locator(".v2-shell.mobile-panel-open").count() == 0

    if mobile:
        await menu.click()
    await page.get_by_test_id("tab-sessions").click()
    await page.locator('[data-testid="session-item"] .v2-session-item').first.wait_for(timeout=15000)
    await page.locator('[data-testid="session-item"] .v2-session-item').first.click()
    if mobile:
        assert await page.locator(".v2-shell.mobile-sidebar-open").count() == 0
    messages = page.locator(".v2-message-list")
    await messages.wait_for(timeout=15000)
    await messages.evaluate(
        "(node) => {const fixture=document.createElement('div');"
        "fixture.style.height='2100px';fixture.style.flex='none';node.appendChild(fixture)}"
    )
    results.append(await scroll_check(page, ".v2-message-list", "conversation"))

    assert not errors, f"Browser JS errors: {errors[:3]}"
    await page.close()
    return results


async def main(url: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=True)
        try:
            all_results = []
            for width, height in ((1440, 600), (390, 844), (320, 568), (844, 390), (390, 430)):
                checks = await run_viewport(browser, url, width, height)
                all_results.append({"viewport": f"{width}x{height}", "checks": checks})
                print(json.dumps(all_results[-1], ensure_ascii=False), flush=True)
            print("WEB_V2_SCROLL_QUALIFICATION_PASS", flush=True)
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8903/ui/v2/")
    args = parser.parse_args()
    asyncio.run(main(args.url))
