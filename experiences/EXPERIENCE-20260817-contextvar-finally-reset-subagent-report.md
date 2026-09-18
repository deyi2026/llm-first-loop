---
title: "子代理工具上下文注入模式: contextvar + finally reset（subagent_report 实现范式）"
scenario: "需要让\"运行在隔离会话中的子代理\"能安全调用\"依赖父侧上下文\"的工具（如中途报告收集、会话归属读写）时；以及子代理工具测试装配与生产对齐时。"
root_cause: ""
solution: contextvar 注入 + finally reset 模式（见 body）；工具内 ctx None 检查如实拒绝；conftest 装配与 factory 对齐；interop 写方加序号防同秒碰撞 + 报告条数上限防御。
evidence: DSH 022 建议 B/A 落地（2026-08-17），测试 10/10 + 子代理回归 19/19 全绿
tags: [contextvar, 子代理, 工具上下文, 模式, 隔离会话]
source: {}
status: active
created_at: "2026-08-17T18:38:15.913320+08:00"
updated_at: "2026-08-17T18:38:15.913320+08:00"
---

## 模式
1. 定义模块级 contextvar（默认 None 表示非子代理上下文）：
   `_CTX: ContextVar[tuple[list[str], str] | None] = ContextVar("name", default=None)`
2. runner.run() 在切换子会话前 `tok = _CTX.set((sink, sid))`，finally 里 `_CTX.reset(tok)`——与现有 session_id 保存/恢复并列，保证任何返回路径（成功/异常/截断）都恢复。
3. 工具 execute() 内 `ctx = _CTX.get(); if ctx is None: 拒绝`——非子代理上下文如实拒绝。
4. 收集器 sink 由 runner 回填进 SubAgentResult.reports，随 spawn_subagent 回执摘要给父级。
5. 测试隔离: conftest 的 build_test_engine 需同步注册新工具（否则子代理调用报工具不存在，测试与生产装配漂移）。

## 注意
- contextvar 与线程池: registry.execute_many 经 copy_context 传播（项目已有先例），子代理循环是单线程顺序执行，无并发风险。
- 诚实边界: 同步模型下 report 是"轮间可见性"（inbox 注入父会话后续轮），非毫秒级实时——向协作方如实标注。

## 落地
- subagent_report 工具: src/llm_loop/tools/builtin/subagent_report.py（_SUBAGENT_REPORT_CTX）
- runner: src/llm_loop/subagent/runner.py run() 注入/恢复
- 测试: tests/unit/test_subagent_report.py 6+4 用例