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
