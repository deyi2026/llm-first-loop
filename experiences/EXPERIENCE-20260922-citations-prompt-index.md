---
title: 干净环境三组对照验证记忆 citations 修复设计：prompt 示例 + 真实 index 锚点缺一不可
scenario: "记忆提取 citations 溯源修复前需在隔离环境验证 LLM 行为（不污染生产记忆库、不 mock 解析链路），以及任何\"prompt 字段示例 → 模型产出 → 结构化解析\"链路的干预验证"
root_cause: ""
solution: "A/B 对照锁基线（生产 prompt 复现故障）→ 单变量干预（新 prompt）→ 错位压力测试分离隐含假设（行序=消息序）：构造程序反馈消息使行序≠消息序，无锚点组 refs 系统性错位、真实 index 锚点组精确。判定自动化（ref regex + ground truth 映射），temperature=0 各 2-3 次验证稳定性。注意 .format 模板中 JSON 示例需 {{}} 转义，实验脚本用 replace(\"{history}\", hist) 规避。"
evidence: "数据文件: .tmp-ci/mem-citations-exp/results.json（A 组 3 次全空）、rerun_bb.json（B'/B 各 3 次全带 citations 全可回溯）、exp_offset.json（NP 2 次 5/5 错位、IX 2 次 5/5 精确，IX-1 首条 ground_ok=False 为关键词假阴性已人工核实 ref=msg:2 正确）; 后台任务输出 job-4ddd393bce2443e6942e / job-b093b2b6aec84e1b8edb; 源码锚点 src/llm_loop/memory/extractor.py:47-53,275,317-335 与 src/llm_loop/memory/extract.py:76-89 已本轮 read_file 复核。"
tags: [memory, citations, prompt-engineering, clean-room-experiment, llm-first-loop]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-22T06:35:32.967396+08:00"
updated_at: "2026-09-22T06:35:32.967396+08:00"
---

背景: llm-first-loop 记忆库 1629 条 citations 全空，根因是独立提取器 _EXTRACT_PROMPT 只示例 type/content/keywords 三字段。需验证修复设计。方法: 干净环境（.tmp-ci 隔离目录 + 真实 DeepSeek v4-flash + 生产解析链路 extract_memory_blocks→memory_blocks_to_entries，不 mock）三组对照 A/B'/B 各 3 次（temperature=0）+ 错位压力测试 NP/IX 各 2 次。结果: ①A 组（生产 prompt）15 entries 0 citations 根因复现；②B/B' 组（prompt 加 citations 字段示例 + msg:N ref 规则）18/18 entries 带 citations 且 ref 逐一精确对应出处消息——prompt 是唯一瓶颈；③错位测试（会话头插 2 条程序反馈使行序≠消息序）: 无锚点 NP 组 refs=msg:1/3/5/7/9 按 messages[N] 解读 5/5 系统性错位（msg:1 指向被过滤的程序反馈消息）；真实 index 锚点组（行前缀 [N][role]，N=enumerate 真实下标，过滤消息占号不占行）refs=msg:2/4/6/8/10 5/5 精确。结论: 只改 prompt 会产出"看似合法实则错位"的装饰性 citations（比空更危险）；正确最小改动 = prompt 加字段示例 + _build_history_text 行前缀加真实 index 两处缺一不可。附带: 模型全标 type=fact（示例单一所致）；模板经 .format 需 {{}} 转义（有 EVO-20260812 纠错兜底但应正写）。