"""EVO-20260823-12be9cac: Path Registry 正帧/对账查询 + search_files path 参数测试."""

from __future__ import annotations

from llm_loop.tools import path_registry as pr
from llm_loop.tools.builtin.search_files import SearchFilesTool


def _setup(monkeypatch, tmp_path):
    pr.reset()
    monkeypatch.setattr(pr, "_REGISTRY_PATH", None)
    monkeypatch.setattr(pr, "_LOADED", None)

    def fake_registry_file():
        return tmp_path / "path_registry.json"

    monkeypatch.setattr(pr, "_registry_file", fake_registry_file)
    return pr


def test_register_seen_and_query_cache_hit(monkeypatch, tmp_path):
    """正帧登记后 query_path 缓存命中（mtime 未变 → O(1) 不碰磁盘）."""
    pr_mod = _setup(monkeypatch, tmp_path)
    f = tmp_path / "seen.txt"
    f.write_text("hello")
    st = f.stat()
    pr_mod.register_seen(str(f), mtime=st.st_mtime_ns, size=st.st_size, kind="file")
    info = pr_mod.query_path(str(f))
    assert info["exists"] is True
    assert info["from"] == "cache"  # mtime 未变 → 缓存命中
    assert info["kind"] == "file"


def test_query_stat_refresh_on_mtime_change(monkeypatch, tmp_path):
    """文件内容变更（mtime 变）→ 缓存过期 → stat 对账刷新."""
    pr_mod = _setup(monkeypatch, tmp_path)
    f = tmp_path / "refresh.txt"
    f.write_text("v1")
    st1 = f.stat()
    pr_mod.register_seen(str(f), mtime=st1.st_mtime_ns, size=st1.st_size, kind="file")
    # 修改文件（mtime 变化）
    f.write_text("v2 longer content")
    info = pr_mod.query_path(str(f))
    assert info["exists"] is True
    assert info["from"] == "stat"  # mtime 变 → 重新 stat
    assert info["size"] > st1.st_size


def test_query_missing_returns_negative(monkeypatch, tmp_path):
    """不存在路径 → query_path 判不存在并登记负帧."""
    pr_mod = _setup(monkeypatch, tmp_path)
    missing = str(tmp_path / "never_exist.py")
    info = pr_mod.query_path(missing)
    assert info["exists"] is False
    assert pr_mod.check_known_missing(missing) is True  # 已登记负帧


def test_negative_frame_short_circuit(monkeypatch, tmp_path):
    """负帧命中且未过期 → query_path 直接返回不存在（from=negative_frame，不碰磁盘）."""
    pr_mod = _setup(monkeypatch, tmp_path)
    missing = str(tmp_path / "neg.py")
    pr_mod.register_missing(missing)
    info = pr_mod.query_path(missing)
    assert info["exists"] is False
    assert info["from"] == "negative_frame"


def test_search_files_path_query(monkeypatch, tmp_path):
    """search_files(path=...) 精确路径查询: 存在→SUCCESS 元数据; 不存在→FAILURE + 提示."""
    pr_mod = _setup(monkeypatch, tmp_path)
    tool = SearchFilesTool()
    f = tmp_path / "known.py"
    f.write_text("x = 1")
    r1 = tool.execute(path=str(f))
    assert r1.status.value == "success"
    assert "[路径查询]" in r1.content and "文件" in r1.content
    r2 = tool.execute(path=str(tmp_path / "no_such.py"))
    assert r2.status.value == "failure"
    assert "路径不存在" in r2.content
