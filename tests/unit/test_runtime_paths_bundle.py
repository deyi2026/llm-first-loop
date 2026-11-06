"""Wheel install fallback: bundled assets are found without manual wiring.

A wheel install resolves the code root to the interpreter library directory,
which holds no docs/skills/methods; the tracked assets live in
``llm_loop/_bundled`` inside site-packages.  Without the fallback such an
install starts with zero rules, zero method seeds and zero skills.
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.runtime import installation
from llm_loop.runtime.paths import resolve_runtime_paths


def _code_root(tmp_path: Path) -> Path:
    code = tmp_path / "code"
    code.mkdir()
    return code


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "_bundled"
    for name in ("docs", "skills", "methods"):
        (bundle / name).mkdir(parents=True)
    return bundle


def test_bundle_assets_are_used_when_code_root_has_none(monkeypatch, tmp_path):
    code = _code_root(tmp_path)
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    paths = resolve_runtime_paths(
        data_dir=str(tmp_path / "data"),
        code_root=str(code),
        env={},
    )
    assert paths.docs_dir == (bundle / "docs").resolve()
    assert paths.skills_dir == (bundle / "skills").resolve()
    assert paths.method_seed_dir == (bundle / "methods").resolve()
    assert paths.docs_source == "package_bundle"
    assert paths.skills_source == "package_bundle"
    assert paths.method_seed_source == "package_bundle"


def test_explicit_env_wins_over_bundle(monkeypatch, tmp_path):
    code = _code_root(tmp_path)
    bundle = _bundle(tmp_path)
    monkeypatch.setattr(installation, "bundle_root", lambda: bundle)
    docs = tmp_path / "custom-docs"
    docs.mkdir()
    skills = tmp_path / "custom-skills"
    skills.mkdir()
    seeds = tmp_path / "custom-methods"
    seeds.mkdir()
    paths = resolve_runtime_paths(
        data_dir=str(tmp_path / "data"),
        code_root=str(code),
        env={
            "DOCS_DIR": str(docs),
            "SKILLS_DIR": str(skills),
            "METHOD_SEED_DIR": str(seeds),
        },
    )
    assert paths.docs_dir == docs.resolve()
    assert paths.docs_source == "explicit_env"
    assert paths.skills_dir == skills.resolve()
    assert paths.skills_source == "explicit_env"
    assert paths.method_seed_dir == seeds.resolve()
    assert paths.method_seed_source == "explicit_env"


def test_source_checkout_without_bundle_is_unchanged(monkeypatch, tmp_path):
    code = _code_root(tmp_path)
    for name in ("docs", "skills", "methods"):
        (code / name).mkdir()
    monkeypatch.setattr(installation, "bundle_root", lambda: None)
    paths = resolve_runtime_paths(
        data_dir=str(tmp_path / "data"),
        code_root=str(code),
        env={},
    )
    assert paths.docs_dir == (code / "docs").resolve()
    assert paths.skills_dir == (code / "skills").resolve()
    assert paths.method_seed_dir == (code / "methods").resolve()
    assert paths.docs_source == "code_root"
    assert paths.skills_source == "code_root"
    assert paths.method_seed_source == "code_root"


def test_missing_bundle_keeps_code_root_path(monkeypatch, tmp_path):
    code = _code_root(tmp_path)
    monkeypatch.setattr(installation, "bundle_root", lambda: None)
    paths = resolve_runtime_paths(
        data_dir=str(tmp_path / "data"),
        code_root=str(code),
        env={},
    )
    assert paths.docs_dir == (code / "docs").resolve()
    assert paths.docs_source == "code_root"
    assert not paths.docs_dir.exists()
