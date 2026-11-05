---
method_id: migrate-consumers-not-directories-before-archive-deletion-483931578266
name: migrate-consumers-not-directories-before-archive-deletion
description: 清理计划把『删除机器生成归档树』gate 在『先迁移』上时，迁移的单位不是目录，而是三件可机械裁决的事：①grep 路径前缀找出仍从该树解析内容的在库 consumer，逐个改指 canonical tracked 源并与 runtime 解析顺序对齐；②before/after 解析全集 diff（数量+名称集合+种子条目落点）证无损失，顺带暴露双源版本漂移（工具读旧归档副本、runtime 读新 tracked 版）；③为仅经该树可达的提交建 archive ref 作删除硬前置。迁移独立成 commit 后停在删除 gate：live 引用与待用户裁决项不并入本步。与『清理建议期先聚类生成器+grep live refs』互补：那条管建议期分类，本条管迁移执行期。
aliases: 删归档目录前先解除工具路径依赖, release树清理的迁移前置怎么做, 删除前给不可达提交建ref, 工具读旧归档副本和tracked版本不一致, 改完依赖来源怎么证明没丢内容
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:676:3c8d14b3ba944770181f
evidence_refs: learning:learn:3190a530b402
created_at: 2026-11-05T16:47:31.108223+08:00
updated_at: 2026-11-05T16:47:31.108223+08:00
---
## Trigger
清理/退役计划把『删除某归档或快照层（release 树、镜像目录、机器存档）』显式 gate 在『先迁移后统一处理』上，且该树的路径前缀可能仍被仓库内工具当作内容解析来源或兜底来源

## Discriminator
两条删除前即可机械确认的依赖证据，任一非空即禁止直接删：grep 该树路径前缀命中的在库 consumer（工具的解析/兜底来源指向树内路径）；for-each-ref/rev-list 显示存在仅经该树可达、不被任何 ref 覆盖的提交。清理清单文档若已具名这类提交（如『N 个不可达』），该清单本身就是待抢救项

## Short path
- 读清理文档的 gate 定义与具名风险项（不可达提交、live 引用），把『迁移』翻译成待解除依赖清单
- grep 路径前缀枚举全部在库 consumer；逐个把解析来源改指 canonical tracked 源，解析顺序与 runtime 对齐（不是删掉 fallback 了事）
- 等价核验：迁移前后解析全集对比——数量相等、名称集合 diff 为空、种子条目全部落 canonical；diff 失败＝发现双源版本漂移，统一到 canonical 后复验，不许放宽口径
- 为仅经该树可达的提交建 archive ref，rev-list 确认由 ref 可达
- 迁移独立成 commit（只含 rewiring 文件＋回归测试，不卷入工作树既有他人脏文件）；重建下游索引
- 停在删除 gate：live 部署引用条目保留，待用户裁决项列清单上报；实际删除等其自身前置满足，是另一步

## Stop conditions
- 全部 consumer 已改指 canonical 且 before/after 解析全集 diff 为空
- 仅经该树可达的提交均已建 ref 并验证可达
- 迁移 commit 落盘、下游索引重建成功——迁移步骤到此为止，不顺势执行删除

## Verification
- 迁移前后解析出的条目集合：数量相等且名称集合 diff 为空
- 解析输出不再含归档树路径（注意区分：条目正文文本里出现的路径字样不算路径依赖）
- 新增回归测试钉住『只存在于归档树里的条目不可见』的语义
- ref 创建后 for-each-ref + rev-list 确认原不可达提交可达

## Counterexamples
- grep 无任何在库 consumer、可达性检查也无树内独有提交 → 无迁移可做，直接进入清理流程
- 归档层比 canonical 更新（tracked 落后）→ 直接 rewire 会静默回退内容；必须先把内容同步/提升进 canonical，此时等价 diff 失败是发现而非噪声
- consumer 有意读归档旧版本做历史审计 → 统一到 canonical 会改变语义，应保留显式历史入口而非 rewiring
