---
title: 子代理 live 验证：以事件日志为准，勿信自我报告；ContextVar 写入必须经真实派发路径测试
scenario: 验证子代理工具范围控制/新工具 live 行为时，依赖子代理最终报告或直调式单测作为证据
root_cause: ""
solution: 以事件日志为唯一事实源核对工具调用；单测覆盖真实派发路径（copy_context 边界）；预算类护栏用连续多次调用验证
evidence: "evidence://v1/a72bd81137515443c484a8202dea69dfa57e0118ec8af032a2c380fbe305df5e（live 回执）；evidence://v1/5ef41c9f730b9f80c53e65e09a1a1f0a30b74c98c82886466283c1229ebfb77d（事件日志提取）"
tags: [live-验证, 子代理, 单测盲区, contextvars, 证据纪律]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-12T07:14:07.184959+08:00"
updated_at: "2026-10-12T07:14:07.184959+08:00"
---

live E2E 验证（subagent_eba6474f31e8，2026-10-12）暴露两个盲区并发现一个真缺陷：
1. child 最终报告称"两次发起 read_file 调用尝试，未收到回执"——事件日志（message.appended 的 tool_calls 数组）显示三轮调用全部是 wait，read_file 从未被发出。模型在文本中描述的"尝试"≠ API 事实。
2. 单测 test_e4_requires_enforcement_e5_wait.py 直接调用 WaitTool().execute()，同 context 下 set 立即可见；而 registry.py:1572 真实派发路径经 copy_context() 副本执行，set 写入即弃。导致 12 项单测全绿而 live 累计预算失效（回执 1/1/5s，应 1/2/7s）。
验证纪律：(a) 子代理自我报告只作参考，结论必须核对 data/event_logs/<child_id>.jsonl 的 message.appended/tool.execution 事件；(b) 涉及 ContextVar 写入的工具，单测必须经 registry.execute 真实派发路径验证持久性，直调单测存在系统性盲区；(c) 单次调用的 E2E 无法区分"累计"与"本次"，预算/计数类护栏的 E2E 必须连续多次调用。