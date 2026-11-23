"""Exact-sequence history hydration must not replay a long event log."""

from pathlib import Path

from llm_loop.event_log.model import Event, serialize_event
from llm_loop.event_log.store import EventStore


def _event(seq: int, *, session_id: str = "s1", text: str = "ok") -> Event:
    return Event(
        event_id=f"event-{session_id}-{seq}-{text}",
        session_id=session_id,
        seq=seq,
        type="program.final",
        ts="2026-11-23T00:00:00+00:00",
        payload={"full_text": text},
    )


def test_exact_lookup_skips_full_replay_and_only_decodes_tail(tmp_path: Path, monkeypatch) -> None:
    store = EventStore(tmp_path / "events")
    sid = "s1"
    root = tmp_path / "events"
    root.mkdir()
    target = _event(4001, text="最新结论")
    rows = [serialize_event(_event(i, text="noise")) for i in range(1, 4001)]
    rows.append(serialize_event(target))
    (root / f"{sid}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    parsed: list[str] = []
    original = store._parse_line  # pyright: ignore[reportPrivateUsage]

    def record(line: str):
        parsed.append(line)
        return original(line)

    monkeypatch.setattr(store, "_parse_line", record)
    monkeypatch.setattr(store, "read", lambda _sid: (_ for _ in ()).throw(AssertionError("full read")))
    monkeypatch.setattr(store, "read_cached", lambda _sid: (_ for _ in ()).throw(AssertionError("cache replay")))
    found = store.read_seqs(sid, {4001})
    assert found == {4001: target}
    assert len(parsed) == 1


def test_exact_lookup_across_segments_with_corruption_and_duplicate(tmp_path: Path) -> None:
    root = tmp_path / "events"
    segments = root / "s1"
    segments.mkdir(parents=True)
    first = [_event(1, text="older"), _event(2, text="first")]
    (segments / "1.jsonl").write_text(
        "\n".join(serialize_event(ev) for ev in first) + "\n", encoding="utf-8"
    )
    newer = [_event(2, text="newest"), _event(3, text="latest")]
    with (segments / "2.jsonl").open("wb") as stream:
        stream.write(b"bad json\n\xff\n")
        for ev in newer:
            stream.write((serialize_event(ev) + "\n").encode("utf-8"))
    store = EventStore(root)
    assert store.read_seqs("s1", {1, 2, 3, 999}) == {
        1: first[0], 2: newer[0], 3: newer[1]
    }


def test_exact_lookup_does_not_create_files_or_accept_other_session(tmp_path: Path) -> None:
    root = tmp_path / "events"
    store = EventStore(root)
    assert store.read_seqs("../bad", {1}) == {}
    assert store.read_seqs("missing", {1}) == {}
    assert not root.exists()
    root.mkdir()
    (root / "s1.jsonl").write_text(serialize_event(_event(1, session_id="s2")) + "\n")
    assert store.read_seqs("s1", {1}) == {}
    assert store.read_seqs("s1", {0, -1, True}) == {}


def test_exact_lookup_disabled_is_read_only(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events", enabled=False)
    assert store.read_seqs("s1", {1}) == {}
    assert not (tmp_path / "events").exists()


def test_numeric_segment_order_picks_latest_duplicate(tmp_path: Path) -> None:
    root = tmp_path / "events"
    segments = root / "s1"
    segments.mkdir(parents=True)
    for name, event in [
        ("1.jsonl", _event(1)),
        ("2.jsonl", _event(2, text="old")),
        ("10.jsonl", _event(2, text="new")),
    ]:
        (segments / name).write_text(serialize_event(event) + "\n")
    assert EventStore(root).read_seqs("s1", {1, 2}) == {
        1: _event(1), 2: _event(2, text="new")
    }


def test_reverse_reader_aborts_short_read_without_partial_event(tmp_path: Path) -> None:
    path = tmp_path / "truncated.jsonl"
    path.write_text(serialize_event(_event(1)) + "\n")

    class ShortRead:
        def __init__(self, stream):
            self.stream = stream

        def fileno(self):
            return self.stream.fileno()

        def seek(self, pos):
            return self.stream.seek(pos)

        def read(self, size):
            return self.stream.read(size)[:-1]

    with path.open("rb") as stream:
        assert list(EventStore._reverse_event_lines(ShortRead(stream))) == []  # pyright: ignore[reportPrivateUsage]


def test_exact_lookup_does_not_follow_event_file_symlinks(tmp_path: Path) -> None:
    import os

    if not hasattr(os, "O_NOFOLLOW"):
        return  # Windows fallback is not the supported production host here.
    root = tmp_path / "events"
    root.mkdir()
    outside = tmp_path / "private.jsonl"
    outside.write_text(serialize_event(_event(1, text="private")) + "\n")
    (root / "s1.jsonl").symlink_to(outside)
    assert EventStore(root).read_seqs("s1", {1}) == {}
