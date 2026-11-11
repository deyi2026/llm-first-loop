"""EVO-20261111-c273f61c：replay 型 rebase 降级重验通道的机械判据与签发侧闸。

判据全部机检（patch-id 序列纯 replay + 路径不相交），任一判不了 fail-closed。
读侧 check_verify_covers_base 语义不变：carryover 只是签发一条 base=新 base 的
凭证行，降级闸全部在签发侧。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from llm_loop.introspection.merge_queue import (
    assess_rebase_replay,
    check_verify_covers_base,
    issue_verify_receipt,
    load_receipts,
)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if check:
        assert proc.returncode == 0, f"git {args} 失败: {proc.stderr.strip()}"
    return proc


def _commit(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo


@pytest.fixture()
def replay_repo(tmp_path: Path) -> dict:
    """old_base 上挂 lane 提交；随后 main 前进（不相交路径），lane rebase 纯 replay。"""
    repo = _make_repo(tmp_path)
    old_base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    old_head = _commit(repo, "lane_file.txt", "lane change\n")
    # main 前进：另一个文件（路径不相交）
    _git(repo, "checkout", "-b", "other", old_base)
    advance_head = _commit(repo, "other_file.txt", "upstream advance\n")
    _git(repo, "checkout", "main")
    _git(repo, "reset", "--hard", advance_head)
    # lane 分支 rebase 到前进后的 main
    _git(repo, "branch", "-f", "lane", old_head)
    _git(repo, "checkout", "lane")
    _git(repo, "rebase", "main")
    new_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    new_base = _git(repo, "rev-parse", "main").stdout.strip()
    return {
        "repo": repo,
        "old_base": old_base,
        "old_head": old_head,
        "new_base": new_base,
        "new_head": new_head,
    }


class TestAssessRebaseReplay:
    def test_pure_replay_disjoint_paths_eligible(self, replay_repo):
        r = assess_rebase_replay(
            replay_repo["repo"],
            old_base=replay_repo["old_base"],
            old_head=replay_repo["old_head"],
            new_base=replay_repo["new_base"],
            new_head=replay_repo["new_head"],
        )
        assert r["eligible"] is True
        assert r["patch_ids_match"] is True
        assert r["paths_disjoint"] is True
        assert r["commit_count"] == 1
        assert "lane_file.txt" in r["lane_paths"]
        assert "other_file.txt" in r["base_advance_paths"]

    def test_conflicting_rebase_breaks_replay(self, replay_repo, tmp_path):
        """rebase 中改了内容（patch-id 变化）⇒ 不 eligible（应拦核心场景）。"""
        repo = replay_repo["repo"]
        _git(repo, "checkout", "lane")
        (repo / "lane_file.txt").write_text("lane change MODIFIED\n", encoding="utf-8")
        _git(repo, "commit", "-am", "modify lane content")
        new_head2 = _git(repo, "rev-parse", "HEAD").stdout.strip()
        r = assess_rebase_replay(
            repo,
            old_base=replay_repo["old_base"],
            old_head=replay_repo["old_head"],
            new_base=replay_repo["new_base"],
            new_head=new_head2,
        )
        assert r["eligible"] is False
        assert r["patch_ids_match"] is False

    def test_overlapping_paths_not_eligible(self, replay_repo):
        """base 前进提交触碰 lane 修改的文件 ⇒ 路径相交 ⇒ 不 eligible。"""
        repo = replay_repo["repo"]
        _git(repo, "checkout", "main")
        (repo / "lane_file.txt").write_text("upstream touched lane file\n", encoding="utf-8")
        _git(repo, "add", "lane_file.txt")
        _git(repo, "commit", "-m", "upstream touches lane path")
        new_base2 = _git(repo, "rev-parse", "HEAD").stdout.strip()
        r = assess_rebase_replay(
            repo,
            old_base=replay_repo["old_base"],
            old_head=replay_repo["old_head"],
            new_base=new_base2,
            new_head=replay_repo["new_head"],
        )
        assert r["eligible"] is False
        assert r["paths_disjoint"] is False

    def test_bad_ref_fail_closed(self, replay_repo):
        r = assess_rebase_replay(
            replay_repo["repo"],
            old_base=replay_repo["old_base"],
            old_head="deadbeef0" * 4,
            new_base=replay_repo["new_base"],
            new_head=replay_repo["new_head"],
        )
        assert r["eligible"] is False
        assert "fail_closed" in r["reason"]


def _seed_old_receipt(tmp_path, rr, **kw):
    path = tmp_path / "receipts.jsonl"
    row = issue_verify_receipt(
        path,
        lane_id="lane-x",
        base_sha=rr["old_base"],
        head_sha=rr["old_head"],
        reviewer="merge-review",
        **kw,
    )
    return path, row["receipt_id"]


class TestIssueCarryoverReceipt:
    def test_carryover_issued_when_eligible(self, tmp_path, replay_repo):
        path, rid = _seed_old_receipt(tmp_path, replay_repo)
        row = issue_verify_receipt(
            path,
            lane_id="lane-x",
            base_sha=replay_repo["new_base"],
            head_sha=replay_repo["new_head"],
            carryover_of=rid,
            repo_path=replay_repo["repo"],
            old_base=replay_repo["old_base"],
            old_head=replay_repo["old_head"],
        )
        assert row["carryover_of"] == rid
        assert row["result"] == "pass"
        assert row["evo"] == "EVO-20261111-c273f61c"
        assert row["replay_evidence"]["patch_ids_match"] is True
        # 末行胜出：load 后该 lane+new_base 的行即 carryover 行
        loaded = load_receipts(path)
        assert loaded[row["receipt_id"]]["carryover_of"] == rid

    def test_carryover_refused_when_not_replay(self, tmp_path, replay_repo):
        """RULE-AI-35 应拦实测：判据不过时 carryover 签发必须被拒。"""
        path, rid = _seed_old_receipt(tmp_path, replay_repo)
        repo = replay_repo["repo"]
        _git(repo, "checkout", "lane")
        (repo / "lane_file.txt").write_text("semantic change\n", encoding="utf-8")
        _git(repo, "commit", "-am", "real change")
        bad_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        with pytest.raises(ValueError, match="carryover"):
            issue_verify_receipt(
                path,
                lane_id="lane-x",
                base_sha=replay_repo["new_base"],
                head_sha=bad_head,
                carryover_of=rid,
                repo_path=repo,
                old_base=replay_repo["old_base"],
                old_head=replay_repo["old_head"],
            )

    def test_carryover_refused_when_source_missing(self, tmp_path, replay_repo):
        path = tmp_path / "receipts.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="carryover"):
            issue_verify_receipt(
                path,
                lane_id="lane-x",
                base_sha=replay_repo["new_base"],
                head_sha=replay_repo["new_head"],
                carryover_of="lane-x:nonexist1",
                repo_path=replay_repo["repo"],
                old_base=replay_repo["old_base"],
                old_head=replay_repo["old_head"],
            )

    def test_carryover_refused_when_expired_source(self, tmp_path, replay_repo):
        path, rid = _seed_old_receipt(
            tmp_path, replay_repo, ttl_s=-1
        )
        with pytest.raises(ValueError, match="过期|expire"):
            issue_verify_receipt(
                path,
                lane_id="lane-x",
                base_sha=replay_repo["new_base"],
                head_sha=replay_repo["new_head"],
                carryover_of=rid,
                repo_path=replay_repo["repo"],
                old_base=replay_repo["old_base"],
                old_head=replay_repo["old_head"],
            )


class TestReaderSemanticsUnchanged:
    def test_check_verify_covers_base_accepts_carryover(self, tmp_path, replay_repo):
        """读侧零放宽：carryover 行 base=新 base，机检 d 语义原样通过。"""
        path, rid = _seed_old_receipt(tmp_path, replay_repo)
        row = issue_verify_receipt(
            path,
            lane_id="lane-x",
            base_sha=replay_repo["new_base"],
            head_sha=replay_repo["new_head"],
            carryover_of=rid,
            repo_path=replay_repo["repo"],
            old_base=replay_repo["old_base"],
            old_head=replay_repo["old_head"],
        )
        entry = {
            "lane_id": "lane-x",
            "base_main_sha": replay_repo["new_base"],
            "verify_ref": row["receipt_id"],
        }
        result = check_verify_covers_base(entry, load_receipts(path))
        assert result["check"] == "verify_covers_base"
        assert result["verdict"] == "pass"

    def test_check_verify_still_stale_for_old_base(self, tmp_path, replay_repo):
        """旧凭证在新 base 下仍判 verify_stale（原语义未动）。"""
        path, rid = _seed_old_receipt(tmp_path, replay_repo)
        entry = {
            "lane_id": "lane-x",
            "base_main_sha": replay_repo["new_base"],
            "verify_ref": rid,
        }
        result = check_verify_covers_base(entry, load_receipts(path))
        assert result["verdict"] == "fail"
        assert result["reason_code"] == "verify_stale"


class TestCliCarryoverSmoke:
    """CLI 参数粘合层冒烟：正常 carryover + 两个应拦分支。"""

    def _run_cli(self, *args):
        import sys
        cli = Path(__file__).resolve().parents[2] / "scripts" / "issue_verify_receipt.py"
        return subprocess.run(
            [sys.executable, str(cli), *args], capture_output=True, text=True, check=False
        )

    def test_cli_carryover_issue_and_refuse(self, tmp_path, replay_repo):
        rr = replay_repo
        receipts = tmp_path / "cli_receipts.jsonl"
        ok = self._run_cli(
            "--lane-id", "cli-lane",
            "--base-sha", rr["old_base"], "--head-sha", rr["old_head"],
            "--receipts-path", str(receipts), "--apply",
        )
        assert ok.returncode == 0, ok.stderr
        carry = self._run_cli(
            "--lane-id", "cli-lane",
            "--base-sha", rr["new_base"], "--head-sha", rr["new_head"],
            "--carryover-from", f"cli-lane:{rr['old_base'][:8]}",
            "--old-base", rr["old_base"], "--old-head", rr["old_head"],
            "--repo", str(rr["repo"]),
            "--receipts-path", str(receipts), "--apply",
        )
        assert carry.returncode == 0, carry.stderr
        assert "CARRYOVER of" in carry.stdout
        rows = [json.loads(ln) for ln in receipts.read_text().splitlines() if ln.strip()]
        assert rows[-1]["carryover_of"] == f"cli-lane:{rr['old_base'][:8]}"
        assert rows[-1]["evo"] == "EVO-20261111-c273f61c"
        # 应拦1：缺 --old-head ⇒ exit 2（fail-closed 提示）
        miss = self._run_cli(
            "--lane-id", "cli-lane",
            "--base-sha", rr["new_base"],
            "--carryover-from", f"cli-lane:{rr['old_base'][:8]}",
            "--repo", str(rr["repo"]),
            "--receipts-path", str(receipts), "--apply",
        )
        assert miss.returncode == 2
        assert "fail-closed" in miss.stderr
        # 应拦2：old-head 指向不相干提交（非纯 replay）⇒ ValueError 路径 exit != 0
        bad = self._run_cli(
            "--lane-id", "cli-lane",
            "--base-sha", rr["new_base"], "--head-sha", rr["new_head"],
            "--carryover-from", f"cli-lane:{rr['old_base'][:8]}",
            "--old-base", rr["old_base"], "--old-head", rr["new_base"],
            "--repo", str(rr["repo"]),
            "--receipts-path", str(receipts), "--apply",
        )
        assert bad.returncode != 0


class TestCarryoverSourceBinding:
    """P1（2026-11-11 审查）：源凭证必须绑定到被评估的 commit 范围。"""

    def test_carryover_refused_when_source_base_mismatches(self, tmp_path, replay_repo):
        """源凭证 base 与 old_base 不符（凭证不覆盖被评估范围）⇒ 拒绝。"""
        path, rid = _seed_old_receipt(tmp_path, replay_repo)
        with pytest.raises(ValueError, match="base_sha 与 old_base 不符"):
            issue_verify_receipt(
                path,
                lane_id="lane-x",
                base_sha=replay_repo["new_base"],
                head_sha=replay_repo["new_head"],
                carryover_of=rid,
                repo_path=replay_repo["repo"],
                old_base=replay_repo["new_base"],  # 伪造：评估范围不是源凭证覆盖的范围
                old_head=replay_repo["old_head"],
            )

    def test_carryover_refused_when_source_head_mismatches(self, tmp_path, replay_repo):
        """源凭证记录了 head 时必须与 old_head 一致 ⇒ 拒绝不符。"""
        path, rid = _seed_old_receipt(tmp_path, replay_repo)
        with pytest.raises(ValueError, match="head_sha 与 old_head 不符"):
            issue_verify_receipt(
                path,
                lane_id="lane-x",
                base_sha=replay_repo["new_base"],
                head_sha=replay_repo["new_head"],
                carryover_of=rid,
                repo_path=replay_repo["repo"],
                old_base=replay_repo["old_base"],
                old_head=replay_repo["new_base"],  # 伪造 old_head
            )


class TestWhitespaceVerbatim:
    """审查 P1（2026-11-11 第三轮）：裸 patch-id 忽略空白，Python 缩进即语义。"""

    def test_whitespace_only_change_is_not_replay(self, replay_repo):
        """rebase 后缩进变化（语义变化）必须判非 replay（--verbatim 应拦实测）。"""
        repo = replay_repo["repo"]
        _git(repo, "checkout", "lane")
        (repo / "lane_file.txt").write_text("lane change\n\tindented tail\n", encoding="utf-8")
        _git(repo, "commit", "-am", "whitespace change")
        ws_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        r = assess_rebase_replay(
            repo,
            old_base=replay_repo["old_base"],
            old_head=replay_repo["old_head"],
            new_base=replay_repo["new_base"],
            new_head=ws_head,
        )
        assert r["eligible"] is False
        assert r["patch_ids_match"] is False

    def test_empty_head_fail_closed(self, replay_repo):
        """空 rev 前置校验：new_head 空串不得把范围解析成 HEAD。"""
        r = assess_rebase_replay(
            replay_repo["repo"],
            old_base=replay_repo["old_base"],
            old_head=replay_repo["old_head"],
            new_base=replay_repo["new_base"],
            new_head="",
        )
        assert r["eligible"] is False
        assert "fail_closed" in r["reason"]
