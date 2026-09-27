from __future__ import annotations

import pytest

from llm_loop.llm.chatgpt_page import ChatGPTPageAdapter, PageContractError

LABELS = ["即时", "中", "高", "极高", "Pro"]
EFFORTS = ["instant", "medium", "high", "xhigh", "pro"]


class _Keyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key):
        assert key == "Escape"
        self.page.menu_open = False
        self.page.strength_open = False


class _Item:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind

    def is_visible(self):
        if self.kind == "trigger":
            if self.page.trigger_hidden_checks > 0:
                self.page.trigger_hidden_checks -= 1
                return False
            return True
        if self.kind == "strength":
            return self.page.menu_open
        if self.kind == "status":
            return self.page.strength_open
        return False

    def inner_text(self):
        if self.kind == "trigger":
            return f"5.6 {LABELS[self.page.level]}"
        if self.kind == "status":
            return f"{LABELS[self.page.level]}，第 {self.page.level + 1} 项，共 5 项。"
        return ""

    def click(self):
        if self.kind == "trigger":
            self.page.menu_open = True
        elif self.kind == "strength":
            self.page.strength_open = True

    def press(self, key):
        assert self.kind == "strength"
        if key == "ArrowRight":
            self.page.level = min(4, self.page.level + 1)
        elif key == "ArrowLeft":
            self.page.level = max(0, self.page.level - 1)
        else:
            raise AssertionError(key)


class _Locator:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]

    @property
    def first(self):
        return self.items[0]


class _Page:
    def __init__(self, level=2, trigger_hidden_checks=0):
        self.level = level
        self.trigger_hidden_checks = trigger_hidden_checks
        self.menu_open = False
        self.strength_open = False
        self.keyboard = _Keyboard(self)
        self.url = "https://chatgpt.com/g/g-project/project"

    def get_by_role(self, role, name=None):
        if role == "button" and name == "选择 ChatGPT 模型":
            return _Locator([_Item(self, "trigger")])
        if role == "menuitem" and name == "强度":
            return _Locator([_Item(self, "strength")])
        if role == "status":
            return _Locator([_Item(self, "status")])
        return _Locator([])

    def wait_for_timeout(self, _ms):
        return None

    def title(self):
        return "ChatGPT"


@pytest.mark.parametrize("label,effort", list(zip(LABELS, EFFORTS, strict=True)))
def test_reasoning_effort_parser_covers_qualified_five_levels(label, effort):
    assert ChatGPTPageAdapter._reasoning_effort_from_text(f"5.6 {label}") == effort
    assert ChatGPTPageAdapter._reasoning_effort_from_text(
        f"{label}，第 {EFFORTS.index(effort) + 1} 项，共 5 项。"
    ) == effort


def test_ensure_reasoning_effort_is_noop_when_already_correct():
    page = _Page(level=2)
    adapter = ChatGPTPageAdapter(page, profile_label="fixture")

    assert adapter.ensure_reasoning_effort("high") == "high"
    assert page.level == 2
    assert page.menu_open is False


def test_ensure_reasoning_effort_moves_both_directions_and_verifies():
    page = _Page(level=2)
    adapter = ChatGPTPageAdapter(page, profile_label="fixture")

    assert adapter.ensure_reasoning_effort("pro") == "pro"
    assert page.level == 4
    assert page.menu_open is False
    assert adapter.ensure_reasoning_effort("medium") == "medium"
    assert page.level == 1
    assert page.menu_open is False


def test_ensure_reasoning_effort_rejects_unknown_requested_level():
    adapter = ChatGPTPageAdapter(_Page(), profile_label="fixture")
    with pytest.raises(PageContractError, match="unsupported ChatGPT reasoning effort"):
        adapter.ensure_reasoning_effort("turbo")


def test_observe_reasoning_effort_fails_closed_on_unknown_visible_state():
    page = _Page()
    trigger = _Item(page, "trigger")
    trigger.inner_text = lambda: "5.6 Mystery"
    original = page.get_by_role

    def get_by_role(role, name=None):
        if role == "button" and name == "选择 ChatGPT 模型":
            return _Locator([trigger])
        return original(role, name=name)

    page.get_by_role = get_by_role
    adapter = ChatGPTPageAdapter(page, profile_label="fixture")
    with pytest.raises(PageContractError, match="unrecognized"):
        adapter.observe_reasoning_effort()


def test_ensure_reasoning_effort_waits_for_project_root_control_hydration():
    page = _Page(level=2, trigger_hidden_checks=3)
    adapter = ChatGPTPageAdapter(page, profile_label="fixture")

    assert adapter.ensure_reasoning_effort("high", timeout_s=1.0, poll_ms=1) == "high"
    assert page.trigger_hidden_checks == 0
