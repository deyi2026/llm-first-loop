---
title: token 预算标定必须用 provider 真实 usage，不能用估算；且标定值要分字符类
scenario: "需要判断一份 1.9M 字符的代码/JSON 混合材料能否装进模型的 800K 输入 token 窗口。registry 提供的 chars_per_token=0.6 是中文混合标定（1.676 tok/char），对 88% ASCII 的代码 diff 高估约 4.4 倍；我最初按\"ASCII 3.5 / CJK 0.6\"估算，估算值 806K 仍超物理窗口，看起来\"物理装不下\"，差点得出错误结论。"
root_cause: ""
solution: "用 provider 的真实 usage.prompt_tokens 标定：直接 POST 一次 chat/completions（max_tokens=1）读 usage，拿到材料的真实 token 数（762,018），并对 ASCII 部分与 CJK 部分分别标定（2.633 / 1.432 字符每 token）。三点要注意：(1) 真实 tokenizer 只能在 API 返回里取，client 的 count_tool_schema_tokens 只对本地 llama.cpp 运行时可用；(2) BPE 跨字符类会合并，逐类相加会高估约 5.8%，修正量与\"少数类字符数\"成正比（本次 0.198811 token/少数类字符），所以纯 ASCII 或纯 CJK 材料不受该修正影响；(3) 校准后估算仍应保持偏保守（本次 +1.7%），方向上宁可误拒不可误放。标定结果与门禁回执一并落盘备查。当前性验证：跑 `grep -n \"_WIRE_ASCII_CHARS_PER_TOKEN\|_WIRE_NON_ASCII_CHARS_PER_TOKEN\|_WIRE_CROSS_CLASS_SAVING_TOKENS\" src/llm_loop/subagent/runner.py` 应得三个常量定义；跑 `.venv/bin/python -c \"import sys;sys.path.insert(0,'src');from llm_loop.subagent.runner import _wire_chars_per_token;print(_wire_chars_per_token([{'content':'x'*10000}],0.6))\"` 应得 >2.0（ASCII 用实测比率而非 registry 0.6）；若返回 0.6 说明标定常量已丢失或未生效。"
evidence: "GLM-5.3 API 实测：材料 1,935,808 字符 -> usage.prompt_tokens=762,018；ASCII 400K 样 -> 2.633 字符/token；非 ASCII 40K 样 -> 1.432；逐类相加 806,537 与真实差 44,519（跨类 BPE 合并）。落盘 evals/results/review_cap_change_20261023/calibration.txt"
tags: [token-budget, calibration, provider-usage, measurement, bpe]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-23T19:12:20.299572+08:00"
updated_at: "2026-10-23T19:12:20.299572+08:00"
---