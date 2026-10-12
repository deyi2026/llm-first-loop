---
title: 连续 400 根因：压缩折叠切断 tool_calls↔tool 配对 → 提交视图孤儿消息（V2 双向清洗修复）
scenario: "llm-first-loop（OpenAI 兼容多协议客户端）长会话压缩/上下文注入后连续 HTTP 400，跨 provider（deepseek/glm/本地 qwen）复现；Anthropic 路径已有 orphan 清洗但 OpenAI 路径无对称防御的场景。判据：grep event_logs 找 \"must be followed by tool messages\"（反向孤儿主签名）/ \"must be a response to a preceding message\"（正向次签名），并与 message.cache_compact 事件时间对齐。"
root_cause: "history.py 的 cache_compacted_for 过滤按消息逐条执行不校验 tool_calls↔tool 配对，折叠切在配对中间产生反向孤儿（声明在、应答被过滤），provider 拒收整包请求；标记持久化导致每轮 build 复现孤儿 → 连续 400。Anthropic 路径 _to_anthropic_messages 已有 orphan tool_use 清洗（client.py:1109-1116），OpenAI 路径无对称防御——历史修复只做了单侧。"
solution: LLMClient._sanitize_openai_tool_pairs 双向清洗（copy-on-write）：正向删孤儿 tool/重复应答；反向剔除无应答 tool_call_id（剔空且无文本则整条删 assistant）。在 chat_stream 协议分发点接入（openai/lms-chat 及未知回退路径，anthropic/google 除外）。快速路径零开销；fail-open + warning 如实记录修复量。验证：inline 7 用例 + 相关单测 132 passed。
evidence: "提交 d5f538b（fix(client): OpenAI 路径 tool_calls↔tool 配对双向清洗）；取证数据：6 会话 39 次 400（eb5c2686=11/6485b02b=11/4ab10dd7=8/5afa2364=4/fd3b57fc=2/507c5bf0=2），跨 provider；18:14:41 400 与 187 条 cache_compact 同秒；单测 132 passed（-k client|protocol|history|build|message）+ ruff 通过 + inline 7/7"
tags: [openai-protocol, tool-calls-pairing, orphan-tool, http-400, cache-compaction, continuous-failure, client-defense, mirror-verified]
source:
  session: 6485b02b-007f-4950-8c20-765f19c67d07
  commit: d5f538b
  files: "['src/llm_loop/llm/client.py']"
  evo: EVO-20260827
status: active
created_at: "2026-08-27T02:29:14.637964+08:00"
updated_at: "2026-08-27T02:29:14.637964+08:00"
---

## 时间线与教训

1. 18:14:41 本会话出现 400，与 187 条 message.cache_compact 同秒；我初判"单发自愈"——错误，用户指出"已经出现过几次了，是连续"
2. 全库取证：6 个会话 39 次 400，跨 deepseek/glm/本地 qwen 复现 → 客户端提交视图结构问题
3. eb5c2686 错误体两种签名："role 'tool' must be a response to preceding 'tool_calls'"（正向孤儿）与记忆确认的 "assistant message with 'tool_calls' must be followed by tool messages"（反向孤儿，主签名）
4. V1 只修正向、反向仅告警——方向反了；且磁盘改码后当前进程未重启，修复未生效，用户又见 400
5. V2 双向清洗 + inline 验收抓出 keep 条件写反（`id in pending` 恰保留孤儿）、改名后 3 处调用点未同步 NameError——dry_run 预览与分步验收避免了带病提交

## 根因机理（为何"连续"）

cache_compacted_for 标记一旦写入会话历史，之后每轮 build_history_messages 都按 provider 过滤折叠消息——若折叠切在 assistant tool_calls 与其 tool 应答之间，反向孤儿在后续每轮提交视图中复现 → 持续 400 直到标记外推或会话终结。上游 history.py:689-695 过滤不校验配对（666-687 的锚点孤儿丢弃只处理正向）。

## 修复模式（d5f538b）

LLMClient._sanitize_openai_tool_pairs 双向清洗：
- 正向：孤儿 tool（无在案声明/重复应答）→ 删
- 反向：pending 中无应答 id 从 assistant tool_calls 剔除；剔空且无文本 → 整条删
- copy-on-write；user/system 插队即触发截断剥离；chat_stream 协议分发点接入（anthropic/google 除外——前者已有对称清洗）