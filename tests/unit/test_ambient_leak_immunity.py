"""D4 ambient 泄漏免疫（design 2026-10-20）：web/execute_command 派生 shell 继承
部署绑定 LFL_WORKSPACE_ROOT；查询 CLI 必须在泄漏存在时仍行为正确.

真实 CLI 路径验证（subprocess）：显式构造子进程 env，不依赖 CI ambient 注入，
任何环境可跑。仓库无 ``llm_loop.__main__``（``python -m llm_loop`` 不是合法
入口），故用 ``python -c`` 引导 ``application_main``——即 pyproject
``[project.scripts]`` 注册的 ``lfl`` console entry，入口语义等价。子进程
PYTHONPATH 钉到本仓库 ``src``：真实部署派生 shell 连 PYTHONPATH 一起泄漏
（指向 .releases/<hash>/src 的旧快照），钉值保证被测对象恒为源码树。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from llm_loop.workspace.store import WorkspaceStore

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")

# `lfl` console entry（pyproject [project.scripts] → llm_loop.cli:application_main）。
# `python -m llm_loop` 非法（无 __main__.py），`-c` 引导与 console script 同一入口。
_CONSOLE_ENTRY_BOOTSTRAP = (
    "import sys; from llm_loop.cli import application_main; sys.exit(application_main())"
)


def _run_query(
    args: list[str], env_extra: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """跑真实查询 CLI：env_extra 覆盖一切 ambient 值，其余部署泄漏全部剥离."""
    env = {**os.environ, **env_extra}
    env.pop("LFL_WORKSPACE_ROOT", None)
    env.update(env_extra)
    env["PYTHONPATH"] = _REPO_SRC
    return subprocess.run(
        [sys.executable, "-c", _CONSOLE_ENTRY_BOOTSTRAP, *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60,
    )


def _make_workspace(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'ws'\n", encoding="utf-8")
    return root


def test_ambient_leak_with_explicit_workspace_succeeds(tmp_path: Path) -> None:
    """泄漏存在时显式 --workspace 仍直达已注册 workspace（sessions list exit 0）."""
    ws = _make_workspace(tmp_path / "ws")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)  # conftest isolated_data_dir 已建同名目录
    WorkspaceStore(data).register(ws)

    result = _run_query(
        [
            "--config", str(tmp_path / "absent.env"),
            "--data-dir", str(data),
            "--workspace", str(ws),
            "sessions", "list",
        ],
        env_extra={"LFL_WORKSPACE_ROOT": str(tmp_path / "fake-release-root")},
        cwd=tmp_path,
    )

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


def test_ambient_leak_inside_deployment_tree_exits_3(tmp_path: Path) -> None:
    """cwd 位于部署根内且与泄漏绑定重合 → 拒绝猜测：exit 3 + 双候选 stderr."""
    deploy = _make_workspace(tmp_path / "deploy")
    sub = deploy / "sub"
    sub.mkdir()
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)  # conftest isolated_data_dir 已建同名目录

    result = _run_query(
        [
            "--config", str(tmp_path / "absent.env"),
            "--data-dir", str(data),
            "sessions", "list",
        ],
        env_extra={"LFL_WORKSPACE_ROOT": str(deploy)},
        cwd=sub,
    )

    assert result.returncode == 3, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "cwd-derived" in result.stderr
    assert "deployment-bound" in result.stderr
