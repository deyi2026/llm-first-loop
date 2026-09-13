from pathlib import Path

from llm_loop.runtime.knowledge_health import inspect_knowledge_health
from llm_loop.runtime.paths import resolve_runtime_paths


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_code_assets(code_root: Path) -> None:
    _touch(code_root / "methods" / "seed-one" / "METHOD.md")
    _touch(code_root / "skills" / "probe" / "SKILL.md")
    _touch(code_root / "docs" / "ai_rules.md", "## RULE-AI-00\nprobe\n")


def test_sidecar_missing_local_assets_auto_rebinds_to_canonical_store(tmp_path):
    canonical = tmp_path / "canonical"
    code_root = tmp_path / "sidecar"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    _seed_code_assets(code_root)
    _touch(canonical / "experiences" / "EXPERIENCE-20260913-known.md")
    _touch(data_dir / "methods" / "runtime-one" / "METHOD.md")
    _touch(code_root / "methods" / "seed-one" / "METHOD.md")
    _touch(code_root / "skills" / "probe" / "SKILL.md")
    _touch(code_root / "docs" / "ai_rules.md", "## RULE-AI-00\nprobe\n")

    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})
    health = inspect_knowledge_health(paths)

    assert health["status"] == "healthy"
    assert health["binding"]["auto_rebind_applied"] is True
    assert health["stores"]["experience"]["records"] == 1
    assert health["stores"]["runtime_method"]["records"] == 1
    assert health["stores"]["seed_method"]["records"] == 1
    assert health["stores"]["skill"]["records"] == 1
    assert health["stores"]["rule"]["records"] == 1
    assert health["writes_enabled"] is True


def test_nonempty_legacy_and_canonical_mutable_stores_quarantine_writes(tmp_path):
    canonical = tmp_path / "canonical"
    code_root = tmp_path / "sidecar"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    _seed_code_assets(code_root)
    _touch(canonical / "experiences" / "EXPERIENCE-20260913-canonical.md")
    _touch(code_root / "experiences" / "EXPERIENCE-20260913-fork.md")
    _touch(data_dir / "methods" / "canonical" / "METHOD.md")
    _touch(code_root / "data" / "methods" / "fork" / "METHOD.md")

    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})
    health = inspect_knowledge_health(paths)

    assert health["status"] == "quarantined"
    assert health["writes_enabled"] is False
    assert "legacy_experience_divergence" in health["reasons"]
    assert "legacy_method_divergence" in health["reasons"]


def test_explicit_overrides_are_operator_owned_not_called_auto_rebind(tmp_path):
    data_dir = tmp_path / "state" / "data"
    code_root = tmp_path / "code"
    exp = tmp_path / "explicit" / "experiences"
    methods = tmp_path / "explicit" / "methods"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    _seed_code_assets(code_root)
    _touch(exp / "EXPERIENCE-20260913-e.md")
    _touch(methods / "m" / "METHOD.md")

    paths = resolve_runtime_paths(
        data_dir=data_dir,
        code_root=code_root,
        env={"EXPERIENCES_DIR": str(exp), "METHODS_DIR": str(methods)},
    )
    health = inspect_knowledge_health(paths)

    assert health["status"] == "healthy"
    assert health["binding"]["auto_rebind_applied"] is False
    assert health["binding"]["experiences_source"] == "explicit_env"
    assert health["binding"]["methods_source"] == "explicit_env"


def test_recovery_receipt_is_deduped_and_never_written_when_quarantined(tmp_path):
    from llm_loop.runtime.knowledge_health import write_recovery_receipt

    canonical = tmp_path / "canonical"
    code_root = tmp_path / "sidecar"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    _seed_code_assets(code_root)
    _touch(canonical / "experiences" / "EXPERIENCE-20260913-ok.md")
    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})
    health = inspect_knowledge_health(paths)

    first = write_recovery_receipt(data_dir, paths, health, service="web")
    second = write_recovery_receipt(data_dir, paths, health, service="web")
    assert first is not None
    assert second == first
    assert first["action"] == "rebind"
    assert first["status"] == "recovered"
    log = data_dir / "runtime" / "knowledge_recovery.jsonl"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1

    # Legitimate store growth must not create a second "rebind" receipt.
    _touch(canonical / "experiences" / "EXPERIENCE-20260913-new.md")
    grown_health = inspect_knowledge_health(paths)
    third = write_recovery_receipt(data_dir, paths, grown_health, service="web")
    assert third == first
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1

    _touch(code_root / "experiences" / "EXPERIENCE-20260913-fork.md")
    bad = inspect_knowledge_health(paths)
    assert bad["status"] == "quarantined"
    assert write_recovery_receipt(data_dir, paths, bad, service="web") is None
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_persistent_baseline_detects_canonical_store_loss_without_count_equality(tmp_path):
    from llm_loop.runtime.knowledge_health import ensure_knowledge_baseline

    canonical = tmp_path / "canonical"
    code_root = tmp_path / "sidecar"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    _seed_code_assets(code_root)
    exp_a = canonical / "experiences" / "EXPERIENCE-20260913-a.md"
    exp_b = canonical / "experiences" / "EXPERIENCE-20260913-b.md"
    method = data_dir / "methods" / "runtime-one" / "METHOD.md"
    _touch(exp_a)
    _touch(exp_b)
    _touch(method)
    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})

    first = inspect_knowledge_health(paths)
    baseline = ensure_knowledge_baseline(paths, first)
    assert baseline is not None
    assert baseline["store_id"]
    assert baseline["generation"] == 1

    # Legitimate growth must not trip a fixed-count invariant.
    _touch(canonical / "experiences" / "EXPERIENCE-20260913-c.md")
    grown = inspect_knowledge_health(paths)
    assert grown["status"] == "healthy"

    # Total loss of a previously non-empty canonical store is a hard regression.
    for p in (exp_a, exp_b, canonical / "experiences" / "EXPERIENCE-20260913-c.md"):
        p.unlink()
    lost = inspect_knowledge_health(paths)
    assert lost["status"] == "quarantined"
    assert lost["writes_enabled"] is False
    assert "baseline_experience_empty_regression" in lost["reasons"]
    assert "baseline_experience_probe_missing" in lost["reasons"]


def test_corrupt_baseline_fails_closed_for_mutation(tmp_path):
    canonical = tmp_path / "canonical"
    code_root = tmp_path / "sidecar"
    data_dir = canonical / "data"
    data_dir.mkdir(parents=True)
    code_root.mkdir()
    _seed_code_assets(code_root)
    _touch(canonical / "experiences" / "EXPERIENCE-20260913-ok.md")
    baseline = data_dir / "runtime" / "knowledge_baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("{broken", encoding="utf-8")
    paths = resolve_runtime_paths(data_dir=data_dir, code_root=code_root, env={})

    health = inspect_knowledge_health(paths)
    assert health["status"] == "quarantined"
    assert health["writes_enabled"] is False
    assert "baseline_unreadable" in health["reasons"]
