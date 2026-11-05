---
method_id: self-held-run-lock-idle-gate-defer-activation-with-predicate-f28e9b22c4dc
name: self-held-run-lock-idle-gate-defer-activation-with-predicate
description: 受管服务 publish 新一代后需 restart 激活，但重启门禁是 waiting_for_idle（target 必须空闲），而回执显示 active run locks≥1 且锁可归因于发起 run 自身时，等待/重试是结构性死路而非瞬态竞争：run 不结束锁就不释放，等满超时只会得到 status=failed 与 ever_live=false 的空转 publish。正确做法：从回执归因锁→判定结构冲突→不再阻塞等待；要么按回执点名的 override 逃生门（带证据）执行，要么登记『空闲时段 restart+expected_generation』的延迟激活，并以 service_control(status) 的 live_code_heads==publish 的 git_head 且 convergence.lagging 不含该服务作为唯一生效判据，向用户如实分层报告当前实际运行代。
aliases: 重启等不到空闲被自己的锁挡住, publish 成功但服务没真正生效, restart 等满 900 秒还是 failed, 发布的新一代一直没上线, 部署被活跃 run 锁卡住
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d0e6ba0c-dfdb-4a7e-b110-850f0ae238a6:1252:5dc0e2ced0c615d38873
evidence_refs: learning:learn:d1a8abeebba5
created_at: 2026-11-05T13:56:24.314401+08:00
updated_at: 2026-11-05T13:56:24.314401+08:00
---
## Trigger
run 内刚 publish 新一代服务（publish 成功只登记 generation），随后需要 service_control(restart) 激活，而重启回执显示 gate=waiting_for_idle、confirmed_busy: active run locks ≥ 1，且活跃锁可归因于本 run 自身（单活跃 run 或 requester_session_id 吻合）

## Discriminator
回执 detail 同时给出三件事：门禁名（gate=waiting_for_idle）、忙证据（active run locks: 1）、requester_session_id，并自带 override 逃生门（action=override, evidence_level=E1|E2|E3）。当锁数可归因于发起 run 自己时，门禁条件与本 run 的存在自指——这是『结构性不可满足』与『瞬态竞争』的分界事实；被取代代的 supersedes.ever_live:false（publish 空转先例）可在本 run 内直接观察到。

## Short path
- 读 restart 回执：提取 gate 名、busy 证据（active run locks 数）、锁归属线索与 override 选项
- 归因锁：若为本 run 自身 → 判定结构死锁，禁止再发阻塞式 restart 或重 burn 等待预算（900s 等满必失败）
- 分叉：能给安全证据（锁属自己、重启幂等、无他人依赖该 target）→ 按回执走 override；否则登记延迟激活——空闲时段执行 restart(target, expected_generation=publish 的代)
- 把生效判据写成可重采样谓词：service_control(action=status) 要求 live_code_heads.<svc>==本次 publish 的 git_head 且 convergence.lagging 不含 <svc>
- 如实分层汇报：代码已 push、publish 已登记第 N 代、实际运行仍是第 M 代旧 head，生效以 status 回读为准

## Stop conditions
- status 回读 live_code_heads.<target>==publish 的 git_head 且 convergence.lagging 不含 target（真正生效）
- 或 override 已带证据执行并通过同一 status 谓词验证
- 或延迟激活指令（restart+expected_generation+验证谓词）已明确登记/交代，本次不再消耗等待预算

## Verification
- 唯一生效证据 = service_control(action=status) 的 live_code_heads 与 convergence.lagging；publish 回执与 restart 登记回执都不构成生效证据
- 对照被取代代的 supersedes.ever_live 标志，确认没有再产生从未上线的空转 publish

## Counterexamples
- active run locks 属于其他 session/worker 而非自身：这是协调/瞬态问题，有界等待或跨会话协调可能成功，机械延迟反而拖延（此时应按普通异步门禁重采样谓词）
- 门禁不是自指条件（如等健康检查通过、等依赖就绪）：等待可能真实收敛，不适用本方法
- staging/一次性环境里 override 例行安全且无人共享 target：直接 override+status 验证通常比登记延迟激活更省
