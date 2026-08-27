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
