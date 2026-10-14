"""Read-only Web v2 post-approval scroll qualification.

The approval POST is intercepted in Chromium and fulfilled with a synthetic
response. No approval, mutation or copy is sent to a live LFL backend.

Usage:
  python scripts/qualification/web_v2_evolution_receipt_scroll.py --url http://127.0.0.1:8903/ui/v2/
"""

from __future__ import annotations

import argparse
import asyncio
import json

from playwright.async_api import async_playwright

ITEM_ID = "EVO-SCROLL-RECEIPT-QUALIFICATION"
ITEM = {
    "id": ITEM_ID,
    "ts": "2026-10-14T00:00:00+08:00",
    "status": "pending_review",
    "priority": "P1",
    "requires_human": False,
    "content": "只读浏览器测试记录：不产生真正的审批。",
    "impact_hint": "webui/src/components/sidebar/EvolutionPanel.tsx",
}
RESULT = (
    "【模拟回执】已批准但仍待执行验证；请检查工具和证据状态后继续。"
    "状态为 executing，且不代表真实任务已经完成。"
) * 24


async def check_viewport(browser: object, url: str, width: int, height: int) -> dict[str, object]:
    page = await browser.new_page(viewport={"width": width, "height": height})
    state = {"review_calls": 0}
    javascript_errors: list[str] = []
    page.on("pageerror", lambda exc: javascript_errors.append(str(exc)))

    async def block_unexpected_writes(route: object) -> None:
        if route.request.method != "GET":
            await route.fulfill(status=403, json={"detail": "fixture-only browser test: blocked mutation"})
        else:
            await route.continue_()

    async def mock_list(route: object) -> None:
        await route.fulfill(
            status=200,
            json={"suggestions": [ITEM] if not state["review_calls"] else [], "count": int(not state["review_calls"])},
        )

    async def mock_review(route: object) -> None:
        payload = route.request.post_data_json
        assert payload["id"] == ITEM_ID and payload["decision"] == "accepted"
        assert payload["expected_status"] == "pending_review"
        state["review_calls"] += 1
        await route.fulfill(status=200, json={"ok": True, "message": RESULT, "new_status": "executing"})

    # Last registered route wins: only the exact synthetic approval request
    # may pass the catch-all mutation guard, and it never reaches the server.
    await page.route("**/api/**", block_unexpected_writes)
    await page.route("**/api/v1/evolution/list?*", mock_list)
    await page.route("**/api/v1/evolution/review", mock_review)

    response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    assert response and response.status == 200
    await page.get_by_test_id("topbar").wait_for(timeout=12000)
    if width <= 900:
        await page.get_by_test_id("topbar").locator("button").first.click()
    await page.get_by_test_id("tab-evo").click()
    await page.get_by_text(ITEM_ID, exact=True).click()
    await page.get_by_test_id("evo-approve").click()
    await page.get_by_test_id("evo-prompt-surface-check").check()
    await page.get_by_test_id("evo-confirm-ok").click()
    await page.get_by_test_id("evo-review-receipt").wait_for(timeout=12000)

    scrollport = page.locator(".v2-evo-body")
    approval = page.get_by_test_id("evo-action-msg")
    receipt = page.get_by_test_id("evo-review-receipt")
    copy_button = page.get_by_test_id("evo-review-receipt-copy")
    dimensions = await scrollport.evaluate(
        """(node) => {
          const receipt = document.querySelector('[data-testid="evo-review-receipt"]');
          const status = document.querySelector('[data-testid="evo-action-msg"]');
          const copy = document.querySelector('[data-testid="evo-review-receipt-copy"]');
          return {
            client: node.clientHeight, content: node.scrollHeight,
            overflow: getComputedStyle(node).overflowY,
            receiptWithinScrollport: node.contains(receipt),
            statusWithinScrollport: node.contains(status),
            copyWithinScrollport: node.contains(copy),
          };
        }"""
    )
    assert state["review_calls"] == 1, "approval was not exercised exactly once"
    assert await approval.is_visible() and await receipt.is_visible()
    assert dimensions["receiptWithinScrollport"] and dimensions["statusWithinScrollport"], (
        f"approval feedback is outside scrollport: {dimensions}"
    )
    assert dimensions["copyWithinScrollport"]
    sidebar = page.locator(".v2-sidebar")
    outer = await sidebar.evaluate(
        "(node) => ({client:node.clientHeight,content:node.scrollHeight,"
        "overflow:getComputedStyle(node).overflowY})"
    )
    use_inner = dimensions["overflow"] == "auto" and dimensions["content"] - dimensions["client"] > 200
    use_outer = outer["overflow"] == "auto" and outer["content"] - outer["client"] > 200
    assert use_inner or use_outer, f"no usable scrollport: inner={dimensions}, outer={outer}"
    wheel_target = scrollport if use_inner else sidebar
    await wheel_target.hover()
    await page.mouse.wheel(0, 550)
    await page.wait_for_timeout(150)
    wheel_offset = await wheel_target.evaluate("(node) => node.scrollTop")
    assert wheel_offset > 0, "mouse wheel could not scroll the approval feedback"
    await copy_button.scroll_into_view_if_needed()
    bounds = await page.evaluate(
        """(outer) => {
          const s = document.querySelector(outer ? '.v2-sidebar' : '.v2-evo-body').getBoundingClientRect();
          const b = document.querySelector('[data-testid="evo-review-receipt-copy"]').getBoundingClientRect();
          return { top:s.top,bottom:s.bottom,buttonTop:b.top,buttonBottom:b.bottom };
        }""",
        not use_inner,
    )
    assert bounds["buttonTop"] >= bounds["top"] - 2
    assert bounds["buttonBottom"] <= bounds["bottom"] + 2, (
        f"copy receipt button remains clipped: {bounds}"
    )
    assert not javascript_errors, javascript_errors[:3]
    await page.close()
    return {
        "viewport": f"{width}x{height}",
        "scrollport": dimensions,
        "activeScrollport": "evo-body" if use_inner else "sidebar",
        "wheelScrollTop": wheel_offset,
        "copyVisible": True,
        "mockReviewCount": state["review_calls"],
    }


async def main(url: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=True)
        try:
            for width, height in ((1024, 600), (490, 800), (390, 844), (390, 430)):
                print(json.dumps(await check_viewport(browser, url, width, height), ensure_ascii=False), flush=True)
            print("WEB_V2_APPROVAL_RECEIPT_SCROLL_PASS", flush=True)
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8903/ui/v2/")
    args = parser.parse_args()
    asyncio.run(main(args.url))
