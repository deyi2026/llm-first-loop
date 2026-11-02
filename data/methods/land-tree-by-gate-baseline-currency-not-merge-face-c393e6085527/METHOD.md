---
method_id: land-tree-by-gate-baseline-currency-not-merge-face-c393e6085527
name: land-tree-by-gate-baseline-currency-not-merge-face
description: 带棘轮/基线型全量提交门禁的多工作树仓库（main/integrate 并行）里，新改动的落码树由『门禁可绿性』决定：落码前的状态盘点回执若显示某树的基线重登记提交尚未合入其 HEAD（全量门禁结构性红），且该树工作树 WIP 与本次目标文件重叠，应直接排除该树，选基线与 HEAD 同步的干净树落码。本集先以『无合并冲突面』为由选 main，中途才发现 main 棘轮基线未合入、全量门禁红，被迫迁至 integrate 工作树——而两条判据在最初的双树状态盘点回执里都已存在。
aliases: main 门禁红 改动落哪个分支, 棘轮基线没合入 落码树怎么选, 落码选 main 还是 integrate, 全量门禁红的分支不要落码, 基线滞后 换树提交
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fb9d2fd4-22ec-46f0-9f10-3dd3f2341da5:907:be3136368b70e6be053f
evidence_refs: learning:learn:b204192228ef
created_at: 2026-11-01T01:11:14.233825+08:00
updated_at: 2026-11-01T01:11:14.233825+08:00
---
## Trigger
准备在多工作树仓库（如 main + integrate worktree 并行）落一段新代码、需要选定落码树/分支时；直觉判据『这棵树没有合并冲突面』不足以预测提交门禁能否通过。

## Discriminator
落码前的只读盘点回执（各树 HEAD 主题行 + git status 脏清单）已含两条决定性事实：(1) 最新的基线/棘轮重登记提交是否在该树 HEAD 祖先内——未合入则全量门禁结构性红；(2) 该树脏文件是否与本次目标文件重叠——重叠则落码会混入在途 WIP。任一条不满足即排除该树，无需真正跑一次门禁才知道。

## Short path
- 落码前一次只读盘点：各树 HEAD 主题行、git status 完整脏清单、最新基线重登记提交落在哪棵树
- 判据一：基线重登记提交属于该树 HEAD 的祖先（否则门禁红，排除该树）
- 判据二：脏文件与本次目标文件交集为空（否则先收编 WIP 或换树）
- 在通过双判据的树上直接落码；『无合并冲突面』只作平手裁决，不作主判据

## Stop conditions
- 已唯一确定一棵基线同步、无 WIP 重叠的树：停止选树，进入落码
- 所有候选树基线均滞后：先搬运/合入基线重登记提交，而不是带红落码或中途搬迁

## Verification
- 在选定树先跑门禁链最便宜的静态棘轮段确认绿，再进入昂贵全量段
- 提交回执确认全量门禁与基线在同一树通过，无『门禁红因基线滞后』类失败

## Counterexamples
- 改动不触碰任何棘轮覆盖维度（纯文档/注释/独立脚本）时，按合并面或就近树落码即可，不必做基线核查
- 候选树门禁红的原因是环境而非基线滞后（失败集合与 diff 无交集、errno 级环境物证）——应先做 base-commit 对照定性，直接换树会掩盖真因
- 单工作树或无基线型门禁的仓库不存在树选择问题，方法不适用
