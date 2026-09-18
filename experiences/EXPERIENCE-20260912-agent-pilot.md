---
title: 本地三方 agent 对比 pilot：同模型、脚本化任务、程序化验收的可复用骨架
scenario: 需要在同一本地模型上对比多个 coding agent（本框架/Deep Agents/Cline）的任务成功率与失败模式，无现成评测设施
root_cause: ""
solution: 12 个脚本化可判定任务×3 次×3 系统：tasks.py 定义 setup/prompt/verify；run_pilot.py 提供 lfl（CLI）、da（dsh 隔离进程）、cline（--json headless）三适配器，共用 8901 端点同一模型 Ornith-1.5-35B-A3B；analyze.py 从 results.jsonl 去重汇总
evidence: "evals/pilot/{tasks.py,run_pilot.py,analyze.py,REPORT.md,data/results.jsonl}；提交 635f3b19、58c510f6、80e46cb8 已推送 lfl main；analyze.py 输出 108 run 三方矩阵"
tags: [eval, pilot, cline, deep-agents, wilson-ci]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-12T15:06:14.599069+08:00"
updated_at: "2026-09-12T15:06:14.599069+08:00"
---

三方对比 pilot 落地路径：①任务集程序化生成（tasks.py，setup/verify 全脚本，每 run 独立 tmp ws，不写死任何 agent 专属接口）；②每 agent 一个薄 adapter（lfl CLI / dsh+deepagents / cline --json），共用同一 8901 LM Studio 端点与同一模型，排除模型变量；③原始 JSONL 只追加不改，分析时按 (agent,task,run) 取最新 ts 去重，修 bug 后重跑自然覆盖；④报告必须附 Wilson CI（36 样本 CI 宽达 [0.78,1.00]，只能解读失败模式不能宣称成功率差异）；⑤数据入库前脱敏绝对路径（repo git hook 会拦 /Users/）。