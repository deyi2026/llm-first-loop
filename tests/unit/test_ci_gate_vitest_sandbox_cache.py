"""Keep WebUI test writes inside the reviewed candidate's sandbox workspace."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ci_gate_scopes_workspace_private_tmp_to_node_commands() -> None:
    gate = (ROOT / "scripts" / "ci_gate.sh").read_text(encoding="utf-8")
    vite = (ROOT / "webui" / "vite.config.ts").read_text(encoding="utf-8")
    npm_test = gate.index("npm test -- --maxWorkers=2 --minWorkers=1")

    for declaration in (
        'CI_TEST_TMP="$CI_TEST_HOME/tmp"',
        'CI_TEST_VITE_CACHE="$CI_TEST_HOME/vite-cache"',
        'export LFL_CI_VITE_CACHE_DIR="$CI_TEST_VITE_CACHE"',
    ):
        assert declaration in gate
        assert gate.index(declaration) < npm_test

    assert "cacheDir: process.env.LFL_CI_VITE_CACHE_DIR || undefined" in vite
    assert "node_modules/.vite" not in gate[:npm_test]

    for command in ("npm run build", "npm test -- --maxWorkers=2 --minWorkers=1"):
        assert f'TMPDIR="$CI_TEST_TMP/" TMP="$CI_TEST_TMP" TEMP="$CI_TEST_TMP" {command}' in gate
    for variable in ("TMPDIR", "TMP", "TEMP"):
        assert f"export {variable}=" not in gate
