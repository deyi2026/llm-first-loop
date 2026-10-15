"""Regression: deploying stale Web V2 JS/CSS must fail before any restart.

2026-10-15 incident: gen264 contained fixed ServicesPanel.tsx but its
gitignored dist was copied from an older, broken UI build. Artifact SHA
validated the stale copy, not its source provenance.
"""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from llm_loop.runtime.service_control import (
    DeploymentBindingError,
    build_deployment,
    main,
    verify_deployment_binding,
)
from llm_loop.runtime.webui_provenance import (
    tracked_webui_fingerprint,
    verify_webui_source_binding,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True, timeout=10,
    ).stdout.strip()


def _source_digest(root: Path) -> tuple[str, int]:
    """Independent test-side implementation of the build-provenance contract."""
    files = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "webui"],
        check=True, capture_output=True, timeout=10,
    ).stdout.split(b"\0")
    tracked = sorted(item for item in files if item)
    digest = hashlib.sha256()
    for raw_path in tracked:
        digest.update(raw_path)
        digest.update(b"\0")
        digest.update(hashlib.sha256((root / raw_path.decode()).read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest(), len(tracked)


def _create_repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "code"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "provenance@test.invalid")
    _git(root, "config", "user.name", "provenance-test")
    (root / ".gitignore").write_text("webui/dist/\n", encoding="utf-8")
    ui = root / "webui"
    (ui / "src").mkdir(parents=True)
    (ui / "package.json").write_text('{"name":"webui-fixture"}\n', encoding="utf-8")
    (ui / "src" / "main.tsx").write_text("export const layout = 'fixed-grid';\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixed source")
    dist = ui / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>old narrow grid</html>\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    return root, runtime


def _emit_fingerprint(root: Path) -> None:
    digest, count = _source_digest(root)
    (root / "webui" / "dist" / ".lfl-webui-source.json").write_text(
        json.dumps({
            "schema": "lfl-webui-source/v1",
            "source_sha256": digest,
            "tracked_files": count,
        }), encoding="utf-8",
    )


def test_publish_rejects_unproven_old_dist_before_materializing_release(tmp_path: Path) -> None:
    code, runtime = _create_repo(tmp_path)
    # Old source grid JS can be internally consistent and serve HTTP 200.
    # A new commit with correct JSX must not publish that old dist.
    with pytest.raises(DeploymentBindingError, match="webui source"):
        build_deployment(code_root=code, runtime_root=runtime, generation=1)
    assert not (runtime / ".releases").exists()


def test_publish_rejects_reused_bundle_when_tracked_source_changes(tmp_path: Path) -> None:
    code, runtime = _create_repo(tmp_path)
    _emit_fingerprint(code)
    (code / "webui" / "src" / "main.tsx").write_text(
        "export const layout = 'new approval scroll region';\n", encoding="utf-8",
    )
    _git(code, "add", "-A")
    _git(code, "commit", "-qm", "new source but reused dist")
    with pytest.raises(DeploymentBindingError, match="webui source"):
        build_deployment(code_root=code, runtime_root=runtime, generation=1)
    assert not (runtime / ".releases").exists()


def test_publish_rejects_untracked_frontend_inputs(tmp_path: Path) -> None:
    code, runtime = _create_repo(tmp_path)
    _emit_fingerprint(code)
    (code / "webui" / "src" / "untracked-component.tsx").write_text(
        "export const extra = true;\n", encoding="utf-8",
    )
    with pytest.raises(DeploymentBindingError, match="untracked WebUI inputs"):
        build_deployment(code_root=code, runtime_root=runtime, generation=1)
    assert not (runtime / ".releases").exists()


def test_symlink_outside_webui_is_rejected(tmp_path: Path) -> None:
    code, _ = _create_repo(tmp_path)
    outside = tmp_path / "external.txt"
    outside.write_text("not a WebUI source", encoding="utf-8")
    source = code / "webui" / "src" / "main.tsx"
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes webui"):
        tracked_webui_fingerprint(code)


@pytest.mark.parametrize("case", ["pass", "changed_source", "wrong_output_dir"])
def test_real_node_builder_and_python_verifier_agree(tmp_path: Path, case: str) -> None:
    """Exercise the exact Node build wrapper with fixture compiler executables."""
    code, _ = _create_repo(tmp_path)
    ui = code / "webui"
    wrapper = Path(__file__).resolve().parents[2] / "webui/scripts/build-with-source-binding.mjs"
    script = ui / "scripts" / "build-with-source-binding.mjs"
    script.parent.mkdir()
    shutil.copyfile(wrapper, script)
    (code / ".gitignore").write_text(
        "webui/dist/\nwebui/node_modules/\nwebui/alternate-dist/\n",
        encoding="utf-8",
    )
    _git(code, "add", "-A")
    _git(code, "commit", "-qm", "track reproducible build wrapper")
    bin_dir = ui / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    tsc = bin_dir / "tsc"
    tsc.write_text("#!/bin/sh\ntest \"$1\" = -b\n", encoding="utf-8")
    tsc.chmod(0o755)
    vite = bin_dir / "vite"
    if case == "pass":
        command = "mkdir -p dist; echo '<html>new</html>' > dist/index.html"
    elif case == "changed_source":
        command = "echo '// changed' >> src/main.tsx; mkdir -p dist; echo ok > dist/index.html"
    else:
        command = "mkdir -p alternate-dist; echo '<html>wrong</html>' > alternate-dist/index.html"
    vite.write_text(
        f"#!/bin/sh\ntest \"$1\" = build || exit 2\n{command}\n",
        encoding="utf-8",
    )
    vite.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["node", str(script)], cwd=ui, env=env,
        capture_output=True, text=True, timeout=20,
    )
    manifest = ui / "dist" / ".lfl-webui-source.json"
    if case == "pass":
        assert result.returncode == 0, result.stderr
        assert manifest.is_file()
        assert json.loads(manifest.read_text())["source_sha256"] == _source_digest(code)[0]
        verify_webui_source_binding(code)
    else:
        assert result.returncode != 0
        assert not manifest.exists()
        expected_error = "changed during build" if case == "changed_source" else "build.outDir"
        assert expected_error in (result.stderr + result.stdout)


def test_publish_accepts_exact_build_source_and_preserves_binding(tmp_path: Path) -> None:
    code, runtime = _create_repo(tmp_path)
    _emit_fingerprint(code)
    desired = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    release = Path(desired.code_root)
    assert (release / "webui" / "dist" / ".lfl-webui-source.json").exists()
    assert verify_deployment_binding(
        desired, code_root=release, runtime_root=runtime,
    ) == []


def test_restart_binding_detects_replaced_old_source_provenance(tmp_path: Path) -> None:
    code, runtime = _create_repo(tmp_path)
    _emit_fingerprint(code)
    desired = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    release = Path(desired.code_root)
    path = release / "webui" / "dist" / ".lfl-webui-source.json"
    bad = json.loads(path.read_text(encoding="utf-8"))
    bad["source_sha256"] = "0" * 64
    path.write_text(json.dumps(bad), encoding="utf-8")
    problems = verify_deployment_binding(
        desired, code_root=release, runtime_root=runtime,
    )
    assert any("webui artifact source binding invalid" in item for item in problems)


def test_cli_update_reports_stale_artifact_and_rebuild_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code, runtime = _create_repo(tmp_path)
    rc = main([
        "update", "--code-root", str(code), "--runtime-root", str(runtime),
        "--data-dir", str(runtime / "data"), "--target", "web",
    ])
    assert rc == 10
    output = capsys.readouterr().err
    payload = json.loads(next(line for line in output.splitlines() if line.startswith("{")))
    assert payload["error"] == "artifact_stale"
    assert "webui source binding" in payload["detail"]
    assert payload["next_step"][0]["problem_kind"] == "webui_artifact_mismatch"
    assert not (runtime / ".releases").exists()


def test_non_webui_fixture_keeps_existing_artifact_contract(tmp_path: Path) -> None:
    """Lightweight backend-only fixtures do not synthesize an npm provenance."""
    code, runtime = _create_repo(tmp_path)
    (code / "webui" / "package.json").unlink()
    _git(code, "add", "-A")
    _git(code, "commit", "-qm", "backend-only fixture")
    desired = build_deployment(code_root=code, runtime_root=runtime, generation=1)
    assert verify_deployment_binding(
        desired, code_root=Path(desired.code_root), runtime_root=runtime,
    ) == []
