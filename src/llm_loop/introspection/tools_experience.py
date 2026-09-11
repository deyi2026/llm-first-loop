"""经验沉淀/生命周期工具实现（design §2.3.2.1/§2.3.2.2）.

save_experience/refine_experience：参数校验 → 调 ExperienceStore → 如实回执（fail-open 不阻断主循环）。
程序仅提供通道；提取/判断/应用归 AI 自主（RULE-AI-00）。
"""

from __future__ import annotations

from datetime import datetime

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.tools.arg_coerce import coerce_obj, coerce_str_list


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
    now = datetime.now().astimezone().isoformat()
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
    except OSError as exc:
        return f"[程序异常] 经验状态更新失败（{type(exc).__name__}: {exc}）"
    if not ok:
        return f"[未找到] experience:{normalized_id}"
    return (
        f"[refine_experience] experience:{normalized_id} "
        f"状态已更新为 {target_status}"
    )
