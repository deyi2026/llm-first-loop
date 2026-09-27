"""Stable browser-surface ownership for the ChatGPT Web adapter.

This module owns only browser transport identity/lifecycle.  It does not own an
agent loop, tool policy, or any LFL semantic decision.

The key invariant is that a durable LFL/ChatGPT session binds to one logical
surface lease.  A live CDP target id is preferred over URL matching.  When the
target disappears (for example after Chrome restart), recovery creates one new
program-owned tab at the already-known Project/conversation URL and moves the
same logical lease to that new target.  It never picks arbitrarily among two
same-URL tabs.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .chatgpt_page import PageBinding, PageContractError

LEASE_VERSION = 1


class BrowserSurfaceLeaseError(PageContractError):
    """The owned ChatGPT browser surface cannot be proven or recovered safely."""


def _now() -> str:
    # Use the host OS local timezone.  This module cannot depend on the separate
    # timekeeping branch while this feature remains isolated from that WIP.
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _conversation_url(project_url: str, conversation_id: str) -> str:
    parts = urlsplit(project_url)
    path = parts.path.rstrip("/")
    if path.endswith("/project"):
        path = path[: -len("/project")]
    return urlunsplit((parts.scheme, parts.netloc, f"{path}/c/{conversation_id}", "", ""))


def _is_generic_chatgpt_conversation_url(url: str, conversation_id: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.netloc == "chatgpt.com"
        and parts.path.rstrip("/") == f"/c/{conversation_id}"
    )


@dataclass(frozen=True)
class BrowserSurfaceLease:
    version: int
    lease_id: str
    project_ref: str
    project_url: str
    profile_label: str
    target_id: str
    conversation_id: str | None
    conversation_url: str | None
    created_at: str
    updated_at: str

    @classmethod
    def new(
        cls,
        *,
        project_ref: str,
        project_url: str,
        profile_label: str,
        target_id: str,
        conversation_id: str | None = None,
        conversation_url: str | None = None,
    ) -> BrowserSurfaceLease:
        now = _now()
        return cls(
            version=LEASE_VERSION,
            lease_id=uuid.uuid4().hex,
            project_ref=project_ref,
            project_url=project_url,
            profile_label=profile_label,
            target_id=target_id,
            conversation_id=conversation_id,
            conversation_url=conversation_url,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BrowserSurfaceLease:
        try:
            lease = cls(
                version=int(value["version"]),
                lease_id=str(value["lease_id"]),
                project_ref=str(value["project_ref"]),
                project_url=str(value["project_url"]),
                profile_label=str(value["profile_label"]),
                target_id=str(value["target_id"]),
                conversation_id=(
                    str(value["conversation_id"]) if value.get("conversation_id") else None
                ),
                conversation_url=(
                    str(value["conversation_url"]) if value.get("conversation_url") else None
                ),
                created_at=str(value["created_at"]),
                updated_at=str(value["updated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BrowserSurfaceLeaseError(f"invalid surface lease: {exc}") from exc
        lease.verify()
        return lease

    def verify(self) -> None:
        if self.version != LEASE_VERSION:
            raise BrowserSurfaceLeaseError(f"unsupported surface lease version: {self.version}")
        if not self.lease_id or not self.project_ref or not self.project_url:
            raise BrowserSurfaceLeaseError("surface lease identity fields must be non-empty")
        if not self.profile_label or not self.target_id:
            raise BrowserSurfaceLeaseError("surface lease target fields must be non-empty")


class BrowserSurfaceLeaseStore:
    """Small durable store for one logical ChatGPT browser surface."""

    FILE = "surface-lease.json"
    LOCK = ".surface-lease.lock"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / self.FILE
        self.lock_path = self.root / self.LOCK
        self.root.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _lock(self):
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - production target is POSIX
            raise BrowserSurfaceLeaseError("surface lease store requires POSIX fcntl") from exc
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> BrowserSurfaceLease:
        with self._lock():
            return self._load_unlocked()

    def _load_unlocked(self) -> BrowserSurfaceLease:
        if not self.path.is_file():
            raise BrowserSurfaceLeaseError("surface lease is missing")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BrowserSurfaceLeaseError(f"surface lease is unreadable: {exc}") from exc
        if not isinstance(value, dict):
            raise BrowserSurfaceLeaseError("surface lease root must be an object")
        return BrowserSurfaceLease.from_dict(value)

    def save(self, lease: BrowserSurfaceLease) -> BrowserSurfaceLease:
        lease.verify()
        with self._lock():
            self._write_unlocked(lease)
        return lease

    def update(self, **changes: Any) -> BrowserSurfaceLease:
        with self._lock():
            lease = self._load_unlocked()
            updated = replace(lease, updated_at=_now(), **changes)
            updated.verify()
            self._write_unlocked(updated)
            return updated

    def _write_unlocked(self, lease: BrowserSurfaceLease) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        data = json.dumps(asdict(lease), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        dir_fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


class ChatGPTSurface:
    """Own/reacquire exactly one program-controlled ChatGPT tab."""

    def __init__(
        self,
        endpoint: str,
        *,
        lease_store: BrowserSurfaceLeaseStore,
        project_url: str,
        project_ref: str,
        profile_label: str,
        recovery_conversation_id: str | None = None,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.lease_store = lease_store
        self.project_url = project_url
        self.project_ref = project_ref
        self.profile_label = profile_label
        self.recovery_conversation_id = recovery_conversation_id
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
            result = session.send("Target.getTargetInfo")
            target_id = str((result.get("targetInfo") or {}).get("targetId") or "")
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
                f"dedicated ChatGPT browser requires exactly one context; got {len(contexts)}"
            )
        return contexts[0]

    def _find_target(self, target_id: str) -> Any | None:
        for context in self._browser.contexts:
            for page in context.pages:
                try:
                    is_closed = getattr(page, "is_closed", None)
                    if callable(is_closed) and is_closed():
                        continue
                    if self._target_id(context, page) == target_id:
                        return page
                except Exception:
                    # A closing/unmounted target is equivalent to a missing
                    # target for lease recovery.  Do not let one stale page
                    # prevent inspection of the remaining dedicated pages.
                    continue
        return None

    def _create_owned_page(self, url: str) -> tuple[Any, str]:
        context = self._owned_context()
        page = context.new_page()
        try:
            # ChatGPT can keep a navigation alive well past the first committed
            # document during browser/session recovery.  Surface ownership only
            # needs the exact target plus the committed route; semantic page
            # readiness remains ChatGPTPageAdapter's responsibility.
            page.goto(url, wait_until="commit", timeout=15_000)
            self._wait_for_page_context(page, expected_url=url)
            target_id = self._target_id(context, page)
        except Exception:
            with contextlib.suppress(Exception):
                page.close()
            raise
        return page, target_id

    @staticmethod
    def _wait_for_page_context(page: Any, *, expected_url: str, timeout_s: float = 10.0) -> None:
        """Wait until the newly-created page has a usable execution context.

        ChatGPT may commit the requested conversation route and immediately do
        another client-side/document navigation.  During that short window,
        `page.title()` can fail with an execution-context-destroyed error even
        though the CDP target itself is healthy.  Treat that as transport
        readiness, not as a runner failure.  No model/tool semantics live here.
        """
        deadline = time.monotonic() + timeout_s
        stable = 0
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                current_url = str(page.url or "")
                title = str(page.title() or "")
                if current_url == expected_url and title:
                    stable += 1
                    if stable >= 2:
                        return
                else:
                    stable = 0
            except Exception as exc:  # transient Playwright navigation context
                last_error = exc
                stable = 0
            page.wait_for_timeout(150)
        detail = f": {last_error}" if last_error is not None else ""
        raise BrowserSurfaceLeaseError(
            "owned ChatGPT page did not reach a stable execution context within "
            f"{timeout_s:g}s{detail}"
        )

    def open(self) -> Any:
        self._pw = self._start_playwright()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.endpoint)
            if self.lease_store.exists():
                lease = self.lease_store.load()
                if lease.project_ref != self.project_ref or lease.project_url != self.project_url:
                    raise BrowserSurfaceLeaseError("surface lease Project identity mismatch")
                page = self._find_target(lease.target_id)
                if page is not None:
                    expected_url = lease.conversation_url or self.project_url
                    try:
                        current_url = str(getattr(page, "url", "") or "")
                        if current_url != expected_url:
                            # Exact target-id ownership was already proven above.
                            # If that owned tab is left on a stale route (for example
                            # ChatGPT canonicalized a Project conversation to generic
                            # `/c/<id>` before the previous process exited), restore
                            # the durable lease route on the same target.  Never use
                            # URL matching to choose a different tab here.
                            page.goto(expected_url, wait_until="commit", timeout=15_000)
                        self._wait_for_page_context(page, expected_url=expected_url)
                    except BrowserSurfaceLeaseError:
                        is_closed = getattr(page, "is_closed", None)
                        if not (callable(is_closed) and is_closed()):
                            raise
                        page = None
                if page is not None:
                    self.page = page
                    self.lease = lease
                    return page

                recovery_url = lease.conversation_url or self.project_url
                page, target_id = self._create_owned_page(recovery_url)
                lease = self.lease_store.update(target_id=target_id)
                self.page = page
                self.lease = lease
                return page

            conversation_id = self.recovery_conversation_id
            url = (
                _conversation_url(self.project_url, conversation_id)
                if conversation_id
                else self.project_url
            )
            page, target_id = self._create_owned_page(url)
            lease = BrowserSurfaceLease.new(
                project_ref=self.project_ref,
                project_url=self.project_url,
                profile_label=self.profile_label,
                target_id=target_id,
                conversation_id=conversation_id,
                conversation_url=(url if conversation_id else None),
            )
            self.lease_store.save(lease)
            self.page = page
            self.lease = lease
            return page
        except Exception:
            self.close()
            raise

    def bind_conversation(self, binding: PageBinding) -> BrowserSurfaceLease:
        if self.lease is None or self.page is None:
            raise BrowserSurfaceLeaseError("surface is not open")
        if binding.project_ref is not None and binding.project_ref != self.project_ref:
            raise BrowserSurfaceLeaseError("cannot bind conversation from another Project")
        if not binding.conversation_id:
            return self.lease
        if self.lease.conversation_id and self.lease.conversation_id != binding.conversation_id:
            raise BrowserSurfaceLeaseError(
                "surface conversation drift: "
                f"{self.lease.conversation_id!r} -> {binding.conversation_id!r}"
            )
        conversation_url = binding.url
        if binding.project_ref is None:
            # ChatGPT can occasionally canonicalize a conversation created from a
            # Project root to the generic `/c/<id>` route after the assistant has
            # completed.  Missing Project identity is not evidence of a different
            # Project, but it is also not safe durable recovery state: on restart
            # the lease would claim the configured Project while the owned target
            # still sits on a generic route.  Re-anchor that *same completed
            # conversation* through the configured Project route and require the
            # navigation to stabilize before persisting it.  An explicit non-empty
            # different project_ref remains fail-closed above.
            if not _is_generic_chatgpt_conversation_url(binding.url, binding.conversation_id):
                raise BrowserSurfaceLeaseError(
                    "cannot recover conversation without configured Project identity"
                )
            conversation_url = _conversation_url(self.project_url, binding.conversation_id)
            current_url = str(getattr(self.page, "url", "") or "")
            if current_url != binding.url:
                raise BrowserSurfaceLeaseError("surface page changed before conversation bind")
            self.page.goto(conversation_url, wait_until="commit", timeout=15_000)
            self._wait_for_page_context(self.page, expected_url=conversation_url)
        self.lease = self.lease_store.update(
            conversation_id=binding.conversation_id,
            conversation_url=conversation_url,
        )
        return self.lease

    def reset_to_project_root(self) -> BrowserSurfaceLease:
        """Return the owned tab to the Project root for one fresh model snapshot.

        ChatGPT Web is a transport for LFL model decisions, not a second owner of
        conversation state.  Each provider decision must therefore start from a
        fresh outer ChatGPT thread and receive only the current LFL-built request
        snapshot.  The durable lease keeps physical target ownership, while the
        previous ChatGPT conversation identity is cleared before the next send.
        """
        if self.lease is None or self.page is None:
            raise BrowserSurfaceLeaseError("surface is not open")
        current_url = str(getattr(self.page, "url", "") or "")
        if current_url != self.project_url:
            self.page.goto(self.project_url, wait_until="commit", timeout=15_000)
        self._wait_for_page_context(self.page, expected_url=self.project_url)
        self.lease = self.lease_store.update(
            conversation_id=None,
            conversation_url=None,
        )
        return self.lease

    def snapshot_identity(self) -> BrowserSurfaceLease:
        if self.lease is None:
            raise BrowserSurfaceLeaseError("surface is not open")
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

    def __enter__(self) -> Any:
        return self.open()

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()
