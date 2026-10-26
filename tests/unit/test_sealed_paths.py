"""held-out 读侧封条（``src/llm_loop/sealed_paths.py``）定向测试。

纪律：所有 sealed root 都用 ``tmp_path`` 现造，**绝不读取真实
``evals/heldout/v1/tasks`` 下任何文件内容**（评测/改进期读取 held-out 材料即该轮作废）。
本文件只做路径判定与工具 guard 的机械断言，不触碰真实材料。
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from llm_loop.sealed_paths import (
    reset_cache,
    seal_enabled,
    sealed_command_reason,
    sealed_path_reason,
    sealed_roots,
)
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.inspect_code import InspectCodeTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.builtin.search_files import SearchFilesTool
from llm_loop.tools.builtin.source_synopsis import SourceSynopsisTool

SEAL_ENV = "LFL_HELDOUT_SEALED"
ROOT_ENV = "LFL_HELDOUT_ROOT"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例从「未启用 + 无自定义根」起跑，结束清缓存。"""
    monkeypatch.delenv(SEAL_ENV, raising=False)
    monkeypatch.delenv(ROOT_ENV, raising=False)
    reset_cache()
    yield
    reset_cache()


@pytest.fixture()
def fake_holdout(tmp_path, monkeypatch):
    """假 held-out 根：<tmp>/ws/tasks（内含两个敏感样例文件，仅用于判定）。"""
    base = tmp_path / "ws"
    root = base / "tasks"
    (root / "nested").mkdir(parents=True)
    (root / "statement.md").write_text("SENSITIVE-STATEMENT", encoding="utf-8")
    (root / "nested" / "solution.py").write_text("SENSITIVE-SOLUTION", encoding="utf-8")
    monkeypatch.setenv(ROOT_ENV, str(root))
    reset_cache()
    return {"base": base, "root": root}


def _enable(monkeypatch) -> None:
    monkeypatch.setenv(SEAL_ENV, "1")
    reset_cache()


# ---------------------------------------------------------------- 开关与根

@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", " yes "])
def test_seal_enabled_truthy(raw, monkeypatch):
    monkeypatch.setenv(SEAL_ENV, raw)
    assert seal_enabled() is True


@pytest.mark.parametrize("raw", ["0", "", "no", "false", "off"])
def test_seal_enabled_falsy(raw, monkeypatch):
    monkeypatch.setenv(SEAL_ENV, raw)
    assert seal_enabled() is False


def test_seal_enabled_unset():
    assert seal_enabled() is False


def test_sealed_roots_uses_env_when_dir_exists(fake_holdout):
    assert [p.resolve() for p in sealed_roots()] == [fake_holdout["root"].resolve()]


def test_sealed_roots_falls_back_when_env_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(ROOT_ENV, str(tmp_path / "nope-not-a-dir"))
    roots = sealed_roots()
    assert roots, "默认根应存在（仓库 evals/heldout/v1/tasks 路径，不读取其内容）"
    assert str(roots[0]).endswith(os.path.join("evals", "heldout", "v1", "tasks"))


# ---------------------------------------------------------------- 判定口径

def test_disabled_returns_none(fake_holdout):
    """1) 未启用 → 即便路径就在 sealed root 内也放行（开发态零行为变化）。"""
    assert seal_enabled() is False
    assert sealed_path_reason(str(fake_holdout["root"] / "statement.md")) is None


def test_enabled_root_itself_blocked(fake_holdout, monkeypatch):
    """2) 启用 + 根本身。"""
    _enable(monkeypatch)
    reason = sealed_path_reason(str(fake_holdout["root"]))
    assert reason is not None
    assert "held-out" in reason
    # 绝不回显文件内容
    assert "SENSITIVE" not in reason


def test_enabled_subfile_blocked(fake_holdout, monkeypatch):
    """3) 启用 + 子文件（含不存在文件：realpath 不要求存在）。"""
    _enable(monkeypatch)
    root = fake_holdout["root"]
    assert sealed_path_reason(str(root / "nested" / "solution.py")) is not None
    assert sealed_path_reason(str(root / "not-created-yet.txt")) is not None


def test_enabled_symlink_into_root_blocked(fake_holdout, tmp_path, monkeypatch):
    """4) 启用 + symlink 指向根内 → realpath 后命中。"""
    _enable(monkeypatch)
    link = tmp_path / "shortcut_tasks"
    os.symlink(fake_holdout["root"], link)
    assert sealed_path_reason(str(link / "statement.md")) is not None


def test_enabled_dotdot_traversal_blocked(fake_holdout, monkeypatch):
    """5) 启用 + a/../tasks/x 穿越 → realpath 归一后命中。"""
    _enable(monkeypatch)
    base = fake_holdout["base"]
    traversed = os.path.join(str(base), "a", "..", "tasks", "statement.md")
    assert sealed_path_reason(traversed) is not None


def test_enabled_literal_marker_even_if_root_missing(tmp_path, monkeypatch):
    """3b) 根目录缺失时靠字面片段 /evals/heldout/v1/tasks 兜底。"""
    _enable(monkeypatch)
    monkeypatch.setenv(ROOT_ENV, str(tmp_path / "missing-root"))
    reset_cache()
    mirror = tmp_path / "mirror" / "evals" / "heldout" / "v1" / "tasks" / "x.md"
    assert sealed_path_reason(str(mirror)) is not None


@pytest.mark.parametrize(
    "make",
    [
        lambda base: base / "tasks_backup" / "x.md",
        lambda base: base / "tasks2" / "x.md",
        lambda base: base / "evals" / "heldout" / "v1" / "tasks_backup" / "x.md",
    ],
)
def test_prefix_similar_paths_allowed(fake_holdout, monkeypatch, make):
    """6) 启用 + 前缀相似但不同目录 → 放行（分隔符边界，不误命中）。"""
    _enable(monkeypatch)
    assert sealed_path_reason(str(make(fake_holdout["base"]))) is None


def test_unrelated_path_allowed(fake_holdout, monkeypatch):
    """7) 启用 + 无关路径 → 放行。"""
    _enable(monkeypatch)
    assert sealed_path_reason(str(fake_holdout["base"] / "notes.md")) is None


# ---------------------------------------------------------------- 工具接线

def test_read_file_blocks_sealed(fake_holdout, monkeypatch):
    """8) 启用时 read_file 返回 FAILURE(error_type=HeldoutSealed)，且不泄露内容。"""
    _enable(monkeypatch)
    result = ReadFileTool().execute(path=str(fake_holdout["root"] / "statement.md"))
    assert result.status.value == "failure"
    assert result.error_type == "HeldoutSealed"
    assert "[held-out 封条]" in result.content
    assert "SENSITIVE-STATEMENT" not in result.content


def test_read_file_normal_when_disabled(tmp_path):
    """9) 未启用时 read_file 正常读 tmp 文件（零回归）。"""
    target = tmp_path / "ok.txt"
    target.write_text("plain-content", encoding="utf-8")
    result = ReadFileTool().execute(path=str(target))
    assert result.status.value == "success"
    assert "plain-content" in result.content


def test_search_files_blocks_sealed_root(fake_holdout, monkeypatch):
    """root 参数命中 → FAILURE。"""
    _enable(monkeypatch)
    result = SearchFilesTool().execute(root=str(fake_holdout["root"]), pattern="*.md")
    assert result.status.value == "failure"
    assert result.error_type == "HeldoutSealed"


def test_search_files_filters_sealed_results(fake_holdout, monkeypatch):
    """结果列表逐条过滤（不补位）+ 回执声明过滤条数。"""
    _enable(monkeypatch)
    ws = fake_holdout["base"]
    (ws / "probe_open.txt").write_text("probe_token open", encoding="utf-8")
    (fake_holdout["root"] / "probe_sealed.txt").write_text("probe_token sealed", encoding="utf-8")

    result = SearchFilesTool().execute(root=str(ws), pattern="probe_*", content="probe_token")
    assert result.status.value == "success"
    assert "probe_open" in result.content
    assert "probe_sealed" not in result.content
    assert "已过滤 1 条" in result.content


def test_inspect_code_blocks_sealed(fake_holdout, monkeypatch):
    _enable(monkeypatch)
    result = InspectCodeTool().execute(path=str(fake_holdout["root"] / "nested" / "solution.py"))
    assert result.status.value == "failure"
    assert result.error_type == "HeldoutSealed"


def test_edit_file_blocks_sealed_and_does_not_write(fake_holdout, monkeypatch):
    """写侧防复制/篡改：guard 先于任何磁盘写入。"""
    _enable(monkeypatch)
    target = fake_holdout["root"] / "nested" / "solution.py"
    result = EditFileTool().execute(
        path=str(target), old_string="SENSITIVE-SOLUTION", new_string="tampered"
    )
    assert result.status.value == "failure"
    assert result.error_type == "HeldoutSealed"
    assert target.read_text(encoding="utf-8") == "SENSITIVE-SOLUTION"


def test_source_synopsis_blocks_sealed_file_path(fake_holdout, monkeypatch):
    """source_ref 是文件路径（无 scheme）→ guard；不得触达 resolver。"""
    _enable(monkeypatch)

    def _boom(ref):  # pragma: no cover - 命中封条时不应被调用
        raise AssertionError(f"resolver 不应被调用: {ref}")

    tool = SourceSynopsisTool(store=object(), source_resolver=_boom)
    result = tool.execute(
        action="save",
        source_ref=str(fake_holdout["root"] / "statement.md"),
        summary="x",
    )
    assert result.status.value == "failure"
    assert result.error_type == "HeldoutSealed"


# ── P2-8（Rule28 修复轮）：execute_command 命令串字面片段拒绝 ──────────
# 判定只依赖命令字面片段（evals/heldout/v1/tasks、evals/heldout、/heldout/v1/），
# 归一 = lower + 连续空白折叠；封条未启用时零行为变化。


def test_sealed_command_reason_disabled_returns_none(monkeypatch):
    """seal off → 恒 None（开发态零行为变化，硬要求）。"""
    assert sealed_command_reason("cat evals/heldout/v1/tasks/x/solution.md") is None


@pytest.mark.parametrize(
    "command",
    [
        "cat evals/heldout/v1/tasks/x/solution.md",
        'python3 -c "open(\'repo/evals/heldout/v1/tasks/x/solution.md\').read()"',
        "ls evals/heldout",
        "grep foo /repo/evals/heldout/v1/manifest.json",
        # 大小写变形
        "cat EVALS/HELDOUT/V1/TASKS/x/solution.md",
        "ls Evals/Heldout",
        # 连续空白变形（折叠后命中）
        "cat    evals/heldout/v1/tasks/x/solution.md",
        "ls\t evals/heldout",
    ],
)
def test_sealed_command_reason_enabled_hits_literal_markers(command, monkeypatch):
    """seal on → 命中任一字面片段即拒；原因只含类别不含路径内容。"""
    _enable(monkeypatch)
    reason = sealed_command_reason(command)
    assert reason is not None
    assert "held-out" in reason
    assert "literal_path" in reason
    assert "evals" not in reason  # 绝不回显路径内容


def test_sealed_command_reason_enabled_normal_commands_pass(monkeypatch):
    """seal on → 正常命令（本修复轮用到的 cp/sed/git 等）放行。"""
    _enable(monkeypatch)
    for command in (
        "cp a.txt b.txt",
        "sed -n '1,50p' src/llm_loop/sealed_paths.py",
        "git status",
        "git diff --stat",
        ".venv/bin/python -m pytest tests/unit -q -p no:cacheprovider",
        "grep -n resolve_auto_backend src/llm_loop/tools/sandbox.py",
    ):
        assert sealed_command_reason(command) is None


def test_execute_command_blocks_sealed_literal(monkeypatch, tmp_path):
    """seal on → execute_command 入口拒绝（先于灾难守卫/执行），Popen 不被调用。"""
    _enable(monkeypatch)
    with mock.patch("subprocess.Popen") as popen:
        tool = ExecuteCommandTool()
        r = tool.execute(
            command="cat evals/heldout/v1/tasks/x/solution.md", workdir=str(tmp_path)
        )
    assert r.status.value == "failure"
    assert r.error_type == "HeldoutSealed"
    assert "[held-out 封条]" in r.content
    assert "evals" not in r.content  # 回执不回显路径内容
    popen.assert_not_called()


def test_execute_command_blocks_sealed_literal_argv_mode(monkeypatch, tmp_path):
    """seal on → argv 模式同样拒绝（守卫基准 = shlex.join(argv)，与既有守卫一致）。"""
    _enable(monkeypatch)
    with mock.patch("subprocess.Popen") as popen:
        r = ExecuteCommandTool().execute(
            argv=["cat", "evals/heldout/v1/tasks/x/solution.md"], workdir=str(tmp_path)
        )
    assert r.status.value == "failure"
    assert r.error_type == "HeldoutSealed"
    popen.assert_not_called()


def test_execute_command_sealed_normal_commands_run(monkeypatch, tmp_path):
    """seal on → 正常命令（cp/sed/git）照常执行（无误伤）。"""
    _enable(monkeypatch)
    for command in ("cp a.txt b.txt", "sed -n '1p' src/x.py", "git status"):
        with mock.patch("subprocess.Popen") as popen:
            fake = mock.MagicMock()
            fake.communicate.return_value = ("ok", "")
            fake.returncode = 0
            popen.return_value = fake
            r = ExecuteCommandTool().execute(command=command, workdir=str(tmp_path))
        assert r.status.value == "success", f"误伤正常命令: {command}"
        popen.assert_called_once()


def test_execute_command_sealed_off_literal_runs(monkeypatch, tmp_path):
    """seal off → 同一字面片段命令放行（Popen 被调用），零行为变化。"""
    with mock.patch("subprocess.Popen") as popen:
        fake = mock.MagicMock()
        fake.communicate.return_value = ("ok", "")
        fake.returncode = 0
        popen.return_value = fake
        r = ExecuteCommandTool().execute(
            command="cat evals/heldout/v1/tasks/x/solution.md", workdir=str(tmp_path)
        )
    assert r.status.value == "success"
    popen.assert_called_once()
