"""review_admission 知识资产告警回归（2026-11-09 立；EVO-20261125-e802c5c8 P0 降为告警）。

背景：``.githooks/pre-push`` 的知识闸发生在审查全部跑完之后——卡片没入库时白烧
一个完整审查周期，模型只能从钩子的 stderr 反推原因（``--no-verify`` 还会绕开）。
2026-11-09 起本层把同一事实提前到 ``git_push`` 准入最前面并拒绝受理；但「工作区有
任何未入库卡即拒」把无关会话的知识债务记在每次代码推送头上（2026-11-25 02:13 实测
97 个文件全部非推送会话产物，受理恒拒）。P0 起两层同口径降为**结构化非阻塞告警**：
受理回执带机器可读的 ``warnings[]``，卡片入库走 ``scripts/knowledge_flush.py`` 独立安全批次。

口径必须与 ``scripts/knowledge_flush.py::collect()`` 及 pre-push 一致，否则两层互相打架：
1. 未入库卡 → 受理回执带 warnings[]（code=knowledge_flush_pending、blocking=false、
   cards/experiences 计数与样本路径），不拒绝；消费口只记审计事件，不消费资格；
2. 入库后 → 不再告警（不是恒告警，恒告警会训练出忽略习惯）；
3. 40 字节以下的半成品卡不计入——flush 也清不掉它，计入就是一条清不掉的告警；
4. 扫描失败 → 不伪报干净：告警码换成 knowledge_flush_scan_unavailable，同样不拒绝
   （RULE-AI-30 在告警级成立：闸已不挡路，看不见的后果只是少一条告警）；
5. 只作用于 git_push，full_test 的准入行为不变；
6. 回执占位闸不变，仍是硬拒绝——P0 只动知识闸（应拦输入仍拦）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.tools import review_host_admission as admission_module
from llm_loop.tools.review_host_admission import (
    AdmissionDecision,
    HostReviewAdmission,
    _consume_knowledge_warning,
    _knowledge_gate_warning,
    _receipt_placeholder_receipt,
)

# 生产无内置 reviewer 模型默认：测试必须显式声明模型链。
TEST_REVIEWER_MODELS = "glm/glm-5.3,glm/glm-5.3-flashx"

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


def _push_repo(tmp_path: Path) -> Path:
    """带 bare origin 的可推送仓库：git_push 的 start/_target 需要真实的远端 ref。

    origin/main 停在基线提交，本地在其上多一个 feature 提交——推送区间非空；
    未入库卡不在区间内（它们是别的会话的产物，与本次交付无关）。
    """
    repo = _repo(tmp_path)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(bare)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(bare)], check=True)
    base = _git(repo, "rev-parse", "HEAD")
    subprocess.run(
        ["git", "-C", str(repo), "push", "-q", "origin", base + ":refs/heads/main"], check=True,
    )
    (repo / "feature.py").write_text("y = 2\n")
    subprocess.run(["git", "-C", str(repo), "add", "feature.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "feature"], check=True)
    return repo


class _FakeRunner:
    """最小 reviewer 替身：受理成功并回 child-review-1，供 start/poll 端到端走通。"""

    def __init__(self) -> None:
        self.answer = ""
        self.state = "running"
        self.model = ""

    def start(self, task: str, **kwargs):
        self.model = str(kwargs["model"])
        return {
            "accepted": True, "child_id": "child-review-1", "state": "running",
            "model": kwargs["model"],
        }

    def review_terminal_current(self, child_id: str, parent_id: str):
        if self.state != "completed":
            return None
        return {
            "child_id": child_id, "parent_id": parent_id, "state": self.state,
            "generation": "gen-1", "review_isolated": True, "final_answer": self.answer,
            "observed_model": self.model,
        }

    def result_current(self, child_id: str, wait_seconds=0):
        result = SimpleNamespace(final_answer=self.answer, outcome=self.state)
        return True, "ok", {
            "child_id": child_id, "parent_id": "author-1", "state": self.state,
            "result_id": "result-verified" if self.state == "completed" else "",
            "generation": "gen-1", "result": result,
            "local_active": self.state == "running",
        }


def _host() -> HostReviewAdmission:
    host = HostReviewAdmission(reviewer_models_raw=TEST_REVIEWER_MODELS)
    host.attach_runner(_FakeRunner())
    return host


def test_untracked_card_does_not_block_start_before_target(tmp_path: Path, monkeypatch) -> None:
    """未入库方法卡不再挡受理：start 越过知识层走到了 _target（P0 前在这里被拒）。"""

    def _sentinel(*args, **kwargs):
        raise ValueError("sentinel_target_reached")

    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-1/METHOD.md")
    monkeypatch.setattr(HostReviewAdmission, "_target", staticmethod(_sentinel))
    receipt = _host().start(
        "author-1", "git_push", workdir=str(repo), command="git push origin main",
    )
    assert receipt["accepted"] is False
    assert receipt["reason"] == "sentinel_target_reached"


def test_foreign_cards_do_not_block_push_at_either_admission_layer(
    tmp_path: Path, monkeypatch
) -> None:
    """EVO 场景端到端：工作区有未入库卡 → start 受理并带 warnings；消费口放行且留审计。"""
    repo = _push_repo(tmp_path)
    _card(repo, "data/methods/foreign-1/METHOD.md")
    _card(repo, "experiences/EXPERIENCE-foreign.md", "# 经验\n" + "回归测试用经验正文。" * 3)
    runner = _FakeRunner()
    host = HostReviewAdmission(reviewer_models_raw=TEST_REVIEWER_MODELS)
    host.attach_runner(runner)
    issued = host.start("author-1", "git_push", workdir=str(repo), command="git push origin main")
    assert issued["accepted"] is True, issued
    assert len(issued["warnings"]) == 1
    warning = issued["warnings"][0]
    assert warning["code"] == "knowledge_flush_pending" and warning["blocking"] is False
    assert warning["cards"] == 1 and warning["experiences"] == 1
    assert "data/methods/foreign-1/METHOD.md" in warning["files"]
    assert "knowledge_flush.py" in warning["fix"]

    runner.answer = f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    runner.state = "completed"
    assert host.poll("author-1", "child-review-1")["qualification"] == "PASS"

    audited: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        host, "_audit", lambda parent, event, payload: audited.append((event, payload)),
    )
    decision = host.check_shell("author-1", "git push origin main", str(repo))
    assert decision.allowed is True, decision.reason
    knowledge_events = [
        payload for event, payload in audited if event == "review_admission_knowledge_warning"
    ]
    assert [item["code"] for item in knowledge_events] == ["knowledge_flush_pending"]
    assert knowledge_events[0]["blocking"] is False and knowledge_events[0]["cards"] == 1


def test_clean_workspace_receipt_carries_no_warnings(tmp_path: Path) -> None:
    """无未入库卡 → 受理回执没有 warnings 键（告警只在有事时出现）。"""
    repo = _push_repo(tmp_path)
    issued = _host().start(
        "author-1", "git_push", workdir=str(repo), command="git push origin main",
    )
    assert issued["accepted"] is True, issued
    assert "warnings" not in issued


def test_flushed_card_no_longer_warns(tmp_path: Path) -> None:
    """入库后 → 无告警（闸不是恒告警）。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-2/METHOD.md")
    _commit_all(repo, "flush cards")
    assert _knowledge_gate_warning(str(repo)) is None


def test_modified_tracked_card_is_pending(tmp_path: Path) -> None:
    """已入库卡片的未提交修改也算未入库（与 flush 的 M 口径一致）。"""
    repo = _repo(tmp_path)
    path = _card(repo, "data/methods/probe-3/METHOD.md")
    _commit_all(repo, "flush cards")
    path.write_text(CARD_BODY + "\n补充一行未入库的修改内容。\n")
    warning = _knowledge_gate_warning(str(repo))
    assert warning is not None and warning["cards"] == 1
    assert warning["code"] == "knowledge_flush_pending" and warning["blocking"] is False
    assert warning["files"] == ["data/methods/probe-3/METHOD.md"]


def test_experience_card_is_counted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _card(repo, "experiences/EXPERIENCE-probe.md", "# 经验\n" + "回归测试用经验正文。" * 3)
    warning = _knowledge_gate_warning(str(repo))
    assert warning is not None
    assert warning["experiences"] == 1 and warning["cards"] == 0


def test_card_directory_aux_file_is_pending(tmp_path: Path) -> None:
    """卡目录附属文件（qualification.json）随卡入库 → 也必须计入，否则与 flush 打架。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-4/METHOD.md")
    aux = _card(repo, "data/methods/probe-4/qualification.json", "{}\n")
    _commit_all(repo, "flush cards")
    aux.write_text('{"verdict": "pass"}\n')
    warning = _knowledge_gate_warning(str(repo))
    assert warning is not None
    assert warning["other_files"] == 1 and warning["cards"] == 0


def test_too_small_new_card_is_ignored(tmp_path: Path) -> None:
    """<40 字节的半成品卡不计入：flush 会跳过它，计入就是一条清不掉的告警。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-5/METHOD.md", "# 半成品\n")
    assert _knowledge_gate_warning(str(repo)) is None


def test_scan_failure_is_reported_not_clean(tmp_path: Path) -> None:
    """非 git 目录 → 无法判定 → 不伪报干净：给 scan_unavailable 告警，而不是拒绝。"""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    warning = _knowledge_gate_warning(str(plain))
    assert warning is not None
    assert warning["code"] == "knowledge_flush_scan_unavailable"
    assert warning["blocking"] is False
    assert "knowledge_flush.py --check --json" in warning["fix"]


def test_scan_failure_does_not_block_start(tmp_path: Path, monkeypatch) -> None:
    """知识扫描失败不挡受理：只把告警码换成 scan_unavailable，照常受理并留给调用方自查。

    只让知识扫描失败、仓库本身有效——回执占位闸在无效目录下的 fail-closed 拒绝
    （receipt_placeholder_scan_unavailable）不归本层管，也不该被这里顺带改掉。
    """

    def _scan_fails(root):
        raise ValueError("simulated knowledge scan failure")

    repo = _push_repo(tmp_path)
    monkeypatch.setattr(admission_module, "_knowledge_flush_pending", _scan_fails)
    issued = _host().start(
        "author-1", "git_push", workdir=str(repo), command="git push origin main",
    )
    assert issued["accepted"] is True, issued
    assert [item["code"] for item in issued["warnings"]] == ["knowledge_flush_scan_unavailable"]
    assert issued["warnings"][0]["blocking"] is False


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
    host = HostReviewAdmission(reviewer_models_raw=TEST_REVIEWER_MODELS)
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


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return out.stdout.strip()


# --- 审查残余③④（2026-11-09 收口）：admission 与 hook 同口径 ---
def test_committed_placeholder_with_backfilled_worktree_blocks_start(tmp_path: Path) -> None:
    """残余④：回执已提交占位、工作区已回填 → 必须按 HEAD blob 拒，不再白烧资格。"""
    repo = _repo(tmp_path)
    _receipt(repo, "| main_sha_after | 待回填 |\n")
    _commit_all(repo, "receipt v1")
    _git(repo, "update-ref", "refs/remotes/origin/main", _git(repo, "rev-parse", "HEAD~1"))
    # 工作区副本已回填（未提交）——旧实现读工作区会放行，push 时 hook 才拦
    _receipt(repo, "| main_sha_after | 4866ffa36 |\n")
    receipt = _receipt_placeholder_receipt(str(repo))
    assert receipt is not None
    assert receipt["accepted"] is False
    assert receipt["reason"] == "receipt_placeholder_pending"
    assert any("merge-probe.md" in f for f in receipt["files"])


def test_renamed_receipt_placeholder_in_range_blocks_start(tmp_path: Path) -> None:
    """残余③：rename+modify 的回执（--diff-filter=AM 为空）在 range 扫描中仍须命中。"""
    repo = _repo(tmp_path)
    path = _receipt(repo, "| main_sha_after | 4866ffa36 |\n")
    _commit_all(repo, "receipt old")
    _git(repo, "mv", "docs/governance/receipts/merge-probe.md",
         "docs/governance/receipts/merge-renamed.md")
    _commit_all(repo, "receipt renamed")
    path.unlink(missing_ok=True)
    (repo / "docs/governance/receipts/merge-renamed.md").write_text(
        "| main_sha_after | 待回填 |\n"
    )
    _commit_all(repo, "receipt placeholder")
    _git(repo, "update-ref", "refs/remotes/origin/main", _git(repo, "rev-parse", "HEAD~2"))
    receipt = _receipt_placeholder_receipt(str(repo))
    assert receipt is not None
    assert receipt["accepted"] is False
    assert receipt["reason"] == "receipt_placeholder_pending"
    assert any("merge-renamed.md" in f for f in receipt["files"])


def test_untracked_directory_row_enumerates_files(tmp_path: Path, monkeypatch) -> None:
    """审查 P2（full_test 复审）：status 折叠成目录行时不得因 IsADirectoryError 误拒。"""
    repo = _repo(tmp_path)
    _receipt(repo, "| main_sha_after | 待回填 |\n")  # 未跟踪回执（含占位）
    monkeypatch.setattr(
        admission_module,
        "_porcelain_rows",
        lambda raw: [("??", "docs/governance/receipts/")],
    )
    receipt = _receipt_placeholder_receipt(str(repo))
    assert receipt is not None
    assert receipt["accepted"] is False
    assert receipt["reason"] == "receipt_placeholder_pending"
    assert any("merge-probe.md" in f for f in receipt["files"])


# --- 收口治理③（2026-11-10）立；EVO-20261125-e802c5c8 P0：消费口只留审计 -------------
def test_consume_side_knowledge_is_audited_never_denied(
    tmp_path: Path, monkeypatch
) -> None:
    """消费口口径：有未入库卡 → 不拒绝、不消费资格，只记一条结构化告警（审计事件）。

    2026-11-10 的实现是「非消费性拒绝」：防审查窗口内新落卡导致 push 被 pre-push
    知识闸拦下而资格已消费。pre-push 同步降为告警后该风险不复存在，消费口不再拒绝；
    这里用哨兵证明它确实越过了知识层（P0 前在知识层被拒、到不了 _target）。
    """
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-consume/METHOD.md")
    host = HostReviewAdmission(reviewer_models_raw=TEST_REVIEWER_MODELS)
    record = admission_module._Frozen(
        kind="git_push", parent="author-2", target="git_push:origin/main:main",
        sha="a" * 64, child_id="child-consume", granted=True, consumed=False,
        created_at=0.0, state="settled",
    )
    host._records["child-consume"] = record
    monkeypatch.setattr(
        HostReviewAdmission,
        "_lane_push_precheck",
        staticmethod(lambda parent, command, workdir: None),
    )
    audited: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        host, "_audit", lambda parent, event, payload: audited.append((event, payload)),
    )

    class _ReachedError(Exception):
        pass

    def _sentinel(*args, **kwargs):  # 消费口必须先越过知识层再到 _target
        raise _ReachedError

    monkeypatch.setattr(HostReviewAdmission, "_target", staticmethod(_sentinel))
    with pytest.raises(_ReachedError):
        host.check_shell("author-2", "git push origin main", str(repo))
    assert [event for event, _payload in audited] == ["review_admission_knowledge_warning"]
    assert audited[0][1]["code"] == "knowledge_flush_pending"
    assert audited[0][1]["blocking"] is False


# --- EVO-20261123-d43138fc：纯删 ref 的 push 不受知识闸约束 -----------------
@pytest.mark.parametrize(
    "command",
    [
        "git push origin --delete feat/merged-branch",
        "git push --delete origin feat/merged-branch",
        "git push origin :feat/merged-branch",
        "git push origin --delete feat/a feat/b",
        "git push --no-verify origin --delete feat/merged-branch",
    ],
)
def test_delete_only_push_is_detected(command: str) -> None:
    """删除型 refspec 不携带任何提交/文件。"""
    assert admission_module._is_delete_only_push(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "",
        "git push origin main",
        "git push origin --delete feat/x && git push origin main",
        "git push origin :feat/x main",
        "git push --all origin",
        "git push --mirror origin",
        "git push --tags origin",
        "git push origin feat/x:main",
        "git push -u origin main",
        "git push origin --delete",
        "git push origin --delete 'weird ref'",
        "git push $R --delete feat/x",
        "git -C /tmp/repo push origin --delete feat/x",
    ],
)
def test_content_or_unreadable_push_is_not_exempt(command: str) -> None:
    """应拦输入仍拦：带内容/看不懂/多命令 → 照旧走知识判定，不豁免告警。"""
    assert admission_module._is_delete_only_push(command) is False


def test_start_preconditions_exempts_delete_only_push_only(tmp_path: Path) -> None:
    """有未入库卡时：删除型 push 连告警都不出；内容型 push 出告警但不再拒绝。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-delete/METHOD.md")
    _scope, _paths, denial, no_warnings = admission_module._start_preconditions(
        "git_push", "patch", ["example.py"], str(repo), "git push origin --delete feat/x"
    )
    assert denial is None, denial
    assert no_warnings == []
    _scope2, _paths2, unblocked, warnings = admission_module._start_preconditions(
        "git_push", "patch", ["example.py"], str(repo), "git push origin main"
    )
    assert unblocked is None, unblocked
    assert [item["code"] for item in warnings] == ["knowledge_flush_pending"]
    # 消费口同口径：纯删 ref 无告警，内容型 push 有告警。
    assert _consume_knowledge_warning(str(repo), "git push origin --delete feat/x") is None
    assert _consume_knowledge_warning(str(repo), "git push origin main")["code"] == (
        "knowledge_flush_pending"
    )


def test_receipt_placeholder_still_blocks_with_knowledge_pending(tmp_path: Path) -> None:
    """应拦输入仍拦：P0 只降知识闸；回执占位（交付证据不完整）仍是硬拒绝，且优先于告警。"""
    repo = _repo(tmp_path)
    _card(repo, "data/methods/probe-both/METHOD.md")
    _receipt(repo, "| main_sha_after | 待回填 |\n")
    _scope, _paths, denial, _warnings = admission_module._start_preconditions(
        "git_push", "patch", ["example.py"], str(repo), "git push origin main"
    )
    assert denial is not None and denial["reason"] == "receipt_placeholder_pending"
