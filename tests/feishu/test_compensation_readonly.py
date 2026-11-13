"""M2-2: read_only_compensation_records 纯只读语义与 fail-closed 测试.

安全边界（spec M2-2 边界 4）：service_control 空闲判定只能零写副作用读取——
绝不能走 CompensationStore.read_all 的 _ensure_migrated（迁移会改写 JSONL 并
删除 legacy 单文件）。本文件验证：不创建/不删除/不改写任何文件；读取/解析
失败一律返回 None（fail-closed），绝不把"读不了"当作"无补偿"。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from llm_loop.feishu.compensation import (
    CompensationStore,
    read_only_compensation_records,
)

GOOD_RECORDS = [
    {
        "receive_id": "oc_a",
        "reply_type": "chat_id",
        "interrupt_cause": "crash",
        "interrupted_at": "2026-11-13T10:09:21+08:00",
        "context_ref": "",
        "msg_id": "om_1",
    },
    {
        "receive_id": "ou_b",
        "reply_type": "open_id",
        "interrupt_cause": "process_timeout",
        "interrupted_at": "2026-11-13T10:15:00+08:00",
        "msg_id": "om_2",
    },
]

LEGACY_DATA = {
    "reply_id": "oc_legacy",
    "reply_type": "chat_id",
    "interrupted_at": "2026-11-13T09:00:00+08:00",
    "msg_id": "om_legacy",
}


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEISHU_COMPENSATION_PATH", raising=False)
    monkeypatch.delenv("FEISHU_INTERRUPTED_PATH", raising=False)


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_missing_files_returns_empty_and_creates_nothing(tmp_path: Path) -> None:
    # conftest 的 isolated_data_dir 会预建 tmp_path/data；断言口径 = 调用前后
    # 目录树零变化（helper 连一个文件都不新建）。
    before = _snapshot_tree(tmp_path)
    records = read_only_compensation_records(tmp_path)
    assert records == []
    assert _snapshot_tree(tmp_path) == before


def test_parses_jsonl_and_legacy_with_zero_side_effects(tmp_path: Path) -> None:
    jsonl = tmp_path / "data" / "feishu_compensation.jsonl"
    legacy = tmp_path / "data" / "feishu_interrupted.json"
    _write_jsonl(jsonl, GOOD_RECORDS)
    legacy.write_text(json.dumps(LEGACY_DATA), encoding="utf-8")
    before = _snapshot_tree(tmp_path)

    records = read_only_compensation_records(tmp_path)
    assert records is not None

    # 零字节级改动：不迁移、不删除、不改写 legacy 单文件或 JSONL
    assert _snapshot_tree(tmp_path) == before
    assert [(r.msg_id, r.interrupt_cause) for r in records] == [
        ("om_1", "crash"),
        ("om_2", "process_timeout"),
        ("om_legacy", "crash"),
    ]
    assert records[2].receive_id == "oc_legacy"


def test_store_still_migrates_when_explicitly_used(tmp_path: Path) -> None:
    """对照组：显式 CompensationStore.read_all 才做迁移（helper 绝不做）."""
    jsonl = tmp_path / "data" / "feishu_compensation.jsonl"
    legacy = tmp_path / "data" / "feishu_interrupted.json"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text("", encoding="utf-8")
    legacy.write_text(json.dumps(LEGACY_DATA), encoding="utf-8")

    read_only_compensation_records(tmp_path)
    assert legacy.exists()  # helper 不迁移

    CompensationStore(jsonl, legacy_path=legacy).read_all()
    assert not legacy.exists()  # store 迁移并删除 legacy
    assert jsonl.read_text(encoding="utf-8").strip()


def test_env_relative_path_resolved_against_runtime_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alt = tmp_path / "alt" / "c.jsonl"
    _write_jsonl(alt, GOOD_RECORDS[:1])
    monkeypatch.setenv("FEISHU_COMPENSATION_PATH", "alt/c.jsonl")
    assert [r.msg_id for r in (read_only_compensation_records(tmp_path) or [])] == ["om_1"]

    abs_legacy = tmp_path / "legacy2.json"
    abs_legacy.write_text(json.dumps(LEGACY_DATA), encoding="utf-8")
    monkeypatch.setenv("FEISHU_INTERRUPTED_PATH", str(abs_legacy))
    records = read_only_compensation_records(tmp_path)
    assert [r.msg_id for r in (records or [])] == ["om_1", "om_legacy"]


def test_relative_path_without_runtime_root_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEISHU_COMPENSATION_PATH", "data/feishu_compensation.jsonl")
    assert read_only_compensation_records(None) is None


def test_absolute_jsonl_and_missing_absolute_legacy(tmp_path: Path, monkeypatch) -> None:
    alt = tmp_path / "alt" / "c.jsonl"
    _write_jsonl(alt, GOOD_RECORDS[:1])
    monkeypatch.setenv("FEISHU_COMPENSATION_PATH", str(alt))
    monkeypatch.setenv("FEISHU_INTERRUPTED_PATH", str(tmp_path / "no-such-legacy.json"))
    assert [r.msg_id for r in (read_only_compensation_records(None) or [])] == ["om_1"]


def test_fail_closed_on_corrupted_jsonl_line(tmp_path: Path) -> None:
    jsonl = tmp_path / "data" / "feishu_compensation.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text('{"receive_id": "oc_a"\n', encoding="utf-8")
    assert read_only_compensation_records(tmp_path) is None


def test_fail_closed_on_missing_interrupted_at(tmp_path: Path) -> None:
    bad = dict(GOOD_RECORDS[0])
    bad.pop("interrupted_at")
    _write_jsonl(tmp_path / "data" / "feishu_compensation.jsonl", [GOOD_RECORDS[1], bad])
    # 不允许构造器自动补时点：存储侧缺时点 = 记录无效 = 整体失败
    assert read_only_compensation_records(tmp_path) is None


def test_fail_closed_on_invalid_record_fields(tmp_path: Path) -> None:
    bad = dict(GOOD_RECORDS[0])
    bad["receive_id"] = ""
    _write_jsonl(tmp_path / "data" / "feishu_compensation.jsonl", [bad])
    assert read_only_compensation_records(tmp_path) is None


def test_fail_closed_on_jsonl_being_a_directory(tmp_path: Path) -> None:
    path = tmp_path / "data" / "feishu_compensation.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    assert read_only_compensation_records(tmp_path) is None


def test_fail_closed_on_unreadable_file(tmp_path: Path) -> None:
    jsonl = tmp_path / "data" / "feishu_compensation.jsonl"
    _write_jsonl(jsonl, GOOD_RECORDS)
    os.chmod(jsonl, 0o000)
    try:
        result = read_only_compensation_records(tmp_path)
        if result is not None:
            pytest.skip("运行环境以特权身份读文件（root），权限失败关闭不可模拟")
        assert result is None
    finally:
        os.chmod(jsonl, 0o644)


def test_fail_closed_on_corrupted_legacy(tmp_path: Path) -> None:
    jsonl = tmp_path / "data" / "feishu_compensation.jsonl"
    _write_jsonl(jsonl, GOOD_RECORDS)
    legacy = tmp_path / "data" / "feishu_interrupted.json"
    legacy.write_text("{not json", encoding="utf-8")
    assert read_only_compensation_records(tmp_path) is None


def test_fail_closed_on_legacy_missing_interrupted_at(tmp_path: Path) -> None:
    jsonl = tmp_path / "data" / "feishu_compensation.jsonl"
    _write_jsonl(jsonl, GOOD_RECORDS)
    bad_legacy = dict(LEGACY_DATA)
    bad_legacy.pop("interrupted_at")
    legacy = tmp_path / "data" / "feishu_interrupted.json"
    legacy.write_text(json.dumps(bad_legacy), encoding="utf-8")
    assert read_only_compensation_records(tmp_path) is None


# --- M2-2 复检 P1-B：JSONL 必填字段显式存在且为字符串，缺失不得默认补全 ---------


@pytest.mark.parametrize(
    "missing_field",
    [
        "receive_id",
        "reply_type",
        "interrupt_cause",
        "interrupted_at",
        "msg_id",
    ],
)
def test_fail_closed_on_missing_required_field(tmp_path: Path, missing_field: str) -> None:
    """M2-2 P1-B：五个必填字段任一缺失（不得默认 chat_id/CRASH/空串）→ 整体 None."""
    records = [dict(GOOD_RECORDS[0])]
    records[0].pop(missing_field)
    _write_jsonl(tmp_path / "data" / "feishu_compensation.jsonl", records)
    assert read_only_compensation_records(tmp_path) is None


@pytest.mark.parametrize(
    "field,bad_value",
    [("reply_type", 123), ("interrupt_cause", None), ("msg_id", 456), ("receive_id", [])],
    ids=["reply-type-int", "cause-null", "msg-id-int", "receive-id-list"],
)
def test_fail_closed_on_non_string_required_field(
    tmp_path: Path, field: str, bad_value: object
) -> None:
    """必填字段非字符串类型 → 整体 None（fail-closed）."""
    records: list[dict[str, object]] = [dict(GOOD_RECORDS[0])]
    records[0][field] = bad_value
    _write_jsonl(tmp_path / "data" / "feishu_compensation.jsonl", records)
    assert read_only_compensation_records(tmp_path) is None


def test_fail_closed_on_empty_interrupted_at(tmp_path: Path) -> None:
    """interrupted_at 显式空串 → None（构造器会自动补 now，读侧必须拒绝）."""
    records = [dict(GOOD_RECORDS[0], interrupted_at="")]
    _write_jsonl(tmp_path / "data" / "feishu_compensation.jsonl", records)
    assert read_only_compensation_records(tmp_path) is None


def test_msg_id_empty_string_allowed_for_crash(tmp_path: Path) -> None:
    """msg_id 可为空字符串（dataclass 语义：无 msg_id 打断必须是 CRASH）."""
    records = [dict(GOOD_RECORDS[0], msg_id="")]
    _write_jsonl(tmp_path / "data" / "feishu_compensation.jsonl", records)
    parsed = read_only_compensation_records(tmp_path)
    assert parsed is not None
    assert parsed[0].msg_id == ""


def test_context_ref_optional_and_non_string_coerced(tmp_path: Path) -> None:
    """context_ref 可选：缺失/非字符串都按缺省处理，不影响记录有效性."""
    no_ctx = [dict(GOOD_RECORDS[0])]
    no_ctx[0].pop("context_ref")
    null_ctx = [dict(GOOD_RECORDS[0], context_ref=None)]
    for records in (no_ctx, null_ctx):
        _write_jsonl(tmp_path / "data" / "feishu_compensation.jsonl", records)
        parsed = read_only_compensation_records(tmp_path)
        assert parsed is not None
        assert parsed[0].context_ref == ""


def test_writer_reader_roundtrip(tmp_path: Path) -> None:
    """写侧 to_dict() 全字段输出必须能被严格读侧读回（写读契约一致）."""
    from llm_loop.feishu.compensation import (
        CRASH,
        CompensationStore,
        InterruptionCompensationRecord,
        _now_iso,
    )

    record = InterruptionCompensationRecord(
        receive_id="oc_roundtrip",
        reply_type="chat_id",
        interrupt_cause=CRASH,
        interrupted_at=_now_iso(),
        context_ref="ctx://v1/test",
        msg_id="om_roundtrip",
    )
    jsonl = tmp_path / "data" / "feishu_compensation.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    store = CompensationStore(jsonl, legacy_path=tmp_path / "data" / "feishu_interrupted.json")
    store.append(record)
    parsed = read_only_compensation_records(tmp_path)
    assert parsed is not None
    assert len(parsed) == 1
    assert parsed[0] == record
