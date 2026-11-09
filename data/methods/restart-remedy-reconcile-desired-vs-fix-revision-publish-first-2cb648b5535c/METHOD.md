---
method_id: restart-remedy-reconcile-desired-vs-fix-revision-publish-first-2cb648b5535c
name: restart-remedy-reconcile-desired-vs-fix-revision-publish-first
description: 把『受控重启某托管服务』当修复手段（清错误进程内状态或加载修复代码）执行前，先用权威回执对账 desired 版本与修复实际所在修订：重启只加载 desired，不加载仓库 HEAD；desired 落后则纯重启只会重载旧码，须先建目标修订快照、补齐 gitignored 构建产物并 publish，再正式 restart；外部预检值与回执不符以回执为准并如实上报边界。
aliases: 重启修bug前先核对要加载的版本, 重启不等于升级到最新代码, 先发布再重启, 重启后还是旧代码, 受管重启前对账desired与main
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:2333:55ee375f879715fbc6c0
evidence_refs: learning:learn:8775241f02c2
created_at: 2026-11-08T14:32:34.198290+08:00
updated_at: 2026-11-08T14:32:34.198290+08:00
---
## Trigger
用户/上游指令把受控重启某托管服务当修复手段，并附外部预检值（PID/HEAD/generation），而本轮尚未读取该服务的 desired/live 权威快照

## Discriminator
权威回执中 desired 的 git_head/code_root 与实测『修复所在修订』（当前 main HEAD 等）是否一致：重启只会加载 desired，不会加载仓库 HEAD；两者不一致即可在动手前判定纯重启无效（只清进程内存态、旧码重载）。外部预检 PID/HEAD 与回执不符本身即是预检过时信号，以回执为准

## Short path
- 读目标服务 desired/live/stable 权威快照（真实回执），同时实测修复所在修订（如 rev-parse main）
- 判别：desired 是否已含目标修复？是→按原令纯重启；否→重启前须先 publish 新 desired
- 从目标修订建干净快照 worktree；对照既有部署记录的绑定字段（构建产物 sha 等）补齐 gitignored 构建产物——发布通道通常不自动构建
- publish 推进 desired generation → 正式 restart → 按 action_id 复核 status=succeeded 且 live.git_head==desired.git_head、非目标服务不受扰动
- 全程如实记录预检差异、授权边界与残余缺口（重启加载的修复≠定因缺陷本身已修）

## Stop conditions
- desired 已指向含修复修订且 restart 终态 succeeded、live 收敛到新 generation
- 无可靠单服务恢复路径，或完成 publish 所需授权/审查闸不在本次授权内 → 停下报告，不裸 kill、不绕过 service_control

## Verification
- service_control status：live.git_head==desired.git_head==含修复修订；generation 递增；非目标服务 PID 不变
- publish 回执 code_root 指向新快照且构建产物绑定字段齐全

## Counterexamples
- 重启只为清进程内死锁/缓存态，代码版本无关紧要 → 直接重启，desired 落后也无妨
- desired 已与修复修订一致（此前已发布）→ 纯重启即可，重复 publish 徒增 generation 与风险
- 非受管 OS 单元服务（launchd/systemd）→ 句柄是注册表 unit，不存在 publish 链
- 发布需过独立审查/R9 闸而本次授权只批了重启 → 不得为让重启生效擅自越闸发布
