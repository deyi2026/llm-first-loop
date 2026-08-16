"""路径 K 依赖图测试（tasks.md §6.1 验收）."""

from __future__ import annotations

import time
from pathlib import Path

from llm_loop.task_quality.dep_graph import DepGraph


def _mk_project(tmp_path: Path) -> Path:
    """迷你项目: src/calc.py ← tests/test_calc.py + src/util.py."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "calc.py").write_text(
        "import util\n\ndef add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "src" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "import calc\n\ndef test_add():\n    assert calc.add(1, 2) == 3\n",
        encoding="utf-8")
    return root


def test_build_nodes_edges(tmp_path):
    """首次构建: 节点/边数与 import 关系一致."""
    root = _mk_project(tmp_path)
    g = DepGraph(src_root=root)
    assert g.build() is True
    # 3 个 py 文件（calc/util/test_calc）→ 3 节点
    assert g.node_count() == 3
    # calc → util（1 边）；test_calc → calc（1 边）
    assert g.edge_count() >= 2


def test_affected_tests_reverse_lookup(tmp_path):
    """affected_tests: 修改 src/calc.py → 返回 tests/test_calc.py."""
    root = _mk_project(tmp_path)
    g = DepGraph(src_root=root)
    g.build()
    tests, available = g.affected_tests([str(root / "src" / "calc.py")])
    assert available is True
    assert any("test_calc.py" in t for t in tests)


def test_affected_tests_not_built(tmp_path):
    """依赖图未构建: ([], False) → 调用方回退全量."""
    root = _mk_project(tmp_path)
    g = DepGraph(src_root=root)
    tests, available = g.affected_tests([str(root / "src" / "calc.py")])
    assert available is False
    assert tests == []


def test_incremental_update(tmp_path):
    """增量更新: 新增文件后 affected 反映新依赖."""
    root = _mk_project(tmp_path)
    g = DepGraph(src_root=root)
    g.build()
    # 新增 src/newmod.py 并被 test_calc 导入 → 增量更新
    (root / "src" / "newmod.py").write_text("def new():\n    return 2\n", encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(
        "import calc, newmod\n\ndef test_add():\n    assert calc.add(1, 2) == 3\n",
        encoding="utf-8")
    assert g.incremental_update([str(root / "tests" / "test_calc.py")]) is True
    tests, available = g.affected_tests([str(root / "src" / "newmod.py")])
    assert available is True
    assert any("test_calc.py" in t for t in tests)


def test_build_readonly(tmp_path):
    """构建只读: 不修改任何源文件."""
    root = _mk_project(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*.py")}
    g = DepGraph(src_root=root)
    g.build()
    after = {p: p.read_bytes() for p in root.rglob("*.py")}
    assert before == after


def test_cache_persist_load(tmp_path):
    """缓存落盘 + 加载: 重启后恢复（损坏重建）."""
    root = _mk_project(tmp_path)
    cache = tmp_path / "dep_cache.json"
    g1 = DepGraph(src_root=root, cache_path=cache)
    g1.build()
    assert cache.exists()
    g2 = DepGraph(src_root=root, cache_path=cache)
    assert g2.load_cache() is True
    assert g2.node_count() == 3
    # 损坏缓存 → load 失败
    cache.write_text("{broken json", encoding="utf-8")
    g3 = DepGraph(src_root=root, cache_path=cache)
    assert g3.load_cache() is False


def test_build_latency(tmp_path):
    """首次构建时延 ≤ 60s（小项目秒级）."""
    root = _mk_project(tmp_path)
    g = DepGraph(src_root=root)
    start = time.perf_counter()
    g.build()
    assert time.perf_counter() - start < 60


def test_thread_safety(tmp_path):
    """线程安全: 并发查询不崩."""
    import threading

    root = _mk_project(tmp_path)
    g = DepGraph(src_root=root)
    g.build()
    errors = []
    def _query():
        try:
            for _ in range(10):
                g.affected_tests([str(root / "src" / "calc.py")])
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=_query) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
