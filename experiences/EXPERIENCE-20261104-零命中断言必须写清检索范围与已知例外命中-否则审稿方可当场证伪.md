---
title: 零命中断言必须写清检索范围与已知例外命中，否则审稿方可当场证伪
scenario: LFL 推广稿正文里写「全仓库检索 tool_version、tool_hash、schema_hash、verify_tool、tool_fingerprint 五个关键词，命中 0 处」，用来论证仓库内没有工具实现校验代码；两名独立审稿子代理同时指出该句按字面可被证伪（eval/verdicts.py 的 verify_tools 命中 3 处）。
root_cause: ""
solution: 零命中断言必须写成「检索根 + 文件类型过滤 + 与主题相关的命中数 + 已知例外命中及其无关理由」四件套；禁止只写「命中 0 处」。改前：全仓库检索五个关键词，命中 0 处。改后：在 src/llm_loop 下的 .py 源码里检索这五个关键词，与工具实现版本/哈希校验相关的命中 0 处；唯一命中的是评测代码里的参数名 verify_tools（3 处，src/llm_loop/eval/verdicts.py），与工具实现校验无关。凡正文里出现「0 处/没有/不存在」这类全称断言，都按同一模板自检后再发布。
evidence: docs/promotion/receipts/daily58-content-review.json（子代理 subagent_2537c8e2b3c5 的 P1）、docs/promotion/receipts/daily58-content-review-b.json（子代理 subagent_635f5fc025c6 同一 P1）、docs/promotion/receipts/d58-lfl-static-readings.txt（命令 5 真实输出：3 处 verify_tools）、docs/promotion/receipts/20261104-daily58-public-body.json（公网 has_fix=true / has_old=false）
tags: [写作纪律, 事实核验, 零命中断言, 审稿, grep]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T09:20:55.400133+08:00"
updated_at: "2026-11-04T09:20:55.400133+08:00"
---

零命中断言必须写成「检索根 + 文件类型过滤 + 与主题相关的命中数 + 已知例外命中及其无关理由」四件套；禁止只写「命中 0 处」。改前：全仓库检索五个关键词，命中 0 处。改后：在 src/llm_loop 下的 .py 源码里检索这五个关键词，与工具实现版本或哈希校验相关的命中 0 处；唯一命中的是评测代码里的参数名 verify_tools（3 处，src/llm_loop/eval/verdicts.py），与工具实现校验无关。凡正文出现「0 处/没有/不存在」这类全称断言，都按同一模板自检后再发布。
当前性验证：跑 `grep -rn "tool_version\|tool_hash\|schema_hash\|verify_tool\|tool_fingerprint" src/llm_loop --include=*.py`，应得 3 处命中且全部是 src/llm_loop/eval/verdicts.py 的 verify_tools；若命中数变化，正文与台账须同步改写。