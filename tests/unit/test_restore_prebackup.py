"""scripts/restore_prebackup.sh 单测（P0-E1 工作树搬迁消费端）。

夹具全部用 tmp_path（临时 git 仓库 + 临时备份目录），围栏根经
LFL_PREBACKUP_ROOTS 放宽到 tmp_path，不依赖 /tmp/lfl-prebackup* 真实产物。
脚本经 subprocess 真实执行：--check 只读、冲突写 restored/、路径围栏拒绝
（含 --dir /etc 反例与 symlink 逃逸反例）、legacy 推导标 derived、幂等。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "restore_prebackup.sh"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file() or subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="需要 git 与 scripts/restore_prebackup.sh",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    assert proc.returncode == 0, f"git {args} 失败: {proc.stderr}"
    return proc.stdout


def _make_tgz(tgz: Path, files: dict[str, str]) -> None:
    with tarfile.open(tgz, "w:gz") as t:
        for name, content in sorted(files.items()):
            info = tarfile.TarInfo(name)
            data = content.encode()
            info.size = len(data)
            info.mtime = 0
            t.addfile(info, __import__("io").BytesIO(data))


def build_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """临时 git 仓库 + legacy 备份目录；返回 (repo, backup_dir)，仓库已还原为干净态。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "f.py").write_text("print('base')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    # 搬迁前的工作树：1 个 tracked 修改 + 2 个 untracked
    (repo / "a.txt").write_text("modified-by-pipeline\n", encoding="utf-8")
    (repo / "u1.txt").write_text("u1-content\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / "u2.txt").write_text("u2-content\n", encoding="utf-8")

    backup = tmp_path / "lfl-prebackup-fixture"
    backup.mkdir()
    (backup / "tracked.patch").write_text(_git(repo, "diff"), encoding="utf-8")
    (backup / "status.txt").write_text(_git(repo, "status", "--porcelain"), encoding="utf-8")
    _make_tgz(backup / "untracked.tgz", {"u1.txt": "u1-content\n", "sub/u2.txt": "u2-content\n"})
    (backup / "untracked.list.z").write_bytes(
        b"\0".join(p.encode() for p in ("u1.txt", "sub/u2.txt")) + b"\0"
    )
    (backup / "head.txt").write_text(_git(repo, "rev-parse", "HEAD"), encoding="utf-8")
    (backup / "ahead-behind.txt").write_text("0\t0\n", encoding="utf-8")
    sums = "".join(
        f"{_sha256(backup / n)}  {n}\n"
        for n in ("tracked.patch", "untracked.tgz", "status.txt")
    )
    (backup / "SHA256SUMS").write_text(sums, encoding="utf-8")

    # 模拟"搬迁已发生"：工作树回到干净基线
    _git(repo, "checkout", "--", "a.txt")
    (repo / "u1.txt").unlink()
    (repo / "sub" / "u2.txt").unlink()
    (repo / "sub").rmdir()
    assert _git(repo, "status", "--porcelain").strip() == ""
    return repo, backup


def run_script(repo: Path, backup_root: Path, *args: str, use_default_fence: bool = False) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items()}
    env["LFL_PREBACKUP_LATEST_TXT"] = str(backup_root / "no-such-pointer.txt")
    if not use_default_fence:
        env["LFL_PREBACKUP_ROOTS"] = str(backup_root)
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=str(repo), env=env,
        capture_output=True, text=True,
    )
    # 摘要 JSON 恒在 stdout 末行（stderr 的拒绝/中止信息不能压过它）
    return proc.returncode, proc.stdout, proc.stdout + proc.stderr


def last_json(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, "脚本 stdout 无输出"
    return json.loads(lines[-1])


def test_check_mode_is_readonly(tmp_path: Path) -> None:
    repo, backup = build_fixture(tmp_path)
    code, stdout, out = run_script(repo, tmp_path, "--dir", str(backup), "--check")
    summary = last_json(stdout)
    assert code == 0
    assert summary["mode"] == "T1"
    assert summary["reason_code"] == "ok"
    assert summary["conflicts"] == 0
    assert summary["applied"] == 0
    assert summary["derived"] is True  # legacy：无 LATEST.json → derived
    assert summary["backup_dir"] == str(backup)
    # 只读证明：仓库仍干净、a.txt 仍是基线、未创建 restored/
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert (repo / "a.txt").read_text(encoding="utf-8") == "base\n"
    assert not (backup / "restored").exists()
    assert "would-restore: u1.txt" in out


def test_full_restore_then_idempotent(tmp_path: Path) -> None:
    repo, backup = build_fixture(tmp_path)
    code, stdout, out = run_script(repo, tmp_path, "--dir", str(backup))
    summary = last_json(stdout)
    assert code == 0 and summary["reason_code"] == "ok"
    assert summary["applied"] == 3  # tracked.patch + 2 个 untracked
    assert (repo / "a.txt").read_text(encoding="utf-8") == "modified-by-pipeline\n"
    assert (repo / "u1.txt").read_text(encoding="utf-8") == "u1-content\n"
    assert (repo / "sub" / "u2.txt").read_text(encoding="utf-8") == "u2-content\n"
    # 幂等：重复运行不重复应用
    code2, stdout2, out2 = run_script(repo, tmp_path, "--dir", str(backup))
    s2 = last_json(stdout2)
    assert code2 == 0 and s2["applied"] == 0 and s2["conflicts"] == 0
    assert s2["tracked_state"] == "already_applied"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "modified-by-pipeline\n"


def test_untracked_conflict_saved_to_restored_not_overwritten(tmp_path: Path) -> None:
    repo, backup = build_fixture(tmp_path)
    (repo / "u1.txt").write_text("current-different\n", encoding="utf-8")
    code, stdout, out = run_script(repo, tmp_path, "--dir", str(backup))
    summary = last_json(stdout)
    assert code == 4 and summary["reason_code"] == "conflicts_detected"
    assert summary["conflicts"] == 1
    # 同名不同内容：不覆盖工作树文件
    assert (repo / "u1.txt").read_text(encoding="utf-8") == "current-different\n"
    # 备份版本落到 <backup_dir>/restored/
    saved = backup / "restored" / "u1.txt"
    assert saved.read_text(encoding="utf-8") == "u1-content\n"
    assert "conflict-saved:" in out
    # 非冲突的 untracked 照常恢复
    assert (repo / "sub" / "u2.txt").read_text(encoding="utf-8") == "u2-content\n"


def test_tracked_conflict_aborts_without_half_state(tmp_path: Path) -> None:
    repo, backup = build_fixture(tmp_path)
    (repo / "a.txt").write_text("third-content\n", encoding="utf-8")
    code, stdout, out = run_script(repo, tmp_path, "--dir", str(backup))
    summary = last_json(stdout)
    assert code == 5 and summary["reason_code"] == "tracked_apply_failed"
    # 不留半应用状态：a.txt 保持应用前内容；T3 未执行（u1.txt 未落地）
    assert (repo / "a.txt").read_text(encoding="utf-8") == "third-content\n"
    assert not (repo / "u1.txt").exists()
    assert "stash" in out  # 兜底指引在场


def test_fence_rejects_etc_with_default_fence(tmp_path: Path) -> None:
    """围栏反例（默认根，不放宽）：--dir /etc 必须被确定性拒绝。"""
    repo, _ = build_fixture(tmp_path)
    code, stdout, out = run_script(repo, tmp_path, "--dir", "/etc", "--check", use_default_fence=True)
    summary = last_json(stdout)
    assert code == 2 and summary["reason_code"] == "path_outside_fence"
    assert "REJECT" in out
    # 拒绝路径上不产生任何写入
    assert _git(repo, "status", "--porcelain").strip() == ""


def test_fence_rejects_dir_outside_env_roots(tmp_path: Path) -> None:
    """围栏反例（env 根=tmp_path）：tmp_path 之外的既有目录必须被拒绝。"""
    repo, _ = build_fixture(tmp_path)
    outside = tmp_path.parent  # pytest 基础 tmp 目录：存在、但在 tmp_path 之外
    code, stdout, out = run_script(repo, tmp_path, "--dir", str(outside), "--check")
    summary = last_json(stdout)
    assert code == 2 and summary["reason_code"] == "path_outside_fence"


def test_fence_rejects_symlink_escape(tmp_path: Path) -> None:
    """名字匹配 lfl-prebackup* 但 realpath 逃出围栏 → 拒绝。"""
    repo, _ = build_fixture(tmp_path)
    evil = tmp_path / "lfl-prebackup-evil"
    evil.symlink_to("/etc")
    code, stdout, out = run_script(repo, tmp_path, "--dir", str(evil), "--check")
    summary = last_json(stdout)
    assert code == 2 and summary["reason_code"] == "path_outside_fence"


def test_no_backup_found(tmp_path: Path) -> None:
    repo, _ = build_fixture(tmp_path)
    empty_root = tmp_path / "empty-root"
    empty_root.mkdir()
    code, stdout, out = run_script(repo, empty_root)
    summary = last_json(stdout)
    assert code == 3 and summary["reason_code"] == "no_backup_found"
    assert summary["backup_dir"] is None


def test_pointer_file_selects_backup(tmp_path: Path) -> None:
    repo, backup = build_fixture(tmp_path)
    other = tmp_path / "lfl-prebackup-older"
    other.mkdir()
    (other / "status.txt").write_text("?? x\n", encoding="utf-8")
    os.utime(other, (1_000_000, 1_000_000))  # 更旧：mtime 发现会选 fixture，指针应压过它
    ptr = tmp_path / "pointer.txt"
    ptr.write_text(str(other) + "\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items()}
    env["LFL_PREBACKUP_ROOTS"] = str(tmp_path)
    env["LFL_PREBACKUP_LATEST_TXT"] = str(ptr)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--check"], cwd=str(repo), env=env,
        capture_output=True, text=True,
    )
    summary = last_json(proc.stdout)
    assert proc.returncode == 0
    assert summary["backup_dir"] == str(other)  # 指针 > mtime 发现


def test_latest_json_wins_over_derived(tmp_path: Path) -> None:
    repo, backup = build_fixture(tmp_path)
    (backup / "LATEST.json").write_text(
        json.dumps({"backup_dir": str(backup), "created_at": "2026-11-01T10:40:15+08:00"}),
        encoding="utf-8",
    )
    code, stdout, out = run_script(repo, tmp_path, "--dir", str(backup), "--check")
    summary = last_json(stdout)
    assert summary["derived"] is False
    assert summary["created_at"] == "2026-11-01T10:40:15+08:00"
