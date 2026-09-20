---
method_id: prior-round-citation-to-commit-provenance-before-doc-sweeps-7d95c13d2fa6
name: prior-round-citation-to-commit-provenance-before-doc-sweeps
description: 当任务指令引用上一轮会话产出的 § 编号/缺口编号/"实施记录"，而仓库中没有直接路径时，权威 provenance 通常是那一轮的 commit + CHANGELOG，而非 docs 树。对被引文档只做一次定向 grep；若结构化检索（search_docs/search_files）明确 miss，应把假设翻转为"被引物可能根本不在文档树"，立即转向该子系统的 git log/show 取锚点；确认文档不存在时，把"不存在"本身记为发现，并从 commit+CHANGELOG+代码锚点重建范围，而不是继续放宽 grep 模式追猎不存在的目标。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6e0fb83b-03af-44ff-be33-c3498380b42f:690:d5431649d5b819d22965
evidence_refs: learning:learn:9ed370a4f7d4
created_at: 2026-09-20T17:59:13.870625+00:00
updated_at: 2026-09-20T17:59:13.870625+00:00
---
## Trigger
任务/续接消息引用上一轮的 § 编号、缺口编号或"实施记录"等会话产物，且该产物在仓库内无直接命中路径；或对用户引用物的结构化检索已返回明确 miss。

## Discriminator
用户消息引用的是上一轮会话的"实施记录/缺口①/§编号"（实现产物以 commit+CHANGELOG 形式落地），且 search_docs 与 search_files 两个结构化通道都已明确 miss 被引术语——docs 树命中率为零这一事实在被引用物定位阶段即已可见，足以把"继续在文档树放宽搜索"收缩为"切换证据类别到版本历史"。

## Short path
- 从用户引用的"上一轮实施记录/缺口①/§编号"出发，先 git log（或 CHANGELOG 尾部）定位上一轮相关 commit；未知量：该轮工作的权威范围陈述与残留边界在哪
- 读 commit message + 对应 CHANGELOG 版本条目，取得 § 锚点与"剩余缺口"边界注记，作为新缺口（缺口②）的范围依据
- 打开该 commit 点名的代码文件，锚定新缺口各交付物的具体触点
- 对被引"设计文档"本身只做一次定向检索；miss ⇒ 记录发现"被引文档不存在，范围由 commit/CHANGELOG/代码重建"，停止文档追猎
- 逐条验证新缺口范围条款可回溯到 commit/CHANGELOG/代码锚点后停止

## Stop conditions
- 缺口/范围已锚定到 commit message + CHANGELOG 条目 + 代码三重 provenance，且每个交付物触点有对应证据
- 被引设计文档实际存在且被定位到 → 直接读文档并停止重建式推理
- 仓库无 VCS 或该轮工作从未提交（只在工作树）→ 转向 git status/diff 或文档，停止强查历史

## Verification
- 每条范围条款能回溯到具体 commit hash / CHANGELOG 版本注记 / 代码锚点（如 df103c26a + v0.6.14 边界注记）
- 若一次定向检索后确认被引文档不存在，该"不存在"结论被显式写进交付物（诚实边界），而非静默略过或继续搜索
- 自查调用序列：search_docs/search_files 双 miss 之后未再新增更宽的 grep 模式

## Counterexamples
- 被引设计文档确实存在于 docs/ 且第一次定向 grep 即命中 → 应直接读文档，git 绕行是浪费
- 上一轮工作未提交、只在工作树（如本例的 M AGENTS.md）→ git show 看不到，应改用 git status/diff
- § 编号来自外部标准/协议而非本仓库会话 → 仓库 commit provenance 无关，应查外部来源
- 仓库无版本控制或历史被重写 → 回退到 docs/笔记或直接向用户求证，不套用本方法
