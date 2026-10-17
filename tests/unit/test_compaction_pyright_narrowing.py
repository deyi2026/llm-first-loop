"""Compaction type narrowing must preserve existing runtime semantics."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.loop.engine_services import compaction_gate as gate


def _entry(role: str, text: str, sequence: object) -> dict:
    return {
        "role": role,
        "msg_seq": sequence,
        "chars": len(text),
        "original": text,
    }


def test_manifest_seq_range_uses_only_integer_sequences(tmp_path: Path) -> None:
    entries = [
        _entry("assistant", "first", 9),
        _entry("tool", "missing", None),
        _entry("tool", "str", "11"),
        _entry("tool", "float", 3.5),
        _entry("assistant", "last", 4),
    ]
    result = gate.write_compaction_manifest(str(tmp_path), "seq-mixed", entries)
    assert result is not None
    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert saved["seq_range"] == [4, 9]


def test_manifest_seq_range_none_when_no_integer(tmp_path: Path) -> None:
    entries = [_entry("tool", "no seq", None), _entry("tool", "str", "4")]
    result = gate.write_compaction_manifest(str(tmp_path), "seq-none", entries)
    assert result is not None
    saved = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert saved["seq_range"] is None


def test_receipt_field_matching_ignores_nonmatches_and_missing_fields() -> None:
    ref = "a" * 64
    fields = (
        "1. 任务目标：完成设计评审\n"
        "2. 下一步：更新文档\n"
        "3. 未决负结果：无\n"
        "4. 关键数字出处：report\n"
        "5. 交付物位置：output\n"
    )
    header = "[压缩恢复回执]\nmanifest_ref=" + ref + "\ngoal_ref=GOAL-1\n"
    valid = SimpleNamespace(role="assistant", content="prefix 1. 任务目标：伪造\n" + header + fields + "junk\n")
    result = gate.evaluate_confirmation([valid], 0, ref, "compaction_snapshots/seq")
    assert result["receipt_valid"] is True
    assert result["confirmed"] is False  # A matching recovery tool is still required.
    missing = SimpleNamespace(role="assistant", content=header + fields.replace("4. 关键数字出处：report\n", ""))
    assert gate.evaluate_confirmation([missing], 0, ref, "compaction_snapshots/seq")["receipt_valid"] is False
