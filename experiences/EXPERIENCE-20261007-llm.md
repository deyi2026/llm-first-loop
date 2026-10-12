---
title: LLM 空响应有界重试的幂等性证明与实现模式
scenario: LLM 流式响应正常结束但零内容零工具调用（glm-5.3 thinking 模式高发瞬态），run 整轮中断需用户手动重发。
root_cause: ""
solution: 在 client stream() 分发器层做同模型有界重试（1 次 + 0.5s 退避）后仍空才上抛；并把 LLMEmptyResponseError 加入引擎 fallback 可降级清单（仅默认装配路径）。幂等性不靠 delta 跟踪包装：空响应条件本身保证零 text/tool delta 已投递；唯一可能已上抛的是 reasoning delta，重复投递只影响 UI 展示与中断半截产物，非权威状态；非收敛熔断需 3 连击相似窗口，单次重试不可触发。
evidence: job-6df0179866004578a2fc 全量 tests/unit 6404 passed/107 skipped/exit=0；定向 -k empty_response 4 passed（2026-10-07）
tags: [llm-client, stream-retry, idempotence, glm]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-07T09:02:42.762231+08:00"
updated_at: "2026-10-07T09:02:42.762231+08:00"
---

实现位置：src/llm_loop/llm/client.py stream() 分发器——try/分发/yield from 外包 while True，空响应时计数+warning+退避后 continue，达上限（1 次）才 raise；fallback 资格在 fallback.py _is_fallback_eligible_error 增列。关键坑：① Python 3.11+ 裸 yield from 丢子生成器 return 值，重试包装若引入中间生成器必须显式捕获 StopIteration.value 再 return（client.py:1686 既有注释警告）；② 重试幂等性靠触发条件本身证明而非 delta 跟踪——零 text/tool delta 已投递由 not result.content and not result.tool_calls 直接蕴含（text delta 必进 content_parts）。测试模式：monkeypatch _stream_openai 为返回空 LLMResponse 的假生成器，断言调用次数=2/仍抛/非空不重试。当前性验证：grep -n "_empty_retries_used" src/llm_loop/llm/client.py 应命中 ~1713/1749；.venv/bin/python -m pytest tests/unit/test_llm_client.py -k empty_response -q 应 4 passed。