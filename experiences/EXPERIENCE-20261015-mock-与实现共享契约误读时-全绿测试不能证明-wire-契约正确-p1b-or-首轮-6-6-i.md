---
title: Mock 与实现共享契约误读时，全绿测试不能证明 wire 契约正确（P1b-OR 首轮 6/6 invalid 根因）
scenario: 对外部结构化 API（TypeSafe/OpenRouter Decisions）实现 wire 契约解析与校验，且用 Mock 传输 + fixture 样本做 TDD
root_cause: 实现层 wire 字段名（answer）与官方契约（choice/score/noul）不符；Mock 与 fixture 共享同一误读使测试全绿；文档正文抽取剥离字段名导致初检漏检
solution: "契约字段名一律锚定官方 OpenAPI 或带字段名的响应示例（第三方转述/正文抽取可能剥掉字段名）；invalid 判定时持久化被拒原始对象的最小摘录（answers map 级）供事后诊断；修复按新一轮预注册执行（wire.py 三验证器改 choice/score/noul + fixture 同步 + manifest 重冻）。当前性验证：grep -n 'raw.get(\"answer\")' src/llm_loop/knowledge/jev/wire.py——若仍有命中且官方 openapi.json 的 DecisionsChoiceAnswer 必填键仍为 choice，则本教训仍适用；若 grep 零命中则修复已落地（见 DESIGN 附录 C 对应轮次）。"
evidence: "outputs/jev-p1b-20261015/p1b_or_report.json（6/6 answer_not_in_options、probabilities 键集吻合）；docs.typesafe.ai/primitives/choice（官方字段名 choice）；openrouter.ai/openapi.json DecisionsChoiceAnswer.choice/DecisionsScoreAnswer.score/DecisionsNoulAnswer.noul（required）；src/llm_loop/knowledge/jev/wire.py:218/257/283 三处 raw.get(\"answer\")"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-15T12:25:47.898759+08:00"
updated_at: "2026-10-15T12:25:47.898759+08:00"
---

P1b-OR 首轮真实外发（2026-10-15）：OpenRouter /api/v1/systemone 两请求全部往返成功、resolved model 正确、probabilities 键集与发送选项集完全吻合，但 6/6 题被本地校验判 contract_invalid（answer_not_in_options）。根因：官方 wire 响应的选项字段名是 `choice`（DecisionsChoiceAnswer.choice, required；同族 score/noul），本地 wire.py 三个验证器从 P1a 起全部读不存在的 `raw["answer"]`。Mock 传输与 fixture wire_examples 编码了同一误读，88 个定向测试全绿无法暴露——被测实现与测试替身共享同一契约误读时，测试通过不构成契约正确的证据。设计文档 §8.2 原文（"每题 choice/probabilities/confidence"）是对的，实现偏离了设计。此外：原始响应未持久化（仅 raw_response_hash），判定值不可事后恢复；初审时官方文档抓取经正文抽取器把响应字段名剥掉，实现是凭转述文本定的字段名。预防性做法：(1) 外部契约实现应锚定官方 OpenAPI/schema 或带字段名的响应示例，不锚定转述正文；(2) 判定层把被拒的原始逐题对象以最小摘录持久化（answers map 级），使 invalid 可事后诊断；(3) Mock/fixture 与实现的契约一致性要有一个独立于两者的第三源（官方 schema）做差异检查。