"""反向守卫（2026-09-09 回归收口）：per-round K-fold 渐进折叠已退役。

d03c913（align context/recovery/tool authority boundaries）退役了
EVO-20260824-54d46549 的 progressive_fold 实验，替换为 provider 标记 +
连续最老段投影（cache_archive_provider 标记防重复归档，语义见
src/llm_loop/core/history.py 归档路径注释）。移植链若带回带
progressive_fold/cache_archive_budget 旧语义的测试（如
test_progressive_fold.py），应删除而非接线——本守卫固化该裁决。
"""

from __future__ import annotations

import inspect

from llm_loop.core.history import build_history_messages


def test_progressive_fold_kwarg_is_retired() -> None:
    sig = inspect.signature(build_history_messages)
    assert "progressive_fold" not in sig.parameters, (
        "progressive_fold 已于 d03c913 退役（per-round K-fold 实验），"
        "不应重新接线；现行中段压缩走 cache_archive_provider 标记投影。"
    )


def test_progressive_fold_experiment_test_file_not_reintroduced() -> None:
    from pathlib import Path

    tests_dir = Path(__file__).resolve().parent
    assert not (tests_dir / "test_progressive_fold.py").exists(), (
        "test_progressive_fold.py 是 CR-R1 移植残留（期望已退役语义），已于"
        " 2026-09-09 回归收口时删除，勿再回灌。"
    )
