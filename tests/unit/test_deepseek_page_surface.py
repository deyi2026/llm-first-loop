from __future__ import annotations

from dataclasses import dataclass

import pytest

from llm_loop.llm.chatgpt_page import PageBinding
from llm_loop.llm.chatgpt_surface import BrowserSurfaceLeaseStore
from llm_loop.llm.deepseek_page import (
    DeepSeekPageAdapter,
    DeepSeekPageContractError,
)
from llm_loop.llm.deepseek_surface import DeepSeekSurface

ROOT = "https://chat.deepseek.com/"
CID = "749e6bbd-6a45-4440-beaa-ae5238bf06d8"
CHAT = f"https://chat.deepseek.com/a/chat/s/{CID}"


class _TitlePage:
    def __init__(self, url=ROOT):
        self.url = url
    def title(self): return "DeepSeek"


def test_deepseek_identity_is_exact_host_and_uuid_route():
    adapter = DeepSeekPageAdapter(_TitlePage(CHAT), profile_label="fixture")
    binding = adapter.observe_identity()
    assert binding.project_ref == "deepseek-web"
    assert binding.conversation_id == CID
    assert binding.url == CHAT

    outside = DeepSeekPageAdapter(_TitlePage("https://example.com/"), profile_label="fixture")
    assert outside.observe_identity().project_ref is None
    with pytest.raises(DeepSeekPageContractError, match="left chat.deepseek.com"):
        outside.require_binding(PageBinding("fixture", ROOT, "x", "deepseek-web", None))


def test_runtime_controls_map_only_instant_high_and_always_disable_search(monkeypatch):
    adapter = DeepSeekPageAdapter(_TitlePage(), profile_label="fixture")
    events = []
    monkeypatch.setattr(
        adapter,
        "_ensure_default_model_if_available",
        lambda: events.append("default-model") or True,
    )
    monkeypatch.setattr(
        adapter,
        "_set_feature",
        lambda index, enabled: events.append((index, enabled)) or enabled,
    )

    assert adapter.ensure_runtime_controls("high") == "high"
    assert events == ["default-model", (0, True), (1, False)]
    events.clear()
    assert adapter.ensure_runtime_controls("instant") == "instant"
    assert events == ["default-model", (0, False), (1, False)]
    with pytest.raises(DeepSeekPageContractError, match="unsupported"):
        adapter.ensure_runtime_controls("xhigh")


def test_toggle_state_prefers_aria_pressed_and_falls_back_to_selected_class():
    class Button:
        def __init__(self, class_name, aria_pressed=None):
            self.class_name = class_name
            self.aria_pressed = aria_pressed
        def get_attribute(self, name):
            if name == "aria-pressed":
                return self.aria_pressed
            if name == "class":
                return self.class_name
            raise AssertionError(name)

    assert DeepSeekPageAdapter._toggle_selected(  # noqa: SLF001
        Button("ds-toggle-button ds-toggle-button--selected ds-toggle-button--md")
    ) is True
    assert DeepSeekPageAdapter._toggle_selected(  # noqa: SLF001
        Button("ds-toggle-button ds-toggle-button--md")
    ) is False
    assert DeepSeekPageAdapter._toggle_selected(  # noqa: SLF001
        Button("ds-toggle-button ds-toggle-button--selected", "false")
    ) is False
    assert DeepSeekPageAdapter._toggle_selected(  # noqa: SLF001
        Button("ds-toggle-button", "true")
    ) is True


def test_message_projection_separates_thinking_from_final_answer():
    rows = [
        {"rawText": "hello", "finalText": "", "thinkingText": "", "turnKey": "u1"},
        {
            "rawText": "private reasoning visible on page\nFINAL",
            "finalText": "FINAL",
            "thinkingText": "private reasoning visible on page",
            "turnKey": "a1",
        },
    ]

    class Bubbles:
        def evaluate_all(self, _script): return rows

    class Page(_TitlePage):
        def locator(self, selector):
            assert selector == ".ds-message"
            return Bubbles()

    adapter = DeepSeekPageAdapter(Page(CHAT), profile_label="fixture")
    messages = adapter.observe_messages()
    assert [(m.role, m.content) for m in messages] == [
        ("user", "hello"),
        ("assistant", "FINAL"),
    ]
    assert "private reasoning" not in messages[-1].content


@dataclass
class _Page:
    target_id: str
    url: str
    closed: bool = False
    fronted: int = 0

    def goto(self, url, *, wait_until, timeout):
        assert wait_until == "commit" and timeout == 15_000
        self.url = url
    def wait_for_timeout(self, _ms): return None
    def title(self): return "DeepSeek"
    def close(self): self.closed = True
    def is_closed(self): return self.closed
    def bring_to_front(self): self.fronted += 1


class _Session:
    def __init__(self, page): self.page = page
    def send(self, name):
        assert name == "Target.getTargetInfo"
        return {"targetInfo": {"targetId": self.page.target_id}}
    def detach(self): return None


class _Context:
    def __init__(self, pages=None):
        self.pages = list(pages or [])
        self.created = 0
    def new_page(self):
        self.created += 1
        page = _Page(f"owned-{self.created}", "about:blank")
        self.pages.append(page)
        return page
    def new_cdp_session(self, page): return _Session(page)


class _Browser:
    def __init__(self, context): self.contexts = [context]


class _Chromium:
    def __init__(self, browser): self.browser = browser
    def connect_over_cdp(self, endpoint):
        assert endpoint == "http://127.0.0.1:9229"
        return self.browser


class _Playwright:
    def __init__(self, browser): self.chromium = _Chromium(browser)
    def stop(self): return None


def _surface(tmp_path, context):
    pw = _Playwright(_Browser(context))
    return DeepSeekSurface(
        "http://127.0.0.1:9229",
        lease_store=BrowserSurfaceLeaseStore(tmp_path),
        root_url=ROOT,
        profile_label="fixture",
        playwright_factory=lambda: pw,
    )


def test_surface_never_adopts_ambiguous_existing_deepseek_tabs(tmp_path):
    first = _Page("user-a", ROOT)
    second = _Page("user-b", ROOT)
    context = _Context([first, second])
    surface = _surface(tmp_path, context)
    owned = surface.open()
    lease = surface.lease
    assert owned is not first and owned is not second
    assert context.created == 1
    assert lease is not None and lease.target_id == owned.target_id
    assert owned.fronted == 0


def test_surface_reacquires_exact_target_and_resets_same_target(tmp_path):
    context = _Context()
    surface = _surface(tmp_path, context)
    owned = surface.open()
    lease_id = surface.lease.lease_id  # type: ignore[union-attr]
    binding = PageBinding("fixture", CHAT, "x", "deepseek-web", CID)
    owned.url = CHAT
    surface.bind_conversation(binding)
    surface.close()

    context.pages.append(_Page("duplicate", CHAT))
    restarted = _surface(tmp_path, context)
    assert restarted.open() is owned
    assert restarted.lease.lease_id == lease_id  # type: ignore[union-attr]
    restarted.reset_to_root()
    assert owned.url == ROOT
    assert restarted.lease.conversation_id is None  # type: ignore[union-attr]
    assert context.created == 1
    assert owned.fronted == 0
