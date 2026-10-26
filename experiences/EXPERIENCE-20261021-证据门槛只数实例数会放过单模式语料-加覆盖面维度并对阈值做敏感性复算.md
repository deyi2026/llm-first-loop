---
title: 证据门槛只数实例数会放过单模式语料：加覆盖面维度并对阈值做敏感性复算
scenario: "为某方法卡/实验池设\"够不够格进入下游验证\"的数量门槛（如 ≥N 独立实例、≥K 任务族）。池子数量达标，但所有实例的失败模式与判别动作都只有一种：任一条的解释可原样套到其余实例，下游效应无法与近邻检索/形态匹配分离。此时旧门槛仍判通过。"
root_cause: "数量型门槛默认\"多样性随数量自动增长\"，但候选是按键面（如\"调用了受保护命令\"）抽取的，陷阱本身高度同构；门槛不检查\"语料里到底有几种失败模式\"，就挡不住同质语料。"
solution: "① 数量门槛之外加两条覆盖面条件：失败模式 ≥2 种、判别动作 ≥2 类且单类占比 ≤80%；② 任务族必须按任务/交付目标的语义轴定义，禁用\"受保护命令/工具名\"这类封闭词表（任何两工具组合都能满足，门槛近乎恒真）；③ 裁定同时报语义类别口径与字面模板口径的占比（本例 24/24=100% 与 21/24=87.5%），并检验结论对阈值不敏感（放宽到 90% 仍不过）；④ 开裁前先做候选池的失败模式分布快照，只可能覆盖 1 种就停止裁定，结论写\"本语料内不可检验\"，不要\"先裁完再看\"。证据：78 条池、24 条实例全为 F1/verbatim-retry；GATE-RESULT §六。"
evidence: "data/methods/admission-gated-command-run-verbatim-standalone-9ffd75920b0a/{pool.jsonl,pool_status.json,GATE-RESULT.md}；docs/DESIGN-20261021-trigger-instance-pool.md §1/§3/§5；回填脚本 evals/methodcard_rsi_v1/s1d_pool/round2/backfill_v2_fields.py（78 行，instance 24 全 F1/verbatim-retry，14 原字段逐条未变）；verify_v2_landing.py 全部 39 项检查 PASS。"
tags: [门槛设计, 覆盖面, 同质语料, 阈值敏感性, 实例池]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T11:06:44.712363+08:00"
updated_at: "2026-10-21T11:06:44.712363+08:00"
supersedes: [EXPERIENCE-20261021-证据门槛只数-实例-族-会放过单模式语料-须加覆盖面维度-阈值敏感性复算]
---