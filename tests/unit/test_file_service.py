"""P2-A shared file core extraction.

This stage locks the existing edit_file byte semantics before any provider-visible
snapshot/version parameters are added.
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.workspace.file_service import FileService, FileServiceError


def test_legacy_edit_core_applies_and_verifies_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"hello world\nfoo bar\n")

    result = FileService().edit(
        path=path,
        old_string="foo bar",
        new_string="baz qux",
    )

    assert result.applied is True
    assert result.match_count == 1
    assert result.added_lines == 1
    assert result.removed_lines == 1
    assert result.actual_after_bytes == b"hello world\nbaz qux\n"
    assert path.read_bytes() == result.actual_after_bytes


def test_legacy_edit_core_preserves_crlf_and_bom(tmp_path: Path) -> None:
    path = tmp_path / "win.txt"
    path.write_bytes(b"\xef\xbb\xbfline one\r\nline two\r\n")

    result = FileService().edit(
        path=path,
        old_string="line two",
        new_string="LINE TWO",
    )

    assert result.had_bom is True
    assert result.line_ending == "\r\n"
    assert path.read_bytes() == b"\xef\xbb\xbfline one\r\nLINE TWO\r\n"


def test_legacy_edit_core_dry_run_does_not_mutate(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    before = b"old line\n"
    path.write_bytes(before)

    result = FileService().edit(
        path=path,
        old_string="old line",
        new_string="new line",
        dry_run=True,
    )

    assert result.applied is False
    assert result.dry_run is True
    assert result.expected_after_bytes == b"new line\n"
    assert result.actual_after_bytes is None
    assert path.read_bytes() == before


def test_legacy_edit_core_rejects_baseline_change_before_mutation(tmp_path: Path) -> None:
    path = tmp_path / "race.txt"
    path.write_bytes(b"original\n")
    calls = {"n": 0}

    def racing_baseline(target: Path) -> tuple[int, int]:
        calls["n"] += 1
        if calls["n"] == 2:
            target.write_bytes(b"externally modified\n")
        st = target.stat()
        return st.st_mtime_ns, st.st_size

    try:
        FileService(baseline_reader=racing_baseline).edit(
            path=path,
            old_string="original",
            new_string="mine",
        )
    except FileServiceError as exc:
        assert exc.error_type == "BaselineChanged"
    else:  # pragma: no cover - protects the fail-closed contract
        raise AssertionError("baseline race was not rejected")

    assert path.read_bytes() == b"externally modified\n"
