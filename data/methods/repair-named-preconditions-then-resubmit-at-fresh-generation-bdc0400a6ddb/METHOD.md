---
method_id: repair-named-preconditions-then-resubmit-at-fresh-generation-bdc0400a6ddb
name: repair-named-preconditions-then-resubmit-at-fresh-generation
description: 当受管服务的 restart/deploy 批次留下 failed 终态记录时，不要直接重试、也不要改走临时脚本：先读失败记录的结构化字段（problem_kind/detail/next_step），它们已点名阻塞前置条件（如 tracked worktree dirty、desired 与当前 HEAD 不一致）。逐条对照当前状态核实；desired 落后则经规范通道 publish 推进到当前 HEAD（带齐必填参数如 code_root），再把 restart 钉在新 generation 重新提交；受理即停，终态异步核验，不声称已完成。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:1964:0cd1b9222a35622bb09e
evidence_refs: learning:learn:b77bf7de8a95
created_at: 2026-09-24T03:51:01.982985+00:00
updated_at: 2026-09-24T03:51:01.982985+00:00
---
## Trigger
用户要求重启/重发布受管服务，且存在带结构化失败语义的上一批 failed service-action 记录（status 摘要或记录文件显示 binding/precondition 类失败，而非 transient 错误）

## Discriminator
失败记录自身已给出判别事实：聚合输出里已出现 'deployment binding failed: code_root tracked worktree is dirty' 这类点名前置条件的 detail/problem_kind/next_step；且任务第一步已知当前 HEAD 是更新的修复提交（542d98ccf，提交信息即部署面修复）。二者合起来把 '重试/换脚本/全面排查' 缩成 '核实被点名前置条件是否仍阻塞、desired 是否已落后于当前 HEAD'。

## Short path
- 读最近一批 failed action 的聚合摘要或最新一条完整记录，去重出 problem_kind 与 next_step（未知量：到底哪些前置条件阻塞哪些目标）
- 对每个 problem_kind 对照当前状态：git status --porcelain 是否干净；当前 HEAD 与 desired generation 的 git_head 是否一致（未知量：阻塞现在是否仍在）
- 若树干净但 desired 落后 → publish（带必填 code_root 等参数）推进 desired 到当前 HEAD，取得新 generation 回执（未知量：绑定是否已修复）
- 对每个目标 service_control(action=restart, expected_generation=新generation)（未知量：是否被受理）
- 报告 action_id 并声明受理≠完成；终态留给 service_control(status)/service_action_terminal 异步核验

## Stop conditions
- publish 回执 git_head 等于当前 HEAD，且全部目标的 restart 已按该 generation 受理
- 前置条件需操作者决策（tracked 改动未提交/还原）→ 停止自动修复并升级给用户，程序不得 stash/commit/checkout
- desired 已等于当前 HEAD 且树干净 → 跳过 publish，直接按现有 generation 重启

## Verification
- publish 回执的 git_head == git rev-parse HEAD
- 每个 restart 回执的 expected_generation == 刚 publish 的 generation
- 未查询到 status=succeeded/failed 前不宣布完成或失败；failed 终态需显式闭合（verify_acknowledge）
- 后续经 service_control(status) 或 service_action_terminal 事件确认各 action 终态

## Counterexamples
- 失败仅是 transient 超时/5xx、无前置条件语义 → 退避重试即可，前置修复循环不适用
- 服务不受 deployment binding 管理（普通进程）→ 直接重启，临时脚本可能才是正确通道
- desired 已与当前 HEAD 一致且树干净 → 再 publish 只会制造多余 generation，应直接重启
- dirty 的 tracked 改动需人来定夺 → 记录明令禁止程序 stash/commit，必须升级而非'修复'
