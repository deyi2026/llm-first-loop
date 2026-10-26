---
title: 触发实例候选生成：事件级解析可用，文本提及级不可用
scenario: "要从历史会话语料中为一张方法卡找\"触发实例\"候选（陷阱真的出现的会话），卡的用户可观察线索是回执字段（如准入回执 target 含 command:&lt;hash&gt;）。语料是 LLM 会话 jsonl，含完整 messages。"
root_cause: "工具 schema 与源码字段会把工具名撒遍每条会话，使\"提及\"与\"调用\"的基率相差两个数量级；而词汇共现与\"陷阱是否发生\"无因果关系，故任何全局词面阈值都无法追踪卡间精确率差异。"
solution: |
  不要用"文本里出现关键词"做候选。解析 messages[].tool_calls，只取 function.name 等于目标工具的真实调用，再从 arguments 里取指纹字段。
  
  实测同一张卡：
  - 文本提及级：468 条 / 168 会话。抽 5 条即见三类假阳性——工具 schema 清单（每条会话的 tools 数组都含该工具名）、无关短语同名、源码同名字段。
  - 事件级：78 条 / 38 会话（65 条参数含 command 指纹），覆盖 3 类任务（全量测试 53 / 发表 11 / push 7），数量与多样性都达标可用。
  
  通用 n-gram 词面召回同样不可靠：对两张已知真值的卡（精确率 100% vs 10%，相差 11 倍），12 组 n/阈值配置中 0 组能同时贴合两个基准；最贴 P01 的配置把 P28 漏掉 7 倍，最贴 P28 的配置把 P01 冲高 22 倍。说明词面测的是词汇常见度，不是陷阱发生。
  
  结论：候选生成必须逐卡定制，且优先用事件（工具调用、回执结构）而非文本。
evidence: "evals/methodcard_rsi_v1/s1d_pool/round1/{scan_card1.py,scan_card1_v2.py,ROUND1-NOTES.md}（v1 468/168 vs v2 78/38）；evals/methodcard_rsi_v1/s1d_pool/{calibrate_recall.py,RECALL-CALIBRATION.md}（12 组配置 0 组同时贴合 P28 110/85 与 P01 10/8）"
tags: [候选召回, 事件抽取, 触发实例, 四元组, 语料挖掘]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T08:31:16.536004+08:00"
updated_at: "2026-10-21T08:31:16.536004+08:00"
---

顺序很重要：先算事件级候选，再决定要不要做文本级补充；反过来会先得到几百条噪声，再花时间解释它们为什么是噪声。

事件级也有边界：它只证明"工具被调用过"，不证明"陷阱出现过"。38 个会话里多数可能只是正常走闸。四元组（cue/temptation/action/stop）与 direct 仍需逐条人工裁定——这部分没有捷径。

对"用户措辞型"线索（如续跑指令、追问"是否做完"），事件定义要另设：从 user 消息里取指令形态，而不是从 tool_calls 取。