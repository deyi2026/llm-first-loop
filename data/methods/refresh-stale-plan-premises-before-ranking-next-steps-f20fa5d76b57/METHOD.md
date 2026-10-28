---
method_id: refresh-stale-plan-premises-before-ranking-next-steps-f20fa5d76b57
name: refresh-stale-plan-premises-before-ranking-next-steps
description: 继承上一轮审计/计划文档回答『下一步做什么』时，不按其 P0/P2 标签直接排序：先刷新三类前提再给建议——①状态锚点：文档自述的基线 commit/线上版本/开关，对照当前 git log 与控制面 status 回执；②缺陷定级：读对应源码注释/docstring，确认是缺陷还是写明的设计决定；③证据可复现性：commit/文档引用的指标能否在库内定向 grep 到产物。任一前提被推翻都应改变优先级，建议指向闭合最大前提断层的首步（如为已上线变更补真实库基线并预注册判定规则）。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f6f1dadc-64d2-4789-bbac-44b68f133442:1076:501cb58e2a0ac8f9efcd
evidence_refs: learning:learn:9b0239cfc0ee
created_at: 2026-10-20T07:38:34.275531+08:00
updated_at: 2026-10-20T07:38:34.275531+08:00
---
## Trigger
用户基于上一轮产出的审计/计划/缺口文档询问『下一步建议』，且该文档自带可核验状态锚点（自述基线 commit、线上版本或开关值、环节定级、引用的指标数字）

## Discriminator
文档自述锚点与当前已观察事实的差集：git log 中晚于文档基线的新提交、控制面回执的 git_head/开关与文档不符、源码注释把文档定级的『缺陷』声明为设计决定、被引指标在 docs/scripts/evals 定向 grep 无产物——每个差集即一条已翻转前提，直接改写建议排序

## Short path
- 定位并读上一轮权威文档，提取结论清单与自述锚点（基线 commit、线上版本、定级、引用指标）；未知量：上一轮以什么状态为前提
- 用当前 git log 与控制面 status 回执对照锚点；未知量：哪些状态前提已过期（如变更已上线、开关已开）
- 对仍定级为缺陷的条目只读对应源码注释/docstring；未知量：缺陷还是写明的设计决定
- 对关键被引指标做库内定向 grep；未知量：证据是否可复现
- 按前提翻转重排：建议闭合最大断层（如为已上线变更冻结查询集、补真实库基线并预注册判定规则），并显式列出『暂缓项+理由』而非按原文档标签顺序执行

## Stop conditions
- 三类前提（状态锚点、缺陷/设计定级、引用证据可复现性）均已取得回执级确认或翻转
- 首步建议只依赖已核验前提，且明确回答『先做哪个、暂缓哪个』

## Verification
- 每条翻转前提附翻转证据：status 回执的 git_head/开关值、代码 file:line 的设计意图注释、定向 grep 的范围与结果
- 复查首步建议：若只是原文档标签的机械执行、未引用任何核验回执，视为刷新不充分

## Counterexamples
- 上一轮文档是纯任务清单、无任何状态锚点 → 直接按用户目标排序，无需刷新
- 文档与本会话同 HEAD 刚写完、锚点即当前状态 → 刷新冗余，直接采纳
- 源码对被指缺陷保持沉默且行为确违反文档预期 → 缺陷定级成立，不得凭沉默翻成设计决定
- 被引指标存于库外系统（外部看板/CI 历史）→ 库内 grep 无产物不等于不可复现，先界定覆盖范围再查外部权威源
- 用户只想恢复上一轮原文说了什么 → 属有界检索/会话证据方法范畴，本卡不适用
