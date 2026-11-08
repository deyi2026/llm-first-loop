---
method_id: head-caliber-redlist-lower-bound-restage-and-absorb-ec920cd92491
name: head-caliber-redlist-lower-bound-restage-and-absorb
description: 工单点名 N 个行数/基线类守卫违例、但守卫所测源码文件仍是本 lane 未暂存在途修改（porcelain ' M'，守卫回退读 HEAD）时：暂存前跑出的红名单只反映 HEAD 内容，是下界；在途 +N 行要等精确暂存后才进入实测面。应把『精确暂存→同守卫重测』当作必经的一次完整测量：名单多出的同文件违例（如函数被在途改动顶过阈值）属预期暴露，在同一轮极小抽取授权内吸收，不当漂移追查、不重生成基线豁免、不 git add -A 收编范围外文件。与『修复后守卫读数逐字不变→口径错位』为同机制的反方向：这里是口径首次切对时名单变长。
aliases: git add 之后守卫又红出新的函数超长, 修完基线棘轮失败项不减反增, 工单列的违例数和实测对不上数, dirty 工作树下守卫红名单不准, 在途未提交改动躲过行数守卫
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:1433:64ca4802e8c113b42eae
evidence_refs: learning:learn:5903a07bf26d
created_at: 2026-11-08T00:25:48.390460+08:00
updated_at: 2026-11-08T00:25:48.390460+08:00
---
## Trigger
修复工单/brief 已点名待修的棘轮或基线守卫违例清单，而 git status --porcelain 显示守卫所测同一批源码文件上存在本 lane 的未暂存在途修改，且守卫读源口径为提交面（HEAD+staged，未暂存回退 HEAD）。

## Discriminator
porcelain 中守卫测量文件呈 ' M'（纯未暂存）+ 守卫 _read_source 类实现对该类文件回退 git show HEAD ⇒ 暂存前红名单是 HEAD 口径的下界；在途 diff（如 +139 行）中任何把函数顶过阈值（≥120 或超登记值）的增长，此刻全部不可见，只在 'M ' 暂存后重跑时显现为超集。

## Short path
- 核验 goal/lane/HEAD 与 porcelain，标记守卫所测文件中哪些是 ' M' 未暂存、其 diff stat 行数
- 原样复现红名单（HEAD 口径），与工单点名清单逐条比对确认根因，不动基线/豁免
- 按授权做极小保行为修复后，仅按 lane 范围精确暂存（禁 git add -A），确认这些文件 porcelain 变 'M ' 无残留
- 同守卫重跑取 staged 现实全名单；与暂存前名单求差集，多出的同文件新违例=在途增长进入实测面，归因到在途 diff 后在同一授权范围内继续极小抽取吸收
- staged 现实全绿+定向回归后冻结 SHA 送独立审查/原版门禁；最终本地 commit 的 tree 必须与冻结候选逐字节一致

## Stop conditions
- staged 现实红名单与工单一致（无超集）→ 直接进入冻结/审查/门禁，不再重复测量
- 新暴露违例超出授权文件面、或修复需改行为/字段语义 → 停止扩修，如实回报阻断
- 守卫所测文件工作树 clean（无 ' M'）→ HEAD 口径=staged 现实，无需预期超集效应

## Verification
- 采信绿灯前，porcelain 中守卫测量文件不得残留 ' M'/'MM' 状态
- 暂存前后两次红名单的差集逐条归因到在途 diff 的具体 +行数，无法归因的条目才另查
- 最终 commit tree 哈希 == 冻结送审/跑门禁的候选哈希（防测量面与提交面再漂移）

## Counterexamples
- 守卫直读工作树（无 HEAD 回退）→ 首次红名单即完整，暂存不改变测量面，无需预期超集
- 未暂存漂移来自其他会话而非本 lane 在途工作 → 不得暂存收编，保持 HEAD 口径并上报，否则把别人的漂移算进本提交
- 违例属覆盖率/依赖类且在途改动不触及该测量维度 → 无超集效应，仍按原清单修
