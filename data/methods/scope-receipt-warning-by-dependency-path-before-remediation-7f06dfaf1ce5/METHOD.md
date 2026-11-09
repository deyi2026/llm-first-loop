---
method_id: scope-receipt-warning-by-dependency-path-before-remediation-7f06dfaf1ce5
name: scope-receipt-warning-by-dependency-path-before-remediation
description: spawn_subagent 成功但回执附技能披露警告（如技能将被 skill_load 完整性门禁拒载，建议重跑 approve_skills.py 或改派）时，第一未知量不是选哪种补救，而是警告点名的失效通道是否与 child 实际依赖路径相交：任务书是否已内嵌该技能要点、child 白名单 read_file+fs 能否直读技能文件、建议补救是否为违反本会话边界的写动作。依赖均有独立满足路径则照常进行并留痕；只有通道 load-bearing 才补救。
aliases: spawn 报技能警告要不要改派, skill_load 被完整性门禁拒载, approve_skills 重跑前先查依赖, 子代理技能加载失败还能继续吗, 回执警告先判通道再补救, 技能披露警告怎么处理
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cc220110-4732-4841-9bd9-85c35a83e84b:0:e16367cd189347d76a85
evidence_refs: learning:learn:b5c891bbd5c3
created_at: 2026-11-09T20:39:54.242540+08:00
updated_at: 2026-11-09T20:39:54.242540+08:00
---
## Trigger
spawn/启动类工具回执成功但附带警告，点名某辅助通道将失效（如技能 skill_load 被完整性门禁拒载），并给出重登记/改派/重跑等补救建议

## Discriminator
警告文本已精确点名失效通道（skill_load 拒载）；当时已知：任务书已内嵌该技能清单要点、child 工具白名单含 read_file 且 fs=true 可直读技能文件、建议补救 approve_skills.py 属写动作而本会话仅允许写私有回执——即该通道不在依赖路径上且补救本身越权

## Short path
- 收到 spawn 成功+警告：把『选哪种补救』替换为『警告通道是否在 child 依赖路径上』这一未知量
- 用回执与任务书已知事实判定：技能内容已内嵌 ✓、child 可 read_file 直读 SKILL.md ✓ → skill_load 非必需
- 核对补救动作权限：approve_skills.py 为写登记，超出本会话只读边界 → 不执行，记录警告后原样等待真实终态
- 父不 followup/steer；轮询触发 repeat_guard 时先把父侧已核事实+未决项记入 task_state 账本再等
- child 真实 completed+PASS 后按授权落盘私有回执，回执如实注明警告与不补救的理由

## Stop conditions
- 警告通道被证实 load-bearing（child 无任何独立途径取得技能内容或流程资格）→ 转入最小补救或如实停在合并前
- child 真实终态取得且回执按授权落盘 → 停止

## Verification
- 读 child 自身 event_logs（data/event_logs/<child_id>.jsonl）白名单字段确认真实模型/settled/终态，证明未受 skill_load 拒载影响
- 回执中保留警告原文与依赖路径判定依据，供有权限 owner 会话复核

## Counterexamples
- 任务书未内嵌技能内容且 child 白名单无 read_file/fs → skill_load 是唯一内容来源，必须先重登记或改派
- 流程资格要求技能经完整性门禁登记作为合规证据（回执需引用 skill_load 资格）→ 即便内容可直读也不能跳过登记
- 警告点名的通道会在 child 运行时确定性中止整个 child（而非辅助加载）→ 照常进行等于烧掉一次运行，应先补救
