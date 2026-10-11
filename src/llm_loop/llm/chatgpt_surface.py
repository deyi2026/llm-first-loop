"""Stable browser-surface ownership for the ChatGPT Web adapter.

This module owns only browser transport identity/lifecycle.  It does not own an
agent loop, tool policy, or any LFL semantic decision.

The physical browser target has one durable surface lease.  Logical LFL sessions
bind independently to bounded ChatGPT conversation segments; switching sessions
reuses the exact owned target but restores that session's recorded conversation
route.  A live CDP target id is preferred over URL matching.  When the target
disappears (for example after Chrome restart), recovery creates one new
program-owned tab at the already-known Project/conversation URL and moves the
same physical lease to that new target.  It never picks arbitrarily among two
same-URL tabs.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .chatgpt_page import PageBinding, PageContractError

logger = logging.getLogger(__name__)

LEASE_VERSION = 1
SESSION_BINDING_VERSION = 1


class BrowserSurfaceLeaseError(PageContractError):
    """The owned ChatGPT browser surface cannot be proven or recovered safely."""


def _now() -> str:
    # Use the host OS local timezone.  This module cannot depend on the separate
    # timekeeping branch while this feature remains isolated from that WIP.
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class ChatGPTSessionBinding:
    """Durable logical mapping from one LFL session to one active ChatGPT segment.

    LFL remains the sole context/history authority.  This record only remembers
    which outer ChatGPT conversation currently carries the transport continuity
    for a given LFL session, plus bounded rollover accounting.
    """

    version: int
    lfl_session_id: str
    project_ref: str
    conversation_id: str | None
    conversation_url: str | None
    segment_seq: int
    segment_request_count: int
    segment_request_chars: int
    total_request_count: int
    created_at: str
    updated_at: str

    @classmethod
    def new(cls, *, lfl_session_id: str, project_ref: str) -> ChatGPTSessionBinding:
        now = _now()
        binding = cls(
            version=SESSION_BINDING_VERSION,
            lfl_session_id=str(lfl_session_id).strip(),
            project_ref=str(project_ref).strip(),
            conversation_id=None,
            conversation_url=None,
            segment_seq=1,
            segment_request_count=0,
            segment_request_chars=0,
            total_request_count=0,
            created_at=now,
            updated_at=now,
        )
        binding.verify()
        return binding

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ChatGPTSessionBinding:
        try:
            binding = cls(
                version=int(value["version"]),
                lfl_session_id=str(value["lfl_session_id"]),
                project_ref=str(value["project_ref"]),
                conversation_id=(
                    str(value["conversation_id"]) if value.get("conversation_id") else None
                ),
                conversation_url=(
                    str(value["conversation_url"]) if value.get("conversation_url") else None
                ),
                segment_seq=int(value["segment_seq"]),
                segment_request_count=int(value["segment_request_count"]),
                segment_request_chars=int(value["segment_request_chars"]),
                total_request_count=int(value["total_request_count"]),
                created_at=str(value["created_at"]),
                updated_at=str(value["updated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BrowserSurfaceLeaseError(f"invalid ChatGPT session binding: {exc}") from exc
        binding.verify()
        return binding

    def verify(self) -> None:
        if self.version != SESSION_BINDING_VERSION:
            raise BrowserSurfaceLeaseError(
                f"unsupported ChatGPT session binding version: {self.version}"
            )
        if not self.lfl_session_id or not self.project_ref:
            raise BrowserSurfaceLeaseError("ChatGPT session binding identity must be non-empty")
        if self.segment_seq < 1:
            raise BrowserSurfaceLeaseError("ChatGPT session segment_seq must be >= 1")
        if (
            self.segment_request_count < 0
            or self.segment_request_chars < 0
            or self.total_request_count < 0
        ):
            raise BrowserSurfaceLeaseError("ChatGPT session counters must be non-negative")
        if bool(self.conversation_id) != bool(self.conversation_url):
            raise BrowserSurfaceLeaseError(
                "ChatGPT session conversation id/url must be present together"
            )


class ChatGPTSessionBindingStore:
    """Durable per-LFL-session ChatGPT conversation bindings.

    Ordinary safe session ids stay human-readable on disk for operations/debug.
    Unusual or unsafe identifiers fall back to a stable hash so arbitrary input
    can never escape the store root.  The original LFL session id always remains
    inside the JSON record.
    """

    FILE = "binding.json"
    LOCK = ".binding.lock"
    HISTORY = "segments.jsonl"
    EVENTS = "events.jsonl"
    EVENT_SCHEMA = "lfl.chatgpt_binding_event.v1"
    _EVENT_MAX_BYTES = 1_000_000
    _EVENT_TAIL_LINES = 2_000
    _SAFE_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(session_id: str) -> str:
        value = str(session_id).strip()
        if not value:
            raise BrowserSurfaceLeaseError("LFL session id must be non-empty")
        if ChatGPTSessionBindingStore._SAFE_SESSION_RE.fullmatch(value):
            return value
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    def _dir(self, session_id: str) -> Path:
        return self.root / self._key(session_id)

    @contextlib.contextmanager
    def _lock(self, session_id: str):
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - production target is POSIX
            raise BrowserSurfaceLeaseError("session binding store requires POSIX fcntl") from exc
        directory = self._dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(directory / self.LOCK, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield directory
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def load(self, session_id: str) -> ChatGPTSessionBinding | None:
        with self._lock(session_id) as directory:
            path = directory / self.FILE
            if not path.is_file():
                return None
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BrowserSurfaceLeaseError(
                    f"ChatGPT session binding is unreadable: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise BrowserSurfaceLeaseError("ChatGPT session binding root must be object")
            binding = ChatGPTSessionBinding.from_dict(value)
            if binding.lfl_session_id != str(session_id).strip():
                raise BrowserSurfaceLeaseError("ChatGPT session binding id/hash mismatch")
            return binding

    def list_bindings(self) -> list[ChatGPTSessionBinding]:
        """Return all readable durable bindings, newest first.

        Empty/tombstoned directories are ignored. A malformed binding remains a
        hard error so operators do not silently make GC decisions from partial
        state.
        """

        rows: list[ChatGPTSessionBinding] = []
        for path in self.root.glob(f"*/{self.FILE}"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BrowserSurfaceLeaseError(
                    f"ChatGPT session binding is unreadable: {path}: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise BrowserSurfaceLeaseError(
                    f"ChatGPT session binding root must be object: {path}"
                )
            rows.append(ChatGPTSessionBinding.from_dict(value))
        rows.sort(key=lambda item: item.updated_at, reverse=True)
        return rows

    def read_history(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Read bounded closed-segment history for one LFL session."""

        bounded = max(1, min(int(limit), 500))
        with self._lock(session_id) as directory:
            path = directory / self.HISTORY
            if not path.is_file():
                return []
            rows: list[dict[str, Any]] = []
            try:
                for raw in path.read_text(encoding="utf-8").splitlines():
                    if not raw.strip():
                        continue
                    value = json.loads(raw)
                    if isinstance(value, dict):
                        rows.append(value)
            except (OSError, json.JSONDecodeError) as exc:
                raise BrowserSurfaceLeaseError(
                    f"ChatGPT session history is unreadable: {exc}"
                ) from exc
            return rows[-bounded:]

    def read_events(self, session_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        """Read bounded mechanical transport telemetry for one LFL session."""

        bounded = max(1, min(int(limit), self._EVENT_TAIL_LINES))
        with self._lock(session_id) as directory:
            path = directory / self.EVENTS
            if not path.is_file():
                return []
            rows: list[dict[str, Any]] = []
            try:
                for raw in path.read_text(encoding="utf-8").splitlines():
                    if not raw.strip():
                        continue
                    value = json.loads(raw)
                    if isinstance(value, dict):
                        rows.append(value)
            except (OSError, json.JSONDecodeError) as exc:
                raise BrowserSurfaceLeaseError(
                    f"ChatGPT session telemetry is unreadable: {exc}"
                ) from exc
            return rows[-bounded:]

    def record_transport_event(
        self,
        binding: ChatGPTSessionBinding,
        *,
        event: str,
        **facts: object,
    ) -> None:
        """Append one bounded, prompt-free transport event."""

        binding.verify()
        name = str(event or "").strip()
        if not name:
            raise BrowserSurfaceLeaseError("ChatGPT transport event must be non-empty")
        payload: dict[str, object] = {
            "schema": self.EVENT_SCHEMA,
            "ts": _now(),
            "event": name,
            "session_id": binding.lfl_session_id,
            "segment_seq": binding.segment_seq,
        }
        if binding.conversation_id:
            payload["conversation_id"] = binding.conversation_id
        for key, value in facts.items():
            if value is not None:
                payload[str(key)] = value
        with self._lock(binding.lfl_session_id) as directory:
            self._try_append_event_locked(directory, payload)

    def delete_if_unchanged(
        self,
        *,
        session_id: str,
        expected_updated_at: str,
    ) -> bool:
        """Delete one orphan binding only if the observed version is unchanged.

        Session lifecycle eligibility is intentionally *not* decided here; callers
        must prove the LFL session no longer exists immediately before mutation.
        The optimistic timestamp guard prevents an old GC plan from deleting a
        binding that resumed activity after the plan was produced.
        """

        expected = str(expected_updated_at).strip()
        if not expected:
            raise BrowserSurfaceLeaseError("expected_updated_at must be non-empty")
        with self._lock(session_id) as directory:
            path = directory / self.FILE
            if not path.is_file():
                return False
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise BrowserSurfaceLeaseError(
                    f"ChatGPT session binding is unreadable: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise BrowserSurfaceLeaseError("ChatGPT session binding root must be object")
            binding = ChatGPTSessionBinding.from_dict(value)
            if binding.lfl_session_id != str(session_id).strip():
                raise BrowserSurfaceLeaseError("ChatGPT session binding id/hash mismatch")
            if binding.updated_at != expected:
                return False
            for candidate in (
                directory / self.FILE,
                directory / self.HISTORY,
                directory / self.EVENTS,
            ):
                if candidate.exists():
                    candidate.unlink()
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            return True

    def save(self, binding: ChatGPTSessionBinding) -> ChatGPTSessionBinding:
        binding.verify()
        with self._lock(binding.lfl_session_id) as directory:
            self._write(directory / self.FILE, binding)
        return binding

    def _append_event_locked(
        self,
        directory: Path,
        payload: dict[str, object],
    ) -> None:
        path = directory / self.EVENTS
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size <= self._EVENT_MAX_BYTES:
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        tail = lines[-self._EVENT_TAIL_LINES :]
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            if tail:
                handle.write("\n".join(tail) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _try_append_event_locked(
        self,
        directory: Path,
        payload: dict[str, object],
    ) -> bool:
        try:
            self._append_event_locked(directory, payload)
            return True
        except Exception:  # noqa: BLE001 - telemetry must never block provider traffic
            logger.warning("ChatGPT binding telemetry append failed", exc_info=True)
            return False

    @staticmethod
    def _write(path: Path, binding: ChatGPTSessionBinding) -> None:
        tmp = path.with_suffix(".json.tmp")
        data = json.dumps(asdict(binding), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def get_or_create(
        self, *, session_id: str, project_ref: str
    ) -> ChatGPTSessionBinding:
        existing = self.load(session_id)
        if existing is not None:
            if existing.project_ref != project_ref:
                raise BrowserSurfaceLeaseError(
                    "ChatGPT session binding Project identity mismatch"
                )
            return existing
        return self.save(
            ChatGPTSessionBinding.new(
                lfl_session_id=session_id,
                project_ref=project_ref,
            )
        )

    def rollover(
        self,
        binding: ChatGPTSessionBinding,
        *,
        reason: str,
    ) -> ChatGPTSessionBinding:
        binding.verify()
        updated = replace(
            binding,
            conversation_id=None,
            conversation_url=None,
            segment_seq=binding.segment_seq + 1,
            segment_request_count=0,
            segment_request_chars=0,
            updated_at=_now(),
        )
        updated.verify()
        with self._lock(binding.lfl_session_id) as directory:
            if binding.conversation_id and binding.conversation_url:
                normalized_reason = str(reason or "rollover").strip() or "rollover"
                history = {
                    "segment_seq": binding.segment_seq,
                    "conversation_id": binding.conversation_id,
                    "conversation_url": binding.conversation_url,
                    "request_count": binding.segment_request_count,
                    "request_chars": binding.segment_request_chars,
                    "closed_at": updated.updated_at,
                    "reason": normalized_reason,
                }
                history_path = directory / self.HISTORY
                with history_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(history, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                self._try_append_event_locked(
                    directory,
                    {
                        "schema": self.EVENT_SCHEMA,
                        "ts": updated.updated_at,
                        "event": "segment_rollover",
                        "session_id": binding.lfl_session_id,
                        "segment_seq": binding.segment_seq,
                        "conversation_id": binding.conversation_id,
                        "reason": normalized_reason,
                        "request_count": binding.segment_request_count,
                        "request_chars": binding.segment_request_chars,
                    },
                )
            self._write(directory / self.FILE, updated)
        return updated

    def record_exchange(
        self,
        binding: ChatGPTSessionBinding,
        *,
        conversation_id: str,
        conversation_url: str,
        request_chars: int,
    ) -> ChatGPTSessionBinding:
        binding.verify()
        updated = replace(
            binding,
            conversation_id=str(conversation_id).strip(),
            conversation_url=str(conversation_url).strip(),
            segment_request_count=binding.segment_request_count + 1,
            segment_request_chars=binding.segment_request_chars + max(0, int(request_chars)),
            total_request_count=binding.total_request_count + 1,
            updated_at=_now(),
        )
        updated.verify()
        with self._lock(binding.lfl_session_id) as directory:
            self._write(directory / self.FILE, updated)
            self._try_append_event_locked(
                directory,
                {
                    "schema": self.EVENT_SCHEMA,
                    "ts": updated.updated_at,
                    "event": "exchange_committed",
                    "session_id": updated.lfl_session_id,
                    "segment_seq": updated.segment_seq,
                    "conversation_id": updated.conversation_id,
                    "request_chars": max(0, int(request_chars)),
                    "segment_request_count": updated.segment_request_count,
                    "segment_request_chars": updated.segment_request_chars,
                    "total_request_count": updated.total_request_count,
                },
            )
        return updated


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
        if not contexts:
            raise BrowserSurfaceLeaseError("ChatGPT browser has no context")
        # Playwright over CDP reports the default browsing context first.
        # Ownership is the leased target id, not context cardinality: the old
        # exactly-one-context rule silently broke whenever the user opened an
        # incognito window in the daily browser (an extra context).  Extra
        # contexts must not block owned-page recreation; always create in the
        # default context.
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

    def _load_recoverable_lease(self) -> BrowserSurfaceLease | None:
        """Load the durable lease, treating an unreadable/corrupt one as absent.

        The configured Project identity is the durable authority; the lease
        file is a recoverable cache of target/conversation routing state.
        Disk damage, manual edits, or format drift must not permanently poison
        the surface: report, discard, and let ``open()`` recreate the owned
        page plus a fresh lease through the no-lease path.  A *readable* lease
        that names a different Project stays fail-closed (config drift needs
        human eyes, not silent overwrite).
        """
        if not self.lease_store.exists():
            return None
        try:
            lease = self.lease_store.load()
        except BrowserSurfaceLeaseError as exc:
            logger.warning(
                "chatgpt-web surface: surface lease unreadable (%s); "
                "recreating owned page from configured project root",
                exc,
            )
            return None
        if lease.project_ref != self.project_ref or lease.project_url != self.project_url:
            raise BrowserSurfaceLeaseError("surface lease Project identity mismatch")
        return lease

    def open(self) -> Any:
        self._pw = self._start_playwright()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self.endpoint)
            lease = self._load_recoverable_lease()
            if lease is not None:
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
                    except Exception as exc:
                        is_closed = getattr(page, "is_closed", None)
                        if not (callable(is_closed) and is_closed()):
                            raise
                        # The leased tab can be closed between _find_target and the
                        # route restore (Playwright then raises TargetClosedError),
                        # or while waiting for its execution context.  A dead owned
                        # target is equivalent to a missing one: recover through the
                        # owned-page recreation path below instead of failing open().
                        logger.warning(
                            "chatgpt-web surface: leased target closed during route "
                            "restore (%s); recreating owned page",
                            type(exc).__name__,
                        )
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

    def restore_conversation(
        self,
        *,
        conversation_id: str,
        conversation_url: str,
    ) -> BrowserSurfaceLease:
        """Navigate the exact owned tab back to one persisted session segment.

        This changes only the physical transport route.  It does not grant the
        outer ChatGPT thread any context authority; the next request still sends
        the complete LFL-composed snapshot.
        """
        if self.lease is None or self.page is None:
            raise BrowserSurfaceLeaseError("surface is not open")
        conversation_id = str(conversation_id).strip()
        conversation_url = str(conversation_url).strip()
        if not conversation_id or not conversation_url:
            raise BrowserSurfaceLeaseError("conversation restore requires id and url")
        expected = _conversation_url(self.project_url, conversation_id)
        if conversation_url != expected:
            raise BrowserSurfaceLeaseError(
                "session binding conversation URL is outside the configured Project"
            )
        current_url = str(getattr(self.page, "url", "") or "")
        if current_url != expected:
            self.page.goto(expected, wait_until="commit", timeout=15_000)
        self._wait_for_page_context(self.page, expected_url=expected)
        self.lease = self.lease_store.update(
            conversation_id=conversation_id,
            conversation_url=expected,
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

        # ChatGPT occasionally commits the Project-root navigation while the
        # page is still tearing down/recreating its execution context.  A
        # single 10s readiness window can therefore fail even though the exact
        # leased target is healthy and becomes usable moments later.  Retry the
        # *same exact target* once with a larger bounded window.  Never select a
        # different same-URL tab, never relax Project identity, and never clear
        # the durable conversation lease until the Project root is confirmed.
        last_error: BrowserSurfaceLeaseError | None = None
        for attempt, readiness_timeout_s in enumerate((10.0, 20.0)):
            current_url = str(getattr(self.page, "url", "") or "")
            if current_url != self.project_url:
                self.page.goto(self.project_url, wait_until="commit", timeout=15_000)
            try:
                self._wait_for_page_context(
                    self.page,
                    expected_url=self.project_url,
                    timeout_s=readiness_timeout_s,
                )
                last_error = None
                break
            except BrowserSurfaceLeaseError as exc:
                last_error = exc
                is_closed = getattr(self.page, "is_closed", None)
                if callable(is_closed) and is_closed():
                    raise
                if attempt == 0:
                    self.page.wait_for_timeout(250)
                    continue
        if last_error is not None:
            raise BrowserSurfaceLeaseError(
                "owned ChatGPT page did not reach a stable execution context after "
                f"bounded same-target retry: {last_error}"
            ) from last_error
        self.lease = self.lease_store.update(
            conversation_id=None,
            conversation_url=None,
        )
        return self.lease

    def snapshot_identity(self) -> BrowserSurfaceLease:
        if self.lease is None:
            raise BrowserSurfaceLeaseError("surface is not open")
        return self.lease

    def reopen_dead_page(self) -> Any:
        """Replace a runtime-dead owned page handle without dropping the lease.

        When the leased tab is closed while the surface is already open (the
        user closes the tab, or the browser drops the target), the in-memory
        page handle is dead but the durable lease still names the old target.
        ``close()`` only clears in-memory state, so a fresh ``open()`` will not
        find the dead target and recreates the owned page through the lease
        recovery path.  A live page handle is returned untouched.
        """
        page = self.page
        is_closed = getattr(page, "is_closed", None)
        if page is not None and callable(is_closed) and not is_closed():
            return page
        logger.warning(
            "chatgpt-web surface: owned page handle is dead; reopening surface"
        )
        self.close()
        return self.open()

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
