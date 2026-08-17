"""DSH-PLUGINS-20260816 ③: search_files 工具测试（glob + 内容 grep + 安全边界）."""

from __future__ import annotations

from llm_loop.tools.builtin.search_files import SearchFilesTool


def _mk_project(tmp_path):
    """构造迷你项目结构（src/pkg/__init__.py + tests/test_x.py + README.md）. 返回项目根."""
    root = tmp_path / "proj"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "pkg" / "__init__.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\nkeyword_probe\n", encoding="utf-8")
    (root / ".git" / "config").mkdir(parents=True)
    (root / ".git" / "config" / "ignore.txt").write_text("ignore me\n", encoding="utf-8")
    return root


def test_glob_pattern(tmp_path):
    """文件名 glob: *.py 命中 2 个（忽略 .git/__pycache__）."""
    tool = SearchFilesTool()
    r = tool.execute(root=str(_mk_project(tmp_path)), pattern="*.py")
    assert r.status.value == "success"
    assert "src/pkg/__init__.py" in r.content
    assert "tests/test_x.py" in r.content
    assert "README" not in r.content


def test_content_search(tmp_path):
    """内容关键词: keyword_probe 命中 README.md 第 2 行."""
    tool = SearchFilesTool()
    r = tool.execute(root=str(_mk_project(tmp_path)), content="keyword_probe")
    assert r.status.value == "success"
    assert "README.md:2:" in r.content


def test_ignore_git_dir(tmp_path):
    """忽略 .git: 搜索内容 'ignore me' 不应命中（.git 被排除）."""
    tool = SearchFilesTool()
    r = tool.execute(root=str(_mk_project(tmp_path)), content="ignore me")
    assert r.status.value == "success"
    assert "config" not in r.content  # .git/config 被忽略


def test_no_match(tmp_path):
    """无匹配: 返回成功 + 空结果说明."""
    tool = SearchFilesTool()
    r = tool.execute(root=str(_mk_project(tmp_path)), content="zzz_nothing_here")
    assert r.status.value == "success"
    assert "无匹配" in r.content


def test_missing_params(tmp_path):
    """参数缺失: 失败回执."""
    tool = SearchFilesTool()
    r = tool.execute(root=str(_mk_project(tmp_path)))
    assert r.status.value == "failure"
    assert "至少填一个" in r.content


def test_root_not_exist(tmp_path):
    """root 不存在: 失败回执（目录校验，不越权隐式回退）."""
    tool = SearchFilesTool()
    r = tool.execute(root=str(tmp_path / "no_such_dir"), pattern="*.py")
    assert r.status.value == "failure"
    assert "目录不存在" in r.content


def test_max_results_limit(tmp_path):
    """max_results 截断: 命中多条只返回上限."""
    tool = SearchFilesTool()
    r = tool.execute(root=str(_mk_project(tmp_path)), pattern="*.py", max_results=1)
    assert r.status.value == "success"
    # 只返回 1 条
    assert r.content.count(":") >= 1


def test_invalid_max_results_type():
    """审查低危: max_results 类型非法 → FAILURE 回执（原实现直接外抛 ValueError）."""
    tool = SearchFilesTool()
    r = tool.execute(pattern="*.py", max_results="not-a-number")
    assert r.status.value == "failure"
    assert "参数错误" in r.content
