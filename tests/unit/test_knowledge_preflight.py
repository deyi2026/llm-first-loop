from pathlib import Path

from llm_loop.runtime.knowledge_health import run_preflight
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
