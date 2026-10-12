---
title: 长任务调度模式：主循环只调度，重活委托后台（防轮次耗尽）
scenario: 处理含大量可并行/独立子步骤的长任务（多实例修复、批量处理、多文件改动）时，如何避免单循环轮次耗尽
root_cause: 长任务子步骤逐个在前台循环执行 → 每步耗 1 轮 → 40 轮上限快速耗尽；未在开始前评估并行化/后台化
solution: "主循环只做调度：先评估拆分 → 委托后台（job/dsh_task background/workflow 扇出/spawn）→ 轮询汇总（job_output）。预警文案已升级引导此模式。详见本文\"正确姿势\"。"
evidence: 2026-08-18 sympy 12 实例单循环 40 轮耗尽中断（DSH 009 复盘）；后台 job 方式 10-15 轮完成调度（dsh_task background/job 机制已有）；预警文案升级已落地（feedback/honesty.py max_iterations_warning_message）
tags: [长任务, 调度, 后台任务, 轮次管理, 并行]
source: {}
status: active
created_at: "2026-08-18T00:35:00.491204+08:00"
updated_at: "2026-08-18T00:35:00.491204+08:00"
---

## 长任务调度模式（2026-08-18 教训沉淀）

### 反模式（实证踩坑）
单循环硬跑：12 个 sympy 实例逐个 execute_command 修复 → 40 轮上限预警（32/40）→ 达上限中断，剩余实例未完成。串行 + 每轮都耗轮次。

### 正确姿势（主循环只做调度）
1. **评估拆分**：任务含大量可并行/独立子步骤（多实例/批量/多文件）→ 先拆
2. **委托后台**：
   - 后台 job：execute_command(run_in_background=true) → job_output 查结果/job_kill 终止
   - dsh_task(background=true)：进程级子代理（独立会话+工具链），主循环不阻塞
   - workflow_run(mode=parallel/pipeline/dag)：多步骤编排
   - spawn_subagent：进程内子代理（同步阻塞，适合单个委派）
3. **轮询汇总**：主循环 10-15 轮完成调度（起任务+轮询+汇总），40 上限绰绰有余
4. 预警触发前主动拆：轮数预警文案已含此引导（2026-08-18 升级）

### 判断标准
- 子步骤是否可并行/独立 → 是则后台
- 子步骤是否耗轮次（每个 execute_command 1 轮）→ 多则后台
- 主循环只做决策/调度/汇总，重活全委托