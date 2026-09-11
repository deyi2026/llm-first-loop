from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _web_service_version() -> str:
    tree = ast.parse((ROOT / "src/llm_loop/web/routes.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "SERVICE_VERSION"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError("SERVICE_VERSION literal not found")


def test_public_version_surfaces_match_project_version():
    version = _project_version()
    assert _web_service_version() == version

    for path in (ROOT / "README.md", ROOT / "README.en.md"):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"\*\*Version\*\*:\s*([0-9]+\.[0-9]+\.[0-9]+)", text)
        assert match is not None, f"public version marker missing: {path.name}"
        assert match.group(1) == version

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## v{version} " in changelog


def test_release_workflow_rejects_tag_package_version_mismatch():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "GITHUB_REF_NAME" in workflow
    assert "pyproject.toml" in workflow
    assert 'test "v${PACKAGE_VERSION}" = "${GITHUB_REF_NAME}"' in workflow
