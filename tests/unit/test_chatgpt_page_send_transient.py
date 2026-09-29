from __future__ import annotations

from llm_loop.llm.chatgpt_page import (
    ChatGPTPageAdapter,
    GenerationState,
    PageBinding,
    PageMessage,
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


class _Page:
    def __init__(self):
        self.filled = ""
        self.clicked = False
        self.url = "https://chatgpt.com/g/g-project/project"

    def get_by_role(self, role, name=None):
        if role == "textbox":
            return _Locator([_Composer(self)])
        if role == "button" and name == "发送":
            return _Locator([_Send(self)])
        return _Locator([])

    def wait_for_timeout(self, _ms):
        return None


class _Adapter(ChatGPTPageAdapter):
    def __init__(self, page):
        super().__init__(page, profile_label="fixture")
        self.identity_attempts = 0

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
        if self._page.clicked:
            self.identity_attempts += 1
            if self.identity_attempts == 1:
                raise RuntimeError(
                    "Page.title: Execution context was destroyed, most likely because of a navigation"
                )
        return PageBinding(
            profile_label="fixture",
            url="https://chatgpt.com/g/g-project/c/11111111-1111-1111-1111-111111111111",
            title="ChatGPT",
            project_ref="g-project",
            conversation_id="11111111-1111-1111-1111-111111111111" if self._page.clicked else None,
        )

    def observe_messages(self):
        if not self._page.clicked:
            return []
        return [
            PageMessage(
                role="user",
                ordinal=0,
                text=self._page.filled,
                content=self._page.filled,
                identity="user-1",
            )
        ]


def test_send_confirmation_retries_navigation_execution_context_teardown():
    page = _Page()
    adapter = _Adapter(page)

    receipt = adapter.send_text(
        "payload request-token",
        timeout_s=1.0,
        confirm_timeout_s=1.0,
        poll_ms=1,
        confirm_token="request-token",
    )

    assert receipt.conversation_id == "11111111-1111-1111-1111-111111111111"
    assert receipt.user_message_identity == "user-1"
    assert adapter.identity_attempts == 2


def test_wait_for_completion_retries_transient_missing_conversation_identity():
    page = _Page()

    class CompletionAdapter(ChatGPTPageAdapter):
        def __init__(self):
            super().__init__(page, profile_label="fixture")
            self.calls = 0

        def observe_generation(self):
            from llm_loop.llm.chatgpt_page import PageContractError

            self.calls += 1
            if self.calls == 1:
                raise PageContractError(
                    "message turn observed before conversation identity appeared"
                )
            return GenerationState(
                streaming=False,
                stop_button_count=0,
                user_count=1,
                assistant_count=1,
                latest_assistant_identity="assistant-1",
                latest_assistant_text="done",
            )

        def observe_messages(self):
            return [
                PageMessage("user", 0, "payload", "user-1", content="payload"),
                PageMessage("assistant", 0, "done", "assistant-1", content="done"),
            ]

    adapter = CompletionAdapter()
    state = adapter.wait_for_assistant_completion(
        0,
        timeout_s=1.0,
        poll_ms=1,
        stability_polls=1,
    )
    assert state.latest_assistant_text == "done"
    assert adapter.calls >= 3
