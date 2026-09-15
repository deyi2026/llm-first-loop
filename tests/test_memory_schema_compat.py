"""Memory index schema compatibility and fail-closed regression tests."""

import json
from typing import Any

import pytest

from llm_loop.memory.store import MemoryEntry, MemorySchemaMismatchError, MemoryStore


def _entry(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "MEM-TEST-0001",
        "type": "fact",
        "content": "hello",
    }
    base.update(extra)
    return base


def test_old_format_without_field_loads_with_default():
    e = MemoryEntry(**_entry())
    assert e.observation_history == []


def test_new_format_with_field_loads():
    oh = [{"disposition": "late_observation_not_promoted", "content": "x"}]
    e = MemoryEntry(**_entry(observation_history=oh))
    assert e.observation_history == oh


def test_nonempty_observation_history_roundtrip(tmp_path):
    oh = [{"disposition": "late_observation_not_promoted", "content": "old fact"}]
    store = MemoryStore(tmp_path)
    store.save_entry(MemoryEntry(**_entry(id="MEM-RT-1", observation_history=oh)))
    store2 = MemoryStore(tmp_path)
    got = [e for e in store2.all() if e.id == "MEM-RT-1"]
    assert len(got) == 1
    assert got[0].observation_history == oh


def test_cross_process_merge_preserves_disk_entry_with_field(tmp_path):
    oh = [{"disposition": "late_observation_not_promoted", "content": "m"}]
    MemoryStore(tmp_path).save_entry(
        MemoryEntry(**_entry(id="MEM-A", observation_history=oh))
    )
    s2 = MemoryStore(tmp_path)
    s2.save_entry(MemoryEntry(**_entry(id="MEM-B", content="another fact")))
    s3 = MemoryStore(tmp_path)
    a = [e for e in s3.all() if e.id == "MEM-A"]
    assert a and a[0].observation_history == oh
    assert {e.id for e in s3.all()} >= {"MEM-A", "MEM-B"}


def test_unknown_field_fail_closed_not_corrupt(tmp_path):
    idx = tmp_path / "index.json"
    idx.write_text(
        json.dumps(
            [
                {
                    "id": "X1",
                    "type": "fact",
                    "content": "c",
                    "future_field": [{"a": 1}],
                }
            ]
        ),
        encoding="utf-8",
    )
    before = idx.read_bytes()
    store = MemoryStore(tmp_path)
    assert idx.read_bytes() == before
    assert not (tmp_path / "index.corrupt.json").exists()
    assert store.all() == []
    with pytest.raises(MemorySchemaMismatchError):
        store.save_entry(MemoryEntry(id="X2", type="fact", content="never written"))
    assert idx.read_bytes() == before


def test_broken_json_still_corruption_path(tmp_path):
    idx = tmp_path / "index.json"
    idx.write_text("{ not json", encoding="utf-8")
    store = MemoryStore(tmp_path)
    assert (tmp_path / "index.corrupt.json").exists()
    assert store.all() == []
    store.save_entry(MemoryEntry(id="N1", type="fact", content="recovered"))
    assert {e.id for e in MemoryStore(tmp_path).all()} == {"N1"}


def test_runtime_disk_schema_upgrade_locks_old_writer(tmp_path):
    MemoryStore(tmp_path).save_entry(MemoryEntry(id="A1", type="fact", content="a"))
    s_old = MemoryStore(tmp_path)
    idx = tmp_path / "index.json"
    data = json.loads(idx.read_text(encoding="utf-8"))
    data[0]["future_field"] = [{"v": 2}]
    idx.write_text(json.dumps(data), encoding="utf-8")
    before = idx.read_bytes()
    with pytest.raises(MemorySchemaMismatchError):
        s_old.save_entry(MemoryEntry(id="A2", type="fact", content="must not overwrite"))
    assert idx.read_bytes() == before
