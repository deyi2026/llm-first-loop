---
method_id: layered-merge-gap-adjudication-cherry-vs-integration-signal-ddf15fea71c0
name: layered-merge-gap-adjudication-cherry-vs-integration-signal
description: 当 git cherry/独有提交计数声称分支内容『真缺』，而用户记忆或目标分支 log 显示已集成时，不要二选一，分层裁决：先在目标分支 log 按特性关键词 grep 集成提交、ls-tree 确认核心目录存在；再对每分支做文件级分类（main一致/双方都改/分支独有/main无此文件）；最后跨分支去重并识别最全快照分支。输出『已集成子集+真缺文件数+冲突风险』的量化划分而非二元结论，防止把同一条线的多份快照分支双计成 N×M 净欠账。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:33d3039e-2906-4f07-9dc7-517532290686:37:e55f1d866acb0c061077
evidence_refs: learning:learn:9b67adfaff2e
created_at: 2026-10-14T17:15:45.902033+08:00
updated_at: 2026-10-14T17:15:45.902033+08:00
---
## Trigger
commit 级工具结论（git cherry/独有提交数=『真缺 N 补丁』）与反向信号（用户记忆『已启用』、目标分支 log 命中集成关键词、特性目录存在于目标分支）发生冲突，且待合并分支疑似为同一条演进线的多个快照

## Discriminator
目标分支 log 按特性关键词 grep 是否命中集成提交（如 integrate...default off），且特性核心目录在目标分支 ls-tree 中存在——该事实第一跳即可取得，把『缺/不缺』二值争议缩成『已集成子集 vs 真缺子集』的划分问题，不必先逐分支枚举全部文件

## Short path
- 在目标分支 log 按特性关键词 grep 集成提交（未知量：内容是否已以其他提交形式落地，如 squash/rebase 合并）
- ls-tree 确认特性核心目录/文件在目标分支存在（未知量：机制代码层是否已进 main）
- 对每分支做文件级分类：main内容一致 / 双方都改 / 分支独有 / main无此文件（未知量：每分支真正缺什么、cherry 是否误报）
- 跨分支去重独有文件集，按 docs/代码/测试分类并识别最全快照分支（未知量：净欠账规模与单一合并线索）
- 输出量化划分（已集成子集+真缺文件数+双方都改的冲突面），再交由审核子代理裁决是否合并

## Stop conditions
- 关键词 grep 与 ls-tree 均为空 → cherry 结论可信，直接按真缺处理，无需分层
- 某分支文件级分类为 0 独有改动 → 判定已完全并入，从待办移除
- 去重后已得到『已集成子集+真缺文件数+最全快照分支』三元组 → 停止核验，输出结论

## Verification
- 用 git cat-file -e main:$f 与 git diff --quiet 交叉验证文件分类，不依赖 patch-id 单一证据
- 『已集成』断言必须落到具体提交哈希与文件清单，可被第三方复核
- 冲突风险结论须引用双方都改的文件清单及 main 侧后续重构提交，而非笼统『可能冲突』

## Counterexamples
- FF-only 仓库、无 squash/rebase 历史，cherry 与内容 diff 一致 → 分层核验冗余，直接采信 cherry
- 单分支小 diff、无快照重叠 → 直接读 diff 即可，跨分支去重是浪费
- 用户只问开关是否启用 → 查目标 ref 上配置默认值一处即可，不必全量文件分类
