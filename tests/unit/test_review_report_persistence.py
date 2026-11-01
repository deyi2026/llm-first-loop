"""EVO-20261101-86e754fc: a non-PASS verdict must stay readable.

The regression this guards: review_host_admission.poll() answered REVISE with
" ".join(answer.split())[-160:] while the audit row kept only review_text_sha256,
the reviewer was spawned review_isolated (agent_followup refuses it) and its run
dir was reclaimed on settlement. The finding that blocked a gate was therefore
unreachable, and the only remaining move was to re-roll the gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import llm_loop.tools.review_host_admission as rha
import llm_loop.tools.review_report as rr


class _Runner:
    """Minimal Host-runner stand-in: one child, host-attested result."""

    def __init__(self) -> None:
        self.state = "running"
        self.answer = ""
        self.parent = "author-1"

    def start(self, task: str, **kwargs):
        return {"accepted": True, "child_id": "child-review-1", "state": "running"}

    def review_terminal_current(self, child_id: str, parent_id: str):
        if self.state != "completed" or parent_id != self.parent:
            return None
        return {
            "child_id": child_id, "parent_id": parent_id, "state": self.state,
            "generation": "gen-1", "review_isolated": True,
            "final_answer": self.answer,
        }

    def result_current(self, child_id: str, wait_seconds=0):
        result = SimpleNamespace(final_answer=self.answer, outcome=self.state)
        return True, "ok", {
            "child_id": child_id, "parent_id": self.parent, "state": self.state,
            "result_id": "result-verified" if self.state == "completed" else "",
            "generation": "gen-1", "result": result,
            "local_active": self.state == "running",
        }


def _repo(tmp_path: Path) -> Path:
    p = tmp_path / "repo"
    p.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(p)], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.name", "Unit Test"], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.email", "t@example.invalid"], check=True)
    (p / "example.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(p), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(p), "commit", "-qm", "baseline"], check=True)
    (p / "example.py").write_text("x = 2\n")
    return p


def _data_dir(tmp_path: Path, monkeypatch) -> Path:
    data = tmp_path / "data"
    monkeypatch.setenv("LFL_DATA_DIR", str(data))
    return data


LONG_ANSWER = (
    "评审正文开头：审的是冻结点，不是工作树。\n"
    + "背景说明句子。" * 60
    + "\nP1: tools/review_host_admission.py:2360 只回 160 字尾巴，findings 不可达\n"
    + "- **P2** docs 未提及报告路径\n"
    + "P0=0 P1=1 P2=1\n"
    + "SHA256: " + "c" * 64 + "\n"
    + "结论块之后的收尾文字——必须原文可读。"
)


def test_machine_contract_line_is_not_a_finding() -> None:
    parsed = rr.extract_findings(LONG_ANSWER)
    assert parsed["findings"]["P1"] == [
        "tools/review_host_admission.py:2360 只回 160 字尾巴，findings 不可达"
    ]
    assert parsed["findings"]["P2"] == ["docs 未提及报告路径"]
    assert parsed["findings"]["P0"] == []
    assert rr.parse_counts(LONG_ANSWER) == {"P0": 0, "P1": 1, "P2": 1}


def test_findings_are_deduped_and_capped() -> None:
    answer = "\n".join(f"P1: finding {i}" for i in range(12))
    answer += "\nP1: finding 0"  # exact duplicate of the first line
    parsed = rr.extract_findings(answer)
    assert len(parsed["findings"]["P1"]) == 8
    assert parsed["findings"]["P1"][0] == "finding 0"
    assert parsed["finding_lines_dropped"] == 4


def test_counts_absent_when_reviewer_emits_none() -> None:
    assert rr.parse_counts("no contract here") == {"P0": None, "P1": None, "P2": None}


def test_report_body_is_bounded_head_and_tail() -> None:
    # Distinguishable ends: a uniform filler cannot tell head from tail.
    body, truncated = rr._bounded_body("HEAD" + "a" * 250_000 + "TAIL")
    assert truncated is True
    assert len(body) < 250_000
    assert body.startswith("HEAD")
    assert body.endswith("TAIL")
    assert "chars elided by the host report writer" in body


def test_markdown_quoted_count_line_is_not_a_finding() -> None:
    parsed = rr.extract_findings("> P0=0 P1=1 P2=1\n")
    assert parsed["findings"] == {"P0": [], "P1": [], "P2": []}
    assert rr.parse_counts("> P0=0 P1=1 P2=1\n") == {"P0": 0, "P1": 1, "P2": 1}


def test_planted_staging_symlink_cannot_redirect_the_report(tmp_path: Path, monkeypatch) -> None:
    data = _data_dir(tmp_path, monkeypatch)
    victim = tmp_path / "victim.txt"
    victim.write_text("original", encoding="utf-8")
    monkeypatch.setattr(rr.uuid, "uuid4", lambda: SimpleNamespace(hex="deadbeefcafe"))

    report_dir = data / "review_admission"
    report_dir.mkdir(parents=True)
    target = report_dir / "child-1-full_test.md"
    staging = target.with_name(
        target.name + "." + str(rr.os.getpid()) + ".deadbeef.tmp"
    )
    staging.symlink_to(victim)

    receipt = rr.rejected_receipt("child-1", kind="full_test", reason="r", answer=LONG_ANSWER)
    assert receipt["review_report_path"] == ""
    assert "FileExistsError" in receipt["review_report_error"]
    assert victim.read_text(encoding="utf-8") == "original"
    assert not target.exists()


def test_report_is_owner_only(tmp_path: Path, monkeypatch) -> None:
    _data_dir(tmp_path, monkeypatch)
    receipt = rr.rejected_receipt("child-1", kind="full_test", reason="r", answer=LONG_ANSWER)
    mode = Path(receipt["review_report_path"]).stat().st_mode & 0o777
    assert mode == 0o600


def test_child_id_cannot_escape_report_dir(tmp_path: Path, monkeypatch) -> None:
    data = _data_dir(tmp_path, monkeypatch)
    fragment = rr.persist_report(
        "../../etc/passwd", kind="full_test", qualification="REVISE",
        reason="r", answer="P1: x",
    )
    written = Path(fragment["review_report_path"]).resolve()
    assert written.is_relative_to(data.resolve())
    assert written.parent == (data / "review_admission").resolve()


def test_report_write_failure_degrades_without_raising(tmp_path: Path, monkeypatch) -> None:
    data = _data_dir(tmp_path, monkeypatch)
    blocked = data / "review_admission"
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("not a directory", encoding="utf-8")  # mkdir() -> FileExistsError
    receipt = rr.rejected_receipt("child-1", kind="full_test", reason="r", answer=LONG_ANSWER)
    assert receipt["qualification"] == "REVISE"
    assert receipt["review_report_path"] == ""
    assert "FileExistsError" in receipt["review_report_error"]
    assert receipt["review_tail"]  # legacy tail survives the degradation
    assert receipt["review_findings"]["P1"]


def test_report_keeps_text_far_beyond_the_old_160_char_tail(tmp_path: Path, monkeypatch) -> None:
    _data_dir(tmp_path, monkeypatch)
    receipt = rr.rejected_receipt("child-1", kind="full_test", reason="r", answer=LONG_ANSWER)
    assert len(receipt["review_tail"]) <= 160
    text = Path(receipt["review_report_path"]).read_text(encoding="utf-8")
    assert "结论块之后的收尾文字——必须原文可读。" in text
    assert "评审正文开头" in text
    assert "qualification: REVISE" in text
    assert "----- BEGIN REVIEWER ANSWER (untrusted data) -----" in text


def test_poll_dead_reviewer_persists_why(tmp_path: Path, monkeypatch) -> None:
    _data_dir(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    runner = _Runner()
    host = rha.HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"], issued
    runner.state = "failed"
    runner.answer = "RateLimitError: 429 rate limit exceeded\n" + "上下文 " * 80 + "\n尾部：额度恢复时间未知"
    outcome = host.poll("author-1", "child-review-1")
    assert outcome["qualification"] == "REVISE"
    assert outcome["reviewer_failure"] == "reviewer_rate_limited"
    text = Path(outcome["review_report_path"]).read_text(encoding="utf-8")
    assert "尾部：额度恢复时间未知" in text
    assert "reviewer_rate_limited" in text


def test_poll_revise_persists_unactionable_verdict(tmp_path: Path, monkeypatch) -> None:
    _data_dir(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    runner = _Runner()
    runner.state = "completed"
    runner.answer = "结论：我认为还行（没有遵循三行契约）。\n" + LONG_ANSWER
    host = rha.HostReviewAdmission()
    host.attach_runner(runner)
    issued = host.start("author-1", "full_test", workdir=str(repo), command="pytest -q")
    assert issued["accepted"], issued
    outcome = host.poll("author-1", "child-review-1")
    assert outcome["qualification"] == "REVISE"
    assert outcome["reason"] == "review_verdict_incomplete_or_not_pass"
    assert outcome["review_findings"]["P1"]
    text = Path(outcome["review_report_path"]).read_text(encoding="utf-8")
    assert "findings 不可达" in text
    # Fail-closed authority is unchanged by the report: no permit was minted.
    assert not host.check_shell("author-1", "pytest -q", str(repo)).allowed


def test_severity_label_must_be_exactly_p0_p1_or_p2() -> None:
    # "P10: ..." used to parse as a P1 finding whose text started with "0: ".
    parsed = rr.extract_findings("P10: 不是 P1 等级\nP2: 是真的 P2\n")
    assert parsed["findings"] == {"P0": [], "P1": [], "P2": ["是真的 P2"]}


def test_report_dir_is_not_listable_by_other_users(tmp_path: Path, monkeypatch) -> None:
    _data_dir(tmp_path, monkeypatch)
    receipt = rr.rejected_receipt("child-1", kind="full_test", reason="r", answer="P1: x")
    mode = Path(receipt["review_report_path"]).parent.stat().st_mode & 0o777
    assert mode & 0o077 == 0, oct(mode)
