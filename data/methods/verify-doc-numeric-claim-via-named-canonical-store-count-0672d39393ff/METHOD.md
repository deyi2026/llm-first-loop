---
method_id: verify-doc-numeric-claim-via-named-canonical-store-count-0672d39393ff
name: verify-doc-numeric-claim-via-named-canonical-store-count
description: 审查文档并核验其中的聚合数字声明（如『账本共 N 条回执』）时，先用已读材料中显式命名的 canonical 数据源路径直接计数，而不是对全仓库递归枚举同类文件。仓库常含 .releases/快照/备份目录：其副本既拖慢命令（本集触发 60s 超时），又会在计数中重复累加、破坏核验语义。仅当命名路径缺失或计数不符时，才沿 store 的路径配置定位真实位置，仍不做全库扫描。一句话：命名单一真值源已存在时，『所有同类文件』应先缩为『一两个命名路径』，mismatch 而非默认才触发扩大搜索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:0:4f948c463788c84c0ec7
evidence_refs: learning:learn:fbe3712f17db
created_at: 2026-10-15T20:25:08.245094+08:00
updated_at: 2026-10-15T20:25:08.245094+08:00
---
## Trigger
审查/核验设计或报告文档时，文档引用了具体数量（条数、计数、总量）的声明，且该数字的数据源（账本文件、单一真值存储）已在已读材料（模块 docstring、文档正文、配置）中被显式命名

## Discriminator
已读 artifact 是否显式给出该数字的 canonical 数据源路径。本集在计数动作之前，usage_net.py 模块头注已声明『数据源是两侧既有 usage ledger（methods/usage.jsonl、experiences/usage.jsonl）』——这一当时已知事实足以把『全仓库所有 usage.jsonl』缩为两个命名文件，无需任何递归枚举

## Short path
- 从文档声明提取待验证数字及其所指对象（哪类记录、哪个账本），未知量=该对象的真实总量
- 在已读材料中查该对象被显式命名的 canonical 路径；直接对命名路径做定向计数（wc -l），命令中排除 .releases/.git/快照目录
- 计数之和与文档数字一致（本集 22+20=42）→ 标记该条已核实，立即停止，不枚举其他副本
- 若命名路径不存在或计数不符 → 读 store 代码中的 base-dir/路径配置解析真实位置（本集 methods 账本实际在 data/methods/），再次定向计数
- 仍不匹配且确属跨多源聚合 → 才做有界枚举（排除快照目录），并说明口径

## Stop conditions
- 命名 canonical 路径的定向计数已与文档声明数字对上，该条核验完成
- 发现数字确无任何被命名的单一真值源，且已用有界、排除快照的聚合枚举覆盖全部真实来源

## Verification
- 最终计数命令只触及 canonical 路径（或经 store 路径配置解析后的等价路径），行数之和等于文档声明值
- 确认未把 .releases/快照/备份目录中的重复账本计入总和（副本会虚增计数）
- 复核所用路径与已读 artifact 中命名的数据源一致，或与 store 代码声明的存储布局一致

## Counterexamples
- 文档数字不对应任何被命名的单一真值源（如『历史事件总量』横跨多存储），此时必须有界聚合枚举，直接套用反而漏数
- 文档命名路径与真实运行位置不一致（配置了非默认 base dir）且首次定向计数不符——正确动作是查 store 路径配置，而不是坚持文档命名路径或退回全库递归 find
- 仓库无快照/发布目录且路径完全未知时，一次带 -maxdepth、排除 .git 的定向 find 是合理首选，不必先读配置再计数
