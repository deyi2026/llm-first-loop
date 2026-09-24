---
title: 裸调 engine.registry.execute 需先建立 run_context（evidence capture 依赖 current_session_id contextvar）
scenario: 在 LFL 引擎之外裸调 engine.registry.execute(tool_call) 复用引擎工具面（eval harness/独立 driver 场景）
root_cause: ""
solution: 镜像 lifecycle._bound_run_context 设置 run_context 三个 contextvars（session_id/run_generation/workspace_root）再执行；异常分类只认 LLMError；路径绝对化；.env 注入放 harness 层
evidence: "evals/harness_evolution_v0/results/hev0-p3-20260921T011130Z/gates.json（G1-G4 全绿，其中 G2 真工具经 registry 执行成功）；b0_driver.py b0_run_context()；调试复现记录 evidence://v1/0b41fcbe（RuntimeError: evidence capture 缺少 current session id）"
tags: [lfl-engine, same-source-reuse, contextvars, evidence-capture, eval-harness, b0-driver]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T09:17:17.579256+08:00"
updated_at: "2026-09-21T09:17:17.579256+08:00"
---

背景：hev0 P3 B0 裸会话 driver 需要与 LFL 引擎"工具面 100% 同源"（name/schema/执行语义/硬安全边界），但不运行引擎循环本身。方案是 build_engine(settings) 作脚手架，取 engine.registry 执行工具、engine.llm 作客户端。

发现：直接调 engine.registry.execute(call) 会失败——registry 的执行包裹层含 EvidenceSourceResolver（evidence capture），其 owner_resolver 经 factory._evidence_owner_for_session 读取 contextvar current_session_id（llm_loop.core.run_context），引擎只在 run_stream 入口（lifecycle._bound_run_context）设置它。裸调用返回 FAILURE 回执"[执行异常] RuntimeError: evidence capture 缺少 current session id"，而非抛异常——表面像工具坏了，实际是执行上下文缺失。

修法：driver 镜像 lifecycle 的 contextvars（current_session_id/current_run_generation/current_workspace_root，同 set/reset 纪律）建立执行上下文后再执行工具。这不是 hack：是引擎文档化的执行上下文机制（P0-5 run_context 注释明确说明 CLI 直跑读默认空串走回退）。

次生坑：(1) 异常分类要窄——只把 LLMError 转 provider 终态，其余（驱动 bug/断言）必须如实抛出，否则驱动缺陷被吞成 provider_error 假终态；(2) driver 内 os.chdir(workdir) 后，CLI 相对路径全部错位，gates/调用方必须传绝对路径；(3) load_settings 需要根 .env 的 LLM_API_KEY，子进程环境注入点应放 harness 层（双臂对称）。