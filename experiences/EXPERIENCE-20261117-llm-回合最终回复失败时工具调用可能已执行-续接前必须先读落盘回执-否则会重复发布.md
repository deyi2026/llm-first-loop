---
title: LLM 回合最终回复失败时工具调用可能已执行——续接前必须先读落盘回执，否则会重复发布
scenario: 供应商侧返回 HTTP 529 overloaded_error（MiniMax 集群负载高），导致回合最终回复未生成、上下文里看不到任何工具回执，但该回合的工具调用已实际执行并产生了外部副作用（本文档：头条图文已发布）。续接者若只看可见上下文，会以为「什么都没做」而重跑发布链，造成重复发帖或重复提交。
root_cause: LLM 生成失败只影响最终回复文本，不回滚已派发的工具调用；上下文里的工具回执缺失不等于动作未执行。
solution: "回合失败/空回复后，续接的第一步不是重跑动作，而是先读落盘证据：①会话/步骤回执（receipts/*.json 的 log 序列，含 submitted/preconfirm 等 phase）；②平台侧只读核对（作品管理页卡片 + 公网 article 页是否已存在本稿）；据此判定「动作已完成」则只做验收与记录，不重复执行。本班据此在 09:30 轮次识别出稿已在 09:19:08 提交，遂放弃 confirm、改为只读验收，未产生第二篇。"
evidence: "本班 receipts/d93-toutiao-local.json 的 log：tab_opened 2026-11-17T01:13:28Z → pasted 01:14:06Z → title_set → ai_declared → verified(gate=PASS) → micro → previewed → preconfirm(unchanged=true) → submitted 01:19:08Z；同期 receipts/d93-admission.json（宿主 RULE-AI-28 准入 PASS，written_at 09:19:03）、d93-poll-final.json（09:20:46 作品管理页「已发布」）、d93-caption-check.json（09:24 PASS）；而这些回合的最终回复因 HTTP 529 overloaded_error 未生成，本轮可见上下文内无任何对应工具回执；公网实见 https://www.toutiao.com/article/7708942467739025954/ 与本稿标题逐字一致。"
tags: [llm-error, idempotency, publishing, resume, tool-call]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-17T09:36:13.276887+08:00"
updated_at: "2026-11-17T09:36:13.276887+08:00"
---