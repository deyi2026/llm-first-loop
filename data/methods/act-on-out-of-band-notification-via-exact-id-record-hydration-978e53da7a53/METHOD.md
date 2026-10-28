---
method_id: act-on-out-of-band-notification-via-exact-id-record-hydration-978e53da7a53
name: act-on-out-of-band-notification-via-exact-id-record-hydration
description: 带外通知（人工审批回执/web 面板）声称带稳定 ID 的记录已发生状态迁移并要求核实后继续时：把通知当待验证声明，用精确 ID 从权威存储水合完整正文，而不是凭截断摘要或关键词变体重搜。由正文中的决定性字段（真实 status、actions 是否为空、human_exec_override、impact_files）判定『继续执行』是等自动计划还是亲手实现，再读 impact_files 真实源码动手。本集省掉约 8 次变体搜索/全库枚举，并避免凭摘要改安全相关代码。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:80246fde-e7ed-4d85-a591-1327907b29de:254:981372d5f79749265851
evidence_refs: learning:learn:f2af73df0127
created_at: 2026-10-18T12:25:33.355142+08:00
updated_at: 2026-10-18T12:25:33.355142+08:00
---
## Trigger
外部/带外通知（人工审批回执、web 面板、另一进程）给出稳定唯一记录 ID 并声称状态迁移（如 approved→executing），要求核实后继续执行；后续将产生代码改动或不可逆动作。

## Discriminator
通知已携带可唯一水合的精确 ID；而检索回执可见内容被截断（摘要断句）或按内容关键词 miss——说明关键词搜索只能给摘要/状态碎片，完整正文与执行计划字段只在权威记录本体里。

## Short path
- 提取通知中的精确 ID 与被声称的状态迁移；通知内容=待验证输入，不是事实
- 按 ID 精确水合完整正文：优先用一等状态查询；miss 或截断时不换词重搜，而从记录工具自身模块定位持久化存储（如落盘 jsonl）直接按 ID 过滤
- 读决定性字段：真实 status、actions 是否为空、human_exec_override、impact_files → 判定亲手实现 vs 等自动计划
- 只在完整正文确认后读 impact_files 真实源码，再实施改动
- 以实测验证（定向+全量测试/独立审查），未完成项如实登记，不粉饰

## Stop conditions
- 每条被点名的记录完整正文已从权威来源取得，status 与执行方式已确定
- 后续代码改动均有『完整正文 + 真实源码』双重依据
- 记录 status 与通知不符时停止执行并回报，而不是按通知继续

## Verification
- 所做改动与记录正文 impact_files/建议范围一致
- 状态断言来自按 ID 水合的权威正文，而非通知原文或检索摘要
- 区分『闸门已修复/已部署』与『原任务目标已完成』，两者不混报

## Counterexamples
- 通知不携带稳定 ID 或记录不可按 ID 水合——需要宽发现，本方法不适用
- 简单问询且截断摘要已足以回答——无需水合完整正文
- 存储有并发写者且存在一等实时状态工具——决策时刻应重读一等工具而非读落盘快照，防陈旧
