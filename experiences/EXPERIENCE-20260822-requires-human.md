---
title: "演进审批\"点击不了\"排查：涉边界项 requires_human 前端漏传导致审批流程走不通"
scenario: "用户反馈 web 端左侧演进审批面板有审批\"点击不了\"。排查此类问题的标准路径：① architecture_status 查 evolution_summary（pending_review 计数）→ ② 读 data/audit/evolution_suggestions.jsonl 确认待审批条目及其 requires_human/impact_scope → ③ 对照 webui/src/components/sidebar/EvolutionPanel.tsx 前端审批流 → ④ 对照 src/llm_loop/web/routes.py 后端校验。本次定位为前端缺陷而非设置问题。"
root_cause: Approval UX v2 批 1 前端实现缺陷：涉边界项（requires_human=true）批准需要额外确认标志 extra_confirm，但前端 setConfirm 未透传 requires_human 且请求体未带 extra_confirm，后端 409 硬校验拦截，用户无法完成审批。
solution: "涉边界演进（requires_human=true）审批不可用的根因是前端两处漏传：① 点击\"批准\"时 setConfirm({id, decision}) 未携带 requires_human 字段（EvolutionPanel.tsx ~273 行），导致二次确认弹层的\"我已知悉涉安全边界\"勾选框不渲染；② review() 请求体未带 extra_confirm 字段（~104 行），后端 routes.py 746-757 行硬校验 requires_human 项须 extra_confirm=true 否则返回 409 confirm_required。表现为点确定后报\"涉边界项批准须额外确认\"且面板刷新，即\"点击不了\"。修复：setConfirm 传入 requires_human: it.requires_human；review() body 加 extra_confirm（涉边界且勾选确认后为 true）；重新构建 webui。另注意 requires_human 项 checkbox 批量禁用（disabled={it.requires_human}）属设计（涉边界禁止批量、须单条审批），非 bug。判定标准：pending_review 且 requires_human 的条目必然\"需要审批\"，只是 UI 缺陷堵住了通道。"
evidence: "architecture_status.evolution_summary.pending_review=3（与面板 3 待审批吻合）；evolution_suggestions.jsonl 中 EVO-20260821-69e7f172/e32ba979/d9a213f9 均 requires_human=true；routes.py:746-757（extra_confirm 硬校验）、834-838（批量跳过 requires_human）；EvolutionPanel.tsx:273-276（setConfirm 漏传 requires_human）、312-322（勾选框依赖 confirm.requires_human）、104-109（请求体无 extra_confirm）。"
tags: [演进审批, webui, requires_human, extra_confirm, 前端缺陷, 排查路径]
source: {}
status: active
created_at: "2026-08-22T10:51:08.285198+08:00"
updated_at: "2026-08-22T10:51:08.285198+08:00"
---