"""release checkout dual-root sidecar `.env` 自动物化（gen196/gen197 缺口修复）回归。

E2E 断言与 restart_mirror.sh:_knowledge_binding_preflight 同构：新 publish 的
release checkout 不经人工补文件即可通过 `--check-binding` preflight；复用路径
对漂移 sidecar（路径漂移/白名单外键/mode 漂移）做原子修复。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from llm_loop.runtime.service_control import build_deployment

# 与真实包依赖闭包一致的最小可导入子集（knowledge_health -> paths/config/
# codearts.config/identity），让 gate 子进程完全活在 release checkout 内。
_PKG_FILES = (
    "src/llm_loop/__init__.py",
    "src/llm_loop/config.py",
    "src/llm_loop/codearts/__init__.py",
    "src/llm_loop/codearts/config.py",
    "src/llm_loop/runtime/__init__.py",
    "src/llm_loop/runtime/identity.py",
    "src/llm_loop/runtime/paths.py",
    "src/llm_loop/runtime/knowledge_health.py",
)
_WORKSPACE = Path(__file__).resolve().parents[2]


def _git_code_fixture(tmp_path: Path) -> tuple[Path, Path]:
    code = tmp_path / "code"
    runtime = tmp_path / "runtime"
    code.mkdir()
    runtime.mkdir()
    git = ["git", "-C", str(code)]
    subprocess.run(["git", "init", "-q", str(code)], check=True)
    subprocess.run(git + ["config", "user.email", "sidecar@test.local"], check=True)
    subprocess.run(git + ["config", "user.name", "sidecar-test"], check=True)
    (code / ".gitignore").write_text(".env\nwebui/dist/\n", encoding="utf-8")
    (code / "pyproject.toml").write_text(
        "[project]\nname='sidecar'\nversion='0'\n", encoding="utf-8"
    )
    for rel in _PKG_FILES:
        dst = code / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_WORKSPACE / rel, dst)
    dist = code / "webui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>v1</html>\n", encoding="utf-8")
    subprocess.run(git + ["add", "."], check=True)
    subprocess.run(git + ["commit", "-qm", "fixture"], check=True)
    # canonical dual-root shared-state stores（preflight 要求存在且可写）
    (runtime / "experiences").mkdir(parents=True)
    (runtime / "data" / "methods").mkdir(parents=True)
    return code, runtime


def _expected_sidecar(runtime: Path) -> str:
    return (
        f"EXPERIENCES_DIR={runtime.resolve() / 'experiences'}\n"
        f"METHODS_DIR={runtime.resolve() / 'data' / 'methods'}\n"
    )


def _check_binding_gate(release: Path, runtime: Path) -> dict:
    """逐字复刻 restart_mirror.sh:952 的调用形态（含 env -u 七键）。"""
    env = dict(os.environ)
    for key in (
        "DATA_DIR",
        "LFL_DATA_DIR",
        "EXPERIENCES_DIR",
        "METHODS_DIR",
        "METHOD_SEED_DIR",
        "SKILLS_DIR",
        "DOCS_DIR",
    ):
        env.pop(key, None)
    env["LFL_WORKSPACE_ROOT"] = str(release)
    env["LFL_RUNTIME_ROOT"] = str(runtime)
    env["PYTHONPATH"] = str(release / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "llm_loop.runtime.knowledge_health", "--check-binding"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(release),
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    return json.loads(proc.stdout)


def test_publish_materializes_sidecar_and_binding_gate_passes_without_manual_patch(
    tmp_path: Path,
) -> None:
    code, runtime = _git_code_fixture(tmp_path)
    deployment = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    release = Path(deployment.code_root)
    sidecar = release / ".env"

    assert sidecar.is_file()
    assert (sidecar.stat().st_mode & 0o777) == 0o600
    assert sidecar.read_text(encoding="utf-8") == _expected_sidecar(runtime)
    assert tuple(
        line.split("=", 1)[0]
        for line in sidecar.read_text(encoding="utf-8").splitlines()
    ) == ("EXPERIENCES_DIR", "METHODS_DIR")

    payload = _check_binding_gate(release, runtime)
    assert payload["ok"] is True, payload
    assert payload["dual_root_shared_state"] is True
    assert payload["binding"]["experiences_source"] == "explicit_env"
    assert payload["binding"]["methods_source"] == "explicit_env"


def test_release_reuse_repairs_sidecar_drift_and_strips_foreign_keys(
    tmp_path: Path,
) -> None:
    code, runtime = _git_code_fixture(tmp_path)
    first = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    sidecar = Path(first.code_root) / ".env"

    sidecar.write_text(
        "EXPERIENCES_DIR=/bogus/experiences\n"
        "OPENAI_API_KEY=sk-must-be-stripped\n"
        "METHODS_DIR=/bogus/methods\n",
        encoding="utf-8",
    )
    sidecar.chmod(0o644)

    second = build_deployment(code_root=code, runtime_root=runtime, generation=2)
    assert second.git_head == first.git_head  # 复用路径触发修复
    assert sidecar.read_text(encoding="utf-8") == _expected_sidecar(runtime)
    assert "sk-must-be-stripped" not in sidecar.read_text(encoding="utf-8")
    assert (sidecar.stat().st_mode & 0o777) == 0o600
    assert _check_binding_gate(Path(second.code_root), runtime)["ok"] is True
