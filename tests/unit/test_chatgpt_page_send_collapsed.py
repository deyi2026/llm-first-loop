from __future__ import annotations

import pytest

from llm_loop.llm.chatgpt_page import (
    ChatGPTPageAdapter,
    GenerationState,
    PageBinding,
    PageContractError,
    PageMessage,
)

FULL_PROMPT = (
    "[lfl-model/request] head ... long snapshot ... tail request_id=lfl-model-0005"
)


class _Locator:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]


class _Composer:
    def __init__(self, page):
        self.page = page

    def is_visible(self):
        return True

    def fill(self, text):
        self.page.filled = text


class _Send:
    def __init__(self, page):
        self.page = page

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def click(self):
        self.page.clicked = True


class _Expander:
    def __init__(self, page):
        self.page = page

    def is_visible(self):
        return True

    def click(self):
        self.page.expanded = True


class _Page:
    """Fake sync-Playwright page; latest user turn mounts collapsed first."""

    def __init__(self):
        self.filled = ""
        self.clicked = False
        self.expanded = False
        self.url = "https://chatgpt.com/g/g-project/project"

    def get_by_role(self, role, name=None):
        if role == "textbox":
            return _Locator([_Composer(self)])
        if role == "button" and name == "发送":
            return _Locator([_Send(self)])
        if role == "button" and name == "显示更多":
            return _Locator([] if self.expanded else [_Expander(self)])
        return _Locator([])

    def wait_for_timeout(self, _ms):
        return None


class _CollapsedAdapter(ChatGPTPageAdapter):
    def __init__(self, page):
        super().__init__(page, profile_label="fixture")

    def observe_generation(self):
        return GenerationState(
            streaming=False,
            stop_button_count=0,
            user_count=0,
            assistant_count=0,
            latest_assistant_identity=None,
            latest_assistant_text=None,
        )

    def observe_identity(self):
        return PageBinding(
            profile_label="fixture",
            url="https://chatgpt.com/g/g-project/c/22222222-2222-2222-2222-222222222222",
            title="ChatGPT",
            project_ref="g-project",
            conversation_id="22222222-2222-2222-2222-222222222222",
        )

    def observe_messages(self):
        if not self._page.clicked:
            return []
        if self._page.expanded:
            return [
                PageMessage(
                    role="user",
                    ordinal=0,
                    text=self._page.filled,
                    content=self._page.filled,
                    identity="user-collapsed-1",
                )
            ]
        head = self._page.filled[:32]
        return [
            PageMessage(
                role="user",
                ordinal=0,
                text=head,
                content=head + "\n…\n显示更多",
                identity="user-collapsed-1",
            )
        ]


def test_send_confirmation_expands_collapsed_user_turn():
    page = _Page()
    adapter = _CollapsedAdapter(page)

    receipt = adapter.send_text(
        FULL_PROMPT,
        timeout_s=1.0,
        confirm_timeout_s=1.0,
        poll_ms=1,
        confirm_token="lfl-model-0005",
    )

    assert page.expanded is True
    assert receipt.conversation_id == "22222222-2222-2222-2222-222222222222"
    assert receipt.user_message_identity == "user-collapsed-1"


def test_send_confirmation_fails_closed_without_expander():
    page = _Page()
    adapter = _CollapsedAdapter(page)

    # Simulate a page whose expander never appears (mismatched truncated
    # content that cannot be expanded or confirmed).
    def no_expander(role, name=None):
        if role == "button" and name == "显示更多":
            return _Locator([])
        return _Page.get_by_role(page, role, name)

    page.get_by_role = no_expander

    with pytest.raises(PageContractError, match="send was not confirmed"):
        adapter.send_text(
            FULL_PROMPT,
            timeout_s=0.5,
            confirm_timeout_s=0.5,
            poll_ms=1,
            confirm_token="lfl-model-0005",
        )
    assert page.expanded is False
