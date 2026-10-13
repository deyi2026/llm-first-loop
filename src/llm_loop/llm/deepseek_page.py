"""Visible-page contract for the DeepSeek Web model transport.

Only public DOM/UI semantics are used.  No cookies, storage tokens, private
DeepSeek endpoints, Search, or native file upload belong to this adapter.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlsplit

from .chatgpt_page import (
    GenerationState,
    NativeToolState,
    PageBinding,
    PageCodeBlock,
    PageMessage,
    SendReceipt,
    canonical_text,
    message_identity,
)

DEEPSEEK_SITE_REF = "deepseek-web"
_CONVERSATION_RE = re.compile(
    r"/a/chat/s/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:/|$)"
)


class DeepSeekPageContractError(RuntimeError):
    """The observed DeepSeek page no longer satisfies the qualified contract."""


class DeepSeekPageCancelledError(DeepSeekPageContractError):
    """Phase6 M2：页面轮次被协作取消（engine 窗口打断的 transport 早退）。

    非页面契约破裂——是引擎侧主动取消在页面线程的如实呈现；engine M1
    worker 将其按打断轮丢弃，guard 随线程退出释放。
    """


class DeepSeekPageAdapter:
    COMPOSER_SELECTOR = '#chat-input, textarea[placeholder^="给 DeepSeek 发送消息"]'
    MESSAGE_SELECTOR = ".ds-message"
    FINAL_SELECTOR = ".ds-markdown.ds-assistant-message-main-content"
    THINK_SELECTOR = ".ds-think-content, .ds-markdown--think"
    TOGGLE_SELECTOR = ".ds-toggle-button"
    SELECTED_TOGGLE_CLASS = "ds-toggle-button--selected"
    SEND_SELECTOR = (
        'div[role="button"].ds-button--primary.ds-button--filled.ds-button--circle'
    )
    DISABLED_BUTTON_CLASS = "ds-button--disabled"

    def __init__(self, page: Any, *, profile_label: str):
        self._page = page
        self.profile_label = profile_label

    def observe_identity(self) -> PageBinding:
        url = str(self._page.url or "")
        parts = urlsplit(url)
        host_ok = parts.scheme == "https" and parts.netloc == "chat.deepseek.com"
        match = _CONVERSATION_RE.search(parts.path) if host_ok else None
        return PageBinding(
            profile_label=self.profile_label,
            url=url,
            title=str(self._page.title() or ""),
            project_ref=DEEPSEEK_SITE_REF if host_ok else None,
            conversation_id=match.group(1).lower() if match else None,
        )

    def require_binding(self, expected: PageBinding) -> PageBinding:
        current = self.observe_identity()
        if current.profile_label != expected.profile_label:
            raise DeepSeekPageContractError("browser profile identity changed")
        if current.project_ref != DEEPSEEK_SITE_REF:
            raise DeepSeekPageContractError("owned page left chat.deepseek.com")
        if expected.conversation_id and current.conversation_id != expected.conversation_id:
            raise DeepSeekPageContractError(
                "conversation identity changed: "
                f"{expected.conversation_id!r} -> {current.conversation_id!r}"
            )
        return current

    def _visible_composer(self, *, timeout_s: float = 8.0, poll_ms: int = 100) -> Any:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            loc = self._page.locator(self.COMPOSER_SELECTOR)
            visible = [loc.nth(i) for i in range(loc.count()) if loc.nth(i).is_visible()]
            if len(visible) == 1:
                return visible[0]
            if len(visible) > 1:
                raise DeepSeekPageContractError(
                    f"expected one visible DeepSeek composer; got {len(visible)}"
                )
            self._page.wait_for_timeout(poll_ms)
        raise DeepSeekPageContractError(
            "DeepSeek composer not found; dedicated browser profile may need login"
        )

    def require_ready(self, *, timeout_s: float = 8.0) -> PageBinding:
        binding = self.observe_identity()
        if binding.project_ref != DEEPSEEK_SITE_REF:
            raise DeepSeekPageContractError("page is outside chat.deepseek.com")
        self._visible_composer(timeout_s=timeout_s)
        return binding

    def _feature_button(self, index: int, *, timeout_s: float = 5.0) -> Any:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            toggles = self._page.locator(self.TOGGLE_SELECTOR)
            if toggles.count() > index:
                button = toggles.nth(index)
                if button.is_visible():
                    return button
            self._page.wait_for_timeout(100)
        name = "DeepThink" if index == 0 else "Search"
        raise DeepSeekPageContractError(f"DeepSeek {name} toggle not found")

    @classmethod
    def _toggle_selected(cls, button: Any) -> bool:
        aria_pressed = str(button.get_attribute("aria-pressed") or "").strip().lower()
        if aria_pressed in {"true", "false"}:
            return aria_pressed == "true"
        return cls.SELECTED_TOGGLE_CLASS in str(button.get_attribute("class") or "").split()

    def _send_button(self) -> Any:
        buttons = self._page.locator(self.SEND_SELECTOR)
        visible = [buttons.nth(i) for i in range(buttons.count()) if buttons.nth(i).is_visible()]
        if len(visible) != 1:
            raise DeepSeekPageContractError(
                f"expected one visible DeepSeek primary send control; got {len(visible)}"
            )
        return visible[0]

    def _generation_settled(self) -> bool:
        """Qualified completion: empty composer + primary send returned disabled."""

        try:
            composer = self._visible_composer(timeout_s=1.0, poll_ms=50)
            value = str(composer.input_value() or "")
            if value.strip():
                return False
            send = self._send_button()
            classes = set(str(send.get_attribute("class") or "").split())
            return (
                self.DISABLED_BUTTON_CLASS in classes
                or str(send.get_attribute("aria-disabled") or "").strip().lower() == "true"
            )
        except DeepSeekPageContractError:
            return False

    # Phase6 M2：停止按钮建模（best-effort，不设门）。DeepSeek 生成期发送按钮
    # 通常变为停止形态；环境可行性未证，选择器探测失败一律记 0（如实观察，
    # 不猜 DOM）。取消路径释放生成用同一探测（_try_release_generation）。
    STOP_BUTTON_SELECTORS = (
        'button[aria-label*="停止"]',
        'button[aria-label*="Stop" i]',
        'div[role="button"][aria-label*="停止"]',
    )

    def _stop_button_count(self) -> int:
        total = 0
        for selector in self.STOP_BUTTON_SELECTORS:
            try:
                located = self._page.locator(selector)
                visible = sum(
                    1 for i in range(located.count()) if located.nth(i).is_visible()
                )
                total += visible
            except Exception:  # noqa: BLE001 - best-effort 观察失败记 0
                continue
        return total

    def _try_release_generation(self) -> None:
        """取消时 best-effort 点击停止按钮释放页面（页面线程内执行）。"""

        try:
            for selector in self.STOP_BUTTON_SELECTORS:
                located = self._page.locator(selector)
                for i in range(located.count()):
                    candidate = located.nth(i)
                    if candidate.is_visible():
                        candidate.click()
                        return
        except Exception:  # noqa: BLE001 - 释放失败不影响取消语义
            return

    def _set_feature(self, index: int, enabled: bool) -> bool:
        button = self._feature_button(index)
        before = self._toggle_selected(button)
        if before != enabled:
            button.click()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            button = self._feature_button(index, timeout_s=1.0)
            actual = self._toggle_selected(button)
            if actual == enabled:
                return actual
            self._page.wait_for_timeout(100)
        raise DeepSeekPageContractError(
            f"DeepSeek feature verification failed index={index} requested={enabled}"
        )

    def _ensure_default_model_if_available(self) -> bool:
        radios = self._page.locator('div[role="radio"]')
        # DeepSeek currently has deployments where the model picker is not
        # rendered at all.  Public browser adapters treat that as "selection not
        # supported", not as an authentication failure.  When the picker exists,
        # pin its first/default model; otherwise leave the site-selected model
        # untouched and continue to enforce the features we can mechanically prove.
        if radios.count() == 0:
            return False
        instant = radios.nth(0)
        if instant.get_attribute("aria-checked") != "true":
            instant.click()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if radios.nth(0).get_attribute("aria-checked") == "true":
                return True
            self._page.wait_for_timeout(100)
        raise DeepSeekPageContractError("DeepSeek Instant model selection was not confirmed")

    def ensure_runtime_controls(self, reasoning_effort: str) -> str:
        effort = str(reasoning_effort or "").strip().lower()
        if effort not in {"instant", "high"}:
            raise DeepSeekPageContractError(
                f"unsupported DeepSeek Web reasoning effort: {reasoning_effort!r}"
            )
        self._ensure_default_model_if_available()
        self._set_feature(0, effort == "high")
        # LFL owns all external/tool evidence.  Native Smart Search is always off.
        self._set_feature(1, False)
        return effort

    def observe_messages(self) -> list[PageMessage]:
        binding = self.observe_identity()
        bubbles = self._page.locator(self.MESSAGE_SELECTOR)
        if not hasattr(bubbles, "evaluate_all"):
            raise DeepSeekPageContractError("DeepSeek message locator lacks evaluate_all")
        rows = bubbles.evaluate_all(
            """
            els => els.map(el => {
              const thinking = el.querySelector('.ds-think-content, .ds-markdown--think');
              const markdowns = Array.from(el.querySelectorAll('.ds-markdown'));
              const finals = markdowns.filter(md =>
                !md.classList.contains('ds-markdown--think') &&
                !(thinking && thinking.contains(md))
              );
              const finalEl = finals.length ? finals[finals.length - 1] : null;
              const keyed = el.closest('[data-virtual-list-item-key]');
              return {
                rawText: (el.innerText || '').trim(),
                finalText: finalEl ? (finalEl.innerText || '').trim() : '',
                thinkingText: thinking ? (thinking.innerText || '').trim() : '',
                turnKey: keyed ? (keyed.getAttribute('data-virtual-list-item-key') || '') : ''
              };
            })
            """
        )
        messages: list[PageMessage] = []
        counters = {"user": 0, "assistant": 0}
        for row in rows:
            raw = str(row.get("rawText") or "").strip()
            final = str(row.get("finalText") or "").strip()
            thinking = str(row.get("thinkingText") or "").strip()
            if not raw and not final and not thinking:
                continue
            role = "assistant" if final or thinking else "user"
            content = final if role == "assistant" else raw
            identity_text = content or thinking or raw
            if binding.conversation_id is None:
                raise DeepSeekPageContractError(
                    "message observed before DeepSeek conversation identity appeared"
                )
            ordinal = counters[role]
            counters[role] += 1
            key = str(row.get("turnKey") or "") or None
            messages.append(
                PageMessage(
                    role=role,
                    ordinal=ordinal,
                    text=canonical_text(identity_text),
                    identity=message_identity(
                        binding.conversation_id,
                        role,
                        ordinal,
                        identity_text,
                        stable_key=key,
                    ),
                    content=content,
                    turn_key=key,
                )
            )
        return messages

    def observe_generation(self) -> GenerationState:
        messages = self.observe_messages() if self.observe_identity().conversation_id else []
        users = [m for m in messages if m.role == "user"]
        assistants = [m for m in messages if m.role == "assistant"]
        latest = assistants[-1] if assistants else None
        streaming = bool(latest is not None and not latest.content.strip())
        return GenerationState(
            streaming=streaming,
            stop_button_count=0,
            user_count=len(users),
            assistant_count=len(assistants),
            latest_assistant_identity=latest.identity if latest else None,
            latest_assistant_text=latest.content if latest else None,
        )

    def send_text(
        self,
        text: str,
        *,
        timeout_s: float = 30.0,
        confirm_timeout_s: float | None = None,
        poll_ms: int = 100,
        confirm_token: str | None = None,
        cancelled: Any = None,
    ) -> SendReceipt:
        if not isinstance(text, str) or not text.strip():
            raise DeepSeekPageContractError("refusing to send empty text")
        before = self.observe_generation()
        composer = self._visible_composer(timeout_s=timeout_s, poll_ms=poll_ms)
        composer.fill(text)

        deadline = time.monotonic() + timeout_s
        send_button = None
        while time.monotonic() < deadline:
            if cancelled is not None and cancelled.is_set():
                raise DeepSeekPageCancelledError(
                    "send_text cancelled before dispatch (Phase6 M2)"
                )
            candidate = self._send_button()
            classes = set(str(candidate.get_attribute("class") or "").split())
            disabled = (
                self.DISABLED_BUTTON_CLASS in classes
                or str(candidate.get_attribute("aria-disabled") or "").strip().lower()
                == "true"
            )
            if not disabled:
                send_button = candidate
                break
            self._page.wait_for_timeout(poll_ms)
        if send_button is None:
            raise DeepSeekPageContractError("qualified DeepSeek Send button not found")
        send_button.click()

        expected = canonical_text(text)
        token = canonical_text(confirm_token or "")
        deadline = time.monotonic() + float(confirm_timeout_s or timeout_s)
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(poll_ms)
            if cancelled is not None and cancelled.is_set():
                self._try_release_generation()
                raise DeepSeekPageCancelledError(
                    "send_text cancelled during confirm (Phase6 M2)"
                )
            binding = self.observe_identity()
            if not binding.conversation_id:
                continue
            users = [m for m in self.observe_messages() if m.role == "user"]
            if not users:
                continue
            latest = users[-1]
            latest_text = canonical_text(latest.content)
            if latest_text == expected or (token and token in latest_text):
                return SendReceipt(
                    before_user_count=before.user_count,
                    after_user_count=len(users),
                    conversation_id=binding.conversation_id,
                    user_message_identity=latest.identity,
                )
        raise DeepSeekPageContractError("DeepSeek send could not be mechanically confirmed")

    def wait_for_assistant_completion(
        self,
        before_assistant_count: int,
        *,
        baseline_assistant_identity: str | None = None,
        expected_user_identity: str | None = None,
        expected_user_token: str | None = None,
        timeout_s: float = 120.0,
        poll_ms: int = 250,
        stability_polls: int = 3,
        cancelled: Any = None,
    ) -> GenerationState:
        deadline = time.monotonic() + timeout_s
        stable_text = ""
        stable = 0
        sample_ms = max(750, poll_ms)
        while time.monotonic() < deadline:
            if cancelled is not None and cancelled.is_set():
                # Phase6 M2：页面线程上先 best-effort 释放生成（点击停止按钮），
                # 再以取消异常早退——engine worker 即刻结束，guard 随线程释放。
                self._try_release_generation()
                raise DeepSeekPageCancelledError(
                    "assistant wait cancelled mid-generation (Phase6 M2)"
                )
            self._page.wait_for_timeout(sample_ms)
            messages = self.observe_messages()
            users = [m for m in messages if m.role == "user"]
            assistants = [m for m in messages if m.role == "assistant"]
            if expected_user_identity and not any(
                m.identity == expected_user_identity for m in users
            ):
                continue
            if expected_user_token and not any(
                canonical_text(expected_user_token) in canonical_text(m.content) for m in users
            ):
                continue
            if not assistants:
                continue
            latest = assistants[-1]
            content = latest.content.strip()
            changed = (
                len(assistants) > before_assistant_count
                or baseline_assistant_identity is None
                or latest.identity != baseline_assistant_identity
            )
            if not changed or not content:
                continue
            if content == stable_text:
                stable += 1
            else:
                stable_text = content
                stable = 1
            if stable >= max(2, stability_polls) and self._generation_settled():
                return GenerationState(
                    streaming=False,
                    stop_button_count=self._stop_button_count(),
                    user_count=len(users),
                    assistant_count=len(assistants),
                    latest_assistant_identity=latest.identity,
                    latest_assistant_text=content,
                )
        raise DeepSeekPageContractError("DeepSeek assistant response did not stabilize")

    def observe_native_tool_activity(self) -> NativeToolState:
        search = self._feature_button(1, timeout_s=2.0)
        selected = self._toggle_selected(search)
        return NativeToolState(
            web_search_detected=selected,
            citation_count=1 if selected else 0,
            latest_assistant_citation_count=1 if selected else 0,
            qualified_kinds=("smart_search",),
        )

    def observe_latest_code_blocks(self) -> list[PageCodeBlock]:
        bubbles = self._page.locator(self.MESSAGE_SELECTOR)
        latest = None
        for index in range(bubbles.count()):
            bubble = bubbles.nth(index)
            finals = bubble.locator(self.FINAL_SELECTOR)
            has_final = False
            for md_index in range(finals.count()):
                candidate = finals.nth(md_index)
                in_thinking = bool(
                    candidate.evaluate(
                        "el => !!el.closest('.ds-think-content, .ds-markdown--think')"
                    )
                )
                if not in_thinking:
                    has_final = True
                    break
            if has_final:
                latest = bubble
        if latest is None:
            return []
        markdowns = latest.locator(self.FINAL_SELECTOR)
        if markdowns.count() != 1:
            return []
        root = markdowns.first
        blocks: list[PageCodeBlock] = []
        pres = root.locator("pre")
        for index in range(pres.count()):
            pre = pres.nth(index)
            code = pre.locator("code")
            if not code.count():
                continue
            code_node = code.first
            body = (code_node.inner_text() or "").strip()
            language = str(code_node.get_attribute("data-language") or "").strip()
            class_name = str(code_node.get_attribute("class") or "")
            if not language:
                match = re.search(r"(?:^|\s)language-([^\s]+)", class_name)
                language = match.group(1) if match else ""
            if not language:
                visible = (pre.inner_text() or "").strip().splitlines()
                if visible and visible[0].strip() == "lfl-model-response":
                    language = "lfl-model-response"
            blocks.append(PageCodeBlock(language=language, text=body))
        return blocks
