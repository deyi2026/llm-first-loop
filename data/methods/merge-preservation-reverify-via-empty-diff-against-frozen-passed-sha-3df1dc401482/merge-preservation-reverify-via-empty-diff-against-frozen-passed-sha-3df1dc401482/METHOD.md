---
method_id: merge-preservation-reverify-via-empty-diff-against-frozen-passed-sha-3df1dc401482
name: merge-preservation-reverify-via-empty-diff-against-frozen-passed-sha
description: 冻结候选是『已独立PASS的修复提交』无冲突合入更新main后的merge commit，且任务书给出三个精确SHA（已PASS修复、新main、冻结HEAD）时，『合并是否改变修复』不是要重推的语义未知量，而是机械恒等式：对修复changed_paths做 已PASS修复SHA..HEAD 的路径限定diff，空即逐字节保留。合并引入的风险被限定在main侧带入内容，再补两件事即可终判：用项目权威解释器（worktree场景先定位，常在worktree外）实测合同点名的关键运行时常量一次、定点重跑关键负测套件一次。不要从零重推安全合同，不要做无路径限定的全仓diff让policy侧噪声淹没恒等信号。
aliases: 审查merge提交有没有动之前已经过审的代码改动, 合到最新主干后要不要从头重验修复, 两个SHA之间空差异证明改动原样保留, 冻结候选重新审查 给精确SHA的裁决流程, rebase重写后能不能复用上一轮审查结论
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e29392ab-0c32-4979-910f-cf887c47688b:0:be0d6b6fea4274d1db84
evidence_refs: learning:learn:278d45b24827
created_at: 2026-11-17T02:08:27.166198+08:00
updated_at: 2026-11-17T02:08:27.166198+08:00
---
## Trigger
独立复审任务书声明：候选=已独立PASS的修复提交与更新main的无冲突merge，三个精确SHA（修复SHA、新main SHA、冻结候选SHA）与窄changed_paths均在任务书中给出，要求裁决合并是否改变原修复合同并给出PASS/REVISE+精确SHA。

## Discriminator
任务书自身的SHA拓扑+『无冲突』声明（knowledge-at-time，开局面即有）：它使『合并是否逐字节改动已PASS修复体』退化为一次 git diff <已PASS修复SHA>..<HEAD> -- <修复代码paths> 的空/非空机械判定，无需任何语义重推；合同谓词也被任务书点名，可对准唯一运行时常量做锚点核对。

## Short path
- rev-parse HEAD + status/log：核 HEAD==冻结SHA、树干净、合并拓扑成立（merge父母=新main与已PASS修复线）——未知量：候选身份与结构。
- git diff <新main>..<HEAD> -- 修复changed_paths：确认合并确实携带修复内容——未知量：合并带入了什么。
- git diff <已PASS修复SHA>..<HEAD> -- 修复代码paths：空 ⇒『合并未改修复』关闭，逐字节保留——未知量：合并动了修复没有。此步是方法核心，到此不重推合同。
- 先定位项目权威解释器（worktree场景常在worktree外），用它 import 合同点名的运行时常量并打印实测值——未知量：修复谓词与运行时真值是否仍一致。
- 定点重跑关键负测套件一次并记录通过数——未知量：发起方测试声明是否可独立复现。
- 三项齐备即出 PASS/REVISE+精确SHA；环境不可达项（如生产activation状态）写免责声明不改判，不加轮次。

## Stop conditions
- 路径限定 diff(已PASS修复SHA..HEAD) 为空 且 HEAD==冻结SHA 且树干净 ⇒ 合并未改修复，该未知量关闭
- 权威解释器实测合同常量与修复谓词一致 ⇒ 语义一致性关闭
- 定点负测套件全绿 ⇒ 测试声明复现性关闭
- 三者齐 ⇒ 立即终判停止，不为清单外观察或P2级顾虑追加轮次

## Verification
- 两个方向的diff都必须用精确SHA且路径限定修复changed_paths；全仓diff会让policy侧变更淹没恒等信号
- HEAD==冻结SHA、status干净、merge-base==新main 三点齐才承认候选身份
- 合同关键常量必须本run用权威解释器实测输出，不接受转述
- 终判中区分『本run独立复现』与『仅转述发起方』

## Counterexamples
- 任务书未给出已PASS修复的精确SHA（只说'之前审查过'）⇒ 无恒等式可判，须做完整合同复审，不套用
- 合并存在冲突或手工解决补丁 ⇒ 逐字节保留性不再由无冲突结构保证，必须直接审解决补丁本身
- main侧带入变更与修复有依赖边相交（如改动了合同所引用的状态枚举/协议模块）⇒ 空diff不足，须扩大到依赖面做语义核验
- 候选是rebase/重写后的新SHA而非以已PASS修复为祖先的merge ⇒ 无恒等关系，diff语义失效
