"""Keep WebUI test writes inside the reviewed candidate's sandbox workspace."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ci_gate_exports_workspace_private_vitest_cache_and_tmp() -> None:
    gate = (ROOT / "scripts" / "ci_gate.sh").read_text(encoding="utf-8")
    vite = (ROOT / "webui" / "vite.config.ts").read_text(encoding="utf-8")
    npm_test = gate.index("npm test -- --maxWorkers=2 --minWorkers=1")

    for declaration in (
        'CI_TEST_TMP="$CI_TEST_HOME/tmp"',
        'CI_TEST_VITE_CACHE="$CI_TEST_HOME/vite-cache"',
        'export TMPDIR="$CI_TEST_TMP/"',
        'export TMP="$CI_TEST_TMP"',
        'export TEMP="$CI_TEST_TMP"',
        'export LFL_CI_VITE_CACHE_DIR="$CI_TEST_VITE_CACHE"',
    ):
        assert declaration in gate
        assert gate.index(declaration) < npm_test

    assert "cacheDir: process.env.LFL_CI_VITE_CACHE_DIR || undefined" in vite
    assert "node_modules/.vite" not in gate[:npm_test]
