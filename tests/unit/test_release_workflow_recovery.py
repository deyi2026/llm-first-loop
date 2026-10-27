"""v0.6.37 one-time release recovery must not alter immutable tag content."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/release.yml"
TAG_COMMIT = "8c8bb9971e1e409b1360f92837e7fe432d9e39ba"
TAG_OBJECT = "025eb7d1b81b5959662ec6158f1b9ebc939466c2"
VERIFIER_COMMIT = "d759c1b702aa9953b3dc9d10de091f29a931153a"
VERIFIER_SHA = "fb00b6c1fa83dd4d13041b497ee1403586a7f016e1d69f2340ff9f502945a1f9"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_release_still_has_one_draft_writer_and_tag_push():
    cfg = _workflow()
    triggers = cfg.get("on", cfg.get(True))  # PyYAML 1.1 resolves 'on' as bool
    assert triggers["push"]["tags"] == ["v*"]
    assert triggers["workflow_dispatch"]["inputs"]["recovery_tag"]["required"] is True
    actions = [
        step.get("uses", "")
        for job in cfg["jobs"].values()
        for step in job["steps"]
    ]
    assert actions.count("softprops/action-gh-release@v2") == 1
    assert set(cfg["jobs"]) == {"gate", "release"}
    assert cfg["jobs"]["release"]["needs"] == "gate"
    assert cfg["concurrency"]["cancel-in-progress"] is False


def test_dispatch_restricted_to_main_v0637_and_checkout_immutable_tag():
    cfg = _workflow()
    assert "github.ref == 'refs/heads/main'" in cfg["jobs"]["gate"]["if"]
    assert "inputs.recovery_tag == 'v0.6.37'" in cfg["jobs"]["release"]["if"]
    for job in cfg["jobs"].values():
        checkout = next(s for s in job["steps"] if s.get("uses") == "actions/checkout@v4")
        assert "inputs.recovery_tag" in checkout["with"]["ref"]
        assert "github.ref" in checkout["with"]["ref"]
        identity = next(s for s in job["steps"] if s.get("name", "").startswith("不可变 v0.6.37"))
        assert TAG_COMMIT in identity["run"]
        assert TAG_OBJECT in identity["run"]
        assert identity["if"].strip().endswith("github.event_name == 'workflow_dispatch' }}")
    gate_version = next(s for s in cfg["jobs"]["gate"]["steps"] if s.get("name") == "tag 与包版本一致性")
    assert 'test "v${PACKAGE_VERSION}" = "${RELEASE_TAG}"' in gate_version["run"]
    assert 'test "v${PACKAGE_VERSION}" = "${GITHUB_REF_NAME}"' in gate_version["run"]
    assert 'if [[ "${GITHUB_EVENT_NAME}" == "workflow_dispatch" ]]; then' in gate_version["run"]


def test_recovery_replaces_only_pinned_smoke_harness_not_release_source():
    cfg = _workflow()
    smoke = next(s for s in cfg["jobs"]["release"]["steps"] if s.get("name", "").startswith("独立安装与本地 Web 验收"))
    body = smoke["run"]
    assert VERIFIER_COMMIT + ":scripts/verify_install_distribution.py" in body
    assert VERIFIER_SHA in body
    assert "sha256sum -c -" in body
    assert 'python "${RUNNER_TEMP}/verify_install_distribution_recovery.py"' in body
    assert "python scripts/verify_install_distribution.py" in body
    assert "release_recovery_provenance" in body
    assert hashlib.sha256((ROOT / "scripts/verify_install_distribution.py").read_bytes()).hexdigest() == VERIFIER_SHA
    release = next(s for s in cfg["jobs"]["release"]["steps"] if s.get("uses") == "softprops/action-gh-release@v2")
    assert "inputs.recovery_tag" in release["with"]["tag_name"]
    assert set(release["with"]["files"].splitlines()) == {
        "dist/llm_first_loop-*.whl",
        "dist/llm_first_loop-*.tar.gz",
        "dist/install_linux.sh",
        "dist/uninstall_linux.sh",
        "dist/installation-smoke.json",
        "dist/linux-installer-smoke.json",
        "dist/SHA256SUMS",
    }
