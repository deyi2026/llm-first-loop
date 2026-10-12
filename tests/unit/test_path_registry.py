"""EVO-20260823-12be9cac: Path Registry 测试（否定帧登记/查询/成功翻转/TTL/膨胀）."""

from __future__ import annotations

from llm_loop.tools import path_registry as pr


def _reset_and_run(monkeypatch, tmp_path):
    pr.reset()
    # 重定向登记表到 tmp_path（避免污染真实 data/）
    monkeypatch.setattr(pr, "_REGISTRY_PATH", None)

    def fake_registry_file():
        return tmp_path / "path_registry.json"

    monkeypatch.setattr(pr, "_registry_file", fake_registry_file)
    monkeypatch.setattr(pr, "_LOADED", None)
    monkeypatch.setattr(pr, "_LOADED_PATH", None)
    return pr


def test_register_missing_and_check(monkeypatch, tmp_path):
    pr_mod = _reset_and_run(monkeypatch, tmp_path)
    pr_mod.register_missing("/tmp/not_exist_a.py", source="tool:read_file")
    assert pr_mod.check_known_missing("/tmp/not_exist_a.py") is True
    assert pr_mod.check_known_missing("/tmp/other.py") is False  # 未登记
    # known_missing_note 命中
    note = pr_mod.known_missing_note("/tmp/not_exist_a.py")
    assert "已登记不存在" in note and "停止该路径搜索" in note
    # 未登记路径无提示
    assert pr_mod.known_missing_note("/tmp/other.py") == ""


def test_register_exists_flips_negative(monkeypatch, tmp_path):
    pr_mod = _reset_and_run(monkeypatch, tmp_path)
    pr_mod.register_missing("/tmp/flip.py")
    assert pr_mod.check_known_missing("/tmp/flip.py") is True
    pr_mod.register_exists("/tmp/flip.py")  # 创建/成功 → 否定帧失效
    assert pr_mod.check_known_missing("/tmp/flip.py") is False
    assert pr_mod.known_missing_note("/tmp/flip.py") == ""


def test_ttl_expiry_allows_recheck(monkeypatch, tmp_path):
    pr_mod = _reset_and_run(monkeypatch, tmp_path)
    pr_mod.register_missing("/tmp/ttl.py")
    assert pr_mod.check_known_missing("/tmp/ttl.py") is True
    # 模拟过期（expires_at 置过去）
    reg = pr_mod._load()
    reg["/tmp/ttl.py"]["expires_at"] = 0
    pr_mod._save()
    assert pr_mod.check_known_missing("/tmp/ttl.py") is False  # 过期 → 允许重新验证
    assert pr_mod.known_missing_note("/tmp/ttl.py") == ""


def test_cap_evicts_oldest(monkeypatch, tmp_path):
    pr_mod = _reset_and_run(monkeypatch, tmp_path)
    old_max = pr_mod._MAX_ENTRIES
    pr_mod._MAX_ENTRIES = 3
    try:
        for i in range(5):
            pr_mod.register_missing(f"/tmp/cap_{i}.py", source=f"tool:{i}")
        reg = pr_mod._load()
        assert len(reg) <= 3
    finally:
        pr_mod._MAX_ENTRIES = old_max


def test_read_file_integration(monkeypatch, tmp_path):
    """read_file 失败→登记；再次失败回执含 [路径登记] 提示."""
    from llm_loop.tools.builtin.read_file import ReadFileTool

    pr_mod = _reset_and_run(monkeypatch, tmp_path)
    tool = ReadFileTool()
    # 第一次失败：登记否定帧（回执可能不含提示——第一次登记后同路径立即再查才命中）
    r1 = tool.execute(path="/definitely/not/here_xyz.py")
    assert r1.status.value == "failure"
    assert "文件不存在" in r1.content
    # 第二次失败（同路径）：登记表命中 → 回执内嵌提示
    r2 = tool.execute(path="/definitely/not/here_xyz.py")
    assert "[路径登记]" in r2.content
    # 成功后翻转：再失败不再提示
    tmp_f = tmp_path / "exists.py"
    tmp_f.write_text("x")
    r3 = tool.execute(path=str(tmp_f))
    assert r3.status.value == "success"
    assert pr_mod.check_known_missing(str(tmp_f)) is False


def test_cross_process_register_merge_preserves_both(tmp_path):
    """两个独立进程基于同一旧快照写不同路径，最终不得 last-writer-wins 丢记录。"""
    import json
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    registry = tmp_path / "path_registry.json"
    go = tmp_path / "go"
    worker = r"""
import sys, time
from pathlib import Path
from llm_loop.tools import path_registry as pr
registry, ready, go, target = map(Path, sys.argv[1:])
pr._REGISTRY_PATH = registry
pr._LOADED = None
pr._LOADED_PATH = None
pr._load()  # 两个进程都先缓存同一个空快照，稳定复现旧 RMW 竞态
ready.write_text('ready')
while not go.exists():
    time.sleep(0.005)
pr.register_missing(str(target), source='cross-process-test')
"""
    ready1 = tmp_path / "ready1"
    ready2 = tmp_path / "ready2"
    target1 = tmp_path / "a.txt"
    target2 = tmp_path / "b.txt"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    p1 = subprocess.Popen(
        [sys.executable, "-c", worker, str(registry), str(ready1), str(go), str(target1)],
        env=env,
    )
    p2 = subprocess.Popen(
        [sys.executable, "-c", worker, str(registry), str(ready2), str(go), str(target2)],
        env=env,
    )
    try:
        deadline = time.monotonic() + 5
        while not (ready1.exists() and ready2.exists()) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready1.exists() and ready2.exists(), "子进程未完成同步预热"
        go.write_text("go")
        assert p1.wait(timeout=5) == 0
        assert p2.wait(timeout=5) == 0
    finally:
        for proc in (p1, p2):
            if proc.poll() is None:
                proc.kill()

    data = json.loads(registry.read_text(encoding="utf-8"))
    assert str(target1.resolve()) in data
    assert str(target2.resolve()) in data
