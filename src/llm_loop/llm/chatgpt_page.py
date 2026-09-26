"""Semantic adapter for the real ChatGPT web page.

The contract in this module is grounded by the M2A-P1 probes frozen in
``docs/data/chatgpt-web-page-contract-20260926.{md,json}``.

Important boundaries:

* no cookies, tokens, headers, or private ChatGPT APIs are read;
* the adapter uses visible/accessibility semantics plus a single qualified
  native-Web-Search marker (``data-testid=chatgpt-citation``);
* page/profile/conversation identity is explicit and never fuzzy-rebound;
* the Project-root composer is submitted with the visible ``发送`` button --
  Enter is not treated as a portable send contract;
* the current DOM has no qualified stable message id, so message identity uses
  the reload-qualified fallback hash from P1 Probe D.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any


class PageContractError(RuntimeError):
    """The observed ChatGPT page no longer satisfies the qualified contract."""


_PROJECT_SEGMENT_RE = re.compile(r"/g/([^/]+)")
_CONVERSATION_RE = re.compile(
    r"/c/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:/|$)"
)


def canonical_text(text: str) -> str:
    """Canonicalize visible message text exactly as qualified by Probe D."""
    return " ".join((text or "").split())


def message_identity(
    conversation_id: str,
    role: str,
    ordinal: int,
    text: str,
    *,
    stable_key: str | None = None,
) -> str:
    """Reload-stable message identity, preferring ChatGPT's durable turn key."""
    if not conversation_id:
        raise PageContractError("message identity requires a bound conversation id")
    if role not in {"user", "assistant"}:
        raise PageContractError(f"unsupported message role: {role}")
    if ordinal < 0:
        raise PageContractError("message ordinal must be >= 0")
    if stable_key:
        raw = f"{conversation_id}|{role}|turn:{stable_key}".encode()
    else:
        raw = f"{conversation_id}|{role}|{ordinal}|{canonical_text(text)}".encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class PageBinding:
    profile_label: str
    url: str
    title: str
    project_ref: str | None
    conversation_id: str | None


@dataclass(frozen=True)
class PageMessage:
    role: str
    ordinal: int
    text: str
    identity: str
    content: str = ""
    turn_key: str | None = None


@dataclass(frozen=True)
class PageCodeBlock:
    language: str
    text: str


@dataclass(frozen=True)
class GenerationState:
    streaming: bool
    stop_button_count: int
    user_count: int
    assistant_count: int
    latest_assistant_identity: str | None
    latest_assistant_text: str | None


@dataclass(frozen=True)
class NativeToolState:
    web_search_detected: bool
    citation_count: int
    latest_assistant_citation_count: int
    qualified_kinds: tuple[str, ...] = ("web_search",)


@dataclass(frozen=True)
class SendReceipt:
    before_user_count: int
    after_user_count: int
    conversation_id: str
    user_message_identity: str


@dataclass(frozen=True)
class StopReceipt:
    attempted: bool
    confirmed: bool
    stop_button_count_before: int
    stop_button_count_after: int


class ChatGPTPageAdapter:
    """Semantic operations for one exact ChatGPT page.

    ``page`` is deliberately duck-typed so fixture tests do not require a real
    browser process.  In continuous production-style experiments it is the
    exact Playwright ``Page`` owned/reacquired by ``ChatGPTSurface``.
    """

    USER_HEADING = "你说："
    ASSISTANT_HEADING = "ChatGPT 说："
    ORDINARY_COMPOSER = "询问 ChatGPT"
    SEND_BUTTON = "发送"
    STOP_BUTTON = "停止"
    WEB_SEARCH_CITATION_SELECTOR = '[data-testid="chatgpt-citation"]'

    def __init__(self, page: Any, *, profile_label: str, project_name: str | None = None):
        self._page = page
        self.profile_label = profile_label
        self.project_name = project_name

    @property
    def project_composer(self) -> str | None:
        if not self.project_name:
            return None
        return f"在“{self.project_name}”中新建聊天"

    def observe_identity(self) -> PageBinding:
        url = str(self._page.url)
        project_match = _PROJECT_SEGMENT_RE.search(url)
        conversation_match = _CONVERSATION_RE.search(url)
        return PageBinding(
            profile_label=self.profile_label,
            url=url,
            title=str(self._page.title()),
            project_ref=project_match.group(1) if project_match else None,
            conversation_id=conversation_match.group(1) if conversation_match else None,
        )

    def require_binding(self, expected: PageBinding) -> PageBinding:
        current = self.observe_identity()
        if current.profile_label != expected.profile_label:
            raise PageContractError("browser profile identity changed")
        if current.project_ref != expected.project_ref:
            raise PageContractError(
                f"project identity changed: {expected.project_ref!r} -> {current.project_ref!r}"
            )
        if (
            expected.conversation_id is not None
            and current.conversation_id != expected.conversation_id
        ):
            raise PageContractError(
                "conversation identity changed: "
                f"{expected.conversation_id!r} -> {current.conversation_id!r}"
            )
        return current

    def observe_messages(self) -> list[PageMessage]:
        binding = self.observe_identity()
        headings = self._page.get_by_role("heading")
        if hasattr(headings, "evaluate_all"):
            # Read the currently mounted message headings and their parent
            # article text in one browser round-trip.  Long ChatGPT threads
            # virtualize the DOM aggressively; a prior count()+nth() loop can
            # observe N headings and then block for 30s on nth(N-1) after that
            # node is unmounted between calls.
            rows = headings.evaluate_all(
                """
                els => els.map(el => {
                    let node = el;
                    let turnKey = '';
                    while (node && !turnKey) {
                        turnKey = node.getAttribute && node.getAttribute('data-turn-key') || '';
                        node = node.parentElement;
                    }
                    return {
                        label: el.innerText || '',
                        rawText: (el.parentElement && el.parentElement.innerText) || '',
                        turnKey
                    };
                })
                """
            )
        else:
            # Test doubles and older adapters may not expose evaluate_all().
            # Preserve the same semantic contract for them; the real browser
            # path above is the qualified long-thread implementation.
            rows = []
            for index in range(headings.count()):
                heading = headings.nth(index)
                root = heading.locator("xpath=..")
                rows.append(
                    {
                        "label": heading.inner_text() or "",
                        "rawText": root.inner_text() or "",
                        "turnKey": "",
                    }
                )
        counters = {"user": 0, "assistant": 0}
        messages: list[PageMessage] = []
        for row in rows:
            label = canonical_text(str(row.get("label") or ""))
            if label == self.USER_HEADING:
                role = "user"
            elif label == self.ASSISTANT_HEADING:
                role = "assistant"
            else:
                continue
            if binding.conversation_id is None:
                raise PageContractError(
                    "message turn observed before conversation identity appeared"
                )
            ordinal = counters[role]
            counters[role] += 1
            raw_text = str(row.get("rawText") or "")
            turn_key = str(row.get("turnKey") or "") or None
            text = canonical_text(raw_text)
            label_prefix = self.USER_HEADING if role == "user" else self.ASSISTANT_HEADING
            raw_content = raw_text.strip()
            if raw_content.startswith(label_prefix):
                raw_content = raw_content[len(label_prefix) :].lstrip()
            messages.append(
                PageMessage(
                    role=role,
                    ordinal=ordinal,
                    text=text,
                    identity=message_identity(
                        binding.conversation_id,
                        role,
                        ordinal,
                        text,
                        stable_key=turn_key,
                    ),
                    content=raw_content,
                    turn_key=turn_key,
                )
            )
        return messages

    def _turn_count(self, role: str) -> int:
        if role == "user":
            label = self.USER_HEADING
        elif role == "assistant":
            label = self.ASSISTANT_HEADING
        else:
            raise PageContractError(f"unsupported turn role: {role}")
        return self._page.get_by_role("heading", name=label).count()

    def observe_generation(self) -> GenerationState:
        stop_count = self._page.get_by_role("button", name=self.STOP_BUTTON).count()
        messages = self.observe_messages()
        users = [m for m in messages if m.role == "user"]
        assistants = [m for m in messages if m.role == "assistant"]
        latest = assistants[-1] if assistants else None
        return GenerationState(
            streaming=stop_count > 0,
            stop_button_count=stop_count,
            user_count=len(users),
            assistant_count=len(assistants),
            latest_assistant_identity=latest.identity if latest else None,
            latest_assistant_text=latest.text if latest else None,
        )

    def observe_native_tool_activity(self) -> NativeToolState:
        total = self._page.locator(self.WEB_SEARCH_CITATION_SELECTOR).count()
        assistants = self._page.get_by_role("heading", name=self.ASSISTANT_HEADING)
        latest_count = 0
        if assistants.count():
            latest_root = assistants.last.locator("xpath=..")
            latest_count = latest_root.locator(self.WEB_SEARCH_CITATION_SELECTOR).count()
        return NativeToolState(
            web_search_detected=total > 0,
            citation_count=total,
            latest_assistant_citation_count=latest_count,
        )

    def observe_latest_code_blocks(self) -> list[PageCodeBlock]:
        """Return rendered fenced code blocks from the latest assistant turn."""
        assistants = self._page.get_by_role("heading", name=self.ASSISTANT_HEADING)
        if assistants.count() == 0:
            return []
        root = assistants.last.locator("xpath=..")
        rendered = root.locator('[data-markdown-copy="code-block"]')
        out: list[PageCodeBlock] = []
        for index in range(rendered.count()):
            block = rendered.nth(index)
            visible = block.inner_text() or ""
            lines = visible.splitlines()
            language = lines[0].strip() if lines else ""
            code = block.locator("code")
            body = code.first.inner_text() if code.count() else "\n".join(lines[1:])
            out.append(PageCodeBlock(language=language, text=(body or "").strip()))
        return out

    def _visible_composer(self, *, timeout_s: float = 3.0, poll_ms: int = 100) -> Any:
        names: list[str] = []
        if self.project_composer:
            names.append(self.project_composer)
        names.append(self.ORDINARY_COMPOSER)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for name in names:
                loc = self._page.get_by_role("textbox", name=name)
                for index in range(loc.count()):
                    candidate = loc.nth(index)
                    if candidate.is_visible():
                        return candidate
            self._page.wait_for_timeout(poll_ms)
        raise PageContractError(f"no qualified composer found; tried {names!r}")

    def send_text(
        self,
        text: str,
        *,
        timeout_s: float = 8.0,
        confirm_timeout_s: float | None = None,
        poll_ms: int = 100,
        confirm_token: str | None = None,
    ) -> SendReceipt:
        """Submit one human/control message using the explicit visible Send button."""
        if not isinstance(text, str) or not text.strip():
            raise PageContractError("refusing to send empty text")
        before = self.observe_generation()
        before_messages = self.observe_messages()
        before_users = [message for message in before_messages if message.role == "user"]
        before_latest_user = before_users[-1] if before_users else None
        expected_content = canonical_text(text)
        expected_token = canonical_text(confirm_token or "")
        # Large LFL snapshots (compact history + full callable tool index) can
        # take materially longer to hydrate the Project-root composer than a
        # short ordinary message.  Reuse the caller's already-bounded send
        # timeout instead of imposing a second shorter readiness deadline.
        readiness_timeout_s = timeout_s
        composer = self._visible_composer(timeout_s=readiness_timeout_s, poll_ms=poll_ms)
        composer.fill(text)

        # ChatGPT renders/enables the Send control asynchronously after the
        # contenteditable composer receives input.  P2 real-page smoke proved
        # that inspecting the button in the same frame can fail even though it
        # becomes visible+enabled immediately afterward.  Observe boundedly;
        # never fall back to pressing Enter (Project root Enter inserts a
        # newline per the P1 page contract).
        send_deadline = time.monotonic() + readiness_timeout_s
        visible_send = None
        while time.monotonic() < send_deadline:
            send = self._page.get_by_role("button", name=self.SEND_BUTTON)
            for index in range(send.count()):
                candidate = send.nth(index)
                if candidate.is_visible() and candidate.is_enabled():
                    visible_send = candidate
                    break
            if visible_send is not None:
                break
            self._page.wait_for_timeout(poll_ms)
        if visible_send is None:
            raise PageContractError("qualified visible/enabled Send button not found")
        visible_send.click()

        # Dispatch exactly one click. Large LFL snapshots may already be accepted
        # and generating before the virtualized DOM exposes the newly-created
        # user turn. Confirmation therefore gets its own bounded budget; this
        # never retries the send mutation.
        confirmation_budget_s = float(
            confirm_timeout_s if confirm_timeout_s is not None else timeout_s
        )
        deadline = time.monotonic() + confirmation_budget_s
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(poll_ms)
            binding = self.observe_identity()
            if not binding.conversation_id:
                continue
            messages = self.observe_messages()
            users = [message for message in messages if message.role == "user"]
            if not users:
                continue
            latest = users[-1]
            latest_content = canonical_text(latest.content)
            content_matches = latest_content == expected_content
            token_matches = bool(expected_token) and expected_token in latest_content
            if not (content_matches or token_matches):
                continue

            # Long ChatGPT conversations virtualize old DOM turns.  A newly
            # submitted user turn may replace an old visible user turn, leaving
            # the visible count unchanged.  Confirm by the latest rendered
            # user content/identity instead of requiring count growth.  If the
            # exact same text was already the latest user turn and neither the
            # count nor fallback identity changes, the DOM is ambiguous and we
            # deliberately keep waiting/fail closed rather than mis-ack.
            count_grew = len(users) > before.user_count
            latest_changed = (
                before_latest_user is None or latest.identity != before_latest_user.identity
            )
            if before_latest_user is None:
                prior_content_differs = True
            else:
                prior_content = canonical_text(before_latest_user.content)
                prior_content_differs = (
                    expected_token not in prior_content
                    if expected_token
                    else prior_content != expected_content
                )
            if count_grew or latest_changed or prior_content_differs:
                return SendReceipt(
                    before_user_count=before.user_count,
                    after_user_count=len(users),
                    conversation_id=binding.conversation_id,
                    user_message_identity=latest.identity,
                )
        raise PageContractError(
            f"send was not confirmed within {confirmation_budget_s:g}s"
        )

    def wait_for_assistant_completion(
        self,
        baseline_assistant_count: int,
        *,
        baseline_assistant_identity: str | None = None,
        expected_user_identity: str | None = None,
        expected_user_token: str | None = None,
        timeout_s: float = 45.0,
        poll_ms: int = 100,
        stability_polls: int = 2,
    ) -> GenerationState:
        """Wait for the assistant turn caused by the just-submitted user turn.

        Visible turn counts are advisory only because ChatGPT virtualizes old
        long-conversation DOM nodes.  When ``expected_user_identity`` is
        provided, the qualifying assistant must occur *after* that exact
        rendered user turn in DOM order.  Otherwise a changed latest assistant
        identity can qualify even when the visible assistant count is flat.
        """
        deadline = time.monotonic() + timeout_s
        last_identity: str | None = None
        stable = 0
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(poll_ms)
            state = self.observe_generation()
            if state.streaming:
                stable = 0
                continue
            if not state.latest_assistant_text:
                stable = 0
                continue

            messages = self.observe_messages()
            latest_message = messages[-1] if messages else None
            if latest_message is None or latest_message.role != "assistant":
                stable = 0
                continue

            follows_expected_user = False
            if expected_user_identity is not None or expected_user_token:
                canonical_token = canonical_text(expected_user_token or "")
                expected_index = next(
                    (
                        index
                        for index, message in enumerate(messages)
                        if message.role == "user"
                        and (
                            (
                                expected_user_identity is not None
                                and message.identity == expected_user_identity
                            )
                            or (
                                canonical_token
                                and canonical_token in canonical_text(message.content)
                            )
                        )
                    ),
                    None,
                )
                if expected_index is None:
                    stable = 0
                    continue
                follows_expected_user = len(messages) - 1 > expected_index

            count_grew = state.assistant_count > baseline_assistant_count
            identity_changed = (
                baseline_assistant_identity is not None
                and state.latest_assistant_identity != baseline_assistant_identity
            )
            if not (follows_expected_user or count_grew or identity_changed):
                stable = 0
                continue
            if state.latest_assistant_identity == last_identity:
                stable += 1
                if stable >= stability_polls:
                    return state
            else:
                stable = 0
            last_identity = state.latest_assistant_identity
        raise PageContractError(f"assistant completion not confirmed within {timeout_s:g}s")

    def stop_generation(self, *, timeout_s: float = 5.0, poll_ms: int = 100) -> StopReceipt:
        before = self._page.get_by_role("button", name=self.STOP_BUTTON).count()
        if before == 0:
            return StopReceipt(False, True, 0, 0)
        stops = self._page.get_by_role("button", name=self.STOP_BUTTON)
        clicked = False
        for index in range(stops.count()):
            candidate = stops.nth(index)
            if candidate.is_visible() and candidate.is_enabled():
                candidate.click()
                clicked = True
                break
        if not clicked:
            return StopReceipt(True, False, before, before)
        deadline = time.monotonic() + timeout_s
        after = before
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(poll_ms)
            after = self._page.get_by_role("button", name=self.STOP_BUTTON).count()
            if after == 0:
                return StopReceipt(True, True, before, 0)
        return StopReceipt(True, False, before, after)


class PlaywrightCdpAttachment:
    """Attach to one existing page in the dedicated Chrome CDP endpoint.

    The attachment never launches Chrome, never reads storage state, and never
    calls ``browser.close()``.  ``close()`` stops only the local Playwright
    client so the dedicated browser/profile stays alive for future turns.
    """

    def __init__(self, endpoint: str, *, target_url_contains: str):
        self.endpoint = endpoint
        self.target_url_contains = target_url_contains
        self._pw = None
        self._browser = None
        self.page = None

    def open(self) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise PageContractError(f"playwright is not installed: {exc}") from exc
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.endpoint)
            pages = [page for context in self._browser.contexts for page in context.pages]
            matches = [page for page in pages if self.target_url_contains in str(page.url)]
            if len(matches) != 1:
                raise PageContractError(
                    "exact CDP page attachment requires one match: "
                    f"needle={self.target_url_contains!r}, matches={len(matches)}"
                )
            self.page = matches[0]
            return self.page
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self.page = None
        self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            finally:
                self._pw = None

    def __enter__(self) -> Any:
        return self.open()

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()
