"""workspace_recovery_status 工具单测（P0-E1 工作树搬迁消费端）。

临时 git 仓库 + 临时备份目录（tmp_path），发现根经 LFL_PREBACKUP_ROOTS /
LFL_PREBACKUP_LATEST_JSON / LFL_PREBACKUP_LATEST_TXT 全量隔离，不依赖
/tmp/lfl-prebackup* 真实产物。覆盖：legacy 推导标 derived/retro、LATEST.json
优先、head_matches_prebackup、无备份时如实报告（不伪报 0 指标）、纯只读。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.workspace_recovery_status import WorkspaceRecoveryStatusTool

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "restore_prebackup.sh"

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="需要 git",
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    assert proc.returncode == 0, f"git {args} 失败: {proc.stderr}"
    return proc.stdout


def build_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def build_legacy_backup(
    tmp_path: Path, repo: Path, with_head: bool = True, parent: Path | None = None
) -> Path:
    """legacy 产物备份目录（status.txt: 1 M + 2 ??，与搬迁时工作树一致）。"""
    (repo / "a.txt").write_text("modified\n", encoding="utf-8")
    (repo / "u1.txt").write_text("u1\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / "u2.txt").write_text("u2\n", encoding="utf-8")
    backup = (parent or tmp_path) / "lfl-prebackup-tool-fixture"
    backup.mkdir()
    (backup / "status.txt").write_text(
        " M a.txt\n?? u1.txt\n?? sub/\n", encoding="utf-8"
    )
    for name in ("SHA256SUMS", "tracked.patch", "untracked.tgz", "untracked.list.z"):
        (backup / name).write_bytes(b"")
    if with_head:
        (backup / "head.txt").write_text(
            _git(repo, "rev-parse", "HEAD"), encoding="utf-8"
        )
    # 还原仓库为干净态（模拟搬迁后）
    _git(repo, "checkout", "--", "a.txt")
    (repo / "u1.txt").unlink()
    (repo / "sub" / "u2.txt").unlink()
    (repo / "sub").rmdir()
    return backup


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """发现面全量隔离到 tmp_path/roots：不读 /tmp 真实指针与真实备份。"""
    roots = tmp_path / "roots"
    roots.mkdir()
    monkeypatch.setenv("LFL_PREBACKUP_LATEST_JSON", str(tmp_path / "no-LATEST.json"))
    monkeypatch.setenv("LFL_PREBACKUP_LATEST_TXT", str(tmp_path / "no-pointer.txt"))
    monkeypatch.setenv("LFL_PREBACKUP_ROOTS", str(roots))
    return roots


def run_tool(**kwargs) -> tuple[str, dict]:
    result = WorkspaceRecoveryStatusTool().execute(**kwargs)
    assert result.status == ToolResultStatus.SUCCESS, result.content
    lines = [l for l in result.content.splitlines() if l.strip()]
    payload = None
    for line in reversed(lines):
        if line.startswith("{"):
            payload = json.loads(line)
            break
    assert payload is not None, "回执缺机器可读 JSON 行"
    return result.content, payload


def test_no_backup_reports_honestly(tmp_path: Path, isolated_env: Path) -> None:
    repo = build_repo(tmp_path)
    (repo / "dirty.txt").write_text("d\n", encoding="utf-8")  # 当前真实脏 1 项
    content, payload = run_tool(repo_path=str(repo))
    assert payload["found"] is False
    assert payload["backup_dir"] is None
    assert payload["created_at"] is None
    assert payload["file_counts"] is None  # 不伪报 0
    assert payload["artifacts_present"] == {}
    assert payload["current_dirty_count"] == 1  # 唯一真实测量仍如实给出
    assert "没有备份 ≠ 没有做过搬迁" in content


def test_legacy_backup_derived_retro(tmp_path: Path, isolated_env: Path) -> None:
    repo = build_repo(tmp_path)
    backup = build_legacy_backup(tmp_path, repo, parent=isolated_env)
    content, payload = run_tool(repo_path=str(repo))
    assert payload["found"] is True
    assert payload["backup_dir"] == str(backup)
    assert payload["derived"] is True and payload["retro"] is True
    assert payload["created_at"] is not None  # mtime 推导
    assert payload["file_counts"] == {"modified": 1, "untracked": 2, "other": 0}
    assert payload["artifacts_present"]["status.txt"] is True
    assert payload["artifacts_present"]["ahead-behind.txt"] is False
    assert payload["head_matches_prebackup"] == "true"
    assert payload["current_dirty_count"] == 0
    cmds = payload["restore_cmds"]
    assert len(cmds) == 3 and all(str(SCRIPT) in c for c in cmds)
    assert cmds[0].endswith("--check")
    assert cmds[1].endswith("--tracked-only")
    assert cmds[2].endswith("--untracked-only")


def test_head_mismatch_after_new_commit(tmp_path: Path, isolated_env: Path) -> None:
    repo = build_repo(tmp_path)
    build_legacy_backup(tmp_path, repo, parent=isolated_env)
    (repo / "b.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "moved on")
    _, payload = run_tool(repo_path=str(repo))
    assert payload["head_matches_prebackup"] == "false"


def test_head_txt_absent_is_unavailable(tmp_path: Path, isolated_env: Path) -> None:
    repo = build_repo(tmp_path)
    build_legacy_backup(tmp_path, repo, with_head=False, parent=isolated_env)
    _, payload = run_tool(repo_path=str(repo))
    assert payload["head_matches_prebackup"] == "unavailable"


def test_latest_json_wins_over_legacy(
    tmp_path: Path, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = build_repo(tmp_path)
    backup = build_legacy_backup(tmp_path, repo, parent=isolated_env)
    latest = tmp_path / "LATEST.json"
    latest.write_text(
        json.dumps({"backup_dir": str(backup), "created_at": "2026-11-01T10:40:15+08:00"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LFL_PREBACKUP_LATEST_JSON", str(latest))
    _, payload = run_tool(repo_path=str(repo))
    assert payload["derived"] is False and payload["retro"] is False
    assert payload["created_at"] == "2026-11-01T10:40:15+08:00"
    assert payload["source"] == "latest_json"


def test_tool_is_readonly(tmp_path: Path, isolated_env: Path) -> None:
    repo = build_repo(tmp_path)
    build_legacy_backup(tmp_path, repo, parent=isolated_env)
    before = sorted(str(p.relative_to(repo)) for p in repo.rglob("*"))
    run_tool(repo_path=str(repo))
    after = sorted(str(p.relative_to(repo)) for p in repo.rglob("*"))
    assert before == after  # 不写任何文件
    assert _git(repo, "status", "--porcelain").strip() == ""


def test_non_git_dir_fails_honestly(tmp_path: Path, isolated_env: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    result = WorkspaceRecoveryStatusTool().execute(repo_path=str(plain))
    assert result.status == ToolResultStatus.FAILURE
    assert "git" in result.content
