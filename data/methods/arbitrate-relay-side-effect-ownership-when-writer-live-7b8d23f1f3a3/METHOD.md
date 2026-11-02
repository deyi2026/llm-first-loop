---
method_id: arbitrate-relay-side-effect-ownership-when-writer-live-7b8d23f1f3a3
name: arbitrate-relay-side-effect-ownership-when-writer-live
description: 跨会话接力/交接快照携带未结算的外部副作用动作（git push、发布、部署）时，先判定动作归属再组装执行管线：若目标仓存在严格晚于快照落盘时间戳的提交/mtime（或来源会话事件流缺席近期动作），说明来源写者仍在活跃、快照待办清单按构造已过期。此时第一未知量是『该动作是否已被写者自己完成』，用一次外部真值读数加写者收口台账（receipts/reflog）闭合；确证未做且写者静默才走规则闸门管线，管线运行中外部真值一旦移动立即中止并重定基线。
aliases: 交接任务先查来源会话是不是还在干, 别的会话没结算的 push 别抢着干, 快照比仓库最新提交旧就别信待办清单, 远端真值优先于本地跟踪分支的领先数, 并发会话竞态时怎么避免重放副作用
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e96054d1-d0eb-4746-93ca-d1f9d169b214:0:f95fd762ae6af6dd2393
evidence_refs: learning:learn:0ef78e7a1f1c
created_at: 2026-11-01T12:20:04.798176+08:00
updated_at: 2026-11-01T12:20:04.798176+08:00
---
## Trigger
接手跨会话接力快照/交接材料，其中列有未结算的外部副作用动作（push/发布/部署）；或准备把本地视图（如 ahead-of-origin 计数）当作远端事实并据此启动执行管线之前

## Discriminator
快照落盘时间戳与目标仓最新提交/mtime 的先后关系：存在严格晚于快照的提交即证明写者在快照之后仍活跃，其待办副作用清单已过期；且本地 remote-tracking ref 的领先数不是远端真值，事件流尾部缺席来源会话近期动作同样是活跃性信号

## Short path
- 解析快照：抽出请求的副作用动作、快照落盘时间戳、『先核验外部副作用终态/禁止自动重放』条款
- 对快照点名仓库各做一次只读 status + 带日期 log：未知量=快照以来的本地 delta
- 比较最新提交/mtime 与快照时间戳：晚于快照 ⇒ 写者活跃、待办清单过期，禁止按快照框架直接规划执行
- 一次外部真值读数（对目标 ref 的 ls-remote）+ 写者收口台账（最新 receipts、remote-tracking reflog）：未知量=动作是否已做/在做
- 远端未动且写者静默（无新回执、无新鲜工作树改动）⇒ 动作归属本会话，此时才检索规则并组装扫描+独立审查闸门管线
- 管线运行中外部真值移动（如待推数骤降）⇒ 立即中止扫描、不消耗准入资格，重定基线后输出核验-only 结论

## Stop conditions
- 外部真值、收口回执、reflog 三源一致显示动作已完成 ⇒ 不重放，报告核验结论与真实遗留项
- 确证动作未做且写者静默 ⇒ 归属本会话，进入闸门执行
- 用户明确将动作重新指派给本会话 ⇒ 跳过归属仲裁直接执行

## Verification
- 远端 ref 与本地 main 的祖先/分叉关系逐条核对
- 收口回执的推送分段、审查 PASS 时间、pushed_at 与 reflog 的 update-by-push 记录互相印证
- 声称『未重放/零写副作用』前确认本会话无 push、未消耗任何准入资格、未写目标仓文件

## Counterexamples
- 快照后目标仓无任何新提交/mtime/事件 ⇒ 无活跃写者，动作确属未认领，直接走执行管线（仅保留廉价远端预检）
- 待办动作无外部副作用（读文件、本地文档修改）⇒ 重放风险可忽略，直接执行
- 远端不可达/无凭据 ⇒ 外部真值读数不可用时退回 receipts/reflog 本地证据，不得无限阻塞
- 用户在新会话明确说『由你来执行』⇒ 归属已定，无需仲裁
