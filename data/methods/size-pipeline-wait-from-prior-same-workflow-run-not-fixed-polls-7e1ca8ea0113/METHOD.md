---
method_id: size-pipeline-wait-from-prior-same-workflow-run-not-fixed-polls-7e1ca8ea0113
name: size-pipeline-wait-from-prior-same-workflow-run-not-fixed-polls
description: 等待已知 run ID 的 CI/发布工作流到终态时，若更早的工具回执里已出现同一 workflow 上一次 completed run 的 ID（如上一版本 tag 的 push run），先用一次计时查询取其 started→updated 时长作为基线，把等待压成单次≈基线的长等待（或 gh run watch --exit-status 单调用阻塞），仅在超时或阶段变化时再轮询；轮询回执与上一次完全同相（同 step 同 status）时按指数拉长间隔。本集用 10×120s 等待加 6 次状态查询才守到本可由基线定时的一次等待覆盖的终态。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7c026852-7867-4a41-9ab0-1340271874dc:955:6d8a251c80cd3bd81020
evidence_refs: learning:learn:da662f471f5e
created_at: 2026-10-22T15:14:34.606770+08:00
updated_at: 2026-10-22T15:14:34.606770+08:00
---
## Trigger
发布/CI 工作流已被触发、持有其 run ID、任务只需终态结果（conclusion/产物）即可继续；且此前的回执（如 ls-remote 状态行、run 列表）中已可见同一 workflow 上一条已完成 run 的 ID。

## Discriminator
早前回执里那条 completed 同类 run 的 ID（本集第 1 步 ls-remote 输出即含上一 tag 的 run 39382385299）：一次 gh run view 取 startedAt/updatedAt 即得时长先验；jobs 回执中当前所处 step 进一步给出剩余量估计。固定短间隔轮询在回执内容不变（连续多次同 step 同 status）时是零信息动作。

## Short path
- 存在性探针确认触发物（tag 已在远端），并在同一回执中记下当前 run ID 与上一条 completed 同类 run ID
- 对上一条 run 做一次计时查询得基线时长 D（可得多条时取中位数）
- 当前 run 查一次状态；in_progress 则下一次等待设为≈D，或改用 gh run watch <id> --exit-status 单调用阻塞至终态
- 醒来后一次终态检查：conclusion 已定即转入产物核验（release 资产、digest、head_sha 对链），不再重复轮询
- 仅当 elapsed>≈1.5×D 仍 in_progress 时，才降级为短间隔轮询并查 jobs/日志定位挂死

## Stop conditions
- run 进入终态（conclusion 非空）→ 停止等待，转产物/结论核验
- 轮询回执与上一次完全同相（同 step 同状态）→ 不按原间隔重发，拉长间隔或改阻塞 watch
- elapsed 超过约 1.5×基线仍 in_progress → 停止盲等，转为挂死诊断（jobs 步骤、日志失败行分类）

## Verification
- 终态 conclusion 与 tag 解引用提交的 head_sha 一致
- 产物链独立复核（release 资产 digest 与清单文件逐一相等、验收 JSON 关键字段）不因等待方式而省略

## Counterexamples
- 该 workflow 无历史 completed run（首次发布/新工作流）→ 无基线可用，退回带明确上限的短轮询
- 任务目标是向围观用户实时播报进度 → 增量轮询本身是交付物，不适用单次长等待
- 历史时长高方差或排队时间占比大 → 单次按一点样本定尺易过冲/欠冲，应取多 run 中位数并保留等待上限
- 等待窗口内存在可并行推进的独立核验工作 → 应交错工作与适度等待，而非一次性盲睡
