---
method_id: readiness-gate-before-trusting-async-analysis-server-answers-29986530ad19
name: readiness-gate-before-trusting-async-analysis-server-answers
description: 驱动语言服务器/索引器等状态型分析服务时，协议层成功回执（rc=0、JSON 合法、格式完整，甚至空结果）不构成完整性证明：结果集取决于服务内部已分析的文件范围。先用一次差分校准（同一查询冷进程立即发 vs 等就绪信号后发，或对已知有命中的哨兵符号加裸名 grep 基线）量化差距；若冷/暖结果不一致，后续所有查询统一加就绪门，并随结果报告分析范围快照；空/异常偏少的结果在哨兵复检通过前不得当作『不支持/不存在』的结论。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:588:ed58827d4f24bb4eda03
evidence_refs: learning:learn:73fb457cd97b
created_at: 2026-09-28T20:00:34.320452+08:00
updated_at: 2026-09-28T20:00:34.320452+08:00
---
## Trigger
需要把 LSP/索引器/daemon 等异步分析服务的响应（references、callHierarchy 等）作为证据使用，且响应的完整性取决于服务内部分析进度而非查询本身。

## Discriminator
协议成功回执不编码完整性——当时已可见的信号：脚本必须先等『分析就绪』结果才可信；同一查询在不同时点返回不同计数（726/82 vs 608/77 vs 冷进程 6/1）；空结果（prepareCallHierarchy→0）无法区分『不支持』与『尚未分析完』；同时存在廉价独立基线（裸名 grep 计数 / 已知命中哨兵）可对照。

## Short path
- initialize + 能力协商一次，确认服务声称支持目标能力（未知量：能力是否存在）
- 信任任何结果类之前先做差分校准：同一查询冷进程立即发 vs 等就绪信号后发，或对已知命中哨兵跑一遍并对照 grep 基线（未知量：成功回执何时可信）
- 冷/暖不一致 → 所有后续查询统一加就绪门（如等 publishDiagnostics），结果附带分析范围快照
- 遇到空/明显偏少结果：先在就绪门下用哨兵复检，再决定换查询类还是下『不支持』结论
- 两组就绪门下计数稳定即停止校准，进入正式测量并报告

## Stop conditions
- 冷/暖差值已量化一次，后续查询全部走就绪门
- 哨兵查询在就绪门下返回预期命中，证明该查询类可用
- 空结果已被哨兵/复检消歧后才允许改判能力

## Verification
- 同一查询就绪后重跑，计数跨次稳定（如两次均 608 点/77 文件）
- 已知有引用的哨兵符号在门下返回非空且规模合理
- 精确结果数 ≤ 裸名 grep 基线；出现无法解释的大幅亏空视为截断信号

## Counterexamples
- grep/read_file/本地 AST 等无状态工具：rc=0 + 完整输出即完备，加就绪门纯属浪费调用
- 服务本身提供逐查询完整性/诊断标志，或工作区极小可证瞬间全量分析：跳过差分探针
- 下游只需要『≥1 命中』的存在性判断且空结果自然触发回退路径时，门的成本可能高于收益
