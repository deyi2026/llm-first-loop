"""EVO-20261007-9c6eccf3: publish 物化固定提交 release checkout。

2026-10-07 17:25/18:28 实证：desired 的 code_root 直接绑定开发工作树 HEAD，
publish 后开发树前移（6e78df3）导致既有期望代 restart precheck git_head
mismatch 连续失败。新语义：build_deployment 把发布代码物化为同仓 linked
worktree（HEAD 永久钉在 publish 时的 commit），webui/dist 从开发树复制并按
tree-sha 验证；同 SHA 幂等复用；分歧时 publish 时点重建。
"""

import subprocess
from pathlib import Path

from llm_loop.runtime.service_control import build_deployment, verify_deployment_binding


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
    )


def _head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / ".gitignore").write_text("webui/dist/\n", encoding="utf-8")
    (path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (path / "app.py").write_text("print('v1')\n", encoding="utf-8")
    dist = path / "webui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>ok</html>\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "c1")
    return path


def test_release_checkout_pins_head_and_survives_dev_head_move(tmp_path: Path) -> None:
    code = _make_repo(tmp_path / "code")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    deployment = build_deployment(code_root=code, runtime_root=runtime, generation=1)

    release = Path(deployment.code_root)
    assert release == runtime / ".releases" / deployment.git_head
    assert (release / "app.py").exists()
    assert (release / "webui" / "dist" / "index.html").exists()

    # 回归核心（当日事故类）：开发树 HEAD 前移 + 保持干净，既有期望代绑定不变。
    (code / "app.py").write_text("print('v2')\n", encoding="utf-8")
    _git(code, "add", "-A")
    _git(code, "commit", "-qm", "c2")
    assert _head(code) != deployment.git_head
    assert verify_deployment_binding(
        deployment, code_root=release, runtime_root=runtime,
    ) == []


def test_release_checkout_reuses_same_head_and_rebuilds_on_divergence(tmp_path: Path) -> None:
    code = _make_repo(tmp_path / "code")
    deployment = build_deployment(code_root=code, runtime_root=code, generation=1)

    again = build_deployment(code_root=code, runtime_root=code, generation=2)
    assert again.code_root == deployment.code_root  # 同 SHA 幂等复用
    assert again.git_head == deployment.git_head

    # 分歧（绑定树 HEAD 前移，模拟 E1 拒绝后未重建的漂移状态）→ publish 时点重建。
    _git(Path(deployment.code_root), "commit", "--allow-empty", "-qm", "diverge")
    assert _head(Path(deployment.code_root)) != deployment.git_head

    rebuilt = build_deployment(code_root=code, runtime_root=code, generation=3)
    assert rebuilt.code_root == deployment.code_root
    assert _head(Path(rebuilt.code_root)) == deployment.git_head
    assert verify_deployment_binding(
        rebuilt, code_root=Path(rebuilt.code_root), runtime_root=code,
    ) == []


def test_release_checkout_rebuilds_bogus_dir(tmp_path: Path) -> None:
    code = _make_repo(tmp_path / "code")
    head = _head(code)
    bogus = code / ".releases" / head
    bogus.mkdir(parents=True)
    (bogus / "garbage.txt").write_text("junk\n", encoding="utf-8")

    deployment = build_deployment(code_root=code, runtime_root=code, generation=1)
    release = Path(deployment.code_root)
    assert release == bogus
    assert (release / "app.py").exists()
    assert not (release / "garbage.txt").exists()
    assert _head(release) == deployment.git_head
