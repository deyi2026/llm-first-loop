"""Static responsive contracts that must survive frontend refactors."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEBUI = ROOT / "webui"


def _read(relative: str) -> str:
    return (WEBUI / relative).read_text(encoding="utf-8")


def test_mobile_viewport_and_safe_area_contracts() -> None:
    index_html = _read("index.html")
    app_css = _read("src/tokens/app.css")
    conversation_css = _read("src/tokens/conversation.css")

    assert "viewport-fit=cover" in index_html
    assert "100dvh" in app_css
    assert "env(safe-area-inset-top)" in app_css
    assert "env(safe-area-inset-bottom)" in app_css
    assert "env(safe-area-inset-bottom)" in conversation_css


def test_mobile_touch_and_narrow_layout_contracts() -> None:
    app_css = _read("src/tokens/app.css")
    conversation_css = _read("src/tokens/conversation.css")

    assert "--v2-mobile-touch-target: 44px" in app_css
    assert ".v2-status-badge > span:last-child" in app_css
    assert "text-overflow: ellipsis" in app_css
    assert ".v2-composer-tools {\n    flex-wrap: wrap;" in conversation_css
    assert ".v2-chat-queue-item {\n    flex-wrap: wrap;" in conversation_css
    assert "min-height: var(--v2-mobile-touch-target)" in conversation_css
    # The mobile title has its own row. Wrap the actions instead of clipping
    # the absolute-positioned task menus in a horizontal overflow container.
    assert ".v2-conversation-header {\n    flex-direction: column;" in conversation_css
    assert ".v2-conversation-header-actions {\n    flex: 0 0 auto;" in conversation_css
    actions = conversation_css.split(".v2-conversation-header-actions {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 auto;" in actions
    assert "flex-wrap: wrap;" in actions
    assert "overflow: visible;" in actions
    assert "overflow-x:" not in actions
    assert "position: relative;" in actions
    assert ".v2-conversation-header-actions > .v2-catalog {\n  position: static;" in conversation_css
    touch_rule = conversation_css.split("  .v2-catalog-trigger,", 1)[1].split("}", 1)[0]
    for selector in (".v2-agents-row,", ".v2-jobs-open,", ".v2-conversation-header-actions > .v2-btn {"):
        assert selector in touch_rule
    assert "min-height: var(--v2-mobile-touch-target);" in touch_rule
    assert ".v2-tool-activity-toggle,\n  .v2-tool-activity-row-toggle" in conversation_css


def test_long_tool_detail_uses_bounded_scroll_region() -> None:
    conversation_css = _read("src/tokens/conversation.css")

    assert ".v2-tool-activity-detail {" in conversation_css
    assert "max-height: min(50vh, 360px);" in conversation_css
    assert "overflow: auto;" in conversation_css
    assert "overscroll-behavior: contain;" in conversation_css
