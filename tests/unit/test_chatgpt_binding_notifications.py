from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from llm_loop.runtime.chatgpt_binding_notifications import (
    ChatGPTBindingAlertNotifier,
)


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def _health(*alerts: dict) -> dict:
    status = "healthy"
    if alerts:
        status = (
            "critical"
            if any(row.get("severity") == "critical" for row in alerts)
            else "warning"
        )
    return {"status": status, "alerts": list(alerts)}


def test_notifier_pushes_only_warning_and_critical(tmp_path):
    sent: list[tuple[str, str]] = []
    def probe():
        return {
            "status": "warning",
            "alerts": [
                {"code": "info_only", "severity": "info"},
                {"code": "warn_one", "severity": "warning", "count": 1},
                {"code": "crit_one", "severity": "critical", "count": 2},
            ],
        }
    notifier = ChatGPTBindingAlertNotifier(
        tmp_path,
        probe,
        notify_fn=lambda title, body: sent.append((title, body)) or True,
    )

    result = notifier.tick_once()

    assert result["notified"] == 2
    assert len(sent) == 2
    assert all("info_only" not in body for _title, body in sent)
    assert any("WARNING" in title and "warn_one" in body for title, body in sent)
    assert any("CRITICAL" in title and "crit_one" in body for title, body in sent)


def test_notifier_dedupes_across_restart_and_repeats_after_cooldown(tmp_path):
    clock = _Clock()
    sent: list[tuple[str, str]] = []
    alert = {"code": "restore_failures_recent", "severity": "warning", "count": 1}
    def probe():
        return _health(alert)

    first = ChatGPTBindingAlertNotifier(
        tmp_path,
        probe,
        notify_fn=lambda title, body: sent.append((title, body)) or True,
        repeat_s=3600,
        now_fn=clock.now,
    )
    assert first.tick_once()["notified"] == 1

    restarted = ChatGPTBindingAlertNotifier(
        tmp_path,
        probe,
        notify_fn=lambda title, body: sent.append((title, body)) or True,
        repeat_s=3600,
        now_fn=clock.now,
    )
    clock.advance(120)
    assert restarted.tick_once()["notified"] == 0
    assert len(sent) == 1

    clock.advance(3600)
    assert restarted.tick_once()["notified"] == 1
    assert len(sent) == 2


def test_notifier_escalation_bypasses_repeat_cooldown(tmp_path):
    clock = _Clock()
    sent: list[tuple[str, str]] = []
    health = _health(
        {"code": "restore_failures_recent", "severity": "warning", "count": 1}
    )
    notifier = ChatGPTBindingAlertNotifier(
        tmp_path,
        lambda: health,
        notify_fn=lambda title, body: sent.append((title, body)) or True,
        repeat_s=3600,
        now_fn=clock.now,
    )

    assert notifier.tick_once()["notified"] == 1
    clock.advance(10)
    health.clear()
    health.update(
        _health(
            {
                "code": "restore_failures_recent",
                "severity": "critical",
                "count": 3,
            }
        )
    )
    assert notifier.tick_once()["notified"] == 1
    assert len(sent) == 2
    assert "WARNING" in sent[0][0]
    assert "CRITICAL" in sent[1][0]


def test_notifier_delivery_failure_retries_on_shorter_retry_window(tmp_path):
    clock = _Clock()
    attempts: list[tuple[str, str]] = []
    def probe():
        return _health(
            {"code": "segment_pressure", "severity": "warning", "count": 1}
        )
    notifier = ChatGPTBindingAlertNotifier(
        tmp_path,
        probe,
        notify_fn=lambda title, body: attempts.append((title, body)) or False,
        repeat_s=3600,
        retry_s=300,
        now_fn=clock.now,
    )

    first = notifier.tick_once()
    assert first["delivery_failed"] == 1
    clock.advance(60)
    assert notifier.tick_once()["delivery_failed"] == 0
    assert len(attempts) == 1
    clock.advance(300)
    assert notifier.tick_once()["delivery_failed"] == 1
    assert len(attempts) == 2


def test_notifier_resolution_is_audited_but_not_pushed(tmp_path):
    clock = _Clock()
    sent: list[tuple[str, str]] = []
    health = _health(
        {"code": "segment_pressure", "severity": "warning", "count": 1}
    )
    notifier = ChatGPTBindingAlertNotifier(
        tmp_path,
        lambda: health,
        notify_fn=lambda title, body: sent.append((title, body)) or True,
        now_fn=clock.now,
    )
    assert notifier.tick_once()["notified"] == 1

    clock.advance(30)
    health.clear()
    health.update(_health())
    result = notifier.tick_once()

    assert result["notified"] == 0
    assert result["active"] == 0
    assert len(sent) == 1
    snapshot = notifier.snapshot()
    assert snapshot["last_event"]["event"] == "alert_resolved"
    assert snapshot["state"]["active"] == {}


def test_notifier_probe_failure_is_audited_without_push(tmp_path):
    sent: list[tuple[str, str]] = []

    def broken_probe():
        raise RuntimeError("health unavailable")

    notifier = ChatGPTBindingAlertNotifier(
        tmp_path,
        broken_probe,
        notify_fn=lambda title, body: sent.append((title, body)) or True,
    )
    result = notifier.tick_once()

    assert result["status"] == "probe_failed"
    assert sent == []
    lines = (
        notifier.root / "notifications.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[-1])
    assert event["event"] == "health_probe_failed"
    assert event["error_type"] == "RuntimeError"
