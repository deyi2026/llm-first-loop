from __future__ import annotations

from dataclasses import dataclass

import pytest

from llm_loop.llm.chatgpt_page import PageBinding
from llm_loop.llm.chatgpt_surface import (
    BrowserSurfaceLeaseError,
    BrowserSurfaceLeaseStore,
    ChatGPTSurface,
)

PROJECT_REF = "g-p-fixture-lab"
PROJECT_URL = "https://chatgpt.com/g/g-p-fixture-lab/project"
CONVERSATION_ID = "6ab79522-d4a4-83e8-8265-2d8195ba5a24"
CONVERSATION_URL = f"https://chatgpt.com/g/{PROJECT_REF}/c/{CONVERSATION_ID}"


@dataclass
class _Page:
    target_id: str
    url: str
    closed: bool = False
    title_failures: int = 0
    fronted: int = 0

    def goto(self, url, *, wait_until, timeout):
        assert wait_until == "commit"
        assert timeout == 15_000
        self.url = url

    def wait_for_timeout(self, _ms):
        return None

    def title(self):
        if self.title_failures > 0:
            self.title_failures -= 1
            raise RuntimeError("execution context was destroyed")
        return "ChatGPT"

    def close(self):
        self.closed = True

    def is_closed(self):
        return self.closed

    def bring_to_front(self):
        self.fronted += 1


class _Session:
    def __init__(self, page):
        self.page = page
        self.detached = False

    def send(self, name):
        assert name == "Target.getTargetInfo"
        return {"targetInfo": {"targetId": self.page.target_id}}

    def detach(self):
        self.detached = True


class _Context:
    def __init__(self, pages=None, *, target_prefix="owned"):
        self.pages = list(pages or [])
        self.created = 0
        self.target_prefix = target_prefix

    def new_page(self):
        self.created += 1
        page = _Page(f"{self.target_prefix}-{self.created}", "about:blank")
        self.pages.append(page)
        return page

    def new_cdp_session(self, page):
        return _Session(page)


class _Browser:
    def __init__(self, context):
        self.contexts = [context]


class _Chromium:
    def __init__(self, browser):
        self.browser = browser

    def connect_over_cdp(self, endpoint):
        assert endpoint == "http://127.0.0.1:9229"
        return self.browser


class _Playwright:
    def __init__(self, browser):
        self.chromium = _Chromium(browser)
        self.stopped = False

    def stop(self):
        self.stopped = True


def _surface(tmp_path, context, *, recovery_conversation_id=None):
    pw = _Playwright(_Browser(context))
    surface = ChatGPTSurface(
        "http://127.0.0.1:9229",
        lease_store=BrowserSurfaceLeaseStore(tmp_path),
        project_url=PROJECT_URL,
        project_ref=PROJECT_REF,
        profile_label="fixture-profile",
        recovery_conversation_id=recovery_conversation_id,
        playwright_factory=lambda: pw,
    )
    return surface, pw


def test_duplicate_same_url_tabs_do_not_create_ambiguity(tmp_path):
    first = _Page("user-tab-1", CONVERSATION_URL)
    second = _Page("user-tab-2", CONVERSATION_URL)
    context = _Context([first, second])
    surface, _pw = _surface(
        tmp_path,
        context,
        recovery_conversation_id=CONVERSATION_ID,
    )

    page = surface.open()
    lease = surface.snapshot_identity()

    assert page is not first
    assert page is not second
    assert context.created == 1
    assert page.url == CONVERSATION_URL
    assert lease.target_id == page.target_id
    assert lease.conversation_id == CONVERSATION_ID
    assert page.fronted == 1
    assert first.closed is False and second.closed is False


def test_restart_reacquires_exact_target_id_among_duplicate_urls(tmp_path):
    context = _Context()
    surface, _pw = _surface(
        tmp_path,
        context,
        recovery_conversation_id=CONVERSATION_ID,
    )
    owned = surface.open()
    lease = surface.snapshot_identity()
    surface.close()

    context.pages.extend(
        [
            _Page("duplicate-a", CONVERSATION_URL),
            _Page("duplicate-b", CONVERSATION_URL),
        ]
    )
    restarted, _pw2 = _surface(tmp_path, context, recovery_conversation_id=CONVERSATION_ID)
    page = restarted.open()

    assert page is owned
    assert restarted.snapshot_identity().lease_id == lease.lease_id
    assert restarted.snapshot_identity().target_id == lease.target_id
    assert context.created == 1
    assert page.fronted == 2


def test_missing_target_creates_one_replacement_and_moves_same_lease(tmp_path):
    context1 = _Context()
    surface1, _pw1 = _surface(
        tmp_path,
        context1,
        recovery_conversation_id=CONVERSATION_ID,
    )
    surface1.open()
    before = surface1.snapshot_identity()
    surface1.close()

    context2 = _Context(
        [_Page("unowned-duplicate", CONVERSATION_URL)],
        target_prefix="replacement",
    )
    surface2, _pw2 = _surface(tmp_path, context2, recovery_conversation_id=CONVERSATION_ID)
    replacement = surface2.open()
    after = surface2.snapshot_identity()

    assert context2.created == 1
    assert replacement.url == CONVERSATION_URL
    assert after.lease_id == before.lease_id
    assert after.target_id != before.target_id
    assert after.target_id == replacement.target_id
    assert after.conversation_id == CONVERSATION_ID
    assert replacement.fronted == 1


def test_bind_conversation_persists_route_after_project_root_claim(tmp_path):
    context = _Context()
    surface, _pw = _surface(tmp_path, context)
    page = surface.open()
    assert page.url == PROJECT_URL
    assert surface.snapshot_identity().conversation_id is None

    page.url = CONVERSATION_URL
    lease = surface.bind_conversation(
        PageBinding(
            profile_label="fixture-profile",
            url=CONVERSATION_URL,
            title="fixture",
            project_ref=PROJECT_REF,
            conversation_id=CONVERSATION_ID,
        )
    )

    assert lease.conversation_id == CONVERSATION_ID
    assert lease.conversation_url == CONVERSATION_URL
    assert BrowserSurfaceLeaseStore(tmp_path).load() == lease


def test_bind_conversation_recovers_generic_chat_route_into_configured_project(tmp_path):
    context = _Context()
    surface, _pw = _surface(tmp_path, context)
    page = surface.open()
    assert page.url == PROJECT_URL

    generic_url = f"https://chatgpt.com/c/{CONVERSATION_ID}"
    page.url = generic_url
    lease = surface.bind_conversation(
        PageBinding(
            profile_label="fixture-profile",
            url=generic_url,
            title="fixture",
            project_ref=None,
            conversation_id=CONVERSATION_ID,
        )
    )

    assert page.url == CONVERSATION_URL
    assert lease.project_ref == PROJECT_REF
    assert lease.conversation_id == CONVERSATION_ID
    assert lease.conversation_url == CONVERSATION_URL
    assert BrowserSurfaceLeaseStore(tmp_path).load() == lease


def test_bind_conversation_still_rejects_explicit_other_project(tmp_path):
    context = _Context()
    surface, _pw = _surface(tmp_path, context)
    page = surface.open()
    other_ref = "g-p-explicit-other-project"
    other_url = f"https://chatgpt.com/g/{other_ref}/c/{CONVERSATION_ID}"
    page.url = other_url

    with pytest.raises(BrowserSurfaceLeaseError, match="another Project"):
        surface.bind_conversation(
            PageBinding(
                profile_label="fixture-profile",
                url=other_url,
                title="fixture",
                project_ref=other_ref,
                conversation_id=CONVERSATION_ID,
            )
        )

    assert page.url == other_url
    assert surface.snapshot_identity().conversation_id is None


def test_bind_conversation_rejects_non_chatgpt_route_without_project_identity(tmp_path):
    context = _Context()
    surface, _pw = _surface(tmp_path, context)
    page = surface.open()
    untrusted_url = f"https://example.invalid/c/{CONVERSATION_ID}"
    page.url = untrusted_url

    with pytest.raises(
        BrowserSurfaceLeaseError,
        match="without configured Project identity",
    ):
        surface.bind_conversation(
            PageBinding(
                profile_label="fixture-profile",
                url=untrusted_url,
                title="fixture",
                project_ref=None,
                conversation_id=CONVERSATION_ID,
            )
        )

    assert page.url == untrusted_url
    assert surface.snapshot_identity().conversation_id is None


def test_reset_to_project_root_clears_outer_conversation_but_preserves_surface(tmp_path):
    context = _Context()
    surface, _pw = _surface(
        tmp_path,
        context,
        recovery_conversation_id=CONVERSATION_ID,
    )
    page = surface.open()
    before = surface.snapshot_identity()
    assert page.url == CONVERSATION_URL

    after = surface.reset_to_project_root()

    assert page.url == PROJECT_URL
    assert after.lease_id == before.lease_id
    assert after.target_id == before.target_id
    assert after.conversation_id is None
    assert after.conversation_url is None
    assert page.fronted == 2
    assert BrowserSurfaceLeaseStore(tmp_path).load() == after


def test_new_owned_page_absorbs_transient_navigation_context_loss(tmp_path):
    context = _Context()
    original_new_page = context.new_page

    def _new_page():
        page = original_new_page()
        page.title_failures = 3
        return page

    context.new_page = _new_page
    surface, _pw = _surface(
        tmp_path,
        context,
        recovery_conversation_id=CONVERSATION_ID,
    )

    page = surface.open()

    assert page.url == CONVERSATION_URL
    assert page.title_failures == 0
    assert surface.snapshot_identity().target_id == page.target_id


def test_closed_exact_target_is_replaced_without_selecting_same_url_duplicate(tmp_path):
    context = _Context()
    first, _pw1 = _surface(
        tmp_path,
        context,
        recovery_conversation_id=CONVERSATION_ID,
    )
    owned = first.open()
    before = first.snapshot_identity()
    first.close()
    owned.closed = True
    duplicate = _Page("duplicate-live", CONVERSATION_URL)
    context.pages.append(duplicate)

    restarted, _pw2 = _surface(
        tmp_path,
        context,
        recovery_conversation_id=CONVERSATION_ID,
    )
    replacement = restarted.open()
    after = restarted.snapshot_identity()

    assert replacement is not duplicate
    assert replacement.target_id != before.target_id
    assert after.lease_id == before.lease_id
    assert after.target_id == replacement.target_id
    assert duplicate.closed is False
    assert replacement.fronted == 1
