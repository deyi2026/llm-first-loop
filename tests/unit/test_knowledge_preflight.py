from pathlib import Path

import pytest

from llm_loop.runtime.knowledge_health import check_store_binding, main, run_preflight
from llm_loop.runtime.paths import resolve_runtime_paths


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_code_assets(code_root: Path) -> None:
    _touch(code_root / "methods" / "seed-one" / "METHOD.md")
    _touch(code_root / "skills" / "probe" / "SKILL.md")
    _touch(code_root / "docs" / "ai_rules.md", "## RULE-AI-00\nprobe\n")


def test_preflight_initializes_baseline_and_passes_safe_rebind(tmp_path):
    canonical = tmp_path / "canonical"
    code_root = tmp_path / "sidecar"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    _seed_code_assets(code_root)
    _touch(canonical / "experiences" / "EXPERIENCE-20260913-ok.md")
    _touch(data_dir / "methods" / "m" / "METHOD.md")
    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})

    result = run_preflight(paths, initialize_baseline=True)
    assert result["ok"] is True
    assert result["health"]["status"] == "healthy"
    assert (data_dir / "runtime" / "knowledge_baseline.json").is_file()


def test_preflight_refuses_ambiguous_legacy_fork(tmp_path):
    canonical = tmp_path / "canonical"
    code_root = tmp_path / "sidecar"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    _seed_code_assets(code_root)
    _touch(canonical / "experiences" / "EXPERIENCE-20260913-ok.md")
    _touch(code_root / "experiences" / "EXPERIENCE-20260913-fork.md")
    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})

    result = run_preflight(paths, initialize_baseline=True)
    assert result["ok"] is False
    assert result["health"]["status"] == "quarantined"
    assert not (data_dir / "runtime" / "knowledge_baseline.json").exists()


def test_preflight_refuses_missing_tracked_governance_assets(tmp_path):
    canonical = tmp_path / "canonical"
    code_root = tmp_path / "broken-sidecar"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})

    result = run_preflight(paths, initialize_baseline=True)
    assert result["ok"] is False
    reasons = set(result["health"]["reasons"])
    assert {
        "rule_store_unavailable",
        "seed_method_store_unavailable",
        "skill_store_unavailable",
    } <= reasons
    assert not (data_dir / "runtime" / "knowledge_baseline.json").exists()


# ---------------------------------------------------------------------------
# R2.3 (SPEC-20260922-service-control-restart-fixpack-v1): dual-root 共享态部署
# 的 store 绑定部署预检——缺 EXPERIENCES_DIR/METHODS_DIR 显式声明即 fail。
# ---------------------------------------------------------------------------


def _dual_root_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Real linked worktree: main-root holds canonical/legacy stores, side is the deploy worktree."""
    import subprocess

    main = tmp_path / "main-root"
    main.mkdir()
    subprocess.run(["git", "-C", str(main), "init", "-q"], check=True)
    (main / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(main), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.email=ops@test.local",
            "-c",
            "user.name=ops",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    side = tmp_path / "side-worktree"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "deploy", str(side)], check=True)
    return main, side


def test_check_binding_dual_root_shared_state_requires_explicit_keys(tmp_path):
    main, side = _dual_root_fixture(tmp_path)
    paths = resolve_runtime_paths(data_dir=None, code_root=side, env={})

    result = check_store_binding(paths)

    assert result["dual_root_shared_state"] is True
    assert result["ok"] is False
    assert set(result["reasons"]) == {
        "dual_root_store_binding_missing:experiences",
        "dual_root_store_binding_missing:methods",
    }


def test_check_binding_dual_root_explicit_writable_stores_pass(tmp_path):
    main, side = _dual_root_fixture(tmp_path)
    (main / "experiences").mkdir()
    (main / "methods").mkdir()
    paths = resolve_runtime_paths(
        data_dir=None,
        code_root=side,
        env={
            "EXPERIENCES_DIR": str(main / "experiences"),
            "METHODS_DIR": str(main / "methods"),
        },
    )

    result = check_store_binding(paths)

    assert result["dual_root_shared_state"] is True
    assert result["ok"] is True
    assert result["reasons"] == []


def test_check_binding_dual_root_missing_store_dir_fails(tmp_path):
    main, side = _dual_root_fixture(tmp_path)
    paths = resolve_runtime_paths(
        data_dir=None,
        code_root=side,
        env={
            "EXPERIENCES_DIR": str(main / "experiences"),
            "METHODS_DIR": str(main / "methods"),
        },
    )

    result = check_store_binding(paths)

    assert result["ok"] is False
    assert set(result["reasons"]) == {
        "store_dir_missing:experiences",
        "store_dir_missing:methods",
    }


def test_check_binding_single_root_is_exempt(tmp_path):
    code_root = tmp_path / "plain"
    code_root.mkdir()
    paths = resolve_runtime_paths(data_dir=None, code_root=code_root, env={})

    result = check_store_binding(paths)

    assert result["dual_root_shared_state"] is False
    assert result["ok"] is True


def test_check_binding_sidecar_state_worktree_is_exempt(tmp_path):
    _main, side = _dual_root_fixture(tmp_path)
    paths = resolve_runtime_paths(
        data_dir=side / "data",
        code_root=side,
        env={},
        data_dir_explicit=True,
    )

    result = check_store_binding(paths)

    assert result["dual_root_shared_state"] is False
    assert result["ok"] is True


def test_check_binding_cli_modes_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--preflight", "--check-binding"])
    assert excinfo.value.code == 2
    assert "--preflight / --check-binding" in (capsys.readouterr().err or "exactly")
