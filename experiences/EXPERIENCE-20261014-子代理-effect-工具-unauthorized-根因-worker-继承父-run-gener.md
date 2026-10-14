---
title: 子代理 effect 工具 unauthorized 根因：worker 继承父 run generation（文案误导为 lease fenced）
scenario: "子代理 execute_command 全量 unauthorized（\"run lease fenced\" 文案），需定位根因；同类：错误文案与真实失败源错位的权威分层系统排查"
root_cause: ""
solution: "跳过文案，按证据链排查：磁盘真相（data/fleet/state.json lease 链）→ 事件日志统计（26 会话 0 成功=确定性缺陷）→ journal 权威分层源码（lease fence 之后还有 run_generation_authority）→ 复现生产 contextvar 形态写 red 测试 → 修复=子代理工具执行窗口隔离 current_run_generation.set(\"\")"
evidence: "evidence://v1/2eede9c33959e35d360335beaba153a18459b56551ebdf69dcd32644fda2a83d（ws-87 lease 链磁盘真相：acquire 1791967766.21 → renew 续至 1791968783.74 → settled 1791967905.03）；artifact://v1/d5775eb283f74c61adb2c0664f679c55（修复 diff 快照）；git commit 47773fff5"
tags: [subagent, effect-authority, contextvars, run-generation, fence, misleading-error-message, fleet-lease]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T17:21:34.273199+08:00"
updated_at: "2026-10-14T17:21:34.273199+08:00"
---

现象：spawn 子代理（fs=true、execute_command 在白名单）从 2026-10-12 18:59 起 26 个会话 execute_command 0 成功，全部 round 1-2 即 unauthorized，错误文案统一 "effect authority 丢失（run lease fenced）"。

排查路径与纠偏点：
1. 文案误导：先沿 lease 链路排查（runner.py:797 renew 失败 sticky、store.py lease_is_current），全部排除——data/fleet/state.json 磁盘真相显示 ws-87 lease 链完美（acquire→renew 全成功→settled completed），87 lease 全 settled 无 superseded。
2. 真根因（journal.py:437-449）：effect_mutation_authority 在 lease fence 之后还有 run_generation_authority 层；spawn worker 线程 copy_context() 继承父 run 的 current_run_generation，binding 带父代查子会话注册表（session.py:1242 _run_save_generations 只注册父 sid）→ "" != 父代 → 拒绝。execute_command 文案写死 "run lease fenced"，两源不分。
3. 测试为何全绿：单测直接 runner.run() 路径 generation 默认 ""（legacy 放行），从未覆盖"父代非空"生产形态。

修复：runner.py 子代理工具执行窗口 current_run_generation.set("") 隔离（commit 47773fff5），red→green 测试 tests/unit/test_subagent_effect_generation_isolation.py（修复前 allowed=False 精确复现）。回归子集 315 passed；全量 7508 passed / 1 预先存在失败（test_static_diagnostic_gate，stash 干净树复现同败）。

可复用方法：① unauthorized/失败文案与真实拒绝源可能错位——先取磁盘真相（state.json）与事件日志原始参数（jsonl 里 tool_calls arguments 原文），再沿代码分层逐层排除；② contextvars.copy_context 的线程会继承父 run 全部 contextvar，跨会话边界（父→子代理）必须显式重置会话身份类变量；③ "测试绿但生产 100% 挂"优先怀疑环境形态差异（contextvar 播种/进程边界），写复现测试时显式模拟生产形态（非空 generation）。