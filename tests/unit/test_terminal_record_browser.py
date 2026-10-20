"""R16: no guessing of stored diffs, monotonic read-only paging/navigation."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.terminal.editor import Composer
from llm_loop.terminal.records import RecordBrowser, stored_diff
from llm_loop.terminal.settings import UISettings
from llm_loop.terminal.shell import _dispatch_local, _record_command


def _raw() -> dict:
    return {
        "session_id": "sid",
        "messages": [
            {"role": "user", "content": "first request"},
            {"role": "tool", "content": "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"},
            {"role": "assistant", "content": "\n".join(f"第{i:03}行" for i in range(101)) + "\n"},
            {"role": "assistant", "content": "late answer"},
        ],
    }


def test_r16_record_browser_navigates_indexes_and_searches_without_writes() -> None:
    raw = _raw()
    before = repr(raw)
    cursor = RecordBrowser(page_size=12)
    assert "late answer" in cursor.navigate(raw, [])
    assert cursor.index == 3
    assert "第000行" in cursor.navigate(raw, ["prev"])
    assert "lines 1-12/101" in cursor.navigate(raw, [])
    assert "lines 13-24/101" in cursor.navigate(raw, ["page"])
    assert "lines 25-36/101" in cursor.navigate(raw, ["page"])
    assert "lines 13-24/101" in cursor.navigate(raw, ["back"])
    assert "message 2/4" in cursor.navigate(raw, ["search", "diff", "--git"])
    assert cursor.mode == "content" and cursor.offset == 0
    assert "message 1/4" in cursor.navigate(raw, ["goto", "0"])
    assert "message 1/4" in cursor.navigate(raw, ["prev"])
    assert repr(raw) == before


def test_r16_paging_reaches_last_line_once_and_clamps_without_repeating_first() -> None:
    raw = _raw()
    cursor = RecordBrowser(index=2, page_size=16)
    observed = []
    while True:
        text = cursor.navigate(raw, ["show"] if not observed else ["page"])
        page = text.split("\n", 1)[1].split("\n[next page:", 1)[0]
        observed.extend([line for line in page.splitlines() if line.startswith("第")])
        if "next page:" not in text:
            break
    assert observed == [f"第{i:03}行" for i in range(101)]
    assert cursor.offset == 96
    assert "第100行" in cursor.navigate(raw, ["page"])
    assert cursor.offset == 96


def test_r16_stored_diff_requires_actual_recorded_diff_and_no_fabrication() -> None:
    raw = _raw()
    text = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
    assert stored_diff(raw) == text
    assert stored_diff(raw, 1) == text
    assert stored_diff({"messages": [{"content": "edited 2 lines"}]}).startswith("No persisted diff")
    explicit = {"messages": [{"content": "summary", "metadata": {"diff": "EXACT\nRAW"}}]}
    assert stored_diff(explicit) == "EXACT\nRAW"
    with pytest.raises(ValueError, match="outside"):
        stored_diff(raw, 99)


def test_r16_invalid_navigation_does_not_change_cursor_or_send_a_run() -> None:
    raw = _raw()
    cursor = RecordBrowser(index=2)
    with pytest.raises(ValueError, match="index"):
        cursor.navigate(raw, ["goto", "99"])
    with pytest.raises(ValueError, match="search"):
        cursor.navigate(raw, ["search"])
    assert cursor.index == 2
    assert "cursor unchanged" in cursor.navigate(raw, ["search", "absent phrase"])
    assert cursor.index == 2


def test_r16_browser_is_session_scoped_in_composer_and_shell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    composer = Composer(UISettings(), tmp_path)
    raw = _raw()
    a = SimpleNamespace(session_id="alpha", to_dict=lambda: raw)
    b = SimpleNamespace(session_id="beta", to_dict=lambda: raw)
    assert _dispatch_local(object(), a, "/browse", ["goto", "0"], composer)
    assert "message 1/4" in capsys.readouterr().out
    assert _dispatch_local(object(), b, "/browse", [], composer)
    assert "message 4/4" in capsys.readouterr().out
    assert composer.record_views["alpha"].index == 0
    assert composer.record_views["beta"].index == 3
    _record_command(raw, "/diff", ["1"])
    assert "diff --git a/x b/x" in capsys.readouterr().out
    assert composer.draft == ""


def test_r16_paging_large_record_is_read_only_and_linear() -> None:
    content = "\n".join(f"row{i:05}" for i in range(10_000))
    cursor = RecordBrowser(page_size=100)
    raw = {"messages": [{"role": "tool", "content": content}]}
    text = cursor.navigate(raw, [])
    assert "row00000" in text and "row00100" not in text
    for _ in range(99):
        text = cursor.navigate(raw, ["page"])
    assert "row09999" in text
    assert cursor.offset == 9900
    assert raw["messages"][0]["content"] == content
