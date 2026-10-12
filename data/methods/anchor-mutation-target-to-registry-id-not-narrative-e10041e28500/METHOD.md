---
method_id: anchor-mutation-target-to-registry-id-not-narrative-e10041e28500
name: anchor-mutation-target-to-registry-id-not-narrative
description: 当请求方用叙述性描述（代次号、状态标签、时间、成因）指称一个待确认/待结算的系统对象，而按叙述关键词检索权威记录 miss 或回执被截断时：不要换措辞继续搜，也不要按叙述标签直接执行 mutation。把结构化运行时快照当真值，用 hydration 的 range/next_start 元数据跳跃定位其自带 pending/available_exits 注册块，取系统生成的 action_id，再按 ID 定点拉详情核身（created_at/generation/status/worker_pid）。本集用户称 gen222 failed 已 superseded，注册表里唯一待清理项实为 2026-09-23 的 gen78 僵尸 running 动作（worker_pid=0）；正是按 ID 的详情核身暴露叙述失真，避免按错误标签结算。结算后回读 status 确认 exits 清空并向用户如实纠正。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:40eeca85-e561-4f26-9faf-efda5823cb4b:749:c579be1c5a9b9f606835
evidence_refs: learning:learn:10d859093055
created_at: 2026-10-11T02:01:05.333375+08:00
updated_at: 2026-10-11T02:01:05.333375+08:00
---
## Trigger
用户以叙述性描述指称某个待处理/待结算的系统对象，需先确定确切身份才能执行 mutation；且出现任一信号：回执被截断、叙述关键词检索权威记录 miss、叙述自带“旧账/凭记忆”属性。

## Discriminator
该对象在权威记录中由系统生成 ID（action_id）唯一定位，注册块字段（created_at/generation/status/target/worker）可独立核验；叙述标签与注册块冲突时以注册块为准。当时已有的失真信号：status 显示 admission_barriers 为空、待 exit 块只有一条 web 动作骨架，而 “gen222/failed/superseded” 在证据检索中零命中。

## Short path
- 快照被截断时，用 range/next_start 元数据跳跃定位 pending/available_exits 注册段（识别并跳过已知超长数组如 generation_lag），取系统 action_id
- 叙述关键词检索一次 miss 即改读结构化权威记录，不做换措辞重试
- 按 action_id 定点拉详情核身：核对 created_at/generation/status/target/worker_pid 是否支持“可安全结算”
- 先查工具 schema 确认参数契约，再执行唯一必要 mutation（verify_acknowledge），evidence/reason 落审计
- 回读 status 确认 available_exits 清空、屏障为空；叙述与记录不符处如实写进最终报告

## Stop conditions
- 权威注册块为空或找不到与叙述结构角色对应的待处理项：停下报告差异，不顺手清理弱相关项
- 按 ID 详情显示对象仍活跃（worker 存活、非终态且影响链路）：先确认/升级，不直接裁决结算
- 回读 status 已确认目标终态且 exits 清空：停止，不做 post-sufficiency 操作

## Verification
- mutation 前必须有按 ID 的详情回执证明身份，而非仅叙述标签
- mutation 后重读权威 status，确认终态、exits、barriers 与预期一致
- 叙述与记录不一致处显式披露并纠正，不沿用错误标签结算

## Counterexamples
- 系统提供按状态过滤的直接查询（如列出 pending actions）时：直接用过滤查询，不必翻页读大快照
- 叙述关键词在证据中命中且与注册块 action_id 一致：直接核身执行，无需全量结构化阅读
- 注册表里根本没有叙述所指的待处理项（零 pending）：这是“报告不符”的触发，不是“清理任何在途项”的许可
- 对象是破坏性/不可逆操作且叙述含糊：仅注册表元数据不足以核身，需额外权威确认
