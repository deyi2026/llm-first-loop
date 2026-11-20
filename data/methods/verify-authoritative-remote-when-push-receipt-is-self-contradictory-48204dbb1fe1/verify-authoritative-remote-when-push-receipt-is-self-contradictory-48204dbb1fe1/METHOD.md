---
method_id: verify-authoritative-remote-when-push-receipt-is-self-contradictory-48204dbb1fe1
name: verify-authoritative-remote-when-push-receipt-is-self-contradictory
description: 对远端引用的写操作回执自相矛盾（exit 0 + 'Everything up-to-date'，但 stderr 同时显示本地 remote-tracking ref 写入被沙箱/权限拒绝）时，'up-to-date' 摘要反映的是被拦的本地簿记而非远端真值。不要据此判失败（误 HOLD/重推/强推），也不要仅凭 exit 0 报成功：用一次只读远端定点查询（git ls-remote origin <精确ref>）核验分支 SHA 是否等于冻结目标，并确认受保护分支未动。推送成败的权威永远在远端侧读数，不在本地已被污染的回执。
aliases: push 显示 Everything up-to-date 但远端没更新, remote-tracking ref 写不进去被沙箱拦截, 推送到底成没成功怎么确认, ls-remote 查远端分支真实 SHA, git push 退出码 0 却报权限错误
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:516:cfef4f7eec4a0d675395
evidence_refs: learning:learn:ef9cef50500a
created_at: 2026-11-17T08:53:35.839180+08:00
updated_at: 2026-11-17T08:53:35.839180+08:00
---
## Trigger
push/受管远端写的回执同时含成功信号（退出码 0、'Everything up-to-date'）与本地失败信号（stderr 具名某 .git/refs/remotes/*.lock 'Operation not permitted'），『已推送成功』与『根本没推出去』两种解读表面上都成立。

## Discriminator
knowledge-at-time：推送前权威侧状态已知——本轮首个 rev-parse 回执已显示该分支的远端跟踪 ref（fd777…）≠ 目标 SHA（5dfcd4f1…），故 'Everything up-to-date' 与已知事实直接矛盾；且 stderr 具名失败对象是主仓 .git 内的本地 refs 锁文件写入（沙箱写保护），而非远端侧拒绝（非 fast-forward/认证/服务端错误）——被拦的是本地簿记，不是推送本身。

## Short path
- 不重跑 push、不判 HOLD、不升级为强推：先承认该回执语义不可靠
- 用 stderr 具名的失败位置把失败归类为『本地 remote-tracking 簿记被拦』而非推送失败
- 对权威侧做一次只读定点查询：git ls-remote origin <分支精确 ref>（连同需保护的主分支）
- 回读 SHA 与冻结目标逐字比对；不相等则转入真实失败处理，回到审查/推送链路
- 报告时显式区分两层：远端已到目标 SHA（推送成功）＋ 本地跟踪 ref 未更新（沙箱所致，无影响）

## Stop conditions
- ls-remote 返回分支 SHA == 冻结目标且受保护分支未变 → 成功收口，不再动作
- ls-remote 返回仍为旧 SHA → 推送确实未生效，转入失败处理分支
- stderr 显示的是远端侧拒绝（non-fast-forward、认证失败、hook deny）→ 本方法不适用，按真实失败处理

## Verification
- 远端侧只读读数（ls-remote/服务端 API）是唯一权威；本会话内不再信任本地 remote-tracking ref
- 核对 push_remote == push_src == 冻结目标精确 SHA（与审查回执冻结值一致），受保护分支保持原值

## Counterexamples
- stderr 是远端侧拒绝（non-fast-forward / denied / pre-receive hook）→ 这是真失败，不能当本地簿记问题跳过去只查远端
- 环境对主 .git 无写保护（本地跟踪 ref 可正常更新）且 stderr 无 blocked-write 报文 → exit 0 + 'up-to-date' 通常可径直采信
- 推送前远端状态未知（无任何 rev-parse/ls-remote 前值）→ 缺少『与已知事实矛盾』这条判据，此时远端定点核验仍应作为安全默认，但方法判别强度下降
