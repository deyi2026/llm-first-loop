"""Disposable Git shell integration: Host success/denial never touches real OS.

Only the TEST COPY of r9_commit.sh replaces the fixed Host executable with
an inert fake. Production code has no configurable Host-path override.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GRANT = "dev-commit-test-0123456789abcdef"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)


@pytest.fixture
def flow(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "feat/dev-flow")
    _git(repo, "config", "user.email", "flow@example.invalid")
    _git(repo, "config", "user.name", "Flow Test")
    scripts = repo / "scripts"
    scripts.mkdir()
    source = (ROOT / "scripts" / "r9_commit.sh").read_text()
    fixed = 'HOST_DEV_AUTH="/Library/Application Support/LFL-HostIssuer/bin/dev_commit_host_authority.py"'
    assert source.count(fixed) == 1
    source = source.replace(fixed, 'HOST_DEV_AUTH="scripts/fake_host_authority.py"')
    sudo = "/usr/bin/sudo -n -u _lfl_dual_witness /usr/bin/python3 -I -S"
    assert source.count(sudo) == 1
    source = source.replace(sudo, "bash scripts/fake_host.sh")
    _write(scripts / "r9_commit.sh", source)
    (scripts / "r9_probe_cleanup.sh").write_bytes(
        (ROOT / "scripts" / "r9_probe_cleanup.sh").read_bytes()
    )
    _write(scripts / "fake_host_authority.py", "# test-only inert placeholder\n")
    _write(
        scripts / "r9_commit_check.sh",
        '#!/usr/bin/env bash\necho CHECK >> "$FAKE_LOG"\nexit 0\n',
    )
    _write(
        scripts / "git_security_scan.sh",
        '#!/usr/bin/env bash\necho SCAN >> "$FAKE_LOG"\nexit 0\n',
    )
    _write(
        scripts / "ci_gate.sh",
        '#!/usr/bin/env bash\necho CI_CALLED >> "$FAKE_LOG"\nexit 99\n',
    )
    _write(
        scripts / "dev_gate.sh",
        '''#!/usr/bin/env bash
set -euo pipefail
[[ -z "${FAKE_GATE_FAIL:-}" ]] || exit 9
[[ -z "${LFL_PYTHON:-}" && -z "${PYTEST_ADDOPTS:-}" ]] || exit 17
while [[ "$#" -gt 0 ]]; do
  if [[ "$1" == --receipt ]]; then RECEIPT="$2"; fi
  shift
done
printf '%s\\n' '{"schema":"lfl.dev_gate.v1","status":"PASS"}' > "$RECEIPT"
echo DEV_GATE >> "$FAKE_LOG"
''',
    )
    _write(
        scripts / "fake_host.sh",
        '''#!/usr/bin/env bash
set -euo pipefail
echo HOST >> "$FAKE_LOG"
[[ -z "${FAKE_HOST_DENY:-}" ]] || exit 78
python3 -c '
import json,subprocess,sys,os
receipt=json.load(sys.stdin)
args=sys.argv[1:]
grant=args[args.index("--grant-id")+1]
tree=subprocess.check_output(["git","write-tree"],text=True).strip()
if receipt.get("status")!="PASS":
    sys.exit(78)
if os.environ.get("FAKE_HOST_BAD_REPLY"):
    tree="0"*40
print(json.dumps({"decision":"CONSUMED","grant_id":grant,"tree":tree,
                  "release_qualified":False}))
' "$@"
''',
    )
    _write(repo / "docs" / "design" / "approved.md", "# approved fixture\n")
    _write(repo / "feature.py", "value = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    _write(repo / "feature.py", "value = 2\n")
    _git(repo, "add", "feature.py")
    return repo, base, tmp_path / "flow.log"


def _run(flow, *, options=None, allowlist="feature.py", extra_env=None):
    repo, base, log = flow
    args = [
        "--dev", "--goal", "GOAL-20261120-022593f7",
        "--req", "REQ-FLOW-004", "--base", base,
        "--design", "docs/design/approved.md",
        "--grant-id", GRANT, "feat(r9): local dev feature",
    ]
    if options is not None:
        args = options
    env = {
        **os.environ, "R9_STAGED_ALLOW": allowlist,
        "FAKE_LOG": str(log), **(extra_env or {}),
    }
    result = subprocess.run(
        ["bash", "scripts/r9_commit.sh", *args],
        cwd=repo, capture_output=True, text=True,
        timeout=40, env=env,
    )
    events = log.read_text().splitlines() if log.exists() else []
    return result, events


def test_dev_commit_success_uses_probe_scan_gate_host_and_exact_tree(flow):
    repo, _, _ = flow
    tree = _git(repo, "write-tree")
    result, events = _run(flow)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "DEV_COMMIT_ONLY" in result.stdout
    assert events.count("CHECK") == 2
    assert "SCAN" in events and "DEV_GATE" in events and "HOST" in events
    assert "CI_CALLED" not in events
    assert events.index("SCAN") < events.index("DEV_GATE") < events.index("HOST")
    assert _git(repo, "rev-parse", "HEAD^{tree}") == tree
    assert _git(repo, "rev-list", "--count", "HEAD") == "2"
    assert len(_git(repo, "worktree", "list", "--porcelain").split("worktree ")) == 2


@pytest.mark.parametrize("failure,expected", [
    ({"FAKE_HOST_DENY": "1"}, "Host refused one-use grant"),
    ({"FAKE_HOST_BAD_REPLY": "1"}, "Host consumption response invalid"),
    ({"FAKE_GATE_FAIL": "1"}, ""),
])
def test_dev_failure_never_commits(flow, failure, expected):
    repo, _, _ = flow
    before = _git(repo, "write-tree")
    result, events = _run(flow, extra_env=failure)
    assert result.returncode != 0
    if expected:
        assert expected in result.stderr
    if "FAKE_GATE_FAIL" in failure:
        assert "HOST" not in events
    assert "CI_CALLED" not in events
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"
    assert _git(repo, "write-tree") == before


def test_allowlist_mismatch_denied_before_scan_or_lock(flow):
    repo, _, _ = flow
    result, events = _run(flow, allowlist="not-staged.py")
    assert result.returncode == 78
    assert "staged files do not exactly match allowlist" in result.stderr
    assert not events
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"


def test_dirty_worktree_denied_before_host_consumption(flow):
    repo, _, _ = flow
    _write(repo / "feature.py", "value = 3\n")
    result, events = _run(flow)
    assert result.returncode == 78
    assert "staged tree not clean or changed" in result.stderr
    assert "HOST" not in events
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"


def test_default_path_does_not_use_dev_shortcut(flow):
    repo, _, _ = flow
    result, events = _run(flow, options=["feat(r9): normal full gate"])
    assert result.returncode != 0
    assert "CI_CALLED" in events
    assert "HOST" not in events and "DEV_GATE" not in events
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"


def test_model_controlled_python_and_pytest_flags_cannot_skip_dev_gate(flow):
    repo, _, _ = flow
    result, events = _run(flow, extra_env={
        "LFL_PYTHON": "/bin/false", "PYTEST_ADDOPTS": "-k never",
    })
    assert result.returncode == 0, result.stderr + result.stdout
    assert "DEV_GATE" in events and "HOST" in events
    assert _git(repo, "rev-list", "--count", "HEAD") == "2"


def test_alternate_git_index_is_rejected_before_commit(flow):
    repo, _, _ = flow
    result, events = _run(flow, extra_env={"GIT_INDEX_FILE": "/tmp/untrusted-index"})
    assert result.returncode == 78
    assert "unsafe Git/shell environment: GIT_INDEX_FILE" in result.stderr
    assert not events
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"
