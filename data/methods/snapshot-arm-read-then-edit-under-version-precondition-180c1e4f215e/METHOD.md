---
method_id: snapshot-arm-read-then-edit-under-version-precondition-180c1e4f215e
name: snapshot-arm-read-then-edit-under-version-precondition
description: 在带参数级版本前置的 edit_file 契约（需 expected_snapshot_ref，且普通内容读取的回执不产生 snapshot_ref/file_contract 元数据）下，编辑前唯一关键未知量不是文件内容而是当前路径的权威 snapshot_ref。首次编辑某路径或收到『版本前置条件无效…本次未写入』拒绝时，先 read_file(path, snapshot=true) 取 ref，再以 expected_snapshot_ref 完整重发；拒绝=零副作用，可安全全量重试。按拒绝语分支：路径不符→arm 正确路径；无法验证→文件疑被外部改动，重读再发；权限类拒绝→重 arm 无效。
aliases: 编辑被拒本次未写入怎么办, 改文件前先拿快照引用, snapshot 不属于当前工作区, expected_snapshot_ref 从哪来, 零副作用重发编辑
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:2109:990704c447d0a5fbbfaf
evidence_refs: learning:learn:3f0f7d4b84fc
created_at: 2026-11-14T01:39:37.377791+08:00
updated_at: 2026-11-14T01:39:37.377791+08:00
---
## Trigger
准备在工作区内首次编辑某文件，或 edit_file 回执报『版本前置条件无效: snapshot 不属于当前工作区/路径或无法完整验证；本次未写入』，而此前的普通 read_file 回执头部没有 snapshot_ref/file_contract 字段

## Discriminator
拒绝回执同时给出两个当时即可用的事实：缺失前置就是『该精确路径的 snapshot』，且『本次未写入』= 零副作用可安全重发；而普通读取不产生该 token——说明 armed snapshot 只能由 read_file(path, snapshot=true) 显式获取，编辑前应先补这一跳而不是换姿势重试编辑

## Short path
- 对目标路径做 read_file(path, snapshot=true)，从回执头取 snapshot_ref（artifact://v1/<hash>）与 workspace_path_state
- 以完整重构载荷发起 edit_file(path, ..., expected_snapshot_ref=<该ref>)，不假设早前普通读取已满足前置
- 若仍被拒按拒绝语分支：『不属于当前工作区/路径』→ arm 的是别的路径，改 arm 正确路径；『无法完整验证』→ 疑似外部改动，重新 snapshot 读后再发
- 确认成功回执含 file_contract precondition_checked=true 与写后新 sha/复读一致，后续同路径编辑沿用同一 armed ref 直至再次被拒

## Stop conditions
- 编辑成功且回执同时出现 expected_snapshot_ref=<所传值> 与 precondition_checked=true 及写后校验
- 拒绝原因不是版本前置（权限/沙箱/路径不存在）→ 停止重试 arm，转而解决真正的前置条件

## Verification
- 成功编辑回执必须显式携带 precondition_checked=true 且写后 sha/复读一致
- 被拒后先确认文件内容零变化，再重发全量载荷而非假设部分写入已生效

## Counterexamples
- 编辑工具本身没有版本前置（普通仓库/编辑器）→ 直接编辑，先做 snapshot 读是多余一跳
- 拒绝语指向权限、沙箱或路径不存在而非 snapshot → 重新 arm 无效，需换路径或修权限
- 仅为查阅而重读已读文件（不打算编辑）→ 用有界段落重读即可，不必取 snapshot ref
