---
method_id: verify-config-writes-against-store-not-snapshot-views-26e3d9d3d450
name: verify-config-writes-against-store-not-snapshot-views
description: 验证配置/注册表改动（模型钉定、成本档、推理开关）是否生效时，真值只在两处：带版本标识的写入回执 + 加载器实际读取的权威 store。全仓关键词搜索会命中大量冻结副本（evals 结果目录、fixtures、.bak 备份），同一会话的运行时 catalog 也可能只是本轮锁定的 registry 快照——回执成功而视图仍旧值≠写入失败。先做回执×store 两点对账判定『已写入』，再在快照刷新边界（重启/下一轮）验证『已生效』，不要用宽 grep 或重复 catalog 查询再确认。
aliases: 改了providers配置为什么模型列表还是旧值, 写入成功但本会话看不到新配置, 全仓搜配置值全是evals里的副本, 怎么确认成本档真的改成功了, 问完成了没要查哪些回执
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:9a21b8fd-48b7-47a5-89f5-4b9d739d7129:243:a1db1bbd6f02b678740f
evidence_refs: learning:learn:adb506d050db
created_at: 2026-10-30T12:14:40.772402+08:00
updated_at: 2026-10-30T12:14:40.772402+08:00
---
## Trigger
用户询问此前多项配置改动的完成状态；或写入回执已成功，但 repo 搜索 / 同会话运行时目录仍显示旧值，需要判断是否真的未生效

## Discriminator
存在带新鲜版本标识的成功写入回执（config_version / commit SHA / 发布 generation），且与之矛盾的读数可归因为快照机制：grep 命中的是 evals/results、fixtures、备份文件等冻结副本，或 catalog 展示的是 run 开始时锁定的快照

## Short path
- 逐项改动收集写入回执：配置文件当前值 / admin API 回执（含版本标识）/ commit+发布号
- 确定权威读取路径（加载器实际读的 store 文件或 admin GET），只以 回执×store 对账判定『已写入』
- 把矛盾读数归因到快照机制：grep 命中的冻结副本、同会话锁定快照，均不据此判失败
- 『已生效』只在刷新边界验证：进程重启完成或下一轮新快照，查 live 端点（如 live_git_head、服务状态）
- 每项按 已写入/已生效/待边界刷新 汇报，pending 项挂跟踪动作后停止，不再重复查询同一视图

## Stop conditions
- 每项改动都完成回执与 store 内容一致的对账
- 待生效项已绑定明确刷新边界与跟踪动作
- 不再用宽 grep 或对同一会话视图重复查询做『再确认』

## Verification
- store 文件（或 admin GET）显示新值且版本标识与写入回执一致
- 刷新边界之后的新快照/live 端点显示新值
- 若 store 仍旧值或版本无推进，判为真实写入失败，回写入侧排查而非归因快照

## Counterexamples
- catalog 是真正实时读取（无快照锁定）且 store 未变——旧值就是失败信号，不得用快照说辞开脱
- 任务目标本身是历史 lineage（比较各 eval 快照中配置演变）——冻结副本正是目标而非噪声
- 尚无任何写入回执时，第一未知量是『写没写』，先取回执再谈快照语义
