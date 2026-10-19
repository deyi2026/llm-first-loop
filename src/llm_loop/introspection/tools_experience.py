"""经验沉淀/生命周期工具实现（design §2.3.2.1/§2.3.2.2）.

save_experience/refine_experience：参数校验 → 调 ExperienceStore → 如实回执（fail-open 不阻断主循环）。
程序仅提供通道；提取/判断/应用归 AI 自主（RULE-AI-00）。
"""

from __future__ import annotations

import re

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import (
    ExperienceCommitUncertainError,
    ExperiencePersistError,
    ExperienceStore,
)
from llm_loop.timekeeping import system_local_now
from llm_loop.tools.arg_coerce import coerce_obj, coerce_str_list

# EVO-20260923-6fe23c9b F2(a): 保存时强制"可执行的当前性验证动作"（防裸结论卡 stale 后误导弱模型）
_FRESHNESS_ACTION_RE = re.compile(
    r"grep|\bsed\b|\bcat\b|\bls\b|\bstat\b|\bfind\b|\bgit\b|read_file|execute_command|"
    r"search_files|inspect_code|web_fetch|playwright|\bdsh\b|pytest|\bcurl\b|"
    r"当前性验证|验证动作|验证步骤|验证|核对|复核|复现|实测|"
    r"先[^\n。；;]{0,40}(确认|验证|核对|检查|跑|查)",
    re.IGNORECASE,
)


def freshness_action_ok(*texts: str) -> bool:
    """检查合并文本是否含可执行验证动作信号（命令/工具/复现/当前性验证/先…确认等）。"""
    merged = "\n".join(str(t or "") for t in texts)
    return bool(_FRESHNESS_ACTION_RE.search(merged))


FRESHNESS_ACTION_ERR = (
    "[参数错误] 卡内未检出『可执行的当前性验证动作』（EVO-20260923-6fe23c9b）: "
    "浓缩结论在环境变更后会变成错误答案来源。请在 solution/body 补一行可执行验证动作，"
    "例如『当前性验证：先 grep -n <关键字> <路径> 确认行号仍存在』或『复现：跑 <命令> 应得 <结果>』"
    "（未写入）"
)


def _normalize_experience_id(experience_id: str) -> str:
    """Normalize public stable-ref/file forms to the store's canonical stem."""

    value = str(experience_id or "").strip()
    if value.startswith("experience:"):
        value = value.split(":", 1)[1].strip()
    if value.endswith(".md"):
        value = value[:-3]
    return value


def run_save_experience(
    store: ExperienceStore,
    *,
    title: str,
    scenario: str,
    solution: str,
    record_kind: str = "",
    verification_state: str = "",
    root_cause: str = "",
    evidence: str = "",
    tags: list[str] | None = None,
    source: dict | None = None,
    body: str = "",
) -> str:
    """save_experience 工具逻辑：校验 → 构造 → 写入 → 如实回执。"""
    missing = [f for f, v in (("title", title), ("scenario", scenario), ("solution", solution)) if not v]
    if missing:
        return f"[参数错误] 缺失必填字段: {', '.join(missing)}（未写入）"
    kind = str(record_kind or "").strip().lower()
    verification = str(verification_state or "").strip().lower()
    if kind not in {"experience", "lesson"}:
        return "[参数错误] record_kind 须为 experience/lesson（未写入）"
    if verification not in {"verified", "unverified", "disproven"}:
        return (
            "[参数错误] verification_state 须为 verified/unverified/disproven（未写入）"
        )
    if kind == "experience" and verification != "verified":
        return (
            "[参数错误] record_kind=experience 只用于已有证据证明生效的正向经验；"
            "未验证/已证伪内容请保存为 record_kind=lesson（未写入）"
        )
    if verification in {"verified", "disproven"} and not str(evidence or "").strip():
        return (
            f"[参数错误] verification_state={verification} 必须提供 evidence（未写入）"
        )
    # EVO-20260923-6fe23c9b F2(a): 强制可执行当前性验证动作
    if not freshness_action_ok(solution, body, root_cause, scenario):
        return FRESHNESS_ACTION_ERR
    now = system_local_now().isoformat()
    doc = ExperienceDocument(
        title=title,
        scenario=scenario,
        root_cause=root_cause,
        solution=solution,
        evidence=evidence,
        tags=coerce_str_list(tags),
        source=coerce_obj(source),
        status="active",
        record_kind=kind,
        verification_state=verification,
        created_at=now,
        updated_at=now,
        body=body,
    )
    try:
        filename = store.save(doc)
        experience_id = filename.removesuffix(".md")
        return (
            f"[save_experience] 已沉淀 {filename} "
            f"experience_ref=experience:{experience_id} status=active "
            f"record_kind={kind} verification_state={verification}"
        )
    except FileExistsError as exc:
        return f"[save_experience] 文件冲突: {exc}"
    except ExperienceCommitUncertainError as exc:
        return (
            f"[save_experience] 提交结果不确定: experience:{exc.experience_id} "
            f"已原子可见但目录 fsync 未确认（expected_sha256={exc.expected_sha256} "
            f"visible_state={exc.visible_state}）。禁止盲重存：同日同 slug 已占用，"
            f"重存必然冲突；先按 expected_sha256 逐字核对（store.get/search_records），"
            f"一致即已落盘，无需任何补救写"
        )
    except ExperiencePersistError as exc:
        return (
            f"[save_experience] 确定未提交（{exc}）。"
            f"同一 payload 重试安全；改写内容前先核对库内现状"
        )
    except OSError as exc:
        return f"[程序异常] 经验写入失败（{type(exc).__name__}: {exc}）"


def run_refine_experience(
    store: ExperienceStore,
    *,
    experience_id: str,
    action: str,
) -> str:
    """refine_experience 工具逻辑：状态流转 → 如实回执。"""
    action_map = {"archive": "archived", "invalidate": "invalid", "restore": "active"}
    if action not in action_map:
        return f"[参数错误] action 须为 archive/invalidate/restore，收到: {action}"
    normalized_id = _normalize_experience_id(experience_id)
    if not normalized_id:
        return "[参数错误] experience_id 不能为空"
    target_status = action_map[action]
    try:
        ok = store.update_status(normalized_id, target_status)
    except ExperienceCommitUncertainError as exc:
        return (
            f"[refine_experience] 提交结果不确定: experience:{exc.experience_id} "
            f"已原子可见但目录 fsync 未确认（expected_sha256={exc.expected_sha256} "
            f"visible_state={exc.visible_state}）。禁止叠加第二次语义动作：先 "
            f"exact get()/search_records 按当前实际 status 决定；同目标 status "
            f"重放幂等（updated_at 会刷新），不同目标需基于新读值重判"
        )
    except ExperiencePersistError as exc:
        return (
            f"[refine_experience] 确定未提交（{exc}）。原文件未改动，可安全重试"
        )
    except OSError as exc:
        return f"[程序异常] 经验状态更新失败（{type(exc).__name__}: {exc}）"
    if not ok:
        return f"[未找到] experience:{normalized_id}"
    return (
        f"[refine_experience] experience:{normalized_id} "
        f"状态已更新为 {target_status}"
    )
