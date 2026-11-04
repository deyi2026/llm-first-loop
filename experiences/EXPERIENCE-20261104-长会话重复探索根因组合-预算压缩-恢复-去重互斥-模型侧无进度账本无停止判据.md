---
title: 长会话重复探索根因组合：预算压缩-恢复-去重互斥 + 模型侧无进度账本无停止判据
scenario: "长会话（2.5h、开放任务）在 LFL 运行时 + MiniMax-M3.1-Flash 下出现大量重复探索：同一 evidence 反复读（最高 34 次）、同一命令跨 5 个时间点重复执行、失败模式原样重试，用户观察到\"重复探索\"并要求根因分析。"
root_cause: ""
solution: 分层修复：程序侧（预算/压缩/去重/熔断）+ 模型侧（task_state 账本、验收清单、失败换姿势），详见 EVO 建议与卡正文。
evidence: data/archives/6c13edc8-42f8-4bc3-9245-e19a3c891178.jsonl（1262 条 tool 结果；read_evidence 517；148/348 引用≥2 次）；data/compaction_snapshots/6c13edc8-…/gate_state.json（attempt=2，内嵌 assistant 353 条/0 字符，604 条仅索引）；architecture_status 早期 budget：effective_budget=34206 chars、tool_schema_reserve_tokens=126989、tool_schema=76193 chars、limited_by=input_token_budget；分析脚本 /tmp/lfl_repeat2.py～lfl_repeat4.py 输出 /tmp/lfl_repeat*_out.txt
tags: [重复探索, 压缩恢复, longrun_continuity_reuse, 预算口径, task_state, 停滞检测, MiniMax-M3.1-Flash]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-04T10:46:13.698343+08:00"
updated_at: "2026-11-04T10:46:13.698343+08:00"
---

## 现象
2026-11-04 08:04–10:38 的"自我检查"会话（minimax/MiniMax-M3.1-Flash，session_override）出现重复探索：2.5h 内 1262 次工具结果，read_evidence 517 次（41%），148/348 个 evidence 被读 ≥2 次（Top：34/33/27/25/24 次，首末跨越 08:21→10:38），同批 sha/grep 命令在 09:58/10:02/10:14/10:19/10:37 五个时间点重复执行；可避免失败重试 61+ 次（15×60s 超时、11×E6 硬阻断、10×UTF-8 撕裂、16×Evidence 不可用）。

## 根因（分层，按因果顺序）
1. 预算口径把 1M 窗口压成 ~34K chars：input_token_budget=184K tokens 中工具 schema 预留 126989 tokens（projection_fallback 密度 0.6 chars/token），早期 effective_budget 仅 34206 chars，而 tool_schema 本身 76193 chars → 2.5h 内 19 次压缩（≈7 分钟一次）。
2. 压缩恢复材料以索引为主：gate_state.json 显示"内嵌 assistant 自产文本 353 条 / 0 字符"（内嵌为空，与恢复提示"原文已内嵌"矛盾），604 条仅索引 → 每次压缩后模型必须重读证据重建认知，这是 read_evidence 占 41% 的直接来源。
3. 去重与压缩互斥：longrun_continuity_reuse 对完全相同参数的 read_evidence 只回桩不给内容（假设"已在上下文"），但压缩刚把内容移出上下文 → 模型换 offset/换工具再试 → 新一轮探索；压缩后旧 evidence_ref 还有 16 次"Evidence 不可用"。
4. 模型侧无进度账本、无停止判据：16 次 task_state 全是恢复读、0 次 save；开放任务（"自我检查"）无验收清单，不断"再核一项"；失败姿势不切换（heredoc 被拦 11 次仍原样重试）。
5. 程序侧无重复探索熔断：stagnation_rate 仅 0.02 未识别语义重复；recent_tools 已有 args_sha256 但无"窗口内同参重复≥N 次"提醒。

## 修复
程序侧：① reuse 判定感知压缩（内容已出上下文则重投影或给绕行指引）；② 快照真正内嵌最近 K 轮结论文本（assistant_chars=0 需查计数 bug）；③ 压缩前强制落 task_state、恢复优先注入账本；④ 治理工具 schema 预留（126989/184000=69%）；⑤ 同(工具,参数)窗口内重复≥3 次注入提示。模型侧：开工建 task_state 账本并随核验更新；先写验收清单再查、查完即写报告；失败一次即换姿势。