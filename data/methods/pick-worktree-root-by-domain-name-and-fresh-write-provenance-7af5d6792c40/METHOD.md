---
method_id: pick-worktree-root-by-domain-name-and-fresh-write-provenance-7af5d6792c40
name: pick-worktree-root-by-domain-name-and-fresh-write-provenance
description: 在多根工作区（git worktrees 等）里，假定路径读取失败后不要升级为关键词汤式全库枚举（把多个术语拼进 search_docs/search_records 通常整体 miss）。根目录名本身编码了工作流语义，evidence 库的 source=edit_file 路径记录了最近的写入位置。先按任务领域词汇匹配根名、用最新写入 provenance 交叉确认，选出唯一根，再在该根内部窄枚举定位工件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1f576ea-8082-441a-9f68-2d1021c05410:139:8d69032d48c15f05118f
evidence_refs: learning:learn:f10765f6a04d
created_at: 2026-10-07T04:39:56.174563+08:00
updated_at: 2026-10-07T04:39:56.174563+08:00
---
## Trigger
对预期规范路径的 read 返回 file-not-found（或路径登记为不存在），目标工件真实位置未知，且仓库/工作区存在多个根（git worktree list 可枚举）。

## Discriminator
进入宽搜索前已存在两条事实：(1) `git worktree list` 输出的根名语义与任务领域对应（harness 评测任务的工件应位于名字含 harness-evidence 的根，而非只看 docs/ 主根）；(2) evidence 库最近条目的 source 路径直接落在某个 worktree 下（edit_file:.worktrees/<root>/...），即最新写入 provenance。两者任一即可把候选空间从全仓库缩到一个根。

## Short path
- 读一次假定规范路径验证假设；miss 后未知量=工件在哪个根
- 运行一次 `git worktree list`（或等价根枚举）——候选空间是根列表，不是所有文件
- 把任务领域词汇与根名匹配；有歧义时用 evidence 最新 source=edit_file 路径打破平局，选出唯一根
- 只在该根内窄枚举（ls docs/ | grep 名称模式），一次命中
- 读工件并核验身份（SHA256 对此前登记值）后再据其行动

## Stop conditions
- 在选定根内找到工件且 SHA256/内容与此前记录一致——停止发现，进入裁决/执行
- 零个根名匹配任务领域且 evidence 无近期写入——转入一次有界跨根搜索或直接问用户，不再发变体关键词查询
- 多个根平局且 provenance 不能打破——向用户求证，不要逐根全枚举

## Verification
- 对定位到的工件重算 SHA256 并与先前登记哈希比对（本集 ls 回执中的哈希与决策包引用一致）
- 确认工件内容确含用户所询条目（D1–D5 逐项在文）后再回答

## Counterexamples
- 根名不透明（wt-1、tmp、personal 等）无领域信号——此时靠 provenance 或有界搜索，不靠名字匹配
- 目标工件从未经被跟踪工具写入（无 edit_file/search evidence）且可能来自外部——写入 provenance 边不存在
- 工件大概率就在当前根下但被改名——先在当前根做一次 content search_files 更便宜，不必先做跨根分诊
- 任务目标是一条可从 records/搜索库用单个精确术语取回的事实，而非文件工件——根选择分诊不适用
