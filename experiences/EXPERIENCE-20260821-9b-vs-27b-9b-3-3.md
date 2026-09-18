---
title: 本地 9B vs 27B 实测：简单任务 9B 快 3.3 倍且文本工具协议遵循正常
scenario: "LFL 接入本地模型（LM Studio localhost:1234）速度优化：27B 档 decode 仅 ~18 tok/s（单轮 22.7s/399tok），需判断是否有更快替代用于简单任务"
root_cause: 本地模型 prefill 随输入线性增长、decode 受硬件算力限制；不同参数量模型速度差异巨大（27B 比 9B 慢 3 倍以上），但 LFL 固定单模型无法利用快档
solution: "实测对比（预热后各 2 次均值）：qwythos-9b-claude-mythos-5-1m@q4_k_m（9B/1M 上下文/无 thinking）工具调用任务 2.3s vs qwen3.8-27b-mlx（27B）7.7s——快 3.3 倍；简单问答 1.3s vs 4.6s。9B 走 lms-chat/openai 文本工具协议输出 JSON 完全合法（{\"tool\":..,\"args\":..}）。结论：简单问答/短工具轮优先用 9B（收益 3x），复杂推理用 27B（质量）。注意 9B 首次调用含冷加载（22.5s），必须预热后再比；reasoning_effort 对 27B 有轻微影响（high 11.9s/medium 9.8s/low 10.4s，medium 为质量/速度折中档）。"
evidence: 2026-08-21 llm-first-loop-mirror 镜像实测（LM Studio 1234）：9B 工具任务 2.612/2.037s vs 27B 6.650/8.748s；9B 简单问答 1.3s vs 27B 4.6s；27B effort high 11.9s / medium 9.8s / low 10.4s
tags: [本地模型, 性能, LM Studio, 模型路由, 提速]
source: {}
status: archived
created_at: "2026-08-21T16:55:18.413514+08:00"
updated_at: "2026-09-06T00:19:02.697933+08:00"
---

## 2026-09-06 lifecycle review

这是 2026-08-21 特定模型/协议/预热状态下的速度点测。当前 tool schema、runtime、cache 与本地 serving 栈已多轮演进，旧 3.3x 数字不应参与 active 路由判断；保留为历史 benchmark。

