"""B3: never confuse simulated fixtures with real independent A/B evidence."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_multiagent_convergence.py"
spec = importlib.util.spec_from_file_location("multiagent_benchmark", MODULE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(family: str, mode: str, index: int, wall: float) -> dict:
    return {
        "run_id": f"{family}-{mode}-{index}", "family": family, "mode": mode,
        "model_used": "test-model", "hardware_id": "test-host", "budget_tokens": 1000,
        "wall_seconds": wall, "candidate_sha": "a" * 40,
        "reviewer_sha": "a" * 40, "reviewer_verdict": "PASS",
        "p0": 0, "p1": 0, "r9_exit": 0, "ci_head_sha": "a" * 40,
        "ci_status": "success", "review_count": 1, "r9_count": 1,
        "rework_commits": 0, "tokens_input": 300, "tokens_output": 100,
        "cache_hit_tokens": 200, "unresolved_side_effects": 0,
        "evidence_refs": ["test-fixture-only"],
    }


def complete_rows() -> list[dict]:
    return [row(f, m, i, 100 if m == "serial" else (90 if m == "plain_parallel" else 70))
            for f in module.FAMILIES for m in module.MODES for i in range(2)]


def test_empty_and_partial_trials_never_claim_speedup() -> None:
    assert module.analyze_trials([])["status"] == "EXPLORATORY"
    assert module.analyze_trials([row("shared_api", "serial", 0, 10)])["speedup_claim"] is False


def test_eligible_repeated_comparable_fixture_measures_medians_without_claim() -> None:
    result = module.analyze_trials(complete_rows())
    assert result["status"] == "MEASURED_UNVERIFIED"
    assert result["speedup_claim"] is False
    assert result["candidate_speedup"] is True
    assert len(result["comparisons"]) == 3
    assert result["comparisons"][0]["speedup_fraction"] == 0.3


def test_gate_identity_and_approval_forgery_never_count() -> None:
    for field, value in (
        ("reviewer_sha", "b" * 40), ("ci_head_sha", "b" * 40),
        ("reviewer_verdict", "REVISE"), ("p1", 1), ("r9_exit", 1),
        ("ci_status", "pending"), ("unresolved_side_effects", 1),
    ):
        rows = complete_rows()
        rows[0][field] = value
        result = module.analyze_trials(rows)
        assert result["status"] == "NO_GO", (field, result)
        assert result["speedup_claim"] is False


def test_mismatched_model_or_unknown_usage_blocks_claim() -> None:
    rows = complete_rows()
    rows[0]["model_used"] = "another-model"
    assert module.analyze_trials(rows)["status"] == "INCOMPARABLE"
    rows = complete_rows()
    rows[0]["tokens_input"] = None
    assert module.analyze_trials(rows)["status"] == "INCOMPARABLE"


def test_no_speedup_is_not_reported_as_improvement() -> None:
    rows = complete_rows()
    for item in rows:
        if item["mode"] == "lfl_coordinated":
            item["wall_seconds"] = 110
    result = module.analyze_trials(rows)
    assert result["status"] == "NO_SPEEDUP_CLAIM"
    assert result["speedup_claim"] is False


def test_duplicate_run_id_is_rejected() -> None:
    rows = complete_rows()
    rows[1]["run_id"] = rows[0]["run_id"]
    assert module.analyze_trials(rows)["status"] == "NO_GO"


def test_cli_invalid_input_fails_closed(tmp_path: Path, capsys) -> None:
    path = tmp_path / "trials.jsonl"
    path.write_text('{"not": "complete"}\n')
    assert module.main(["--input", str(path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["speedup_claim"] is False


def test_b3_real_git_shared_api_and_same_file_isolated_integration(tmp_path: Path) -> None:
    """Real Git worktrees/commits; mechanical contract test, not LLM A/B."""
    import subprocess
    import sys

    def git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True,
            text=True, check=True,
        ).stdout.strip()

    def save(repo: Path, path: str, body: str, label: str) -> str:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        git(repo, "add", path)
        git(repo, "commit", "-m", label)
        return git(repo, "rev-parse", "HEAD")

    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    save(root, "api.py", "def value():\n    return 1\n", "base-api")
    base = save(root, "consumer.py", "from api import value\nassert value() == 1\n", "base")
    producer, consumer, integration = (tmp_path / x for x in ("producer", "consumer", "integration"))
    for branch, path in (("producer", producer), ("consumer", consumer),
                         ("integration", integration)):
        git(root, "worktree", "add", "-b", branch, str(path), base)
    producer_sha = save(producer, "api.py", "def value():\n    return 2\n", "producer-api-v2")
    consumer_sha = save(consumer, "consumer.py",
                        "from api import value\nassert value() == 2\n", "consumer-v2")
    git(integration, "cherry-pick", producer_sha)
    git(integration, "cherry-pick", consumer_sha)
    proc = subprocess.run([sys.executable, "consumer.py"], cwd=integration,
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr

    # Same file, separate functions: independent patch handoffs, one writer.
    body = ("def alpha():\n    return 1\n" + "\n".join(f"# gap {i}" for i in range(12))
            + "\n\ndef beta():\n    return 1\n")
    base2 = save(root, "module.py", body, "same-file-base")
    for path in (producer, consumer, integration):
        git(path, "reset", "--hard", base2)
    a_sha = save(producer, "module.py", body.replace("def alpha():\n    return 1",
                                                    "def alpha():\n    return 2"), "alpha")
    b_sha = save(consumer, "module.py", body.replace("def beta():\n    return 1",
                                                    "def beta():\n    return 3"), "beta")
    git(integration, "cherry-pick", a_sha)
    git(integration, "cherry-pick", b_sha)
    result = subprocess.run([sys.executable, "-c",
                             "from module import alpha,beta; assert (alpha(),beta()) == (2,3)"],
                            cwd=integration, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_bad_numeric_types_and_nan_never_crash_or_claim() -> None:
    for field, value in (("review_count", None), ("r9_count", "one"),
                         ("wall_seconds", float("nan")),
                         ("wall_seconds", float("inf"))):
        rows = complete_rows()
        rows[0][field] = value
        result = module.analyze_trials(rows)
        assert result["status"] == "NO_GO", (field, result)
        assert result["speedup_claim"] is False


def test_measured_unverified_candidate_cli_exit_is_not_success(tmp_path: Path, capsys) -> None:
    path = tmp_path / "unverified.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in complete_rows()))
    assert module.main(["--input", str(path)]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "MEASURED_UNVERIFIED"
    assert result["speedup_claim"] is False
    assert result["provenance_verified"] is False
