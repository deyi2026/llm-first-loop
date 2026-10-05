---
title: 一次性裁决分析器的分母硬编码与异构门槛渲染：两处独立 bug 产出假 HOLD（IQ v1 DEV-2）
scenario: 一次性裁决类分析器（iq_analyze.py）对预注册门槛做 PASS/HOLD/FAIL 判定；首跑在两处独立 bug 下产生 KeyError 崩溃 + 一个假 HOLD（门槛误判），且假 HOLD 会直接污染仪器资格结论。
root_cause: "门控阈值表结构 heterogeneous（有的 gate 带 threshold 数值、有的带复合结构），渲染代码按键硬取；比率计算处分母用魔法数 34（疑似早期池设计残留），未从数据推导。二者都属\"分析器写成时假设了一次性结构\"，缺乏对实际池大小的机械校验。"
solution: "1) 比率类指标分母永远从数据结构推导（len(acd_ids)），禁止魔法数；代码评审时 grep 分母常量。2) 渲染复合 gates 结构前显式分支处理无 threshold 的行。3) 修正后用固定 seed 确定性重跑并逐 gate 对比首跑/重跑差异，确认修正面仅限声明范围（κ/bootstrap/CI/per_cell 未动）。4) 分析器单测应断言\"每个比率指标的分母 == 构造侧实际池大小\"，把这类 bug 挡在首跑前。"
evidence: "evals/instrument_qualification_v1/iq_R1_notes.md §偏离登记 DEV-2；修正 diff 证据 evidence://v1/4538f14de17c1d37f1342d3316d70f2fc8723d1a3649c735780f5d5c2e516e4f；重跑回执 evidence://v1/12db7c7616060cc4a8f364d18c97d3e3dfb6c58db9f77b650943b231b2930451"
tags: [analyzer, denominator, magic-number, false-HOLD, gate-rendering, one-shot-adjudication]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-05T23:28:03.153343+08:00"
updated_at: "2026-10-05T23:28:03.153343+08:00"
---

iq_analyze.py 首跑（2026-10-05 23:13:54）渲染 IQ-RESULT.md 崩溃：gates 循环对无 threshold 键的 Q1_kappa/Q3_headroom 直接取键 KeyError；同时 IQ-RESULT.json 含第二处 bug——r1_acd_rate = r1_acd/34，分母 34 硬编码，而 A/C/D 构造确定格实际合计 20，致 R1_vs_intended_ACD 误算 0.5882 触发假 HOLD。修正：分母改 len(acd_ids)（=20）；MD 表格对 Q1/Q3 显式渲染。修正后 seed=20261005 固定重跑，κ/CI/per_cell/headroom 与首跑一致，仅该分母恢复 PASS（真实 20/20=1.0）。