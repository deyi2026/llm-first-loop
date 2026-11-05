"""S1 十条机检执行器 + 自动回滚判定（DESIGN-20261105 §4.4.1 / §8 P2b）.

设计依据: docs/design/DESIGN-20261105-main-lane-parallel-delivery-v1.md §4.4.1
（S1 十条机检表，2026-11-05 用户裁决）与 §4.4.2（K/F 类型加权）。十条的
**条件与失配理由码逐条照抄设计表**；标「细化」的 reason_code 只是把对应行的
判定拆到可归因粒度，方向仍是 fail（细化只收紧、不放宽）。

check_id ↔ 设计表行（条件 → 失配理由码）:
    s1_01  main_broken=false 且部署态可判定（非部署窗口）
           → main_broken / deploy_window
    s1_02  git merge-tree 预检零冲突
           → conflict_precheck
    s1_03  凭证有效: patch_digest 匹配, 且（base_sha == main_head 或 impacted 级复验通过）
           → verify_stale
    s1_04  独立审查 PASS 回执绑定当前 sha 且未过期
           → review_missing（细化: review_sha_mismatch / review_expired）
    s1_05  改动路径 ⊆ auto_merge_allowlist（默认空 = 全不自动，必须显式配置）
           → path_not_allowed（细化: paths_undeclared——声明缺失或不覆盖实际改动面）
    s1_06  改动路径 ∩ sealed_paths = ∅, 且不含 rules / 部署配置 / 迁移脚本
           → sealed_path
    s1_07  K / F 权重未超限（§4.4.2: docs-only 0.3 / 常规 1.0 / sealed 1.5,
           Σ权重 ≤ K_MAX 且 Σ文件 ≤ F_MAX）
           → budget_exceeded
    s1_08  无 need=block 的未决协助请求
           → help_blocking
    s1_09  无其他 lane 对重叠 paths 持有 claim
           → claim_overlap
    s1_10  可一步 revert（--no-ff 且父即当前 main head）
           → not_revertible

裁决语义（fail-closed, RULE-AI-30 / 设计 C4）:
- 任一 check fail → 整单 verdict=fail；**skip ≠ pass**——S1 要求十条「全部满足」，
  证据或依赖不可用的 skip 同样阻断自动合并（s1_08/s1_09 依赖 P1 协助收件箱与
  claim 视图，未接入时返回 skip + dependency_unavailable，绝不视为满足）。
- 开关默认全关（lane_auto_merge=False / lane_auto_rollback=False，裁决 §11.1）:
  开关只能收紧、不能放宽——开关关恒不放行；开关开仍须证据全绿
  （开关不替代证据检查）。

模块边界:
- 纯判定: 不做网络、不部署、不写任何账本/文件；输入为调用方显式组装的证据结构体。
- git 只读命令限 rev-parse / log / show / merge-tree（_GIT_READ_ONLY 硬白名单）。
  merge-tree --write-tree 会向对象库写入中间 tree 对象——设计 §4.4 已裁决其为
  零副作用预检（不建 worktree、不动 index、不写 ref）。
- patch_digest 的重算不在本模块（git diff 不在白名单）: 调用方按凭证同一算法
  sha256(git diff base..head) 重算后经 S1Evidence.current_patch_digest 传入，
  本模块只做比对——凭证绑 patch 而非全树，rebase 本身不应让凭证失效（设计 D3）。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------- 常量

S1_CHECK_IDS: tuple[str, ...] = (
    "s1_01", "s1_02", "s1_03", "s1_04", "s1_05",
    "s1_06", "s1_07", "s1_08", "s1_09", "s1_10",
)

S1_CONDITIONS: dict[str, str] = {
    "s1_01": "main_broken=false 且部署态可判定（非部署窗口）",
    "s1_02": "git merge-tree 预检零冲突",
    "s1_03": "凭证有效: patch_digest 匹配, 且（base_sha == main_head 或 impacted 级复验通过）",
    "s1_04": "独立审查 PASS 回执绑定当前 sha 且未过期",
    "s1_05": "改动路径 ⊆ auto_merge_allowlist（默认空 = 全不自动，必须显式配置）",
    "s1_06": "改动路径 ∩ sealed_paths = ∅, 且不含 rules / 部署配置 / 迁移脚本",
    "s1_07": "K / F 权重未超限（Σ权重 ≤ K_MAX 且 Σ文件 ≤ F_MAX）",
    "s1_08": "无 need=block 的未决协助请求",
    "s1_09": "无其他 lane 对重叠 paths 持有 claim",
    "s1_10": "可一步 revert（--no-ff 且父即当前 main head）",
}

# s1_06 的设计内建保留面: rules / 部署配置 / 迁移脚本（可用 config 收窄或替换）
DEFAULT_RESERVED_PATH_PREFIXES: tuple[str, ...] = (
    "docs/rules",
    "rules",
    "deploy",
    "deployments",
    "migrations",
    "scripts/deploy",
)

_SKIP_REASON = "dependency_unavailable"


class LaneGateProbeError(RuntimeError):
    """git 只读探测失败（子命令越白名单 / 仓库不可读 / 命令异常）。"""


# ---------------------------------------------------------------- 配置与证据


@dataclass(frozen=True)
class GateConfig:
    """S1 机检与自动回滚配置。默认值 = 任何新实例等价 S0（裁决 §11.1）。"""

    lane_auto_merge: bool = False
    lane_auto_rollback: bool = False
    # 默认空 allowlist = 全不自动（设计表第 5 行），必须显式配置才可能 pass
    auto_merge_allowlist: tuple[str, ...] = ()
    sealed_paths: tuple[str, ...] = ()
    k_max: int = 3
    f_max: int = 30
    weight_docs_only: float = 0.3
    weight_normal: float = 1.0
    weight_sealed: float = 1.5
    verify_ttl_s: int = 86400
    review_ttl_s: int = 86400
    reserved_path_prefixes: tuple[str, ...] = DEFAULT_RESERVED_PATH_PREFIXES


@dataclass
class S1Evidence:
    """调用方显式组装的机检证据。None / 缺失 = 依赖不可用 → 对应 check skip。

    字段约定:
    - lane: lanes.jsonl 的 lane 记录（verify_ref / head_sha / paths）
    - main: {"head_sha", "broken", "deploy_window", "last_good_sha"}
    - verify: 验证凭证（设计 D3）: {"receipt_id", "patch_digest", "base_sha",
      "result", "scope", "impacted_result", "created_at", "contract_hit"}
    - current_patch_digest: 调用方按凭证同一算法重算的当前 patch digest（比对基准）
    - review: 审查回执: {"verdict"（"pass"）, "bound_sha", "created_at"}
    - deployment: 部署记录（§11.1 既有格式）: {"target_sha", "rollback_sha", "ts", "phase"}
    - merge_precheck: {"source": "merge-tree", "conflicts": int | list[str]}
    - batch: {"members": [{"lane_id", "kind"}], "changed_files_total": int}
    - help_requests: 协助收件箱在途请求（P1 数据源; None = 未接入）
    - claim_overlaps: 其他 lane 对重叠 paths 的 claim（claim 视图; None = 未接入）
    - merge_plan: {"no_ff": bool, "parent_sha": str}（即将执行的 merge 计划）
    - changed_files: base..head 实际改动文件（git_changed_files 派生或调用方给）
    - now_iso: TTL 判定时刻（调用方显式传，保证判定可复现；缺省视为不可判定）
    """

    lane: dict[str, Any]
    main: dict[str, Any] | None = None
    verify: dict[str, Any] | None = None
    current_patch_digest: str = ""
    review: dict[str, Any] | None = None
    deployment: dict[str, Any] | None = None
    merge_precheck: dict[str, Any] | None = None
    batch: dict[str, Any] | None = None
    help_requests: list[dict[str, Any]] | None = None
    claim_overlaps: list[dict[str, Any]] | None = None
    merge_plan: dict[str, Any] | None = None
    changed_files: list[str] | None = None
    now_iso: str = ""


# ---------------------------------------------------------------- 内部工具


def _norm_path(raw: object) -> str:
    s = str(raw or "").strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def _under_any(path: str, prefixes: object) -> bool:
    """path 是否落在任一前缀下（等值或目录前缀；与 lane_board 重叠判定同口径）。"""
    for raw in prefixes or ():
        p = _norm_path(raw).rstrip("/")
        if not p:
            continue
        if path == p or path.startswith(p + "/"):
            return True
    return False


def _parse_ts(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _within_ttl(created_at: object, now_iso: str, ttl_s: int) -> bool:
    """TTL 内且 created_at 不在未来（设计 F8: 未来时间视为过期; 解析失败=不可判定=否）。"""
    c = _parse_ts(created_at)
    n = _parse_ts(now_iso)
    if c is None or n is None:
        return False
    try:
        age = (n - c).total_seconds()
    except TypeError:  # naive 与 aware 混比
        return False
    return 0 <= age <= int(ttl_s)


def _result(check_id: str, verdict: str, reason_code: str, evidence: dict) -> dict:
    return {
        "check_id": check_id,
        "condition": S1_CONDITIONS[check_id],
        "verdict": verdict,
        "reason_code": reason_code,
        "evidence": evidence,
    }


def _skip(check_id: str, detail: str) -> dict:
    """依赖/证据不可用: skip ≠ pass, 整单仍会被阻断（C4 fail-closed）。"""
    return _result(check_id, "skip", _SKIP_REASON, {"detail": detail})


# ---------------------------------------------------------------- 十条机检


def _check_s1_01(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 1 行: main_broken=false 且部署态可判定（非部署窗口）。"""
    main = ev.main or None
    if not main:
        return _skip("s1_01", "main 状态未提供")
    broken = main.get("broken")
    if broken is None:
        return _result(
            "s1_01", "fail", "main_broken",
            {"detail": "broken 字段缺失，不可判定", "main": main},
        )
    if bool(broken):
        return _result("s1_01", "fail", "main_broken", {"broken": True})
    deploy_window = main.get("deploy_window")
    if deploy_window is None:
        return _result(
            "s1_01", "fail", "deploy_window",
            {"detail": "deploy_window 字段缺失，部署态不可判定", "main": main},
        )
    if bool(deploy_window):
        return _result("s1_01", "fail", "deploy_window", {"deploy_window": True})
    return _result("s1_01", "pass", "", {"broken": False, "deploy_window": False})


def _check_s1_02(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 2 行: git merge-tree 预检零冲突。预检来源不是 merge-tree 不采信（skip）。"""
    mp = ev.merge_precheck or None
    if not mp:
        return _skip("s1_02", "merge-tree 预检结果未提供")
    if str(mp.get("source") or "") != "merge-tree":
        return _skip("s1_02", "预检来源不是 merge-tree: " + repr(mp.get("source")))
    conflicts = mp.get("conflicts")
    if conflicts is None:
        return _result(
            "s1_02", "fail", "conflict_precheck",
            {"detail": "conflicts 字段缺失，预检结果不可判定", "precheck": mp},
        )
    count = len(conflicts) if isinstance(conflicts, (list, tuple)) else int(conflicts)
    if count > 0:
        return _result("s1_02", "fail", "conflict_precheck", {"conflicts": conflicts})
    return _result("s1_02", "pass", "", {"conflicts": 0})


def _check_s1_03(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 3 行: 凭证有效——patch_digest 匹配 + base 一致或 impacted 级复验通过。

    失效口径按设计 D3 表: 无凭证 / digest 不一致 / base 漂移且非 impacted 复验 /
    契约命中 / TTL 过期（created_at 缺失或在未来都算过期）。理由码统一 verify_stale。
    """
    verify = ev.verify or None
    if not verify:
        return _skip("s1_03", "验证凭证未提供")
    lane = ev.lane or {}
    ref = str(lane.get("verify_ref") or "").strip()
    receipt_id = str(verify.get("receipt_id") or "").strip()
    if not ref or (receipt_id and receipt_id != ref):
        return _result(
            "s1_03", "fail", "verify_stale",
            {"detail": "lane.verify_ref 与凭证 receipt_id 不一致（无有效凭证不合, A10）",
             "verify_ref": ref, "receipt_id": receipt_id},
        )
    if str(verify.get("result") or "").lower() != "pass":
        return _result("s1_03", "fail", "verify_stale", {"result": verify.get("result")})
    current = str(ev.current_patch_digest or "").strip()
    if not current:
        return _skip("s1_03", "current_patch_digest 未提供（无法比对, git diff 不在本模块白名单）")
    digest = str(verify.get("patch_digest") or "").strip()
    if digest != current:
        return _result(
            "s1_03", "fail", "verify_stale",
            {"detail": "patch_digest 不匹配（patch 已变, 凭证失效须重跑）",
             "patch_digest": digest, "current_patch_digest": current},
        )
    base = str(verify.get("base_sha") or "").strip()
    main_head = str((ev.main or {}).get("head_sha") or "").strip()
    if not main_head:
        return _result(
            "s1_03", "fail", "verify_stale",
            {"detail": "main.head_sha 缺失, base 一致性不可判定"},
        )
    base_eq = base == main_head
    scope = str(verify.get("scope") or "")
    if not base_eq:
        if bool(verify.get("contract_hit")):
            return _result(
                "s1_03", "fail", "verify_stale",
                {"detail": "base 漂移且契约变更命中本 lane paths, 必须全量重跑（D3）"},
            )
        impacted_ok = (
            scope == "impacted"
            and str(verify.get("impacted_result") or "").lower() == "pass"
        )
        if not impacted_ok:
            return _result(
                "s1_03", "fail", "verify_stale",
                {"detail": "base_sha != main_head 且无 impacted 级复验通过回执",
                 "base_sha": base, "main_head": main_head, "scope": scope},
            )
    if not _within_ttl(verify.get("created_at"), ev.now_iso, cfg.verify_ttl_s):
        return _result(
            "s1_03", "fail", "verify_stale",
            {"detail": "凭证 TTL 过期 / created_at 缺失或在未来（F8）",
             "created_at": verify.get("created_at"), "now_iso": ev.now_iso},
        )
    return _result(
        "s1_03", "pass", "",
        {"digest_match": True, "base_eq_head": base_eq, "scope": scope or "full"},
    )


def _check_s1_04(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 4 行: 独立审查 PASS 回执绑定当前 sha 且未过期（RULE-AI-28 不豁免）。"""
    review = ev.review or None
    if not review:
        # 无审查回执 = 行条件不满足（review_missing 是明确 fail, 不是 skip）
        return _result("s1_04", "fail", "review_missing", {"detail": "无独立审查回执"})
    verdict = str(review.get("verdict") or "").strip().lower()
    passed = verdict == "pass" or review.get("pass") is True
    if not passed:
        return _result("s1_04", "fail", "review_missing", {"verdict": review.get("verdict")})
    bound = str(review.get("bound_sha") or review.get("sha") or "").strip()
    head = str((ev.lane or {}).get("head_sha") or "").strip()
    if not bound or not head or bound != head:
        return _result(
            "s1_04", "fail", "review_sha_mismatch",
            {"detail": "审查回执绑定的 sha != lane.head_sha（SHA 不匹配, 凭证不得复用）",
             "bound_sha": bound, "head_sha": head},
        )
    if not _within_ttl(review.get("created_at"), ev.now_iso, cfg.review_ttl_s):
        return _result(
            "s1_04", "fail", "review_expired",
            {"created_at": review.get("created_at"), "now_iso": ev.now_iso},
        )
    return _result("s1_04", "pass", "", {"bound_sha": bound, "head_sha": head})


def _changed(ev: S1Evidence) -> list[str] | None:
    if ev.changed_files is None:
        return None
    return sorted({_norm_path(f) for f in ev.changed_files if str(f).strip()})


def _check_s1_05(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 5 行: 改动路径 ⊆ auto_merge_allowlist（默认空 = 全不自动）。

    细化 paths_undeclared: 实际改动面必须被 lane.paths 声明完整覆盖
    （声明缺失/不完整 = 无法核对 = 不通过, C4）。
    """
    files = _changed(ev)
    if files is None:
        return _skip("s1_05", "改动面（changed_files）未提供")
    if not files:
        return _result(
            "s1_05", "fail", "paths_undeclared",
            {"detail": "改动面为空（空 diff 不应自动合并）"},
        )
    declared = [_norm_path(p) for p in (ev.lane or {}).get("paths") or []]
    if not declared:
        return _result(
            "s1_05", "fail", "paths_undeclared",
            {"detail": "lane.paths 未声明", "changed_files": files},
        )
    undeclared = [f for f in files if not _under_any(f, declared)]
    if undeclared:
        return _result(
            "s1_05", "fail", "paths_undeclared",
            {"detail": "改动面未被声明覆盖（声明不完整）",
             "undeclared_files": undeclared, "declared": declared},
        )
    outside = [f for f in files if not _under_any(f, cfg.auto_merge_allowlist)]
    if outside:
        return _result(
            "s1_05", "fail", "path_not_allowed",
            {"detail": "改动路径不在 auto_merge_allowlist（默认空 = 全不自动）",
             "outside_allowlist": outside, "allowlist": list(cfg.auto_merge_allowlist)},
        )
    return _result("s1_05", "pass", "", {"files": files})


def _check_s1_06(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 6 行: 改动路径 ∩ sealed_paths = ∅, 且不含 rules/部署配置/迁移脚本。"""
    files = _changed(ev)
    if files is None:
        return _skip("s1_06", "改动面（changed_files）未提供")
    forbidden = tuple(cfg.sealed_paths) + tuple(cfg.reserved_path_prefixes)
    hits = [f for f in files if _under_any(f, forbidden)]
    if hits:
        return _result(
            "s1_06", "fail", "sealed_path",
            {"hits": hits, "sealed_paths": list(cfg.sealed_paths),
             "reserved": list(cfg.reserved_path_prefixes)},
        )
    return _result("s1_06", "pass", "", {"hits": []})


def _check_s1_07(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 7 行: K/F 权重未超限（§4.4.2 类型加权; 未知 kind 按常规 1.0 保守处理）。"""
    batch = ev.batch or None
    if not batch:
        return _skip("s1_07", "批次（batch）信息未提供")
    members = batch.get("members")
    if not isinstance(members, list):
        return _result(
            "s1_07", "fail", "budget_exceeded",
            {"detail": "batch.members 缺失或类型错误, 权重不可判定", "batch": batch},
        )
    weights = {
        "docs-only": cfg.weight_docs_only,
        "normal": cfg.weight_normal,
        "sealed": cfg.weight_sealed,
    }
    weight_sum = sum(
        weights.get(str(m.get("kind") or ""), cfg.weight_normal) for m in members
    )
    raw_total = batch.get("changed_files_total")
    try:
        files_total = int(raw_total)
    except (TypeError, ValueError):
        return _result(
            "s1_07", "fail", "budget_exceeded",
            {"detail": "changed_files_total 缺失或非整数, F 不可判定", "batch": batch},
        )
    if weight_sum > cfg.k_max + 1e-9:
        return _result(
            "s1_07", "fail", "budget_exceeded",
            {"detail": "Σ权重 > K_MAX（自动回滚可枚举性, §4.4.2）",
             "weight_sum": round(weight_sum, 3), "k_max": cfg.k_max},
        )
    if files_total > cfg.f_max:
        return _result(
            "s1_07", "fail", "budget_exceeded",
            {"detail": "Σ文件 > F_MAX（审查认知负荷上限）",
             "changed_files_total": files_total, "f_max": cfg.f_max},
        )
    return _result(
        "s1_07", "pass", "",
        {"weight_sum": round(weight_sum, 3), "changed_files_total": files_total},
    )


def _check_s1_08(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 8 行: 无 need=block 的未决协助请求（数据源 = P1 协助收件箱, 未接入则 skip）。"""
    requests = ev.help_requests
    if requests is None:
        return _skip("s1_08", "P1 协助收件箱视图未接入（依赖不可用, skip ≠ pass）")
    blocking = [
        r for r in requests
        if str(r.get("need") or "") == "block"
        and str(r.get("state") or "pending") == "pending"
    ]
    if blocking:
        return _result(
            "s1_08", "fail", "help_blocking",
            {"blocking": [str(r.get("id") or r) for r in blocking]},
        )
    return _result("s1_08", "pass", "", {"checked": len(requests)})


def _check_s1_09(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 9 行: 无其他 lane 对重叠 paths 持有 claim（claim 视图未接入则 skip）。"""
    overlaps = ev.claim_overlaps
    if overlaps is None:
        return _skip("s1_09", "claim 视图未接入（依赖不可用, skip ≠ pass）")
    if overlaps:
        return _result("s1_09", "fail", "claim_overlap", {"overlaps": overlaps})
    return _result("s1_09", "pass", "", {"overlaps": []})


def _check_s1_10(ev: S1Evidence, cfg: GateConfig) -> dict:
    """第 10 行: 可一步 revert（--no-ff 且父即当前 main head）。

    注意 TOCTOU: 机检时点只能比对 merge_plan.parent_sha; 执行临界区内必须
    二次比对真实 main head（设计 F3 口径）, 本行通过不豁免临界区复核。
    """
    plan = ev.merge_plan or None
    if not plan:
        return _skip("s1_10", "merge 计划（merge_plan）未提供")
    if plan.get("no_ff") is not True:
        return _result(
            "s1_10", "fail", "not_revertible",
            {"detail": "merge 计划不是 --no-ff, 无法单 lane revert", "no_ff": plan.get("no_ff")},
        )
    parent = str(plan.get("parent_sha") or "").strip()
    main_head = str((ev.main or {}).get("head_sha") or "").strip()
    if not main_head or parent != main_head:
        return _result(
            "s1_10", "fail", "not_revertible",
            {"detail": "merge 父提交不是当前 main head, revert 单元不可锚定",
             "parent_sha": parent, "main_head": main_head},
        )
    return _result("s1_10", "pass", "", {"no_ff": True, "parent_sha": parent})


_RUNNERS = (
    _check_s1_01, _check_s1_02, _check_s1_03, _check_s1_04, _check_s1_05,
    _check_s1_06, _check_s1_07, _check_s1_08, _check_s1_09, _check_s1_10,
)


# ---------------------------------------------------------------- 整单裁决


def evaluate_s1_gate(
    evidence: S1Evidence,
    config: GateConfig | None = None,
) -> dict:
    """S1 十条机检 → 整单裁决。纯函数, 零副作用。

    返回:
        verdict: "pass" 仅当十条全部 pass; 任一 fail 或 skip → "fail"（skip ≠ pass）。
        auto_denied: 非 pass 的 check_id 列表（A11 的 auto_denied["条件名"]）。
        auto_merge_allowed: verdict==pass 且 lane_auto_merge 开; 开关关即使全绿
            也回落 S0（human_confirm）——开关只能收紧不能放宽。
    """
    cfg = config if config is not None else GateConfig()
    checks = [run(evidence, cfg) for run in _RUNNERS]
    verdict = "pass" if all(c["verdict"] == "pass" for c in checks) else "fail"
    auto_denied = [c["check_id"] for c in checks if c["verdict"] != "pass"]
    allowed = verdict == "pass" and cfg.lane_auto_merge
    if allowed:
        decision_reason = ""
    elif verdict == "fail":
        decision_reason = "checks_failed"
    else:
        decision_reason = "lane_auto_merge_off"
    return {
        "level": "S1",
        "verdict": verdict,
        "checks": checks,
        "auto_denied": auto_denied,
        "denied": [
            {"check_id": c["check_id"], "verdict": c["verdict"], "reason_code": c["reason_code"]}
            for c in checks
            if c["verdict"] != "pass"
        ],
        "auto_merge_allowed": allowed,
        "decision": "auto_merge" if allowed else "human_confirm",
        "decision_reason": decision_reason,
        "switches": {
            "lane_auto_merge": cfg.lane_auto_merge,
            "lane_auto_rollback": cfg.lane_auto_rollback,
        },
    }


def should_auto_rollback(
    *,
    config: GateConfig | None = None,
    deployment: dict[str, Any] | None = None,
    main_head: str = "",
    main_red: bool = False,
    attribution_precise: bool = False,
) -> dict:
    """自动回滚判定（硬约束: 被部署的 target_sha 必须仍等于当前 main head）。

    判定顺序（先命中先返回, 全部为拒绝方向; 开关不替代证据检查）:
        switch_off              lane_auto_rollback 关（默认）——恒拒
        main_not_red            main 未红: 回滚只在合并后 main 全量验证 RED 时触发
        deploy_unattributable   部署记录缺失/无 target_sha, 部署条带不可归因
        main_advanced_reject    target_sha != 当前 main head——回滚会把后续提交一起
                                回滚掉, 必须拒绝（硬约束）
        attribution_unclear     归因不到单条 merge——绝不自动回滚, 只标 broken（A12）
        rollback_anchor_missing 部署记录无 rollback_sha, 回滚锚点不存在
    全部满足才 allow=True（reason_code=""）。
    """
    cfg = config if config is not None else GateConfig()
    record = deployment or {}
    target = str(record.get("target_sha") or "").strip()
    anchor = str(record.get("rollback_sha") or "").strip()
    head = str(main_head or "").strip()
    ev = {
        "target_sha": target,
        "main_head": head,
        "rollback_sha": anchor,
        "main_red": bool(main_red),
        "attribution_precise": bool(attribution_precise),
        "switch": cfg.lane_auto_rollback,
    }

    def _out(allow: bool, reason_code: str) -> dict:
        return {"allow": allow, "reason_code": reason_code, "evidence": ev}

    if not cfg.lane_auto_rollback:
        return _out(False, "switch_off")
    if not main_red:
        return _out(False, "main_not_red")
    if not target:
        return _out(False, "deploy_unattributable")
    if not head or target != head:
        return _out(False, "main_advanced_reject")
    if not attribution_precise:
        return _out(False, "attribution_unclear")
    if not anchor:
        return _out(False, "rollback_anchor_missing")
    return _out(True, "")


# ---------------------------------------------------------------- git 只读取证助手


_GIT_READ_ONLY = ("rev-parse", "log", "show", "merge-tree")

# 调用点固定使用的选项；其余以 "-" 开头的参数一律拒绝，避免调用方传入的
# base/head 被 git 当成选项（--help / --output= / --upload-pack= 等）。
_GIT_ALLOWED_FLAGS = frozenset({"--write-tree", "--name-only", "--no-commit-id", "-n", "-z"})
_GIT_ALLOWED_FLAG_PREFIXES = ("--format=", "--pretty=")


def _flag_allowed(arg: str) -> bool:
    return arg in _GIT_ALLOWED_FLAGS or any(
        arg.startswith(prefix) for prefix in _GIT_ALLOWED_FLAG_PREFIXES
    )


def _run_git_readonly(repo: str, args: list[str]) -> subprocess.CompletedProcess:
    """只允许 rev-parse/log/show/merge-tree 四个只读子命令, 越白名单直接拒绝。

    参数层再一道闸：以 "-" 开头且不在选项白名单内的参数直接拒绝，防止
    base/head 等外部字符串被解析成 git 选项。
    """
    if not args or args[0] not in _GIT_READ_ONLY:
        raise LaneGateProbeError(
            "git 子命令超出只读白名单 " + str(list(_GIT_READ_ONLY)) + ": " + str(list(args)[:1])
        )
    for raw in args[1:]:
        arg = str(raw)
        if arg.startswith("-") and not _flag_allowed(arg):
            raise LaneGateProbeError(f"git 参数含不允许的选项: {arg!r}")
    try:
        return subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LaneGateProbeError(f"git 探测失败: {exc}") from exc


def _is_oid(line: str) -> bool:
    return len(line) in (40, 64) and all(ch in "0123456789abcdef" for ch in line.lower())


def git_head(repo: str) -> str:
    """rev-parse HEAD; 失败抛 LaneGateProbeError（不静默返回空, 判定层需要真值）。"""
    proc = _run_git_readonly(repo, ["rev-parse", "HEAD"])
    if proc.returncode != 0:
        raise LaneGateProbeError(f"rev-parse 失败: {proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def git_merge_tree_conflicts(repo: str, base: str, head: str) -> list[str]:
    """merge-tree --write-tree 冲突预检; 返回冲突文件清单（空 = 零冲突）。

    退出码 0 = 干净; 1 = 有冲突（业务结果, 不是错误）; 其他 = 探测失败抛错。
    输出首行是 tree oid（纯 hex）, 其余行是冲突文件名; 防御式跳过首行仅当
    它确为 oid 形态。
    """
    proc = _run_git_readonly(
        repo, ["merge-tree", "--write-tree", "--name-only", base, head]
    )
    if proc.returncode == 0:
        return []
    if proc.returncode != 1:
        raise LaneGateProbeError(
            f"merge-tree 失败(rc={proc.returncode}): {proc.stderr.strip()[:200]}"
        )
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if lines and _is_oid(lines[0]):
        lines = lines[1:]
    return lines


def git_changed_files(repo: str, base: str, head: str) -> list[str]:
    """base..head 实际改动文件（git log --name-only, 白名单内）; 失败抛错。"""
    proc = _run_git_readonly(repo, ["log", "--format=", "--name-only", f"{base}..{head}"])
    if proc.returncode != 0:
        raise LaneGateProbeError(f"log --name-only 失败: {proc.stderr.strip()[:200]}")
    names = {_norm_path(ln) for ln in proc.stdout.splitlines() if ln.strip()}
    return sorted(n for n in names if n)
