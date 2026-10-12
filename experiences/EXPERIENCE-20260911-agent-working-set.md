---
title: Agent 运行时环境变量泄漏导致源码仓测试假红（working-set 投影案例）
scenario: "LLM agent harness 自身以环境变量（LFL_TOOL_WORKING_SET_RECEIPTS/BATCH_CHARS/GRACE_GROUPS）驱动投影行为；从 harness 内部 shell 跑其源码仓的单测时，这些 ambient env 泄漏进 pytest，monkeypatch 只覆盖部分旋钮导致确定性测试间歇性红。表现为 working-set 投影\"失效\"（旧组不折叠成 receipt），易被误判为投影代码缺陷。"
root_cause: ""
solution: "先做 env 差分实验：env -u 相关变量重跑对照；实测 grace_groups=1 而 grader 只改了 RECEIPTS/BATCH_CHARS。修法：测试侧 monkeypatch.delenv(\"LFL_TOOL_WORKING_SET_GRACE_GROUPS\", raising=False)（或共享 fixture 清空全部 LFL_TOOL_* 旋钮）；结构性修法是测试/确定性 bench 不读 ambient env、显式传配置（参考底座 cognitive_cache 调用点显式 config 模式）。"
evidence: "PYTHONPATH=src 直跑同仓代码 + env -u 对照实验全绿；inspect.getsource 确认 _working_set_grace_groups 默认 \"0\" 但实测返回 1（env 泄漏）；stats 显示 folded_results=0/grace_raw_chars=10000"
tags: [env-leakage, test-isolation, working-set-projection, llm-first-loop, flaky-test]
source: {}
status: active
created_at: "2026-09-11T04:02:15.291472+08:00"
updated_at: "2026-09-11T04:02:15.291472+08:00"
---