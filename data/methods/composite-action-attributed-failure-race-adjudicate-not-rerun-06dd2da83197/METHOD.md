---
method_id: composite-action-attributed-failure-race-adjudicate-not-rerun-06dd2da83197
name: composite-action-attributed-failure-race-adjudicate-not-rerun
description: 复合（多目标）控制动作终态 failed 时，第一步不是重跑、也不是当成部署未落地，而是读动作记录的逐目标 verdict 并做语义分类：若唯一失败目标是归属类条件（如 started_before_restart，进程在但非本动作拉起），且动作库中存在对该目标、落在失败动作时间窗内的 succeeded 单目标动作，则失败是并发竞争的归因伪影。独立核验该目标 manifest（pid 存活、git_head==desired）后，用账本 acknowledge 通道追加裁决（status 保持 failed、仅追加 verify_verdict），再收口；不重发 all 重启，避免全服务再启一轮。
aliases: 重启 all 报失败要不要重跑, 部署动作失败但服务都活着, 并发重启把 all 动作拖成失败, all 重启假失败, 竞态导致重启失败怎么收口, 失败动作被成功动作覆盖
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:2372:d4ad47e3f7b66e099411
evidence_refs: learning:learn:39f52dedef8b
created_at: 2026-11-01T15:00:47.671787+08:00
updated_at: 2026-11-01T15:00:47.671787+08:00
---
## Trigger
多目标复合控制动作（如 restart all）在动作库终态为 failed，需裁决部署是否实际落地或是否重跑；常见于恢复会话时看到 failed 残留、或疑似被后续成功动作覆盖

## Discriminator
failed 动作的 detail/verify_evidence 逐目标分解：非失败目标全部 ok，唯一失败目标是归属类条件（started_before_restart＝进程存在但早于本动作 stage）而非状态类失败（crash/版本不符/超时）；且同一动作 store 内存在对该目标、创建时间落在失败动作窗口内、status=succeeded 的单目标动作。这两条从动作文件一次即可读出，当时已足以把『部署失败？重跑？』缩成『竞争伪影，裁决即可』

## Short path
- 直读 failed 动作完整 JSON，把逐目标 verdict 分成状态类失败（crash/版本不符/超时）与归属类条件（started_before_restart）
- 列动作 store 中同目标、时间窗内的其他动作；读到 succeeded 单目标动作即证实并发竞争归因
- 读该目标 runtime manifest（pid/started_at/git_head）+ pid 存活检查，独立确认已运行 desired 代而非旧码
- 用账本裁决通道追加 verdict=accept 与 evidence refs；预期 status 仍为 failed、仅追加 acknowledged_at/verify_verdict（append-only 诚实裁决，不改写历史）
- goal checkpoint/complete 附证据收口；不重跑 restart，不重发 all

## Stop conditions
- 全部目标经 manifest+存活+至少一条独立旁证确认在 desired 代，且裁决已落盘追加
- 某目标 verdict 为状态类失败，或窗口内无 succeeded 动作兜底 → 仅对该目标做单目标重启，不重发 all
- 账本无追加裁决接口 → 只在 goal/evidence 记录结论，不手改动作文件

## Verification
- 动作文件新增 verify_verdict/acknowledged_at 而 status 仍为 failed（历史未被篡改）
- 每目标 manifest git_head==desired.git_head、pid alive、started_at 晚于并发成功动作
- 至少一条独立旁证（health 端点/连接日志/单测）不依赖 manifest 自述

## Counterexamples
- 失败 verdict 是 crash/版本不符/超时等状态类失败 → 不是竞争伪影，需真实修复或定向重启
- 窗口内没有同目标 succeeded 动作 → started_before_restart 可能意味着该目标从未被重启、仍跑旧码，必须重启而非裁决
- 并发成功动作拉起的是旧代码进程（早于目标代发布）→ 裁决会把真过期洗白，先核 manifest git_head 再裁决
