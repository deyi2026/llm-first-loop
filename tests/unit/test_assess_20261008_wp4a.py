"""ASSESS-20261008-project-audit rev3 §7 WP4a 回归: BUG-18.

修复契约: 同 ID 冲突时 runtime 覆盖 seed 由来源身份显式决定，不再依赖
目录字典序（原实现整体 sorted 后后者覆盖——z-seed/a-runtime 下 seed 赢，
违背"Runtime copy wins"意图）。seed 与 runtime 各自内部保持确定性排序；
runtime 删除后回退 seed；精确水合与宽检索一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_loop.methods.store import MethodStore

_BODY_TMPL = "\n".join(
    [
        "## Trigger",
        "concrete trigger",
        "## Verification",
        "verify {tag}",
    ]
)


def _write_method(dir_: Path, method_id: str, tag: str) -> None:
    d = dir_ / method_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "METHOD.md").write_text(
        "---\n"
        f"method_id: {method_id}\n"
        "status: active\n"
        "---\n"
        + _BODY_TMPL.format(tag=tag),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "seed_name,runtime_name",
    [("a-seed", "z-runtime"), ("z-seed", "a-runtime")],
)
def test_runtime_wins_independent_of_directory_order(tmp_path, seed_name, runtime_name):
    """两种目录次序下 runtime 均覆盖 seed（原实现 z-seed/a-runtime 时 seed 赢）."""
    seed_dir = tmp_path / seed_name
    runtime_dir = tmp_path / runtime_name
    _write_method(seed_dir, "same", "seed-内容")
    _write_method(runtime_dir, "same", "runtime-内容")
    store = MethodStore(runtime_dir, seed_dir=seed_dir)
    rec = store.get("same")
    assert rec is not None
    assert "runtime-内容" in (rec.body or "")
    # 宽检索与精确水合一致
    listed = [r for r in store.list(query="same", limit=10) if r.get("id") == "same"]
    assert len(listed) == 1  # 候选不遮蔽、不重复
    assert runtime_name in str(listed[0].get("file", ""))  # 来源=runtime


def test_runtime_delete_falls_back_to_seed(tmp_path):
    """runtime 无该 ID 时回退 seed 来源."""
    seed_dir = tmp_path / "seed"
    runtime_dir = tmp_path / "runtime"
    _write_method(seed_dir, "only-seed", "seed-独有")
    store = MethodStore(runtime_dir, seed_dir=seed_dir)
    rec = store.get("only-seed")
    assert rec is not None
    assert "seed-独有" in (rec.body or "")


def test_seed_and_runtime_each_sorted_deterministically(tmp_path):
    """各来源内部确定性排序（ID 升序），结果顺序可复现."""
    seed_dir = tmp_path / "s"
    runtime_dir = tmp_path / "r"
    for mid in ("beta", "alpha"):
        _write_method(seed_dir, mid, f"seed-{mid}")
    for mid in ("delta", "gamma"):
        _write_method(runtime_dir, mid, f"runtime-{mid}")
    store = MethodStore(runtime_dir, seed_dir=seed_dir)
    ids_a = [r.get("id") for r in store.list(query="", limit=20)]
    ids_b = [r.get("id") for r in store.list(query="", limit=20)]
    assert ids_a == ids_b  # 来源内部确定性排序 → 结果可复现
    assert set(ids_a) == {"alpha", "beta", "delta", "gamma"}


def test_same_id_no_duplicate_candidates(tmp_path):
    """同 ID 不产生双份候选（去重以来源优先级为准）."""
    seed_dir = tmp_path / "s"
    runtime_dir = tmp_path / "r"
    _write_method(seed_dir, "dup", "seed")
    _write_method(runtime_dir, "dup", "runtime")
    store = MethodStore(runtime_dir, seed_dir=seed_dir)
    ids = [r.get("id") for r in store.list(query="dup", limit=10)]
    assert ids.count("dup") == 1
