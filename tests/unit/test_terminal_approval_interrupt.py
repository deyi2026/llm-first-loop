"""R18 approval interruption and single-settlement lifecycle tests."""
from __future__ import annotations

import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from llm_loop.terminal.approval import ApprovalBridge


def _tty(monkeypatch) -> None:
    monkeypatch.setattr("llm_loop.terminal.approval.sys.stdin",
                        SimpleNamespace(isatty=lambda: True))
    # The fake stdin has no real terminal descriptor; UI choice is stubbed.
    monkeypatch.setattr("llm_loop.terminal.approval.saved_terminal", nullcontext)


def test_r18_closed_or_noninteractive_never_approves(monkeypatch) -> None:
    bridge = ApprovalBridge()
    assert bridge("tool", "secret arguments") is False
    _tty(monkeypatch)
    bridge.close()
    assert bridge("tool", "secret arguments") is False
    assert bridge.pending.empty()


def test_r18_pending_worker_approval_is_serviced_only_once(monkeypatch) -> None:
    _tty(monkeypatch)
    bridge = ApprovalBridge()
    requested = threading.Event()
    decisions = []
    examined = []

    def ask(item):
        examined.append((item.tool, item.arguments))
        return True

    monkeypatch.setattr(bridge, "_ask", ask)

    def worker():
        requested.set()
        decisions.append(bridge("exec", "path=exact"))

    thread = threading.Thread(target=worker)
    thread.start()
    assert requested.wait(1)
    bridge.service()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert decisions == [True]
    assert examined == [("exec", "path=exact")]
    bridge.service()  # no second approval or side effect
    assert examined == [("exec", "path=exact")]
    bridge.close()


def test_r18_shutdown_denies_queued_worker_without_prompt(monkeypatch) -> None:
    _tty(monkeypatch)
    bridge = ApprovalBridge()
    called = []
    monkeypatch.setattr(bridge, "_ask", lambda item: called.append(item) or True)
    result = []
    thread = threading.Thread(target=lambda: result.append(bridge("exec", "X")))
    thread.start()
    item = bridge.pending.get(timeout=1)
    bridge.pending.put(item)  # preserve a queued request for close()
    bridge.close()
    thread.join(timeout=2)
    assert result == [False]
    assert not called
    assert item.ready.is_set()


def test_r18_late_yes_after_close_must_not_authorize(monkeypatch) -> None:
    _tty(monkeypatch)
    bridge = ApprovalBridge()
    entered = threading.Event()
    finish = threading.Event()

    def delayed_yes(_item):
        entered.set()
        assert finish.wait(2)
        return True

    monkeypatch.setattr(bridge, "_ask", delayed_yes)
    results = []
    worker = threading.Thread(target=lambda: results.append(bridge("shell", "dangerous")))
    worker.start()
    item = bridge.pending.get(timeout=1)
    bridge.pending.put(item)

    def close_when_asking():
        assert entered.wait(2)
        bridge.close()
        finish.set()

    closer = threading.Thread(target=close_when_asking)
    closer.start()
    bridge.service()
    closer.join(timeout=2)
    worker.join(timeout=2)
    assert not closer.is_alive() and not worker.is_alive()
    assert results == [False]
    assert item.accepted is False


@pytest.mark.parametrize("answer", ["", "no", "N", "later"])
def test_r18_no_enter_or_ambiguous_word_defaults_to_deny(monkeypatch, answer) -> None:
    import prompt_toolkit

    _tty(monkeypatch)
    monkeypatch.setattr(prompt_toolkit, "prompt", lambda *_a, **_kw: answer)
    assert ApprovalBridge()("tool", "scope") is False


@pytest.mark.parametrize("exception", [EOFError, KeyboardInterrupt])
def test_r18_approval_interrupt_denies_and_marks_current_turn(monkeypatch, exception) -> None:
    import prompt_toolkit

    _tty(monkeypatch)
    def interrupt(*_args, **_kwargs):
        raise exception
    monkeypatch.setattr(prompt_toolkit, "prompt", interrupt)
    bridge = ApprovalBridge()
    interrupted = threading.Event()
    bridge.interrupt = interrupted
    assert bridge("tool", "scope") is False
    assert interrupted.is_set()
