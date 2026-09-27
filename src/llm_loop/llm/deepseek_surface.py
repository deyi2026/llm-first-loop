"""Exact-target browser surface ownership for DeepSeek Web."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .chatgpt_page import PageBinding
from .chatgpt_surface import (
    BrowserSurfaceLease,
    BrowserSurfaceLeaseError,
    BrowserSurfaceLeaseStore,
)
from .deepseek_page import DEEPSEEK_SITE_REF


def _conversation_url(root_url: str, conversation_id: str) -> str:
    parts = urlsplit(root_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/a/chat/s/{conversation_id}", "", "")
    )


class DeepSeekSurface:
    """Own/reacquire one exact background DeepSeek tab by durable target id."""

    def __init__(
        self,
        endpoint: str,
        *,
        lease_store: BrowserSurfaceLeaseStore,
        root_url: str,
        profile_label: str,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.lease_store = lease_store
        self.root_url = root_url.rstrip("/") + "/"
        self.profile_label = profile_label
        self._playwright_factory = playwright_factory
        self._pw = None
        self._browser = None
        self.page = None
        self.lease: BrowserSurfaceLease | None = None

    def _start_playwright(self):
        if self._playwright_factory is not None:
            return self._playwright_factory()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise BrowserSurfaceLeaseError(f"playwright is not installed: {exc}") from exc
        return sync_playwright().start()

    @staticmethod
    def _target_id(context: Any, page: Any) -> str:
        session = context.new_cdp_session(page)
        try:
            info = session.send("Target.getTargetInfo")
            target_id = str((info.get("targetInfo") or {}).get("targetId") or "")
        finally:
            with contextlib.suppress(Exception):
                session.detach()
        if not target_id:
            raise BrowserSurfaceLeaseError("CDP page has no target id")
        return target_id

    def _owned_context(self) -> Any:
        contexts = list(self._browser.contexts)
        if len(contexts) != 1:
            raise BrowserSurfaceLeaseError(
                f"dedicated browser requires exactly one context; got {len(contexts)}"
            )
        return contexts[0]

    def _find_target(self, target_id: str) -> Any | None:
        for context in self._browser.contexts:
            for page in context.pages:
                try:
                    if callable(getattr(page, "is_closed", None)) and page.is_closed():
                        continue
                    if self._target_id(context, page) == target_id:
                        return page
                except Exception:
                    continue
        return None

    @staticmethod
    def _wait_for_page_context(
        page: Any, *, expected_url: str, timeout_s: float = 10.0
    ) -> None:
        deadline = time.monotonic() + timeout_s
        stable = 0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                current = str(page.url or "")
                title = str(page.title() or "")
                if current == expected_url and title:
                    stable += 1
                    if stable >= 2:
                        return
                else:
                    stable = 0
            except Exception as exc:
                last_error = exc
                stable = 0
            page.wait_for_timeout(150)
        suffix = f": {last_error}" if last_error else ""
        raise BrowserSurfaceLeaseError(
            "owned DeepSeek page did not reach a stable execution context within "
            f"{timeout_s:g}s{suffix}"
        )

    def _create_owned_page(self, url: str) -> tuple[Any, str]:
        context = self._owned_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until="commit", timeout=15_000)
            self._wait_for_page_context(page, expected_url=url)
            target_id = self._target_id(context, page)
        except Exception:
            with contextlib.suppress(Exception):
                page.close()
            raise
        return page, target_id

    def open(self) -> Any:
        self._pw = self._start_playwright()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.endpoint)
            if self.lease_store.exists():
                lease = self.lease_store.load()
                if (
                    lease.project_ref != DEEPSEEK_SITE_REF
                    or lease.project_url.rstrip("/") + "/" != self.root_url
                ):
                    raise BrowserSurfaceLeaseError("DeepSeek surface lease identity mismatch")
                page = self._find_target(lease.target_id)
                expected = lease.conversation_url or self.root_url
                if page is not None:
                    if str(getattr(page, "url", "") or "") != expected:
                        page.goto(expected, wait_until="commit", timeout=15_000)
                    self._wait_for_page_context(page, expected_url=expected)
                    self.page = page
                    self.lease = lease
                    return page
                page, target_id = self._create_owned_page(expected)
                self.lease = self.lease_store.update(target_id=target_id)
                self.page = page
                return page

            page, target_id = self._create_owned_page(self.root_url)
            lease = BrowserSurfaceLease.new(
                project_ref=DEEPSEEK_SITE_REF,
                project_url=self.root_url,
                profile_label=self.profile_label,
                target_id=target_id,
            )
            self.lease_store.save(lease)
            self.page = page
            self.lease = lease
            return page
        except Exception:
            self.close()
            raise

    def bind_conversation(self, binding: PageBinding) -> BrowserSurfaceLease:
        if self.page is None or self.lease is None:
            raise BrowserSurfaceLeaseError("DeepSeek surface is not open")
        if binding.project_ref != DEEPSEEK_SITE_REF:
            raise BrowserSurfaceLeaseError("cannot bind page outside chat.deepseek.com")
        if not binding.conversation_id:
            return self.lease
        expected = _conversation_url(self.root_url, binding.conversation_id)
        if binding.url != expected:
            raise BrowserSurfaceLeaseError(
                f"unexpected DeepSeek conversation URL: {binding.url!r}"
            )
        self.lease = self.lease_store.update(
            conversation_id=binding.conversation_id,
            conversation_url=expected,
        )
        return self.lease

    def reset_to_root(self) -> BrowserSurfaceLease:
        if self.page is None or self.lease is None:
            raise BrowserSurfaceLeaseError("DeepSeek surface is not open")
        last_error: BrowserSurfaceLeaseError | None = None
        for attempt, timeout_s in enumerate((10.0, 20.0)):
            if str(getattr(self.page, "url", "") or "") != self.root_url:
                self.page.goto(self.root_url, wait_until="commit", timeout=15_000)
            try:
                self._wait_for_page_context(
                    self.page, expected_url=self.root_url, timeout_s=timeout_s
                )
                last_error = None
                break
            except BrowserSurfaceLeaseError as exc:
                last_error = exc
                if callable(getattr(self.page, "is_closed", None)) and self.page.is_closed():
                    raise
                if attempt == 0:
                    self.page.wait_for_timeout(250)
        if last_error is not None:
            raise BrowserSurfaceLeaseError(
                "owned DeepSeek page did not stabilize after bounded same-target retry: "
                f"{last_error}"
            ) from last_error
        self.lease = self.lease_store.update(
            conversation_id=None,
            conversation_url=None,
        )
        return self.lease

    def close(self) -> None:
        self.page = None
        self.lease = None
        self._browser = None
        if self._pw is not None:
            try:
                stop = getattr(self._pw, "stop", None)
                if callable(stop):
                    stop()
            finally:
                self._pw = None
