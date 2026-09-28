from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from llm_loop.llm.chatgpt_page import PageBinding
from llm_loop.llm.chatgpt_surface import (
    BrowserSurfaceLeaseError,
    BrowserSurfaceLeaseStore,
    ChatGPTSessionBindingStore,
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
    assert page.fronted == 0
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
    assert page.fronted == 0


def test_restart_restores_exact_owned_target_to_lease_expected_url(tmp_path, monkeypatch):
    context = _Context()
    surface, _pw = _surface(tmp_path, context)
    owned = surface.open()
    lease = surface.snapshot_identity()
    assert lease.conversation_id is None
    assert owned.url == PROJECT_URL
    surface.close()

    stale_url = f"https://chatgpt.com/c/{CONVERSATION_ID}"
    owned.url = stale_url
    duplicate = _Page("unowned-project-tab", PROJECT_URL)
    context.pages.append(duplicate)

    def _strict_wait(page, *, expected_url, timeout_s=10.0):
        if page.url != expected_url:
            raise BrowserSurfaceLeaseError(
                f"fixture route mismatch: {page.url!r} != {expected_url!r}"
            )

    monkeypatch.setattr(
        ChatGPTSurface,
        "_wait_for_page_context",
        staticmethod(_strict_wait),
    )

    restarted, _pw2 = _surface(tmp_path, context)
    page = restarted.open()

    assert page is owned
    assert page.url == PROJECT_URL
    assert restarted.snapshot_identity().lease_id == lease.lease_id
    assert restarted.snapshot_identity().target_id == lease.target_id
    assert restarted.snapshot_identity().conversation_id is None
    assert context.created == 1
    assert duplicate.url == PROJECT_URL
    assert duplicate.fronted == 0


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
    assert replacement.fronted == 0


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
    assert page.fronted == 0
    assert BrowserSurfaceLeaseStore(tmp_path).load() == lease


def test_session_binding_store_persists_segment_accounting_and_rollover(tmp_path):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    binding = store.get_or_create(session_id="lfl-session-a", project_ref=PROJECT_REF)

    assert binding.segment_seq == 1
    assert binding.segment_request_count == 0
    assert binding.conversation_id is None

    binding = store.record_exchange(
        binding,
        conversation_id=CONVERSATION_ID,
        conversation_url=CONVERSATION_URL,
        request_chars=12_345,
    )
    assert store.load("lfl-session-a") == binding
    assert binding.segment_request_count == 1
    assert binding.segment_request_chars == 12_345
    assert binding.total_request_count == 1

    rolled = store.rollover(binding, reason="request_cap")
    assert rolled.segment_seq == 2
    assert rolled.segment_request_count == 0
    assert rolled.segment_request_chars == 0
    assert rolled.total_request_count == 1
    assert rolled.conversation_id is None
    assert rolled.conversation_url is None
    history = (
        tmp_path
        / "sessions"
        / "lfl-session-a"
        / ChatGPTSessionBindingStore.HISTORY
    ).read_text(encoding="utf-8")
    row = json.loads(history)
    assert row["segment_seq"] == 1
    assert row["conversation_id"] == CONVERSATION_ID
    assert row["reason"] == "request_cap"
    events = store.read_events("lfl-session-a")
    assert [event["event"] for event in events] == [
        "exchange_committed",
        "segment_rollover",
    ]
    assert events[0]["request_chars"] == 12_345
    assert events[1]["reason"] == "request_cap"


def test_session_binding_store_hashes_raw_session_id_and_rejects_project_drift(tmp_path):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    binding = store.get_or_create(
        session_id="../../not-a-path",
        project_ref=PROJECT_REF,
    )

    assert binding.lfl_session_id == "../../not-a-path"
    assert not (tmp_path / "not-a-path").exists()
    with pytest.raises(BrowserSurfaceLeaseError, match="Project identity mismatch"):
        store.get_or_create(
            session_id="../../not-a-path",
            project_ref="g-p-other",
        )


def test_session_binding_store_lists_history_and_deletes_only_unchanged_binding(tmp_path):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    binding = store.get_or_create(session_id="lfl-session-a", project_ref=PROJECT_REF)
    binding = store.record_exchange(
        binding,
        conversation_id=CONVERSATION_ID,
        conversation_url=CONVERSATION_URL,
        request_chars=321,
    )
    binding = store.rollover(binding, reason="cumulative_request_chars")

    rows = store.list_bindings()
    assert [row.lfl_session_id for row in rows] == ["lfl-session-a"]
    history = store.read_history("lfl-session-a")
    assert len(history) == 1
    assert history[0]["conversation_id"] == CONVERSATION_ID
    assert history[0]["reason"] == "cumulative_request_chars"

    assert store.delete_if_unchanged(
        session_id="lfl-session-a",
        expected_updated_at="stale-plan",
    ) is False
    assert store.load("lfl-session-a") == binding

    assert store.delete_if_unchanged(
        session_id="lfl-session-a",
        expected_updated_at=binding.updated_at,
    ) is True
    assert store.load("lfl-session-a") is None
    assert store.read_history("lfl-session-a") == []
    assert store.read_events("lfl-session-a") == []


def test_binding_telemetry_append_failure_never_blocks_exchange_or_rollover(
    tmp_path,
    monkeypatch,
):
    store = ChatGPTSessionBindingStore(tmp_path / "sessions")
    binding = store.get_or_create(session_id="lfl-session-a", project_ref=PROJECT_REF)

    def broken_append(*_args, **_kwargs):
        raise OSError("telemetry disk unavailable")

    monkeypatch.setattr(store, "_append_event_locked", broken_append)
    binding = store.record_exchange(
        binding,
        conversation_id=CONVERSATION_ID,
        conversation_url=CONVERSATION_URL,
        request_chars=777,
    )
    assert store.load("lfl-session-a") == binding
    assert binding.segment_request_count == 1

    rolled = store.rollover(binding, reason="request_cap")
    assert store.load("lfl-session-a") == rolled
    assert rolled.segment_seq == 2


def test_restore_conversation_reuses_exact_owned_target(tmp_path):
    context = _Context()
    surface, _pw = _surface(tmp_path, context)
    page = surface.open()
    target_id = page.target_id

    restored = surface.restore_conversation(
        conversation_id=CONVERSATION_ID,
        conversation_url=CONVERSATION_URL,
    )

    assert page.target_id == target_id
    assert page.url == CONVERSATION_URL
    assert restored.target_id == target_id
    assert restored.conversation_id == CONVERSATION_ID
    assert restored.conversation_url == CONVERSATION_URL


def test_restore_conversation_rejects_non_project_route(tmp_path):
    context = _Context()
    surface, _pw = _surface(tmp_path, context)
    surface.open()

    with pytest.raises(BrowserSurfaceLeaseError, match="outside the configured Project"):
        surface.restore_conversation(
            conversation_id=CONVERSATION_ID,
            conversation_url=f"https://chatgpt.com/c/{CONVERSATION_ID}",
        )


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
    assert page.fronted == 0
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
    assert page.fronted == 0
    assert BrowserSurfaceLeaseStore(tmp_path).load() == after


def test_reset_to_project_root_retries_transient_context_timeout_on_same_target(
    tmp_path, monkeypatch
):
    context = _Context()
    surface, _pw = _surface(
        tmp_path,
        context,
        recovery_conversation_id=CONVERSATION_ID,
    )
    page = surface.open()
    before = surface.snapshot_identity()
    waits: list[tuple[str, float]] = []

    def _flaky_wait(page_arg, *, expected_url, timeout_s=10.0):
        assert page_arg is page
        waits.append((expected_url, timeout_s))
        if len(waits) == 1:
            raise BrowserSurfaceLeaseError(
                "owned ChatGPT page did not reach a stable execution context within 10s"
            )
        assert page_arg.url == PROJECT_URL

    monkeypatch.setattr(
        ChatGPTSurface,
        "_wait_for_page_context",
        staticmethod(_flaky_wait),
    )

    after = surface.reset_to_project_root()

    assert waits == [(PROJECT_URL, 10.0), (PROJECT_URL, 20.0)]
    assert context.created == 1
    assert page.target_id == before.target_id == after.target_id
    assert page.url == PROJECT_URL
    assert page.fronted == 0
    assert after.conversation_id is None
    assert after.conversation_url is None


def test_reset_to_project_root_persistent_context_timeout_still_fails_closed(
    tmp_path, monkeypatch
):
    context = _Context()
    surface, _pw = _surface(
        tmp_path,
        context,
        recovery_conversation_id=CONVERSATION_ID,
    )
    page = surface.open()
    before = surface.snapshot_identity()
    waits: list[float] = []

    def _always_fail(page_arg, *, expected_url, timeout_s=10.0):
        assert page_arg is page
        assert expected_url == PROJECT_URL
        waits.append(timeout_s)
        raise BrowserSurfaceLeaseError("fixture persistent context timeout")

    monkeypatch.setattr(
        ChatGPTSurface,
        "_wait_for_page_context",
        staticmethod(_always_fail),
    )

    with pytest.raises(BrowserSurfaceLeaseError, match="bounded same-target retry"):
        surface.reset_to_project_root()

    assert waits == [10.0, 20.0]
    assert context.created == 1
    assert page.target_id == before.target_id
    assert surface.snapshot_identity() == before
    assert page.fronted == 0


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
    assert replacement.fronted == 0
