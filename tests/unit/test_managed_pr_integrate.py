"""Fast protected PR integration: fail-closed risk, CI and merge tests."""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "managed_pr_integrate.py"
spec = importlib.util.spec_from_file_location("managed_pr_integrate", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

REPO = "example/llm-first-loop"
HEAD, BASE, MERGE = "a" * 40, "b" * 40, "c" * 40


class FakeGitHub:
    def __init__(self, *, files: list[str] | None = None) -> None:
        names = sorted(module._MINIMUM_CHECKS)
        self.calls: list[str] = []
        self.merge_calls: list[tuple[str, int, str]] = []
        self.pr = {
            "state": "open",
            "draft": False,
            "head": {"sha": HEAD, "repo": {"full_name": REPO}},
            "base": {"ref": "main", "sha": BASE},
            "mergeable": True,
            "mergeable_state": "clean",
            "changed_files": len(files or ["src/llm_loop/learning/summary.py"]),
            "merged": False,
        }
        self.main = {"object": {"sha": BASE}}
        self.files = [
            {"filename": path, "status": "modified"}
            for path in (files or ["src/llm_loop/learning/summary.py"])
        ]
        self.policy = {
            "schema": "lfl.required_checks.v1",
            "checks": [{"context": name, "app_id": 15368} for name in names],
        }
        self.protection = {
            "required_status_checks": {
                "strict": True,
                "checks": [{"context": name, "app_id": 15368} for name in names],
            },
            "enforce_admins": {"enabled": True},
        }
        self.runs = {
            "total_count": len(names),
            "check_runs": [
                {
                    "name": name,
                    "id": i + 1,
                    "app": {"id": 15368},
                    "head_sha": HEAD,
                    "status": "completed",
                    "conclusion": "success",
                }
                for i, name in enumerate(names)
            ],
        }
        self.merge_result = {"merged": True, "sha": MERGE}

    def get(self, path: str):
        self.calls.append(path)
        if path == f"repos/{REPO}/pulls/7":
            return copy.deepcopy(self.pr)
        if path == f"repos/{REPO}/git/ref/heads/main":
            return copy.deepcopy(self.main)
        if path == f"repos/{REPO}/pulls/7/files?per_page=100&page=1":
            return copy.deepcopy(self.files)
        if path == f"repos/{REPO}/branches/main/protection":
            return copy.deepcopy(self.protection)
        if path == f"repos/{REPO}/contents/docs/governance/required-ci-checks.json?ref=main":
            return {
                "encoding": "base64",
                "content": base64.b64encode(json.dumps(self.policy).encode()).decode(),
            }
        if path == f"repos/{REPO}/commits/{HEAD}/check-runs?per_page=100":
            return copy.deepcopy(self.runs)
        raise AssertionError(f"unexpected API path: {path}")

    def merge(self, repo: str, pr: int, head: str):
        self.merge_calls.append((repo, pr, head))
        self.pr.update({"merged": True, "state": "closed", "merge_commit_sha": MERGE})
        return copy.deepcopy(self.merge_result)


def integrate(api, repo, pr, head, base, *, apply):
    return module.integrate(
        api,
        repo,
        pr,
        head,
        base,
        apply=apply,
        slot_guard=lambda: nullcontext(),
    )


def test_apply_without_shared_merge_guard_holds():
    api = FakeGitHub()
    result = module.integrate(api, REPO, 7, HEAD, BASE, apply=True)
    assert (result.decision, result.reason) == ("HOLD", "merge_slot_guard_missing")
    assert not api.merge_calls


def test_existing_merge_slot_holder_blocks(tmp_path):
    (tmp_path / "merge_queue.jsonl").write_text(
        json.dumps(
            {
                "lane_id": "other-lane",
                "status": "merging",
                "version": 2,
            }
        )
        + "\n"
    )
    with pytest.raises(module.MergeSlotBusyError), module.local_merge_slot(tmp_path):
        pytest.fail("must not enter another lane's merge slot")


def test_empty_shared_merge_slot_allows(tmp_path):
    (tmp_path / "merge_queue.jsonl").write_text("")
    with module.local_merge_slot(tmp_path):
        pass


def test_cli_apply_uses_existing_merge_slot(tmp_path, capsys):
    (tmp_path / "merge_queue.jsonl").write_text("")
    api = FakeGitHub()
    rc = module.main(
        [
            "--repo",
            REPO,
            "--pr",
            "7",
            "--expected-head",
            HEAD,
            "--expected-base",
            BASE,
            "--apply",
            "--audit-dir",
            str(tmp_path),
        ],
        api=api,
    )
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "MERGED"
    assert api.merge_calls == [(REPO, 7, HEAD)]


def test_low_risk_ready_readonly(capsys):
    api = FakeGitHub()
    assert (
        module.main(
            ["--repo", REPO, "--pr", "7", "--expected-head", HEAD, "--expected-base", BASE], api=api
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["deployment"] == "not_requested"
    assert api.merge_calls == []


def test_apply_rechecks_and_merges_exact_head_only():
    api = FakeGitHub()
    result = integrate(api, REPO, 7, HEAD, BASE, apply=True)
    assert (result.decision, result.merge_commit) == ("MERGED", MERGE)
    assert api.merge_calls == [(REPO, 7, HEAD)]
    assert api.calls.count(f"repos/{REPO}/pulls/7") == 3
    assert not any("deploy" in call or "restart" in call for call in api.calls)


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "scripts/managed_pr_integrate.py",
        "docs/governance/required-ci-checks.json",
        "src/llm_loop/runtime/service_control.py",
        "src/llm_loop/tools/builtin/execute_command.py",
        "src/llm_loop/learning/auth_gateway.py",
        "src/llm_loop/learning/credential-store.py",
        "tests/unit/test_host_premerge.py",
        "pyproject.toml",
        "../outside.py",
    ],
)
def test_high_risk_path_never_auto_merges(path):
    api = FakeGitHub(files=[path])
    result = integrate(api, REPO, 7, HEAD, BASE, apply=True)
    assert (result.decision, result.risk) == ("HOLD", "high")
    assert not api.merge_calls


@pytest.mark.parametrize(
    ("key", "reason"),
    [
        ("head", "head_sha_changed"),
        ("base", "base_sha_changed"),
        ("main", "main_advanced"),
    ],
)
def test_sha_drift_holds(key, reason):
    api = FakeGitHub()
    if key == "head":
        api.pr["head"]["sha"] = "d" * 40
    elif key == "base":
        api.pr["base"]["sha"] = "d" * 40
    else:
        api.main["object"]["sha"] = "d" * 40
    assert integrate(api, REPO, 7, HEAD, BASE, apply=True).reason == reason
    assert not api.merge_calls


def test_missing_ci_waits():
    api = FakeGitHub()
    api.runs["check_runs"].pop()
    api.runs["total_count"] -= 1
    result = integrate(api, REPO, 7, HEAD, BASE, apply=True)
    assert (result.decision, result.reason) == ("WAIT", "required_check_missing")
    assert not api.merge_calls


def test_newer_pending_run_supersedes_old_success():
    api = FakeGitHub()
    run = copy.deepcopy(api.runs["check_runs"][0])
    run.update({"id": 999, "status": "in_progress", "conclusion": None})
    api.runs["check_runs"].append(run)
    api.runs["total_count"] += 1
    result = integrate(api, REPO, 7, HEAD, BASE, apply=True)
    assert (result.decision, result.reason) == ("WAIT", "required_check_pending")
    assert not api.merge_calls


def test_failed_required_ci_blocks_merge():
    api = FakeGitHub()
    api.runs["check_runs"][0]["conclusion"] = "failure"
    result = integrate(api, REPO, 7, HEAD, BASE, apply=True)
    assert (result.decision, result.reason) == ("HOLD", "required_check_not_success")
    assert not api.merge_calls


def test_wrong_check_publisher_is_not_trusted():
    api = FakeGitHub()
    api.runs["check_runs"][0]["app"]["id"] = 99999
    assert integrate(api, REPO, 7, HEAD, BASE, apply=True).decision == "WAIT"
    assert not api.merge_calls


@pytest.mark.parametrize("variant", ["strict_off", "admins_off", "policy_mismatch", "missing_ci"])
def test_protection_mismatch_holds(variant):
    api = FakeGitHub()
    if variant == "strict_off":
        api.protection["required_status_checks"]["strict"] = False
    elif variant == "admins_off":
        api.protection["enforce_admins"]["enabled"] = False
    elif variant == "policy_mismatch":
        api.policy["checks"][0]["app_id"] = 111
    else:
        api.protection["required_status_checks"]["checks"].pop()
    assert integrate(api, REPO, 7, HEAD, BASE, apply=True).decision == "HOLD"
    assert not api.merge_calls


def test_cross_repo_pr_holds():
    api = FakeGitHub()
    api.pr["head"]["repo"]["full_name"] = "unknown/fork"
    assert integrate(api, REPO, 7, HEAD, BASE, apply=True).decision == "HOLD"


def test_nonclean_github_mergeability_holds():
    api = FakeGitHub()
    api.pr["mergeable_state"] = "blocked"
    assert integrate(api, REPO, 7, HEAD, BASE, apply=True).decision == "HOLD"


def test_removed_file_is_high_risk():
    api = FakeGitHub()
    api.files[0]["status"] = "removed"
    assert integrate(api, REPO, 7, HEAD, BASE, apply=True).risk == "high"


def test_changed_file_count_mismatch_holds():
    api = FakeGitHub()
    api.pr["changed_files"] = 2
    assert integrate(api, REPO, 7, HEAD, BASE, apply=True).decision == "HOLD"


def test_pr_changed_between_first_and_second_read():
    api = FakeGitHub()
    original_get = api.get

    def changing_get(path):
        if path == f"repos/{REPO}/pulls/7" and api.calls.count(path) >= 1:
            api.pr["head"]["sha"] = "d" * 40
        return original_get(path)

    api.get = changing_get
    result = integrate(api, REPO, 7, HEAD, BASE, apply=True)
    assert result.reason == "head_sha_changed"
    assert not api.merge_calls


def test_unverified_merge_response_holds():
    api = FakeGitHub()
    api.merge_result = {"merged": True, "sha": "not-a-sha"}
    assert integrate(api, REPO, 7, HEAD, BASE, apply=True).decision == "HOLD"


def test_postcondition_mismatch_holds():
    api = FakeGitHub()
    api.merge_result["sha"] = "d" * 40
    result = integrate(api, REPO, 7, HEAD, BASE, apply=True)
    assert (result.decision, result.reason) == ("HOLD", "merge_postcondition_unverified")


def test_invalid_repo_identity_never_calls_api():
    api = FakeGitHub()
    assert integrate(api, "../unsafe", 7, HEAD, BASE, apply=True).decision == "HOLD"
    assert api.calls == []
