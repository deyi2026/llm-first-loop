"""Regression: deploying stale Web V2 JS/CSS must fail before any restart.

2026-10-15 incident: gen264 contained fixed ServicesPanel.tsx but its
gitignored dist was copied from an older, broken UI build. Artifact SHA
validated the stale copy, not its source provenance.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from llm_loop.runtime.service_control import (
    DeploymentBindingError,
    build_deployment,
    main,
    verify_deployment_binding,
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
