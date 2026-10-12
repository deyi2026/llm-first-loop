---
method_id: goal-named-doc-miss-switch-to-git-commit-provenance-6b7542581f5a
name: goal-named-doc-miss-switch-to-git-commit-provenance
description: 活动 goal/task 点名一份上游权威文档（评审/报告/设计稿）而语料搜索未命中时，不要对同一索引换措辞重搜。两条当时已知事实可提前收窄：① miss 回执的'最近文档参考'不含该文档→索引不覆盖它；② goal/checkpoint 显示当天有 tag/commit 动作（HEAD 超前 tag）→该文档最可能由先前会话的近期 commit 携带入库，一次 git log --grep/--diff-filter=A 即可经 commit message 定位路径。另：评审内 ordinal（P0-2）跨评审不唯一（SSRF/eval/audit 各有 P0-2），不能作全局检索键，必须与评审全名配对。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:64924088-0141-4a3a-87ee-81f09678620d:111:a28ed6e387e8de0e8996
evidence_refs: learning:learn:4b7edd48b5ad
created_at: 2026-10-10T10:29:09.629293+08:00
updated_at: 2026-10-10T10:29:09.629293+08:00
---
## Trigger
任务/goal 文本引用某个命名上游文档（如 r3 横向评审报告），需要读原文落实需求；首次 docs/content 搜索未命中，且尚未切换 source class。

## Discriminator
进入第二次换词重搜前已可见的事实合取：① search_docs miss 回执明确列出'最近文档参考'且其中没有任何评审/assessment 类文档→语料索引不覆盖目标；② goal 元数据/checkpoint 显示当天早晨有 git 动作（tag v0.6.27 打在 98d1ce90e、HEAD 另多出内容）→r3 产物正通过近期 commit 入库。二者把候选来源从'全语料关键词空间'缩成'近期 commit 的 message/新增文件'。

## Short path
- 读 goal/task 文本，确认目标文档的唯一名称（r3 横向评审 / LFL-COMPARATIVE-REVIEW）及其对任务 ordinal（P0-2）的归属评审
- 对语料索引做一次探测检索；miss 后读回执边界：'最近文档参考'是否已覆盖该类文档
- 若未覆盖且 goal 上下文显示近期 git 活动→切换 source class：git log --grep=<评审关键词> --name-only 或 git log --diff-filter=A --since=<goal创建日> -- docs/
- 从 commit message 点名的路径直接读目标文档的需求节（出向导出四要素）
- 与 task 文本语义核对（记忆/证据/方法学习/工具面出向导出）后停止检索；代码事实线（定向读 mcp 相关文件、pyproject 依赖、import mcp 探测）照常并行推进

## Stop conditions
- commit message/diff 明确点名目标文档路径，且已读到对应需求节
- 文档内容与 task 描述语义一致且期次匹配（同一评审的 P0-2），需求视为已权威验证
- git 定向探测一次未命中→不加深 git 检索，改走其他通道（evidence 库、checkpoint 内联内容、询问用户）

## Verification
- commit message 或 diff 路径包含目标文档名（如 LFL-COMPARATIVE-REVIEW-20261007.md）
- 文档中存在与任务文本对应的需求条目（出向导出四要素），且评审期次与 goal 引用一致

## Counterexamples
- 语料搜索首查即命中相关文档：直接读，不绕 git——本方法只在索引 miss 后启用
- 被引用文档不在版本库内（外部 wiki/evidence store/运行时生成）：一次 git 探测 miss 即应换通道，而非加深 git 检索
- goal 引用的要求已内联在 checkpoint/task 文本中且足以行动：checkpoint 即源，无需外查文档
- 用 P0-2 这类评审内 ordinal 做全局内容搜索：SSRF/eval/audit 各有自己的 P0-2，会命中大量跨评审噪声——ordinal 必须与评审全名配对，命中后先核期次再采信
