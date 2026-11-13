"""M2-2 runtime→feishu 架构边偿还：kernel 侧补偿记录读取器测试.

覆盖（对照父侧任务要求）：
- reader 零写副作用（不创建/不修改任何文件，含两源均缺失场景）；
- JSONL 五字段严格校验 + 取值合法性（原 Feishu dataclass 校验的 kernel 侧
  等价复刻：receive_id 非空 / reply_type 枚举 / cause 枚举）；
- legacy 单文件兼容（默认 chat_id/CRASH；缺 reply_id / interrupted_at、
  非法 reply_type → 整体 fail-closed）；
- JSONL 与 legacy 双源叠加；
- Feishu 层包装等价（read_only_compensation_records 返回原 dataclass 且
  字段与 kernel DTO 一致）；
- reader 模块自身零 llm_loop 依赖（kernel import guard 的定向防回归）。
"""

from __future__ import annotations

import ast
import json
from dataclasses import fields as dataclass_fields
from pathlib import Path

import pytest

from llm_loop.feishu.compensation import (
    InterruptionCompensationRecord,
    read_only_compensation_records,
)
from llm_loop.runtime.feishu_compensation_reader import (
    CompensationRecordData,
    read_compensation_records,
)

_GOOD_JSONL = {
    "receive_id": "oc_a",
    "reply_type": "chat_id",
    "interrupt_cause": "crash",
    "interrupted_at": "2026-11-13T10:09:21+08:00",
    "context_ref": "ctx-1",
    "msg_id": "om_1",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离 env 路径配置（reader 经 os.environ 读默认路径）."""
    monkeypatch.delenv("FEISHU_COMPENSATION_PATH", raising=False)
    monkeypatch.delenv("FEISHU_INTERRUPTED_PATH", raising=False)


def _write_jsonl(root: Path, records: list[dict]) -> Path:
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "feishu_compensation.jsonl"
    path.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in records) + "\n", encoding="utf-8"
    )
    return path


def _write_legacy(root: Path, payload: dict) -> Path:
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "feishu_interrupted.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _snapshot_tree(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_reader_module_imports_confined_to_kernel() -> None:
    """reader 的 llm_loop 依赖只能指向 kernel 内部 root（runtime→feishu 防回归）.

    对齐 test_arch_guards 的 _KERNEL_INTERNAL_ROOTS（含 resolver 依赖，R9
    env-access ratchet 修订：env 经 legacy_env_snapshot 正门读取）。
    """
    import llm_loop.runtime.feishu_compensation_reader as reader_mod

    kernel_roots = {"core", "loop", "event_log", "resources", "runtime", "llm"}
    tree = ast.parse(Path(reader_mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root == "llm_loop":
                assert node.module.split(".")[1] in kernel_roots, (
                    f"reader 不得依赖 kernel 外模块: {node.module}"
                )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "llm_loop", alias.name


def test_zero_write_side_effects_with_both_sources(tmp_path: Path) -> None:
    """读取双源记录后，目录树（文件集合/mtime/size）完全不变."""
    _write_jsonl(tmp_path, [_GOOD_JSONL])
    _write_legacy(
        tmp_path,
        {"reply_id": "oc_b", "interrupted_at": "2026-11-13T10:00:00+08:00", "msg_id": "om_9"},
    )
    before = _snapshot_tree(tmp_path)
    records = read_compensation_records(tmp_path)
    assert records is not None and len(records) == 2
    assert _snapshot_tree(tmp_path) == before


def test_missing_files_returns_empty_and_creates_nothing(tmp_path: Path) -> None:
    """两源均缺失：返回 []（而非 None），且绝不创建任何文件.

    注：tmp_path/data 由全局 autouse fixture ``isolated_data_dir`` 预建（测试
    沙箱防线）；此处断言 reader 只读——目录树快照不变、不新增任何文件。
    """
    before = _snapshot_tree(tmp_path)
    assert read_compensation_records(tmp_path) == []
    assert _snapshot_tree(tmp_path) == before
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def _bad_jsonl_variants() -> list[tuple[str, dict]]:
    base = dict(_GOOD_JSONL)
    variants: list[tuple[str, dict]] = []
    # M2-2 P1-B：五个字段缺失或非字符串 → 整体 fail-closed
    for key in ("receive_id", "reply_type", "interrupt_cause", "interrupted_at", "msg_id"):
        missing = {k: v for k, v in base.items() if k != key}
        variants.append((f"{key}_missing", missing))
        wrong = dict(base)
        wrong[key] = 123
        variants.append((f"{key}_non_str", wrong))
    # 取值合法性（原 dataclass 校验的 kernel 侧复刻）
    variants.append(("interrupted_at_empty", {**base, "interrupted_at": ""}))
    variants.append(("receive_id_empty", {**base, "receive_id": ""}))
    variants.append(("reply_type_invalid", {**base, "reply_type": "group"}))
    variants.append(("cause_invalid", {**base, "interrupt_cause": "oops"}))
    return variants


@pytest.mark.parametrize(
    "name,record",
    _bad_jsonl_variants(),
    ids=[n for n, _ in _bad_jsonl_variants()],
)
def test_jsonl_strict_validation_fail_closed(tmp_path: Path, name: str, record: dict) -> None:
    _write_jsonl(tmp_path, [record])
    assert read_compensation_records(tmp_path) is None, name


def test_valid_jsonl_parsed_exact(tmp_path: Path) -> None:
    second = {
        **_GOOD_JSONL,
        "receive_id": "ou_b",
        "reply_type": "open_id",
        "interrupt_cause": "queue_full",
        "interrupted_at": "2026-11-13T10:11:00+08:00",
        "context_ref": "",
        "msg_id": "",
    }
    _write_jsonl(tmp_path, [_GOOD_JSONL, second])
    records = read_compensation_records(tmp_path)
    assert records is not None
    assert all(isinstance(r, CompensationRecordData) for r in records)
    assert [
        (
            r.receive_id,
            r.reply_type,
            r.interrupt_cause,
            r.interrupted_at,
            r.context_ref,
            r.msg_id,
        )
        for r in records
    ] == [
        ("oc_a", "chat_id", "crash", "2026-11-13T10:09:21+08:00", "ctx-1", "om_1"),
        ("ou_b", "open_id", "queue_full", "2026-11-13T10:11:00+08:00", "", ""),
    ]


def test_context_ref_non_str_coerced_to_empty(tmp_path: Path) -> None:
    """context_ref 非 str 归 ""（既有解析语义；其余字段缺 str 仍整体拒绝）."""
    _write_jsonl(tmp_path, [{**_GOOD_JSONL, "context_ref": 123}])
    records = read_compensation_records(tmp_path)
    assert records is not None and records[0].context_ref == ""


def test_corrupt_json_line_fail_closed(tmp_path: Path) -> None:
    """单行损坏 = 整体 None（不跳过隔离：目标 msg_id 可能恰在损坏行中）."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)  # autouse fixture 已预建 data/
    (data_dir / "feishu_compensation.jsonl").write_text(
        json.dumps(_GOOD_JSONL, ensure_ascii=False) + "\n{broken\n", encoding="utf-8"
    )
    assert read_compensation_records(tmp_path) is None


def test_legacy_defaults_and_dual_source_merge(tmp_path: Path) -> None:
    """legacy 默认 chat_id/CRASH；与 JSONL 双源叠加（非互斥回退）."""
    _write_jsonl(tmp_path, [_GOOD_JSONL])
    _write_legacy(
        tmp_path,
        {"reply_id": "oc_b", "interrupted_at": "2026-11-13T10:00:00+08:00", "msg_id": "om_9"},
    )
    records = read_compensation_records(tmp_path)
    assert records is not None and len(records) == 2
    legacy_rec = records[1]
    assert (
        legacy_rec.receive_id,
        legacy_rec.reply_type,
        legacy_rec.interrupt_cause,
        legacy_rec.interrupted_at,
        legacy_rec.msg_id,
    ) == ("oc_b", "chat_id", "crash", "2026-11-13T10:00:00+08:00", "om_9")


def test_legacy_reply_type_open_id_preserved(tmp_path: Path) -> None:
    _write_legacy(
        tmp_path,
        {
            "reply_id": "ou_x",
            "reply_type": "open_id",
            "interrupted_at": "2026-11-13T10:00:00+08:00",
        },
    )
    records = read_compensation_records(tmp_path)
    assert records is not None and records[0].reply_type == "open_id"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"interrupted_at": "2026-11-13T10:00:00+08:00"}, id="missing_reply_id"),
        pytest.param(
            {
                "reply_id": "oc_b",
                "reply_type": "group",
                "interrupted_at": "2026-11-13T10:00:00+08:00",
            },
            id="invalid_reply_type",
        ),
        pytest.param({"reply_id": "oc_b"}, id="missing_interrupted_at"),
    ],
)
def test_legacy_fail_closed(tmp_path: Path, payload: dict) -> None:
    """legacy 缺 reply_id / 缺 interrupted_at / 非法 reply_type → 整体 None."""
    _write_legacy(tmp_path, payload)
    assert read_compensation_records(tmp_path) is None


def test_relative_path_without_runtime_root_returns_none(tmp_path: Path) -> None:
    """相对路径 + runtime_root=None → None（fail-closed，不得回退解析到 cwd）.

    cwd 已由 autouse ``isolated_data_dir`` 锁进 tmp_path（沙箱防线）；断言
    解析失败不落任何文件。
    """
    before = _snapshot_tree(tmp_path)
    assert read_compensation_records(None) is None
    assert _snapshot_tree(tmp_path) == before
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_env_absolute_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """绝对路径 env 配置不受 runtime_root 影响（既有语义）."""
    alt = tmp_path / "alt_comp.jsonl"
    alt.write_text(json.dumps(_GOOD_JSONL, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setenv("FEISHU_COMPENSATION_PATH", str(alt))
    records = read_compensation_records(tmp_path / "nonexistent-root")
    assert records is not None and records[0].msg_id == "om_1"


def test_feishu_wrapper_equivalence(tmp_path: Path) -> None:
    """capability 层包装：read_only_compensation_records 返回原 dataclass，
    字段与 kernel DTO 逐一相等（公共 API/行为保持不变）."""
    _write_jsonl(tmp_path, [_GOOD_JSONL])
    _write_legacy(
        tmp_path,
        {"reply_id": "oc_b", "interrupted_at": "2026-11-13T10:00:00+08:00", "msg_id": "om_9"},
    )
    kernel_records = read_compensation_records(tmp_path)
    feishu_records = read_only_compensation_records(tmp_path)
    assert kernel_records is not None and feishu_records is not None
    assert all(isinstance(r, InterruptionCompensationRecord) for r in feishu_records)
    field_names = [f.name for f in dataclass_fields(CompensationRecordData)]
    for dto, rec in zip(kernel_records, feishu_records, strict=True):
        for name in field_names:
            assert getattr(dto, name) == getattr(rec, name), name


def test_feishu_wrapper_none_passthrough(tmp_path: Path) -> None:
    """kernel 侧 fail-closed None → capability 包装层透传 None."""
    _write_jsonl(tmp_path, [{**_GOOD_JSONL, "reply_type": "group"}])
    assert read_only_compensation_records(tmp_path) is None


def test_feishu_wrapper_fail_closed_if_dataclass_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9 审查修订回归锁：包装构造期任何 ValueError → 整体 None（fail-closed）.

    与下沉前原实现结构等价——原版 dataclass 构造在 try/except 内；若
    dataclass ``__post_init__`` 未来新增校验（如 msg_id↔cause 组合），包装层
    仍 fail-closed，绝不向 service_control 逃逸未捕获异常。
    """
    _write_jsonl(tmp_path, [_GOOD_JSONL])

    def _future_validation(self: InterruptionCompensationRecord) -> None:
        raise ValueError("dataclass 未来新增校验")

    monkeypatch.setattr(InterruptionCompensationRecord, "__post_init__", _future_validation)
    assert read_only_compensation_records(tmp_path) is None
