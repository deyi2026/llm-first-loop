"""经验沉淀/生命周期工具实现（design §2.3.2.1/§2.3.2.2）.

save_experience/refine_experience：参数校验 → 调 ExperienceStore → 如实回执（fail-open 不阻断主循环）。
程序仅提供通道；提取/判断/应用归 AI 自主（RULE-AI-00）。
"""

from __future__ import annotations

from datetime import datetime

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore


def run_save_experience(
    store: ExperienceStore,
    *,
    title: str,
    scenario: str,
    solution: str,
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
    now = datetime.now().astimezone().isoformat()
    doc = ExperienceDocument(
        title=title,
        scenario=scenario,
        root_cause=root_cause,
        solution=solution,
        evidence=evidence,
        tags=tags or [],
        source=source or {},
        status="active",
        created_at=now,
        updated_at=now,
        body=body,
    )
    try:
        filename = store.save(doc)
        return f"[save_experience] 已沉淀 {filename}"
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
    target_status = action_map[action]
    try:
        ok = store.update_status(experience_id, target_status)
    except OSError as exc:
        return f"[程序异常] 经验状态更新失败（{type(exc).__name__}: {exc}）"
    if not ok:
        return f"[未找到] {experience_id}"
    return f"[refine_experience] {experience_id} 状态已更新为 {target_status}"
