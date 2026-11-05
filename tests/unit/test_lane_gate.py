"""S1 十条机检执行器 + 自动回滚判定单测（RULE-AI-35: 应拦输入实拦才可宣称生效）.

覆盖（DESIGN-20261105 §4.4.1 / §10 P2b 判据）:
- 任务书指定的 3 个 RED: 审查凭证 SHA 不匹配 / paths 未声明·声明不完整 / main broken;
  另加 verify patch_digest 失配 RED 与十条逐行应拦输入（每行至少一条 fail 回执）。
- skip 语义: 仅 s1_08 依赖不可用（skip）→ 整单不得 pass; 全证据缺失 → 全 skip 不 pass。
- pass 语义: 全绿 → pass; impacted 级复验通过不受 base 漂移惩罚（D3/A2）;
  开关关 → human_confirm 回落 S0; 开关开不覆盖任何 fail。
- 自动回滚 should_auto_rollback: 开关关恒拒; main 前进拒; 归因不清拒;
  锚点缺失拒; main 未红拒; 全绿才 allow。
- git 只读助手: 真实 merge-tree 冲突被预检捕获并回灌机检（真拦截, 非只跑 pass 路径）。
"""

from __future__ import annotations

import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from llm_loop.introspection.lane_gate import (
    S1_CHECK_IDS,
    GateConfig,
    S1Evidence,
    evaluate_s1_gate,
    git_changed_files,
    git_head,
    git_merge_tree_conflicts,
    should_auto_rollback,
)

MAIN = "a" * 40
HEAD = "b" * 40
OTHER = "c" * 40
DIGEST = "d" * 64
NOW = "2026-11-05T12:00:00+08:00"
CREATED = "2026-11-05T10:00:00+08:00"  # 2h 前颁发, 远小于 TTL 86400s

GREEN_LANE: dict[str, Any] = {
    "lane_id": "lane-gate0001",
    "branch": "lane/20261105-gate",
    "worktree": "/tmp/wt-gate",
    "base_main_sha": MAIN,
    "goal_id": "goal-1",
    "paths": ["src/llm_loop/x", "tests/unit/test_x.py"],
    "status": "verifying",
    "head_sha": HEAD,
    "verify_ref": "vr-green",
}
GREEN_MAIN = {"head_sha": MAIN, "broken": False, "deploy_window": False, "last_good_sha": MAIN}
GREEN_VERIFY = {
    "receipt_id": "vr-green",
    "patch_digest": DIGEST,
    "base_sha": MAIN,
    "result": "pass",
    "scope": "full",
    "created_at": CREATED,
}
GREEN_REVIEW = {"verdict": "pass", "bound_sha": HEAD, "created_at": CREATED}
GREEN_DEPLOYMENT = {"target_sha": MAIN, "rollback_sha": MAIN, "ts": CREATED, "phase": "pre_deploy"}
GREEN_PRECHECK = {"source": "merge-tree", "conflicts": 0}
GREEN_BATCH = {
    "members": [{"lane_id": "lane-gate0001", "kind": "normal"}],
    "changed_files_total": 2,
}
GREEN_PLAN = {"no_ff": True, "parent_sha": MAIN}
GREEN_FILES = ["src/llm_loop/x/mod.py", "tests/unit/test_x.py"]


def _evidence(**over: Any) -> S1Evidence:
    ev = S1Evidence(
        lane=deepcopy(GREEN_LANE),
        main=deepcopy(GREEN_MAIN),
        verify=deepcopy(GREEN_VERIFY),
        current_patch_digest=DIGEST,
        review=deepcopy(GREEN_REVIEW),
        deployment=deepcopy(GREEN_DEPLOYMENT),
        merge_precheck=deepcopy(GREEN_PRECHECK),
        batch=deepcopy(GREEN_BATCH),
        help_requests=[],
        claim_overlaps=[],
        merge_plan=deepcopy(GREEN_PLAN),
        changed_files=list(GREEN_FILES),
        now_iso=NOW,
    )
    for key, value in over.items():
        setattr(ev, key, deepcopy(value))
    return ev


def _cfg(**over: Any) -> GateConfig:
    """测试默认配置: 开关开 + 显式 allowlist（第 5 行要求必须显式配置才可能 pass）。"""
    base: dict[str, Any] = {
        "lane_auto_merge": True,
        "auto_merge_allowlist": ("src/llm_loop", "tests"),
    }
    base.update(over)
    return GateConfig(**base)


def _gate(ev: S1Evidence, cfg: GateConfig | None = None) -> dict:
    return evaluate_s1_gate(ev, cfg if cfg is not None else _cfg())


def _check(result: dict, check_id: str) -> dict:
    return next(c for c in result["checks"] if c["check_id"] == check_id)


# ================================================================ 契约


def test_contract_ten_checks_in_canonical_order() -> None:
    result = _gate(_evidence())
    assert [c["check_id"] for c in result["checks"]] == list(S1_CHECK_IDS)
    for c in result["checks"]:
        assert set(c) == {"check_id", "condition", "verdict", "reason_code", "evidence"}
        assert c["verdict"] in ("pass", "fail", "skip")


# ================================================================ RED: 应拦输入实拦（任务书指定 3 条 + 凭证 digest）


def test_red_review_receipt_sha_mismatch_denied() -> None:
    """RED 1: 独立审查回执绑定 SHA != lane.head_sha → fail, 回执带 reason_code."""
    ev = _evidence(review={"verdict": "pass", "bound_sha": OTHER, "created_at": CREATED})
    result = _gate(ev)
    assert result["verdict"] == "fail"
    c = _check(result, "s1_04")
    assert c["verdict"] == "fail"
    assert c["reason_code"] == "review_sha_mismatch"
    assert c["evidence"]["bound_sha"] == OTHER and c["evidence"]["head_sha"] == HEAD
    assert "s1_04" in result["auto_denied"]
    assert result["auto_merge_allowed"] is False  # 开关开着也不放行


def test_red_verify_patch_digest_mismatch_denied() -> None:
    """RED 1b: 验证凭证 patch_digest 与当前 patch 不匹配 → fail verify_stale（D3: patch 变则凭证废）。"""
    ev = _evidence(current_patch_digest="e" * 64)
    result = _gate(ev)
    c = _check(result, "s1_03")
    assert c["verdict"] == "fail" and c["reason_code"] == "verify_stale"
    assert c["evidence"]["patch_digest"] == DIGEST
    assert result["verdict"] == "fail" and "s1_03" in result["auto_denied"]


def test_red_paths_undeclared_denied() -> None:
    """RED 2: paths 完全未声明 → fail paths_undeclared."""
    ev = _evidence(lane={**GREEN_LANE, "paths": []})
    result = _gate(ev)
    c = _check(result, "s1_05")
    assert c["verdict"] == "fail" and c["reason_code"] == "paths_undeclared"
    assert "s1_05" in result["auto_denied"] and result["verdict"] == "fail"


def test_red_paths_declaration_incomplete_denied() -> None:
    """RED 2b: 声明不完整——改动面出现未声明文件 → fail, 回执列出未声明文件."""
    ev = _evidence(lane={**GREEN_LANE, "paths": ["src/llm_loop/x"]})
    result = _gate(ev)
    c = _check(result, "s1_05")
    assert c["verdict"] == "fail" and c["reason_code"] == "paths_undeclared"
    assert c["evidence"]["undeclared_files"] == ["tests/unit/test_x.py"]


def test_red_main_broken_denied() -> None:
    """RED 3: main_broken=true → fail main_broken, 整单 fail（A5/D5 联动口径）。"""
    ev = _evidence(main={**GREEN_MAIN, "broken": True})
    result = _gate(ev)
    c = _check(result, "s1_01")
    assert c["verdict"] == "fail" and c["reason_code"] == "main_broken"
    assert result["verdict"] == "fail"
    assert result["auto_merge_allowed"] is False
    assert result["decision"] == "human_confirm" and result["decision_reason"] == "checks_failed"


# ================================================================ RED: 十条逐行应拦（RULE-AI-35 面覆盖）


def test_red_deploy_window_denied() -> None:
    ev = _evidence(main={**GREEN_MAIN, "deploy_window": True})
    c = _check(_gate(ev), "s1_01")
    assert c["verdict"] == "fail" and c["reason_code"] == "deploy_window"


def test_red_deploy_state_undeterminable_denied() -> None:
    ev = _evidence(main={"head_sha": MAIN, "broken": False})  # deploy_window 缺失
    c = _check(_gate(ev), "s1_01")
    assert c["verdict"] == "fail" and c["reason_code"] == "deploy_window"


def test_red_conflict_precheck_denied() -> None:
    ev = _evidence(merge_precheck={"source": "merge-tree", "conflicts": ["src/llm_loop/x/mod.py"]})
    c = _check(_gate(ev), "s1_02")
    assert c["verdict"] == "fail" and c["reason_code"] == "conflict_precheck"


def test_red_verify_base_drift_without_impacted_recheck_denied() -> None:
    """base 漂移且无 impacted 复验 → verify_stale（绿但错防线, D3）。"""
    ev = _evidence(verify={**GREEN_VERIFY, "base_sha": OTHER})
    c = _check(_gate(ev), "s1_03")
    assert c["verdict"] == "fail" and c["reason_code"] == "verify_stale"
    assert c["evidence"]["base_sha"] == OTHER and c["evidence"]["main_head"] == MAIN


def test_red_verify_contract_hit_denied() -> None:
    """base 漂移 + 契约变更命中 → 必须全量重跑, 凭证不得复用（A3）。"""
    ev = _evidence(verify={**GREEN_VERIFY, "base_sha": OTHER, "scope": "impacted",
                           "impacted_result": "pass", "contract_hit": True})
    c = _check(_gate(ev), "s1_03")
    assert c["verdict"] == "fail" and c["reason_code"] == "verify_stale"


def test_red_verify_expired_denied() -> None:
    old = "2026-11-04T00:00:00+08:00"  # > 24h TTL
    ev = _evidence(verify={**GREEN_VERIFY, "created_at": old})
    c = _check(_gate(ev), "s1_03")
    assert c["verdict"] == "fail" and c["reason_code"] == "verify_stale"


def test_red_review_missing_denied() -> None:
    c = _check(_gate(_evidence(review=None)), "s1_04")
    assert c["verdict"] == "fail" and c["reason_code"] == "review_missing"


def test_red_path_not_allowed_default_empty_allowlist_denied() -> None:
    """默认 GateConfig（allowlist 空）→ 全不自动（设计表第 5 行的字面语义）。"""
    result = _gate(_evidence(), GateConfig())
    c = _check(result, "s1_05")
    assert c["verdict"] == "fail" and c["reason_code"] == "path_not_allowed"
    assert c["evidence"]["allowlist"] == []


def test_red_path_not_allowed_outside_allowlist_denied() -> None:
    ev = _evidence()  # 改动面含 src/llm_loop 与 tests, 但 allowlist 只放 docs
    c = _check(_gate(ev, _cfg(auto_merge_allowlist=("docs",))), "s1_05")
    assert c["verdict"] == "fail" and c["reason_code"] == "path_not_allowed"
    assert "src/llm_loop/x/mod.py" in c["evidence"]["outside_allowlist"]


def test_red_sealed_path_denied() -> None:
    ev = _evidence(
        changed_files=["docs/rules/RULE-AI-30.md", "src/llm_loop/x/mod.py"],
        lane={**GREEN_LANE, "paths": ["docs/rules", "src/llm_loop/x"]},
    )
    c = _check(_gate(ev, _cfg(auto_merge_allowlist=("docs", "src/llm_loop"))), "s1_06")
    assert c["verdict"] == "fail" and c["reason_code"] == "sealed_path"
    assert c["evidence"]["hits"] == ["docs/rules/RULE-AI-30.md"]


def test_red_budget_weight_exceeded_denied() -> None:
    batch = {"members": [
        {"lane_id": "l1", "kind": "normal"},
        {"lane_id": "l2", "kind": "normal"},
        {"lane_id": "l3", "kind": "normal"},
        {"lane_id": "l4", "kind": "docs-only"},  # 1+1+1+0.3 = 3.3 > K_MAX=3
    ], "changed_files_total": 10}
    c = _check(_gate(_evidence(batch=batch)), "s1_07")
    assert c["verdict"] == "fail" and c["reason_code"] == "budget_exceeded"
    assert c["evidence"]["weight_sum"] == 3.3 and c["evidence"]["k_max"] == 3


def test_red_budget_files_exceeded_denied() -> None:
    batch = {"members": [{"lane_id": "l1", "kind": "docs-only"}], "changed_files_total": 31}
    c = _check(_gate(_evidence(batch=batch)), "s1_07")
    assert c["verdict"] == "fail" and c["reason_code"] == "budget_exceeded"
    assert c["evidence"]["changed_files_total"] == 31 and c["evidence"]["f_max"] == 30


def test_red_help_blocking_denied() -> None:
    ev = _evidence(help_requests=[{"id": "h1", "need": "block", "state": "pending"}])
    c = _check(_gate(ev), "s1_08")
    assert c["verdict"] == "fail" and c["reason_code"] == "help_blocking"
    assert c["evidence"]["blocking"] == ["h1"]


def test_help_info_level_not_blocking() -> None:
    """need=info 的未决请求不拦（只有 need=block 拦, 设计表第 8 行字面语义）。"""
    ev = _evidence(help_requests=[{"id": "h2", "need": "info", "state": "pending"}])
    assert _check(_gate(ev), "s1_08")["verdict"] == "pass"


def test_red_claim_overlap_denied() -> None:
    ev = _evidence(claim_overlaps=[{"lane_id": "lane-other", "shared_paths": ["src/llm_loop/x/mod.py"]}])
    c = _check(_gate(ev), "s1_09")
    assert c["verdict"] == "fail" and c["reason_code"] == "claim_overlap"


def test_red_not_revertible_ff_denied() -> None:
    c = _check(_gate(_evidence(merge_plan={"no_ff": False, "parent_sha": MAIN})), "s1_10")
    assert c["verdict"] == "fail" and c["reason_code"] == "not_revertible"


def test_red_not_revertible_parent_not_main_head_denied() -> None:
    c = _check(_gate(_evidence(merge_plan={"no_ff": True, "parent_sha": OTHER})), "s1_10")
    assert c["verdict"] == "fail" and c["reason_code"] == "not_revertible"
    assert c["evidence"]["parent_sha"] == OTHER and c["evidence"]["main_head"] == MAIN


# ================================================================ skip 语义（skip ≠ pass）


def test_skip_s1_08_dependency_unavailable_blocks_whole_gate() -> None:
    """任务书指定: 仅 s1_08 为 skip（P1 收件箱未接入）时整单不得放行."""
    ev = _evidence(help_requests=None)
    result = _gate(ev)
    c = _check(result, "s1_08")
    assert c["verdict"] == "skip"
    assert c["reason_code"] == "dependency_unavailable"
    assert result["verdict"] == "fail"  # skip ≠ pass
    assert "s1_08" in result["auto_denied"]
    assert result["auto_merge_allowed"] is False


def test_skip_s1_09_dependency_unavailable_blocks_whole_gate() -> None:
    ev = _evidence(claim_overlaps=None)
    result = _gate(ev)
    assert _check(result, "s1_09")["verdict"] == "skip"
    assert result["verdict"] == "fail" and "s1_09" in result["auto_denied"]


def test_all_evidence_missing_never_passes() -> None:
    """全证据缺失 → 全 skip, 整单 fail（不是 pass）。"""
    result = _gate(S1Evidence(lane=deepcopy(GREEN_LANE)))
    assert all(c["verdict"] != "pass" for c in result["checks"])
    assert result["verdict"] == "fail"
    assert result["auto_denied"] == list(S1_CHECK_IDS)
    assert result["auto_merge_allowed"] is False


# ================================================================ pass 语义


def test_green_all_ten_pass() -> None:
    result = _gate(_evidence())
    assert result["verdict"] == "pass"
    assert result["auto_denied"] == []
    assert result["auto_merge_allowed"] is True
    assert result["decision"] == "auto_merge" and result["decision_reason"] == ""


def test_green_impacted_level_reuse_passes_despite_base_drift() -> None:
    """A2/D3: base 漂移但未触碰其 paths + impacted 级复验通过 → 第 3 行 pass, 不需全量."""
    ev = _evidence(verify={
        **GREEN_VERIFY, "base_sha": OTHER, "scope": "impacted", "impacted_result": "pass",
    })
    result = _gate(ev)
    c = _check(result, "s1_03")
    assert c["verdict"] == "pass" and c["evidence"]["base_eq_head"] is False
    assert result["verdict"] == "pass"


def test_green_but_switch_off_falls_back_to_s0() -> None:
    """十条全绿 + lane_auto_merge=False（默认）→ 回落 S0 人工确认, 不自动执行."""
    cfg = GateConfig(auto_merge_allowlist=("src/llm_loop", "tests"))  # 开关默认 False
    result = _gate(_evidence(), cfg)
    assert result["verdict"] == "pass"
    assert result["auto_merge_allowed"] is False
    assert result["decision"] == "human_confirm"
    assert result["decision_reason"] == "lane_auto_merge_off"
    assert result["switches"]["lane_auto_merge"] is False


def test_switch_on_does_not_override_any_fail() -> None:
    """开关开 ≠ 放行: 任一条 fail 时 auto_merge_allowed 恒 False."""
    ev = _evidence(main={**GREEN_MAIN, "broken": True})
    result = _gate(ev, _cfg(lane_auto_merge=True))
    assert result["verdict"] == "fail"
    assert result["auto_merge_allowed"] is False
    assert result["decision"] == "human_confirm"


# ================================================================ 自动回滚判定 should_auto_rollback


def _rb_cfg() -> GateConfig:
    return GateConfig(lane_auto_rollback=True)


def test_rollback_switch_off_denied_even_with_green_evidence() -> None:
    """开关默认关: 证据全绿也恒拒（开关不能替代证据检查的另一面: 没开关就没有自动回滚）。"""
    out = should_auto_rollback(
        config=GateConfig(),  # lane_auto_rollback 默认 False
        deployment=deepcopy(GREEN_DEPLOYMENT),
        main_head=MAIN,
        main_red=True,
        attribution_precise=True,
    )
    assert out["allow"] is False and out["reason_code"] == "switch_off"


def test_rollback_allowed_when_target_sha_still_main_head() -> None:
    out = should_auto_rollback(
        config=_rb_cfg(),
        deployment=deepcopy(GREEN_DEPLOYMENT),
        main_head=MAIN,  # target_sha == 当前 main head
        main_red=True,
        attribution_precise=True,
    )
    assert out["allow"] is True and out["reason_code"] == ""
    assert out["evidence"]["rollback_sha"] == MAIN


def test_rollback_main_advanced_rejected() -> None:
    """硬约束: target_sha != 当前 main head → 拒绝（回滚会把后续提交一起回滚掉）。"""
    out = should_auto_rollback(
        config=_rb_cfg(),
        deployment=deepcopy(GREEN_DEPLOYMENT),  # target_sha = MAIN
        main_head="f" * 40,  # main 已前进
        main_red=True,
        attribution_precise=True,
    )
    assert out["allow"] is False and out["reason_code"] == "main_advanced_reject"


def test_rollback_attribution_unclear_rejected() -> None:
    """A12: 归因不到单条 merge → 绝不自动回滚, 只标 broken."""
    out = should_auto_rollback(
        config=_rb_cfg(),
        deployment=deepcopy(GREEN_DEPLOYMENT),
        main_head=MAIN,
        main_red=True,
        attribution_precise=False,
    )
    assert out["allow"] is False and out["reason_code"] == "attribution_unclear"


def test_rollback_not_red_rejected() -> None:
    out = should_auto_rollback(
        config=_rb_cfg(),
        deployment=deepcopy(GREEN_DEPLOYMENT),
        main_head=MAIN,
        main_red=False,
        attribution_precise=True,
    )
    assert out["allow"] is False and out["reason_code"] == "main_not_red"


def test_rollback_anchor_missing_rejected() -> None:
    out = should_auto_rollback(
        config=_rb_cfg(),
        deployment={"target_sha": MAIN, "rollback_sha": "", "ts": CREATED},
        main_head=MAIN,
        main_red=True,
        attribution_precise=True,
    )
    assert out["allow"] is False and out["reason_code"] == "rollback_anchor_missing"


def test_rollback_deploy_unattributable_rejected() -> None:
    out = should_auto_rollback(
        config=_rb_cfg(),
        deployment=None,
        main_head=MAIN,
        main_red=True,
        attribution_precise=True,
    )
    assert out["allow"] is False and out["reason_code"] == "deploy_unattributable"


# ================================================================ git 只读助手（真拦截）


_GIT = shutil.which("git")


def _scratch_git(repo: Path, *args: str) -> None:
    subprocess.run(
        [ _GIT or "git", "-C", str(repo),
          "-c", "user.email=gate@test", "-c", "user.name=gate",
          "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    )


@pytest.mark.skipif(_GIT is None, reason="git 不可用, 无法实测 merge-tree 预检")
def test_git_merge_tree_conflict_detected_and_fed_into_gate(tmp_path: Path) -> None:
    """真实冲突 → merge-tree 预检捕获 → 回灌机检 s1_02 fail（RULE-AI-35 真拦截）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _scratch_git(repo, "init", "-q", "-b", "main")
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _scratch_git(repo, "add", ".")
    _scratch_git(repo, "commit", "-q", "-m", "base")
    _scratch_git(repo, "checkout", "-q", "-b", "feat")
    (repo / "f.txt").write_text("feat\n", encoding="utf-8")
    _scratch_git(repo, "add", ".")
    _scratch_git(repo, "commit", "-q", "-m", "feat")
    _scratch_git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("main\n", encoding="utf-8")
    _scratch_git(repo, "add", ".")
    _scratch_git(repo, "commit", "-q", "-m", "main")
    main_sha = git_head(str(repo))

    conflicts = git_merge_tree_conflicts(str(repo), main_sha, "feat")
    assert conflicts, "真实文本冲突必须被 merge-tree 预检捕获"

    result = _gate(_evidence(merge_precheck={"source": "merge-tree", "conflicts": conflicts}))
    c = _check(result, "s1_02")
    assert c["verdict"] == "fail" and c["reason_code"] == "conflict_precheck"
    assert result["verdict"] == "fail"

    # 对照: 不重叠的干净分支 → 零冲突, 该行回到 pass
    _scratch_git(repo, "checkout", "-q", "-b", "clean")
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    _scratch_git(repo, "add", ".")
    _scratch_git(repo, "commit", "-q", "-m", "new")
    assert git_merge_tree_conflicts(str(repo), main_sha, "clean") == []


@pytest.mark.skipif(_GIT is None, reason="git 不可用")
def test_git_changed_files_lists_patch_surface(tmp_path: Path) -> None:
    repo = tmp_path / "repo2"
    repo.mkdir()
    _scratch_git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("1\n", encoding="utf-8")
    _scratch_git(repo, "add", ".")
    _scratch_git(repo, "commit", "-q", "-m", "a")
    base = git_head(str(repo))
    _scratch_git(repo, "checkout", "-q", "-b", "feat2")
    (repo / "b.txt").write_text("2\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / "c.txt").write_text("3\n", encoding="utf-8")
    _scratch_git(repo, "add", ".")
    _scratch_git(repo, "commit", "-q", "-m", "bc")
    assert git_changed_files(str(repo), base, "feat2") == ["b.txt", "sub/c.txt"]
