"""2026-11-02：复合动作（restart all）部分成功时的事实归因.

实测背景：restart all 连续 11 次（gen363→373）全部判 failed。根因是老的 all 分支
只重启 web/feishu/learning，而 worker 的 target=all 覆盖面含 wecom——于是派单范围
比执行范围大，wecom 永远"未重启"，整单永远 confirm_fail。后果是两处自相矛盾：

  - stage_facts 把 web/feishu/learning 记成 failed（其实是 wecom 那一支失败）
  - generation_lag 说 web 停在 gen361 差 12 代（回执落后被当成"没核验过"）

本文件锁两件事：**动作状态与服务结论分列**、**回执口径与核验口径分列**。派生只读，
不改写任何动作状态，也不伪造 durable 回执。
"""

from __future__ import annotations

import json
from pathlib import Path

from llm_loop.runtime.service_control import (
    ManagedServiceDeployment,
    ManagedServiceDeploymentStore,
    ServiceControlAction,
    _generation_lag_signal,
    compose_convergence_view,
    compose_lifecycle_evidence_view,
    compose_service_identity_view,
    parse_verify_evidence,
    read_all_actions,
)

HEAD_A = "a" * 40
HEAD_B = "b" * 40
SHA = "c" * 64
TS = "2026-11-02T13:00:00+00:00"
TS_LATER = "2026-11-02T13:30:00+00:00"

# 真实回执里的形态（svc-98d8…，gen373）：三支 ok，wecom 支失败。
MIXED_EVIDENCE = (
    "verify=confirmed_fail "
    f"web[ok pid=68825 head={HEAD_B[:12]}] "
    f"feishu[ok pid=68912 head={HEAD_B[:12]}] "
    f"learning[ok pid=70245 head={HEAD_B[:12]}] "
    "wecom[pid_dead:0,git_head_mismatch:ce205a4d]"
)


def _deployment(tmp_path: Path, generation: int, git_head: str) -> ManagedServiceDeployment:
    return ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id=f"deploy-{generation}",
        generation=generation,
        git_head=git_head,
        code_root=str(tmp_path / "code"),
        runtime_root=str(tmp_path / "runtime-root"),
        webui_artifact_sha256=SHA,
    )


def _manifest(store: ManagedServiceDeploymentStore, service: str, *, pid: int, head: str) -> None:
    store.runtime_dir.mkdir(parents=True, exist_ok=True)
    (store.runtime_dir / f"runtime_manifest.{service}.json").write_text(
        json.dumps(
            {
                "service": service,
                "pid": pid,
                "started_at": "2026-11-02T12:00:00+00:00",
                "git_head": head,
            }
        ),
        encoding="utf-8",
    )


def _action(
    *,
    action_id: str,
    target: str,
    generation: int,
    status: str,
    updated_at: str,
    evidence: str = "",
    verdict: str = "",
) -> ServiceControlAction:
    return ServiceControlAction(
        schema="service-control-action/v1",
        action_id=action_id,
        action="restart",
        target=target,  # type: ignore[arg-type]
        deployment_id=f"deploy-{generation}",
        deployment_generation=generation,
        requester_session_id="sess-x",
        status=status,
        created_at=updated_at,
        updated_at=updated_at,
        verify_verdict=verdict,
        verify_evidence=evidence,
    )


GEN = 3  # desired 代（回执停在 gen1，复合动作在 gen3 判 failed）


def _store(tmp_path: Path) -> ManagedServiceDeploymentStore:
    """desired=3/HEAD_B，四服务 live 都已是 HEAD_B（现实：进程其实起来了）。"""
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    for generation in range(1, GEN + 1):
        store.compare_and_swap(
            _deployment(tmp_path, generation, HEAD_B), expected_generation=generation - 1
        )
    for service, pid in (("web", 68825), ("feishu", 68912), ("learning", 70245), ("wecom", 75737)):
        _manifest(store, service, pid=pid, head=HEAD_B)
    return store


def _mixed_store(tmp_path: Path) -> ManagedServiceDeploymentStore:
    """复刻现实：gen1 有 web/feishu/learning 的 durable 回执，gen3 的 all 判 failed。"""
    store = _store(tmp_path)
    for service in ("web", "feishu", "learning"):
        store._write_action_unlocked(
            _action(
                action_id=f"svc-1-{service}",
                target=service,
                generation=1,
                status="succeeded",
                updated_at="2026-11-02T10:00:00+00:00",
                evidence=f"verify=confirmed_ok {service}[ok pid=1 head={HEAD_A[:12]}]",
                verdict="confirmed_ok",
            )
        )
    store._write_action_unlocked(
        _action(
            action_id="svc-all-3",
            target="all",
            generation=GEN,
            status="failed",
            updated_at=TS,
            evidence=MIXED_EVIDENCE,
            verdict="confirmed_fail",
        )
    )
    return store


# ---------------------------------------------------------------------------
# 1) 证据文本 → 按服务事实
# ---------------------------------------------------------------------------


def test_parse_verify_evidence_splits_ok_fail_and_absent() -> None:
    facts = parse_verify_evidence(MIXED_EVIDENCE)
    assert set(facts) == {"web", "feishu", "learning", "wecom"}
    assert facts["web"]["outcome"] == "ok"
    assert facts["web"]["pid"] == "68825"
    assert facts["web"]["head"] == HEAD_B[:12]
    assert facts["wecom"]["outcome"] == "fail"
    assert facts["wecom"]["reasons"] == ["pid_dead:0", "git_head_mismatch:ce205a4d"]
    assert "reasons" not in facts["web"]


def test_parse_verify_evidence_keeps_missing_evidence_distinct_from_failure() -> None:
    """判据缺失 ≠ 失败：机器没看过时不能定罪，也不能算 ok."""
    facts = parse_verify_evidence("verify=unconfirmed web[manifest_missing] feishu[no_manifest_skip]")
    assert facts["web"]["outcome"] == "unconfirmed"
    assert facts["feishu"]["outcome"] == "unconfirmed"
    assert parse_verify_evidence("") == {}
    assert parse_verify_evidence("verify=confirmed_ok") == {}


# ---------------------------------------------------------------------------
# 2) stage_facts：整单状态 vs 服务结论
# ---------------------------------------------------------------------------


def test_stage_facts_separates_action_status_from_service_conclusion(tmp_path: Path) -> None:
    store = _mixed_store(tmp_path)
    stage = compose_lifecycle_evidence_view(store)["stage_facts"]

    web = stage["web"]
    assert web["action_id"] == "svc-all-3"
    # 整单 failed 是事实，保留痕迹
    assert web["status"] == "failed"
    # 但本服务分支结论是 ok，且标明口径
    assert web["service_conclusion"] == "ok"
    assert web["verify_outcome"] == "ok"
    assert web["conclusion_scope"] == "composite_branch"
    assert "其余服务分支未通过" in web["conclusion_note"]

    wecom = stage["wecom"]
    assert wecom["status"] == "failed"
    assert wecom["service_conclusion"] == "failed"
    assert "pid_dead:0" in wecom["reasons"]
    assert "conclusion_scope" not in wecom


def test_stage_facts_leaves_service_conclusion_absent_without_evidence(tmp_path: Path) -> None:
    """没有 verify 证据（老回执/未核验）→ 不编服务结论，只报动作状态."""
    store = _store(tmp_path)
    store._write_action_unlocked(
        _action(
            action_id="svc-noverify",
            target="web",
            generation=GEN,
            status="failed",
            updated_at=TS,
        )
    )
    web = compose_lifecycle_evidence_view(store)["stage_facts"]["web"]
    assert web["status"] == "failed"
    assert "service_conclusion" not in web
    assert "verify_outcome" not in web


# ---------------------------------------------------------------------------
# 3) identity / stable：回执口径 vs 核验口径
# ---------------------------------------------------------------------------


def test_identity_view_exposes_composite_branch_verification(tmp_path: Path) -> None:
    store = _mixed_store(tmp_path)
    view = compose_service_identity_view(store)

    web = view["services"]["web"]
    assert web["verify"] is not None
    assert web["verify"]["outcome"] == "ok"
    assert web["verify"]["generation"] == GEN
    assert web["verify"]["action_id"] == "svc-all-3"
    assert web["verify"]["provenance"] == "composite_branch_evidence"
    assert web["verify"]["durable_succeeded_receipt"] is False

    wecom = view["services"]["wecom"]
    assert wecom["verify"]["outcome"] == "fail"


def test_stable_receipt_lag_does_not_claim_unverified(tmp_path: Path) -> None:
    """durable 回执停在 gen1，但分支证据已核到 desired → 两口径并列，effective=0."""
    store = _mixed_store(tmp_path)
    stable = compose_service_identity_view(store)["services"]["web"]["stable"]
    assert stable["generation"] == 1
    assert stable["lag_generations"] == GEN - 1  # durable 口径照实说
    assert stable["verified_generation"] == GEN
    assert stable["verified_action_id"] == "svc-all-3"
    assert stable["verified_provenance"] == "composite_branch_evidence"
    assert stable["effective_lag_generations"] == 0
    assert "不必仅为追平回执而重启" in stable["note"]


def test_stable_receipt_untouched_when_no_branch_verification(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store._write_action_unlocked(
        _action(
            action_id="svc-1-web",
            target="web",
            generation=1,
            status="succeeded",
            updated_at="2026-11-02T10:00:00+00:00",
            evidence=f"verify=confirmed_ok web[ok pid=1 head={HEAD_A[:12]}]",
            verdict="confirmed_ok",
        )
    )
    stable = compose_service_identity_view(store)["services"]["web"]["stable"]
    assert stable["generation"] == 1
    assert "verified_generation" not in stable


# ---------------------------------------------------------------------------
# 4) generation_lag：回执滞后不再冒充未核验
# ---------------------------------------------------------------------------


def test_generation_lag_reports_verified_generation(tmp_path: Path) -> None:
    store = _mixed_store(tmp_path)
    deployment = store.read()
    entries = _generation_lag_signal(read_all_actions(store), deployment)
    by_target = {entry["target"]: entry for entry in entries}
    web = by_target["web"]
    assert web["generation"] == 1
    assert web["lag_generations"] == GEN - 1
    assert web["verified_generation"] == GEN
    assert web["verified_outcome"] == "ok"
    assert web["effective_lag_generations"] == 0


def test_generation_lag_all_entry_lists_per_service_verification(tmp_path: Path) -> None:
    """all 停在旧代时，附带每服务最近核验代，避免"整单差 N 代"被误读成全员落后."""
    store = _mixed_store(tmp_path)
    store._write_action_unlocked(
        _action(
            action_id="svc-all-1",
            target="all",
            generation=1,
            status="succeeded",
            updated_at="2026-11-02T09:00:00+00:00",
        )
    )
    entries = _generation_lag_signal(read_all_actions(store), store.read())
    entry = {item["target"]: item for item in entries}["all"]
    assert entry["generation"] == 1
    assert entry["lag_generations"] == GEN - 1
    assert entry["services_verified"]["web"]["generation"] == GEN
    assert entry["services_verified"]["web"]["outcome"] == "ok"
    assert entry["services_verified"]["wecom"]["outcome"] == "fail"


# ---------------------------------------------------------------------------
# 5) convergence：不加宽 durable 口径，只并列核验口径
# ---------------------------------------------------------------------------


def test_convergence_exposes_verified_but_not_durable(tmp_path: Path) -> None:
    store = _mixed_store(tmp_path)
    view = compose_convergence_view(store)
    web = view["services"]["web"]
    assert web["converged"] is False  # durable 回执仍停在旧代，不放宽
    assert web["verified_generation"] == GEN
    assert web["verified_converged"] is True
    assert web["effective_converged"] is True
    # durable 口径照实列 lagging；effective 口径里 web 不再算落后
    assert "web" in view["lagging"]
    assert "web" not in view["effective_lagging"]
    assert "wecom" in view["effective_lagging"]  # 分支证据是 fail，它确实没核过


# ---------------------------------------------------------------------------
# 6) restart all 的覆盖面契约：执行面 = 核验面 = 屏障面，wecom 不在 all 里
# ---------------------------------------------------------------------------


def test_restart_all_scope_excludes_wecom_by_contract() -> None:
    """all 的物理执行面只有 web/feishu/learning，核验面与屏障面必须同源.

    契约来源：scripts/restart_mirror.sh 的 all 分支不碰 wecom（单机器人同一时刻
    只允许一个长连接，不连带踢在服长连接），
    tests/wecom/test_restart_mirror_wecom.py::test_wecom_branch_is_not_in_all_batch
    锁这一点。若核验面仍按"受管服务全集"算，wecom 每轮必判
    git_head_mismatch/started_before_restart → all 永远 confirm_fail（实测连续 11 次）。
    """
    from llm_loop.runtime.service_control import (
        _MANAGED_SERVICES,
        _RESTART_ALL_BATCH,
        _barrier_services_for_target,
        _services_for_target,
        _verify_services_for_target,
    )

    assert _RESTART_ALL_BATCH == ("web", "feishu", "learning")
    assert "wecom" in _MANAGED_SERVICES  # 仍是受管服务：status/manifest 照列四服务
    # 三个面刻意不同源，各有其理由（改动前先读各自 docstring）：
    #   核验面 = 执行面 = 3 个（all 没重启 wecom，就不能拿它判这张单）
    assert _verify_services_for_target("all") == list(_RESTART_ALL_BATCH)
    #   屏障面 = 4 个（all 换共享代码期间不放 wecom 新进程跑在新代码上）
    assert set(_barrier_services_for_target("all")) == set(_MANAGED_SERVICES)
    #   in_flight 展示面 = 4 个（受 all 影响的运行准入范围）
    assert _services_for_target("all") == list(_MANAGED_SERVICES)
    assert _verify_services_for_target("wecom") == ["wecom"]
    assert _barrier_services_for_target("wecom") == ("wecom",)


def test_all_action_evidence_without_wecom_does_not_verify_wecom(tmp_path: Path) -> None:
    """all 的回执不再承载 wecom 结论时，wecom 的核验事实只能来自它自己的动作."""
    from llm_loop.runtime.service_control import _latest_service_verification

    store = _store(tmp_path)
    store._write_action_unlocked(
        _action(
            action_id="svc-all-3",
            target="all",
            generation=GEN,
            status="succeeded",
            updated_at=TS,
            evidence=(
                f"verify=confirmed_ok web[ok pid=68825 head={HEAD_B[:12]}] "
                f"feishu[ok pid=68912 head={HEAD_B[:12]}] "
                f"learning[ok pid=70245 head={HEAD_B[:12]}]"
            ),
            verdict="confirmed_ok",
        )
    )
    assert _latest_service_verification(read_all_actions(store), "wecom") is None
    verified_web = _latest_service_verification(read_all_actions(store), "web")
    assert verified_web is not None and verified_web[1]["outcome"] == "ok"
