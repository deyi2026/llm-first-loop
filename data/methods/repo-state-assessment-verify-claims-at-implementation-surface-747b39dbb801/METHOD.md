---
method_id: repo-state-assessment-verify-claims-at-implementation-surface-747b39dbb801
name: repo-state-assessment-verify-claims-at-implementation-surface
description: 开放式“项目做得怎么样/有什么建议”的仓库现状评估：用首轮回执（运行时状态 + README）建立能力声明清单，再对每条声明做一次定向表面探查（配置/数据文件、源码目录、设计文档符号 grep），分层为已落地运行时/仅设计/资产堆积后即停。避免全量文件枚举与 miss 后换措辞重搜；miss 回执列出的近期文档与提问目标无关这一事实本身就是 docs/ 非能力语料库的判别信号。
aliases: 项目底子怎么样 从哪看起, 落地了还是只有POC, docs检索未命中 下一步, 陌生仓库全家桶怎么盘点, 资产沉淀还是消化, 全目录扫还是定点验证
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:7:062490abb031f093da31
evidence_refs: learning:learn:8bcf27377c3e
created_at: 2026-10-30T01:18:11.047159+08:00
updated_at: 2026-10-30T01:18:11.047159+08:00
---
## Trigger
用户对某仓库提出开放式现状评估（“X 基础怎么样/进展到哪/有什么建议”），且首轮感知（运行时状态/技能清单/文件列表）已到手

## Discriminator
宽泛多概念 doc 检索 miss 且回执列出的近期文档与提问目标明显无关（安全/事故类），而 README 与运行时状态 flags 已点名全部相关子系统——说明能力真值在 README+运行时状态而非 docs/，下一未知量是“每条声明对应实现表面是否存在”，不是改写检索或全量枚举

## Short path
- 首轮感知在手：运行时状态 flags + 文件列表已浮出 README → 立即完整读 README，建立能力声明清单（运行时/调度/子代理/IM 通道/记忆/评测）
- 用提问核心词（如 bot）做一次范围受限的文件名检索 → 定位多 bot 设计文档与 POC gate 文档，不做全库枚举
- 对设计文档点名的符号做一次针对 src/ 的 grep → 裁决“仅设计”还是“运行时已落地”（0 命中即未落地）
- 对每条已落地声明做一次定向表面验证（调度配置计数、子系统源码目录、skills manifest 存在性）+ 资产计数一次命令行普查
- 各声明均有表面裁决 → 合成分层结论与按杠杆排序的建议，停止，不再读与目标无关的文档

## Stop conditions
- 能力声明清单中每条都有代码/配置/数据表面裁决（或符号级 0 命中裁决）
- 资产层有一组命令行统计的计数（状态分布 + qualification/manifest 完整性）
- 分层结论与建议给出后停止，不继续读与提问目标无关的文档或 runbook

## Verification
- 设计 vs 运行时裁决必须有符号级 grep 证据（设计文档关键词在 src 中 0 命中 ⇒ 未落地），不能采信设计文档自述
- 资产计数来自命令行 tally 而非印象或单文件外推
- 声明清单逐条对应至少一个表面证据；缺表面的降级为“未核实”并如实标注

## Counterexamples
- 用户只问某个具体单点（如“定时发文今天跑没跑”）→ 直接查该子系统运行工件，不做能力分层
- docs/ 本身就是能力描述语料（官方文档仓）→ doc 检索会直接命中，miss 判别器不成立，应消费命中回执
- README 严重滞后或纯营销 → 声明清单不能来自 README，改用运行时状态 + 定向代码普查
