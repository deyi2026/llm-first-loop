"""Durable notification outlet for ChatGPT binding warning/critical alerts.

Observational only: the outlet never mutates Sessions, bindings, routing, rollover,
or GC state. macOS delivery is best-effort/fail-open, while durable state keeps
restart dedupe and cooldown semantics stable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from llm_loop.notify import notify as system_notify

logger = logging.getLogger(__name__)

STATE_SCHEMA = "lfl.chatgpt_binding_notification_state.v1"
AUDIT_SCHEMA = "lfl.chatgpt_binding_notification_event.v1"
DEFAULT_TICK_S = 30.0
DEFAULT_REPEAT_S = 3600.0
DEFAULT_RETRY_S = 300.0
_AUDIT_MAX_BYTES = 1_000_000
_AUDIT_TAIL_LINES = 2_000
_SEVERITY_RANK = {"warning": 1, "critical": 2}


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _alert_fingerprint(alert: Mapping[str, Any]) -> str:
    session_ids = alert.get("session_ids")
    normalized_sessions = (
        sorted(str(item) for item in session_ids)
        if isinstance(session_ids, list)
        else []
    )
    payload = {
        "code": str(alert.get("code") or "binding_alert"),
        "session_ids": normalized_sessions,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _notification_text(alert: Mapping[str, Any]) -> tuple[str, str]:
    severity = str(alert.get("severity") or "warning").lower()
    code = str(alert.get("code") or "binding_alert")
    count = alert.get("count")
    suffix = f" · count={count}" if isinstance(count, int) else ""
    title = f"LFL ChatGPT Binding {severity.upper()}"
    body = f"{code}{suffix} · 打开 LFL Web → 会话绑定 查看详情"
    return title, body


class ChatGPTBindingAlertNotifier:
    """Poll binding health and push only warning/critical alerts."""

    def __init__(
        self,
        data_dir: str | Path,
        health_probe: Callable[[], Mapping[str, Any]],
        *,
        notify_fn: Callable[[str, str], bool] = system_notify,
        tick_s: float = DEFAULT_TICK_S,
        repeat_s: float = DEFAULT_REPEAT_S,
        retry_s: float = DEFAULT_RETRY_S,
        now_fn: Callable[[], datetime] = _now,
    ) -> None:
        self._root = (
            Path(data_dir).expanduser().resolve()
            / "runtime"
            / "chatgpt-binding-alerts"
        )
        self._state_path = self._root / "state.json"
        self._audit_path = self._root / "notifications.jsonl"
        self._health_probe = health_probe
        self._notify_fn = notify_fn
        self._tick_s = max(1.0, float(tick_s))
        self._repeat = timedelta(seconds=max(1.0, float(repeat_s)))
        self._retry = timedelta(seconds=max(1.0, float(retry_s)))
        self._now_fn = now_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="chatgpt-binding-alert-notifier",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=min(5.0, self._tick_s + 1.0))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001 - notification outlet must self-heal
                logger.exception("ChatGPT binding notification tick failed")
            if self._stop.wait(self._tick_s):
                return

    def tick_once(self) -> dict[str, Any]:
        now = self._now_fn().astimezone(UTC)
        try:
            health = dict(self._health_probe())
        except Exception as exc:  # noqa: BLE001 - delivery layer never changes runtime health
            self._append_audit(
                {
                    "schema": AUDIT_SCHEMA,
                    "ts": _iso(now),
                    "event": "health_probe_failed",
                    "error_type": type(exc).__name__,
                }
            )
            return {
                "status": "probe_failed",
                "notified": 0,
                "delivery_failed": 0,
                "active": 0,
            }

        current: dict[str, Mapping[str, Any]] = {}
        for alert in health.get("alerts") or []:
            if not isinstance(alert, Mapping):
                continue
            severity = str(alert.get("severity") or "").lower()
            if severity not in _SEVERITY_RANK:
                continue
            current[_alert_fingerprint(alert)] = alert

        with self._lock:
            return self._apply_current(current, health=health, now=now)

    def _apply_current(
        self,
        current: dict[str, Mapping[str, Any]],
        *,
        health: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        state = self._load_state()
        active = dict(state.get("active") or {})
        notified = 0
        failed = 0

        for fingerprint, alert in current.items():
            severity = str(alert.get("severity") or "warning").lower()
            previous = active.get(fingerprint)
            should_notify = self._should_notify(
                previous,
                severity=severity,
                now=now,
            )
            entry: dict[str, Any] = {
                "code": str(alert.get("code") or "binding_alert"),
                "severity": severity,
                "last_seen_at": _iso(now),
                "last_attempt_at": (
                    str(previous.get("last_attempt_at") or "")
                    if isinstance(previous, dict)
                    else ""
                ),
                "last_success_at": (
                    str(previous.get("last_success_at") or "")
                    if isinstance(previous, dict)
                    else ""
                ),
            }
            if isinstance(alert.get("session_ids"), list):
                entry["session_ids"] = sorted(
                    str(item) for item in alert["session_ids"]
                )
            if isinstance(alert.get("count"), int):
                entry["count"] = int(alert["count"])

            if should_notify:
                delivery_ok = self._deliver(alert)
                entry["last_attempt_at"] = _iso(now)
                if delivery_ok:
                    entry["last_success_at"] = _iso(now)
                    notified += 1
                else:
                    failed += 1
                self._append_audit(
                    {
                        "schema": AUDIT_SCHEMA,
                        "ts": _iso(now),
                        "event": (
                            "notification_delivered"
                            if delivery_ok
                            else "notification_delivery_failed"
                        ),
                        "fingerprint": fingerprint,
                        "code": entry["code"],
                        "severity": severity,
                        "count": entry.get("count"),
                        "delivery": "macos_system_notification",
                    }
                )
            active[fingerprint] = entry

        for fingerprint in sorted(set(active) - set(current)):
            previous = active.pop(fingerprint)
            self._append_audit(
                {
                    "schema": AUDIT_SCHEMA,
                    "ts": _iso(now),
                    "event": "alert_resolved",
                    "fingerprint": fingerprint,
                    "code": previous.get("code"),
                    "severity": previous.get("severity"),
                }
            )

        next_state = {
            "schema": STATE_SCHEMA,
            "updated_at": _iso(now),
            "health_status": str(health.get("status") or "unknown"),
            "active": active,
        }
        if (
            state.get("health_status") != next_state["health_status"]
            or state.get("active") != active
        ):
            self._write_state(next_state)
        return {
            "status": "ok",
            "health_status": next_state["health_status"],
            "notified": notified,
            "delivery_failed": failed,
            "active": len(active),
        }

    def _deliver(self, alert: Mapping[str, Any]) -> bool:
        title, body = _notification_text(alert)
        try:
            return bool(self._notify_fn(title, body))
        except Exception:  # noqa: BLE001 - system outlet must fail-open
            logger.warning("ChatGPT binding system notification failed", exc_info=True)
            return False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._load_state()
            last_event = None
            if self._audit_path.is_file():
                try:
                    lines = [
                        line
                        for line in self._audit_path.read_text(
                            encoding="utf-8"
                        ).splitlines()
                        if line.strip()
                    ]
                    if lines:
                        value = json.loads(lines[-1])
                        if isinstance(value, dict):
                            last_event = value
                except (OSError, json.JSONDecodeError):
                    last_event = {"event": "audit_unreadable"}
            return {
                "schema": STATE_SCHEMA,
                "delivery": "macos_system_notification",
                "status": "running",
                "push_severities": ["warning", "critical"],
                "repeat_seconds": int(self._repeat.total_seconds()),
                "retry_seconds": int(self._retry.total_seconds()),
                "state": state,
                "last_event": last_event,
            }

    def _should_notify(
        self,
        previous: object,
        *,
        severity: str,
        now: datetime,
    ) -> bool:
        if not isinstance(previous, dict):
            return True
        previous_severity = str(previous.get("severity") or "")
        if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(
            previous_severity, 0
        ):
            return True
        last_success = _parse_ts(previous.get("last_success_at"))
        if last_success is not None:
            return now - last_success >= self._repeat
        last_attempt = _parse_ts(previous.get("last_attempt_at"))
        if last_attempt is not None:
            return now - last_attempt >= self._retry
        return True

    def _load_state(self) -> dict[str, Any]:
        if not self._state_path.is_file():
            return {"schema": STATE_SCHEMA, "active": {}}
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("ChatGPT binding notification state unreadable; reset dedupe")
            return {"schema": STATE_SCHEMA, "active": {}}
        if not isinstance(value, dict):
            return {"schema": STATE_SCHEMA, "active": {}}
        if not isinstance(value.get("active"), dict):
            value["active"] = {}
        return value

    def _write_state(self, value: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self._state_path)
        dir_fd = os.open(self._root, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _append_audit(self, value: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        with self._audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            size = self._audit_path.stat().st_size
        except OSError:
            return
        if size <= _AUDIT_MAX_BYTES:
            return
        try:
            lines = self._audit_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        tail = lines[-_AUDIT_TAIL_LINES:]
        tmp = self._audit_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            if tail:
                handle.write("\n".join(tail) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self._audit_path)
