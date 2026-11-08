---
method_id: cas-registry-supplement-writes-carry-full-baseline-union-4ea86a538ad9
name: cas-registry-supplement-writes-carry-full-baseline-union
description: 带版本号/CAS 校验的共享登记 store（lane/goal/协调记录）更新是整体替换语义：载荷里省略的列表项会被静默清空。要做『补充登记』时，把紧邻写入前那条完整读取回执当作唯一合并基线，一次更新携带 基线∪新增 的完整列表，并写后立即复读验证 count==预期并集、抽查一条旧项仍在；发现变小则在下一版本号立即全量回填，之后才让守卫/提交等下游依赖该记录。
aliases: 补登记把原有清单覆盖了, lane paths 只写新增丢了旧项, 登记表更新先并集再提交, 写后核对数量防整体替换, CAS 更新是覆盖不是合并
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:1684:97e4c1200b8b9f521b9e
evidence_refs: learning:learn:b00cfefd0e61
created_at: 2026-11-08T09:48:51.573685+08:00
updated_at: 2026-11-08T09:48:51.573685+08:00
---
## Trigger
首次（或本轮首次）向带版本校验的共享登记记录更新列表型字段（paths/scope/tags 等），且意图是追加/补充而非整列替换；写入前刚拿到该记录的完整当前状态。

## Discriminator
版本校验(CAS)更新天然是『写整个新值』而非增量合并：载荷只含新增项就会把原有全量清空。紧邻写入前的完整读取回执就是唯一可用合并基线——『补充登记』意图与『只写增量』载荷相互矛盾，这个矛盾在提交前即可判定，无需先写坏再发现。

## Short path
- 读完整记录并原样保留当前全量列表（未知量：现有登记范围是什么）
- 计算并集＝当前全量∪本次新增（除非显式移除），一次版本化更新携带完整列表（未知量：新增已登记且旧范围无损）
- 写后立即廉价复读：count==预期并集，并抽查一条写入前就存在的旧项仍在
- 校验通过前不让守卫/提交等下游动作依赖该记录；count 变小⇒整体替换已发生，立即在下一版本号全量回填并复验

## Stop conditions
- 写后复读 count 与旧项抽查均等于预期并集
- store 文档或回执明确证明更新端点是增量(additive/append)语义，delta 载荷本就正确

## Verification
- post-write count == baseline + additions
- 抽查至少一条 pre-existing 列表项仍存在
- 若已发生替换事故：全量回填后再次复读确认完整恢复，才继续后续动作

## Counterexamples
- store 提供显式 append/add 端点（增量 API）——此时 delta 载荷才正确，全量重写反而可能覆盖他方并发新增
- 本次意图就是收敛/删除列表项（如清理过期登记路径）——不应无差别保留基线
- 一次性本地草稿/临时状态，覆盖替换正是目的——无需并集与抽查
