---
method_id: resolve-receipt-identity-to-producer-detail-log-14fe1ff2b7ae
name: resolve-receipt-identity-to-producer-detail-log
description: 失败只剩一份结构化但信息稀薄的权威回执（仅 rc/stage_fact/port 之类）时，回执里的身份字段（action_id、authority、ts、git_head/generation）本身就是指向生产子系统 per-action 明细记录的已命名 provenance 指针，可机械解析。正确路径是：精确取回执→按 authority+action_id 定向定位明细日志→读原始错误→用版本指针做失败/成功单变量对照。禁止开局跑泛化 audit/status 巡检、禁止拿 id 或错误关键词对整个工作区做 content 扫描来“猜”明细位置。本集该规则可把 9 次调用压到约 5 次，省去 1 次巡检噪声与 2 次 search miss。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:1851:d6a5f1fb9fdc685370ac
evidence_refs: learning:learn:bcaede9f9f70
created_at: 2026-10-09T14:59:49.835432+08:00
updated_at: 2026-10-09T14:59:49.835432+08:00
---
## Trigger
排查一次失败动作（restart/start/部署等）的根因：权威回执已存在但字段稀薄（无错误正文，只有 rc/stage/port 类细节），且该动作的唯一 action_id 已在手。

## Discriminator
回执是机器写成的结构化记录，含唯一身份键 action_id 与权威方字段 authority——这些字段可机械解析为生产者明细存储的查找键；此判别事实在首个动作前即已可用（用户已给出回执稀薄+id 可用），足以把“所有文件都可能有答案”缩成“按身份键找 per-action 记录”。

## Short path
- 精确读权威回执本体（路径未知时用事件流按 action_id 做一次窄查询，上轮 trace 已含路径；不做全库 content 扫描），取全字段：action_id、authority、stage_fact、ts、git_head。未知量：回执还暴露了哪些指针。
- 用 authority+action_id 按该子系统的命名约定定向定位 per-action 明细记录（如 <authority-domain>-logs/<action_id>.log），只做目录级定向校验，不做关键词枚举。未知量：失败时的原始输出落在哪。
- 读明细记录，提取直接失败原因（traceback/错误行，如未知字段拒绝启动）。未知量：该版本为何拒绝。
- 用回执自带版本指针对失败版本与成功版本做单变量对照（如两 git_head 的字段注册表 diff + 配置文件确认）。未知量：失败与成功的最小差异。
- 因果链双侧闭合后给出结论，停止。

## Stop conditions
- 已从与 action_id/authority 逐字段一致的明细记录中取得直接失败原因（错误正文/traceback）
- 根因已被两个独立来源交叉验证（错误信息 ↔ 版本间代码/schema 差异），且能同时解释失败与随后的成功动作

## Verification
- 明细记录路径与内容的 action_id、时间戳、authority 必须与回执逐字段一致
- 所提根因必须同时覆盖 rc=1 失败动作与随后 rc=0 成功动作的最小差异，缺任一侧即假设未闭合
- 全程保持只读约束：无写操作、无服务状态变更

## Counterexamples
- 回执 detail 字段已含完整错误正文或 traceback：直接分析，不必再找明细日志
- 回执是自由文本、无结构化身份字段：指针无法机械解析，应按服务名/时间窗做常规日志发现
- 生产子系统没有 per-action 明细存储（回执即唯一记录）：身份指针边断裂，转事件流/常规日志
- 时间窗内多动作混叠、单一 id 不能唯一窄化：先按时间窗或会话范围界定，再解析指针
