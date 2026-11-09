"""review_admission 知识资产闸回归（2026-11-09，RULE-AI-28 push 闸前置层）。

背景：``.githooks/pre-push`` 的知识闸发生在审查全部跑完之后——卡片没入库时白烧
一个完整审查周期，模型只能从钩子的 stderr 反推原因（``--no-verify`` 还会绕开）。
本层把同一事实提前到 ``git_push`` 准入最前面，给出机器可读 reason + 张数 + 修复命令。

口径必须与 ``scripts/knowledge_flush.py::collect()`` 一致，否则两个闸互相打架：
1. 未入库卡 → 拒（reason=knowledge_flush_pending，带 cards/experiences 计数）；
2. 入库后 → 不再拦（不是恒拒，恒拒会逼出绕过习惯）；
3. 40 字节以下的半成品卡不拦——flush 也清不掉它，拦了就是死锁；
4. 扫描失败 → fail-closed（RULE-AI-30）；
5. 只作用于 git_push，full_test 的准入行为不变。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from llm_loop.tools.review_host_admission import (
    AdmissionDecision,
    HostReviewAdmission,
    _knowledge_gate_receipt,
    _receipt_placeholder_receipt,
)

CARD_BODY = "# 测试卡\n" + "这是用于回归测试的临时方法卡正文，必须超过四十字节的入库阈值。" * 2


def _repo(tmp_path: Path) -> Path:
    p = tmp_path / "repo"
    p.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(p)], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.name", "Unit Test"], check=True)
    subprocess.run(["git", "-C", str(p), "config", "user.email", "test@example.invalid"], check=True)
    (p / "example.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(p), "add", "example.py"], check=True)
    subprocess.run(["git", "-C", str(p), "commit", "-qm", "baseline"], check=True)
    return p


def _card(repo: Path, rel: str, body: str = CARD_BODY) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _commit_all(repo: Path, msg: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", msg], check=True)


class _BlowUpRunner:
    """闸之后才该被碰到的依赖：一旦被调用就说明顺序错了。"""

    def start(self, *args, **kwargs):  # pragma: no cover - 只在顺序错时触发
        raise AssertionError("知识闸必须先于 reviewer spawn 判定")


def _host() -> HostReviewAdmission:
    host = HostReviewAdmission()
    host.attach_runner(_BlowUpRunner())
    return host


def test_untracked_card_blocks_start_before_review(tmp_path: Path, monkeypatch) -> None:
    """未入库方法卡 → start 在冻结材料/拉 reviewer 之前就拒。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-1/METHOD.md")

    def _sentinel(*args, **kwargs):  # pragma: no cover - 顺序错时才会走到
        raise AssertionError("知识闸必须先于 _target 判定")

    monkeypatch.setattr(HostReviewAdmission, "_target", staticmethod(_sentinel))
    receipt = _host().start(
        "author-1", "git_push", workdir=str(repo), command="git push origin main",
    )
    assert receipt["accepted"] is False
    assert receipt["reason"] == "knowledge_flush_pending"
    assert receipt["cards"] == 1 and receipt["experiences"] == 0
    assert "data/methods/probe-1/METHOD.md" in receipt["files"]
    assert "knowledge_flush.py" in receipt["fix"]


def test_flushed_card_no_longer_blocks(tmp_path: Path) -> None:
    """入库后 → 本层放行（闸不是恒拒）。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-2/METHOD.md")
    _commit_all(repo, "flush cards")
    assert _knowledge_gate_receipt(str(repo)) is None


def test_modified_tracked_card_is_pending(tmp_path: Path) -> None:
    """已入库卡片的未提交修改也算未入库（与 flush 的 M 口径一致）。"""
    repo = _repo(tmp_path)
    path = _card(repo, "data/methods/probe-3/METHOD.md")
    _commit_all(repo, "flush cards")
    path.write_text(CARD_BODY + "\n补充一行未入库的修改内容。\n")
    receipt = _knowledge_gate_receipt(str(repo))
    assert receipt is not None and receipt["cards"] == 1


def test_experience_card_is_counted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _card(repo, "experiences/EXPERIENCE-probe.md", "# 经验\n" + "回归测试用经验正文。" * 3)
    receipt = _knowledge_gate_receipt(str(repo))
    assert receipt is not None
    assert receipt["experiences"] == 1 and receipt["cards"] == 0


def test_card_directory_aux_file_is_pending(tmp_path: Path) -> None:
    """卡目录附属文件（qualification.json）随卡入库 → 也必须计入，否则与 flush 打架。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-4/METHOD.md")
    aux = _card(repo, "data/methods/probe-4/qualification.json", "{}\n")
    _commit_all(repo, "flush cards")
    aux.write_text('{"verdict": "pass"}\n')
    receipt = _knowledge_gate_receipt(str(repo))
    assert receipt is not None
    assert receipt["other_files"] == 1 and receipt["cards"] == 0


def test_too_small_new_card_is_ignored(tmp_path: Path) -> None:
    """<40 字节的半成品卡不拦：flush 会跳过它，拦了就没有可执行的修复路径。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-5/METHOD.md", "# 半成品\n")
    assert _knowledge_gate_receipt(str(repo)) is None


def test_scan_failure_is_fail_closed(tmp_path: Path) -> None:
    """非 git 目录 → 无法判定 → 拒绝（不静默放行）。"""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    receipt = _knowledge_gate_receipt(str(plain))
    assert receipt is not None
    assert receipt["accepted"] is False
    assert receipt["reason"] == "knowledge_flush_scan_unavailable"


def test_full_test_kind_is_not_gated(tmp_path: Path, monkeypatch) -> None:
    """full_test 不受本层影响：放行到 _target（这里用哨兵证明它确实被调用）。"""

    def _sentinel(*args, **kwargs):
        raise ValueError("sentinel_target_reached")

    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-6/METHOD.md")
    monkeypatch.setattr(HostReviewAdmission, "_target", staticmethod(_sentinel))
    receipt = _host().start(
        "author-1", "full_test", workdir=str(repo), command="pytest -q",
    )
    assert receipt["accepted"] is False
    assert receipt["reason"] == "sentinel_target_reached"


def _receipt(repo: Path, body: str) -> Path:
    path = repo / "docs/governance/receipts/merge-probe.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_untracked_placeholder_receipt_blocks_start(tmp_path: Path, monkeypatch) -> None:
    """未跟踪回执仍有「待回填」→ 在 _target/审查拉起之前拒（P5）。"""
    repo = _repo(tmp_path)
    _receipt(repo, "| main_sha_after | 待回填 |\n")

    def _sentinel(*args, **kwargs):  # pragma: no cover - 顺序错时才会走到
        raise AssertionError("回执占位闸必须先于 _target 判定")

    monkeypatch.setattr(HostReviewAdmission, "_target", staticmethod(_sentinel))
    receipt = _host().start(
        "author-1", "git_push", workdir=str(repo), command="git push origin main",
    )
    assert receipt["accepted"] is False
    assert receipt["reason"] == "receipt_placeholder_pending"
    assert receipt["files"] and "merge-probe.md:1" in receipt["files"][0]


def test_backfilled_receipt_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _receipt(repo, "| main_sha_after | 4866ffa36 |\n")
    assert _receipt_placeholder_receipt(str(repo)) is None


def test_receipt_scan_failure_is_fail_closed(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    receipt = _receipt_placeholder_receipt(str(plain))
    assert receipt is not None
    assert receipt["accepted"] is False
    assert receipt["reason"] == "receipt_placeholder_scan_unavailable"


def test_git_push_lane_precheck_runs_before_consume(monkeypatch, tmp_path: Path) -> None:
    """P2：lane 门命中时不得消费一次性资格（不得走到 _target/_consume）。"""
    host = HostReviewAdmission()
    monkeypatch.setattr(
        HostReviewAdmission,
        "_pending_scopes",
        staticmethod(lambda parent, kind: [((), "", (0, 0))]),
    )
    monkeypatch.setattr(
        HostReviewAdmission,
        "_lane_push_precheck",
        staticmethod(
            lambda parent, command, workdir: AdmissionDecision(
                False, "lane_precheck_denied"
            )
        ),
    )

    def _sentinel(*args, **kwargs):  # pragma: no cover - 顺序错时才会走到
        raise AssertionError("lane 预检必须先于资格消费")

    monkeypatch.setattr(HostReviewAdmission, "_target", staticmethod(_sentinel))
    decision = host.check_shell("parent", "git push origin main", str(tmp_path))
    assert decision.allowed is False
    assert "lane_precheck_denied" in decision.reason
