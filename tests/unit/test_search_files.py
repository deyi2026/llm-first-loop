"""DSH-PLUGINS-20260816 ③: search_files 工具测试（glob + 内容 grep + 安全边界）."""

from __future__ import annotations

import importlib
from pathlib import Path

from llm_loop.core.run_context import current_workspace_root
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


def test_pattern_and_content_scope_content_search(tmp_path):
    """pattern+content 表示在 glob 命中的文件中搜内容，而不是静默忽略 pattern。"""
    root = _mk_project(tmp_path)
    (root / "src" / "pkg" / "match.py").write_text("keyword_probe\n", encoding="utf-8")
    tool = SearchFilesTool()
    r = tool.execute(root=str(root), pattern="*.py", content="keyword_probe")
    assert r.status.value == "success"
    assert "src/pkg/match.py:1:" in r.content
    assert "README.md" not in r.content
    assert "文件名+内容搜索" in r.content


def test_ignore_git_dir(tmp_path):
    """忽略 .git: 搜索内容 'ignore me' 不应命中（.git 被排除）."""
    tool = SearchFilesTool()
    r = tool.execute(root=str(_mk_project(tmp_path)), content="ignore me")
    assert r.status.value == "success"
    assert "config" not in r.content  # .git/config 被忽略


def test_default_search_ignores_transient_workspace_copies(tmp_path):
    """默认根不把 CI/backup/worktree 旁路副本混进当前 workspace 结果。"""
    root = _mk_project(tmp_path)
    (root / "src" / "current.py").write_text("MARKER = 'current'\n", encoding="utf-8")
    for container in (".tmp-ci", ".backup", ".worktrees"):
        copy = root / container / "copy" / "src"
        copy.mkdir(parents=True)
        (copy / "current.py").write_text(f"MARKER = '{container}'\n", encoding="utf-8")

    tool = SearchFilesTool()
    r = tool.execute(root=str(root), pattern="current.py")

    assert r.status.value == "success"
    assert "src/current.py" in r.content
    assert ".tmp-ci" not in r.content
    assert ".backup" not in r.content
    assert ".worktrees" not in r.content


def test_explicit_root_can_search_transient_workspace_copy(tmp_path):
    """旁路副本只是默认降噪；显式 root 仍可审计。"""
    root = _mk_project(tmp_path)
    copy_root = root / ".backup" / "worktrees" / "copy"
    (copy_root / "src").mkdir(parents=True)
    (copy_root / "src" / "current.py").write_text("MARKER = 'backup'\n", encoding="utf-8")

    tool = SearchFilesTool()
    r = tool.execute(root=str(copy_root), pattern="current.py", content="backup")

    assert r.status.value == "success"
    assert "src/current.py:1:" in r.content


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


def test_managed_release_searches_real_runtime_workspace(monkeypatch, tmp_path):
    """Managed source under .releases must not reject the runtime's ordinary directories."""
    module = importlib.import_module("llm_loop.tools.builtin.search_files")
    simulated_home = tmp_path / "home" / "owner"
    workspace = simulated_home / "Project" / "lfl"
    (workspace / "docs" / "promotion" / "receipts").mkdir(parents=True)
    (workspace / "docs" / "governance").mkdir(parents=True)
    (workspace / "experiences").mkdir()
    (workspace / "data" / "methods").mkdir(parents=True)
    (workspace / "docs" / "promotion" / "receipts" / "20261012-check.json").write_text("{}")
    (workspace / "experiences" / "experience.md").write_text("experience")
    (workspace / "data" / "methods" / "method.md").write_text("method")
    (workspace / "docs" / "session-notes-20261012.md").write_text("session notes")
    (workspace / "docs" / "ai_rules.md").write_text("card-lifecycle")

    module_path = workspace / ".releases" / "gen999" / "src" / "llm_loop" / "tools" / "builtin" / "search_files.py"
    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: simulated_home))
    ctx = current_workspace_root.set(str(workspace))
    try:
        tool = SearchFilesTool()
        cases = (
            ("docs/promotion/receipts", "*20261012*", "20261012-check.json"),
            ("experiences", "*", "experience.md"),
            ("data/methods", "*", "method.md"),
            ("docs", "*session-notes*", "session-notes-20261012.md"),
        )
        for subdir, pattern, expected in cases:
            r = tool.execute(root=str(workspace / subdir), pattern=pattern, max_results=1)
            assert r.status.value == "success", (subdir, r.content)
            assert expected in r.content
        r = tool.execute(root=str(workspace / "docs"), pattern="ai_rules.md", content="card-lifecycle")
        assert r.status.value == "success" and "ai_rules.md:1:" in r.content
        r = tool.execute(root="experiences", pattern="experience.md")
        assert r.status.value == "success" and "experience.md" in r.content
        r = tool.execute(pattern="*session-notes*")
        assert r.status.value == "success" and "docs/session-notes-20261012.md" in r.content

        # A missing subdirectory is not a permission denial.
        r = tool.execute(root=str(workspace / "docs" / "governance" / "card-audit"), pattern="*")
        assert r.status.value == "failure" and "[目录不存在]" in r.content
        # A real external HOME root must remain disallowed.
        r = tool.execute(root=str(simulated_home), pattern="*")
        assert r.status.value == "failure" and "[越权拒绝]" in r.content
    finally:
        current_workspace_root.reset(ctx)


def test_unbounded_home_context_cannot_whitelist_entire_home(monkeypatch, tmp_path):
    """Even a misconfigured workspace pointing at HOME cannot search HOME recursively."""
    home = tmp_path / "owner"
    home.mkdir()
    (home / "normal.txt").write_text("visible")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    ctx = current_workspace_root.set(str(home))
    try:
        tool = SearchFilesTool()
        for arg in ({"pattern": "*"}, {"root": str(home), "pattern": "*"}):
            r = tool.execute(**arg)
            assert r.status.value == "failure" and "[越权拒绝]" in r.content
    finally:
        current_workspace_root.reset(ctx)


def test_search_never_uses_process_cwd_as_fallback_for_relative_root(monkeypatch, tmp_path):
    """A nonexistent workspace-relative path must not resolve to an unrelated cwd."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    (outside / "receipt_only").mkdir(parents=True)
    (outside / "receipt_only" / "match.txt").write_text("match")
    monkeypatch.chdir(outside)
    token = current_workspace_root.set(str(workspace))
    try:
        tool = SearchFilesTool()
        r = tool.execute(root="receipt_only", pattern="match.txt")
        assert r.status.value == "failure"
        assert "[目录不存在]" in r.content
        # Existing explicit absolute-root behavior still works outside HOME.
        r = tool.execute(root=str(outside / "receipt_only"), pattern="match.txt")
        assert r.status.value == "success" and "match.txt" in r.content
    finally:
        current_workspace_root.reset(token)


def test_search_does_not_follow_linked_files_outside_the_search_root(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "outside.txt").write_text("outside_marker")
    (workspace / "linked.txt").symlink_to(outside / "outside.txt")
    (workspace / "normal.txt").write_text("normal_marker")
    tool = SearchFilesTool()
    by_name = tool.execute(root=str(workspace), pattern="*.txt")
    assert by_name.status.value == "success"
    assert "normal.txt" in by_name.content
    assert "linked.txt" not in by_name.content
    by_content = tool.execute(root=str(workspace), content="outside_marker")
    assert by_content.status.value == "success"
    assert "无匹配" in by_content.content
