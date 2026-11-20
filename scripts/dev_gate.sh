#!/usr/bin/env bash
# Development-only incremental check. Never a substitute for original R9.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"
if [[ -n "${LFL_PYTHON:-}" ]]; then
  PY="$LFL_PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/../../.venv/bin/python" ]]; then
  # Worktree shares the main repository's managed environment.
  PY="$ROOT/../../.venv/bin/python"
else
  PY=python3
fi
exec "$PY" scripts/dev_gate.py "$@"
