"""T08/T17: real running-turn browse, unread saved messages and opt-in UI."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from llm_loop.llm.client import StreamDelta
from llm_loop.terminal.editor import Composer
from llm_loop.terminal.presentation import Presenter
from llm_loop.terminal.records import RecordBrowser
from llm_loop.terminal.settings import UISettings


def _document() -> dict:
    return {
        "messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "-" * 340 + "\nnext line"},
        ]
    }


def test_new_saved_count_during_paused_browse_and_explicit_follow() -> None:
    raw = _document()
    view = RecordBrowser(index=0)
    assert "+0 new saved" in view.navigate(raw, ["show"])
    raw["messages"].append({"role": "tool", "content": "tool-result"})
    assert "+1 new saved" in view.navigate(raw, ["show"])
    assert view.index == 0  # still reading an older record
    raw["messages"].append({"role": "assistant", "content": "late new answer"})
    assert "+2 new saved" in view.navigate(raw, ["show"])
    assert "late new answer" in view.navigate(raw, ["latest"])
    assert view.new_messages == 0 and view.follow_latest
    raw["messages"].append({"role": "assistant", "content": "next answer"})
    assert "next answer" in view.navigate(raw, ["show"])
    assert view.new_messages == 0
    view.navigate(raw, ["follow"])
    raw["messages"].append({"role": "assistant", "content": "unread"})
    assert "+1 new saved" in view.navigate(raw, ["show"])


def test_horizontal_diff_navigation_and_existing_raw_retention() -> None:
    raw = {"messages": [{"role": "tool", "content": "diff --git a/a b/a\n" + "A" * 600}]}
    view = RecordBrowser(index=0, mode="diff", page_width=64)
    first = view.navigate(raw, [])
    assert "column 1" in first
    assert "diff --git" in first
    assert "column 65" in view.navigate(raw, ["right"])
    assert "column 129" in view.navigate(raw, ["right"])
    assert "column 65" in view.navigate(raw, ["left"])
    view.navigate(raw, ["left"])
    assert "diff --git" in view.navigate(raw, [])
    assert raw["messages"][0]["content"].endswith("A" * 600)


def test_clipping_never_joins_two_long_diff_lines() -> None:
    content = "diff --git " + "A" * 180 + "\n" + "B" * 180 + "\n"
    view = RecordBrowser(index=0, mode="diff", page_width=35)
    raw = {"messages": [{"role": "tool", "content": content}]}
    result = view.navigate(raw, ["right"])
    lines = result.splitlines()
    assert any(line.startswith("A" * 10) for line in lines)
    assert any(line.startswith("B" * 10) for line in lines)
    assert not any("A" in line and "B" in line for line in lines)


def test_preinput_local_record_controls_do_not_queue_a_model_turn(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(Composer, "supports_preinput", property(lambda _self: True))
    composer = Composer(UISettings(), tmp_path)
    composer.draft = "original local draft"
    calls = []
    raw = _document()
    composer.record_source = lambda sid: raw

    def read(sid, model):
        calls.append((sid, model))
        return "/browse goto 0" if len(calls) == 1 else "next intentional request"

    monkeypatch.setattr(composer, "read", read)
    assert composer.start_preinput("session-x", "glm/glm-5.3")
    assert composer.finish_preinput() == "next intentional request"
    assert calls == [("session-x", "glm/glm-5.3")] * 2
    assert "first" in capsys.readouterr().out
    assert composer.draft == "original local draft"
    assert composer.record_views["session-x"].index == 0


def test_presenter_live_counter_does_not_claim_new_saved_messages(tmp_path: Path) -> None:
    composer = Composer(UISettings(), tmp_path)
    composer.record_source = lambda sid: _document()
    composer.show_records("sid", ["show"])
    view = Presenter(plain=True)
    view.activity_hook = lambda: composer.note_stream_update("sid")
    for _ in range(50):
        view.delta(StreamDelta(text=""))
    assert composer._stream_updates["sid"] == 50
    assert composer.record_views["sid"].new_messages == 0
    assert "streaming updates" in composer._toolbar("sid", "glm", 120)


def test_snapshot_error_is_not_a_run_or_a_draft_loss(tmp_path: Path, capsys) -> None:
    composer = Composer(UISettings(), tmp_path)
    composer.draft = "protected"
    def broken(_sid):
        raise OSError("offline")
    composer.record_source = broken
    assert composer._consume_record_command("sid", "/browse")
    assert "record browse failed: OSError" in capsys.readouterr().out
    assert composer.draft == "protected"


def test_fullscreen_viewer_does_not_need_model_or_network(monkeypatch, tmp_path: Path) -> None:
    composer = Composer(UISettings(plain=True), tmp_path)
    composer.record_source = lambda _sid: _document()
    composer.draft = "kept"
    assert "full-screen unavailable" in composer.show_records("sid", ["full"])
    assert composer.draft == "kept"


def test_live_ten_thousand_updates_throttle_redraw_and_do_not_mutate_records(
    tmp_path: Path, monkeypatch,
) -> None:
    """T18: bounded UI work while source stream may be much faster than redraw."""
    composer = Composer(UISettings(), tmp_path)
    raw = _document()
    original = repr(raw)
    composer.record_source = lambda _: raw
    redraws = []
    composer._viewer_app = SimpleNamespace(invalidate=lambda: redraws.append(1))
    ticks = iter([1.0] * 10_000)
    monkeypatch.setattr("llm_loop.terminal.editor.time.monotonic", lambda: next(ticks))
    view = Presenter(plain=True)
    view.activity_hook = lambda: composer.note_stream_update("sid")
    for _ in range(10_000):
        view.delta(StreamDelta(text=""))
    assert composer._stream_updates["sid"] == 10_000
    assert len(redraws) == 1
    assert repr(raw) == original
