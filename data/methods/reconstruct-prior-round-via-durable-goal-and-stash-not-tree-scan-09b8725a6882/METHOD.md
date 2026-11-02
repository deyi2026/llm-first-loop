---
method_id: reconstruct-prior-round-via-durable-goal-and-stash-not-tree-scan-09b8725a6882
name: reconstruct-prior-round-via-durable-goal-and-stash-not-tree-scan
description: 续跑任务引用上一轮交付、但会话状态查询明确 not found 时，第一未知量是『上轮交付的权威记录在哪』而非『仓库长什么样』：先查持久 goal/task store 拿到交付描述与文件清单，再做一次精确存在性检查；缺件则读带描述的 git stash list 定位未合并工作。上轮『已交付』只证明曾存在，不证明在工作树——本集上轮 L1–L4 全部活在 stash 与 /tmp 备份里，树内搜索必然 miss，逐目录枚举 src/tools/docs 纯属绕远；两条权威查询即可闭合，并顺带产出『待恢复资产』风险事实（本集成为 D4 裁决项）。
aliases: 上轮交付找不到 先查 goal 记录和 stash, 文件明明做过但工作树里没有, 会话状态丢了 怎么恢复上一轮上下文, 续跑前先找未提交的 stash 工作, 交付过却不在树里 在途工作找回
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:664:ef06ea2a2a72b55acf69
evidence_refs: learning:learn:e7f7cb9e7e81
created_at: 2026-11-01T11:11:23.214048+08:00
updated_at: 2026-11-01T11:11:23.214048+08:00
---
## Trigger
续跑/后续任务显式引用『上一轮交付/此前发现』，但会话或任务状态查询回执明确 not found，需要先重构上轮做了什么、产物现在在哪

## Discriminator
状态查询失败回执 + 任务文本的『上一轮』锚共同表明：上轮记录不在本会话，只可能存在于持久权威（goal/task store、git stash/log）中；此时对源码树的逐目录枚举不缩小任何未知量，且『树里搜不到上轮文件』本身就是『工作未合并』的证据而非『没做过』

## Short path
- 状态查询 miss 回执出现 → 第一未知量定为『上轮交付的权威记录在哪』：直接查持久 goal/task store 的最近 goal，拿到交付描述、验收判据、涉及文件清单
- 按清单做一次精确存在性检查（ls 精确路径 / git status --porcelain）；命中即进入事实核对，不枚举目录
- 缺件 → 下一未知量『未合并工作在哪』：git stash list 读带描述的 stash（本集 stash 描述直接写明 pre-push 在途集），必要时 stash show 或已知备份路径取内容
- 从 stash/备份版本读上轮设计文档与实现，替代对 src 子目录（tools/builtin/core 等）的逐个枚举
- 把『上轮已交付但仍活在 stash/备份』作为独立待裁决风险写入本次交付，再进入逐条证伪与需求化

## Stop conditions
- 上轮交付的内容与当前位置已由 goal store 记录 + git stash/status 双重确认
- 上轮产物确认已在工作树且与 goal 记录一致 → 停止挖掘，进入当前任务本体
- goal store 与 stash 均无该轮痕迹 → 判定跨仓/跨机/跨工作区，转向兄弟项目目录或归档一次定界，不在同一权威上循环重试

## Verification
- goal 记录列出的文件清单与工作树/stash 实际内容逐一对应
- 新设计文档引用的上轮事实（文件+行号/命令回执）能在当前树或 stash 版本中复现
- 最终交付显式列出『上轮未合并资产』及其当前位置，供用户裁决

## Counterexamples
- 全新任务不引用任何上轮：状态 miss 是常态信号而非线索，直接开工，不查 stash
- 上轮已提交合入 main：一次存在性检查即通过，stash 挖掘无意义
- goal store 为空或查询不可用：一次失败后退到 git log --grep + docs 索引定界，不在 store 上换措辞重试
- 上轮交付在另一仓库/另一工作区（如 mirror vs public）：本仓的 goal store 与 stash 都不是权威，须先定位正确工作区再谈恢复
