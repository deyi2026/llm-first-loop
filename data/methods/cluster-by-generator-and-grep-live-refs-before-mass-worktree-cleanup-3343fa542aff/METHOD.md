---
method_id: cluster-by-generator-and-grep-live-refs-before-mass-worktree-cleanup-3343fa542aff
name: cluster-by-generator-and-grep-live-refs-before-mass-worktree-cleanup
description: 对大批同形 git worktree / 快照树给清理建议时，第一分类维度用路径形态聚生成器类（如 <root>/.releases/<sha> 机器存档 vs .worktrees/<语义名> 开发树 vs /tmp 探针），第二维度才是 git merge 状态；对最大类在判『零风险可删』前必须 grep 代码/脚本对该目录模式的 live 引用——git clean+merged 只证明 commit 可达，不证明没有文件系统级依赖（本集 159 棵『干净』快照实为工具 seed 源）。squash 流程下 fwd>0 ≠ 未合并，需 patch 等价核对。
aliases: worktree 太多怎么清理, 快照树能不能直接删, 批量删 worktree 前先查引用, 发布快照目录占磁盘怎么回收, 干净已合并的树就等于没人用吗, 上一轮说可删的树数字对不上了
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:558:1cecb1514519567c6106
evidence_refs: learning:learn:17cc7f27bf8e
created_at: 2026-11-05T16:20:34.602946+08:00
updated_at: 2026-11-05T16:20:34.602946+08:00
---
## Trigger
要对大量同形 worktree / 生成目录 / 发布快照给出删除或清理建议时；尤其当『干净且已合并』即将被翻译成『零风险可删』，或延续上一轮已给出的可删数量基线（如 265/7 这类口径）

## Discriminator
worktree list 的路径形态本身已把总体分成不同生成器（目录前缀 + 命名模式：sha 存档 / 语义名开发树 / tmp 探针），不同生成器的删除权威不同；merge-base 拓扑只是其中一种权威，『工具把该目录当数据源扫描』这类依赖不出现在任何 git 状态里，只有对最大类做代码引用检查才能裁决

## Short path
- git worktree list 后先按路径形态聚生成器类并计数，识别最大膨胀源；未知量：总体由几类生成器构成、谁占大头
- 对最大类 grep 代码/脚本对其目录模式的引用（谁在扫描/消费它）；未知量：『干净』是否等于『无人用』
- 无引用的类再做 merge-state 审计（clean/dirty/patch_equiv/unmerged）出删除清单；有引用的类单独走『先迁依赖源、后批量删』两段式建议
- fwd>0 的树补 patch 等价核对（squash 工作流下 commit 不可达 ≠ 内容未进 main），得到真实待人工裁决的最小清单
- 删除执行前查活进程 cwd/cmdline 是否落在目标树内；各类结论经其对应权威（拓扑或代码引用）验证即停

## Stop conditions
- 每个生成器类都有独立处置结论，且『可删』结论同时通过 git 拓扑检查与代码引用检查（或显式标注依赖待迁移）
- 上一轮携带的基线数字已与当前实测对账，口径差异已向用户显式说明

## Verification
- 对判为可删的最大子集，抽查其目录模式在仓库代码/脚本中的引用计数为 0（或引用已迁移）
- 判为『未合并』的树，其 diff 内容确实不在 main（patch 等价），而非仅 commit 不可达
- 删除后依赖方（如 seed 扫描工具）的输入源数量不减少

## Counterexamples
- 少数手开分支的开发 worktree、无任何工具从其路径读数据：按生成器聚类是过度工程，直接 merge-state 处置即可
- grep 命中集中在死代码 / 一次性历史脚本 / evals 结果存档：命中 ≠ live 依赖，需先判引用活性再决定是否阻断删除
- 工具消费的是 git 对象（tag、git show <sha>:path）而非工作树文件：worktree remove 不删 commit，可直接删
- 总体本来就只有一个生成器（全部树同一条流水线产出）：聚类无信息量，直接进入拓扑审计
