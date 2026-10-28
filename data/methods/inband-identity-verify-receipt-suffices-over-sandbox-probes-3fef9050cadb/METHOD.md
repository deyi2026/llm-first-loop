---
method_id: inband-identity-verify-receipt-suffices-over-sandbox-probes-3fef9050cadb
name: inband-identity-verify-receipt-suffices-over-sandbox-probes
description: 受管服务重启/发布的终态回执若已内嵌进程级身份核验（verify=confirmed_ok，pid+git head 读自活进程 runtime manifest），该回执本身就是『服务真的在跑目标代码』的权威证据；在限制性沙箱里追加 ps/lsof/find 等带外 OS 探针属于 post-sufficiency 动作：ps 常被 Operation not permitted 拒绝，lsof 的 cwd 在 worktree 部署中指向仓库根而非 release 根，不能证明 code_root。确需佐证时只做一次对控制面声明 artifact 的精确路径读取，并在报告中如实区分证据来源。
aliases: 重启回执已confirmed_ok还要ps吗, 沙箱里ps被拒怎么确认服务上线, lsof看到的cwd不是code_root, 重启成功回执能不能当核验证据, 受管服务上线后要不要独立探针
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:929:bf83bb62edc914a5acbd
evidence_refs: learning:learn:ee6382424957
created_at: 2026-10-27T23:28:20.507298+08:00
updated_at: 2026-10-27T23:28:20.507298+08:00
---
## Trigger
受管控制面的 restart/update 终态回执已含 status=succeeded 且 verify_evidence/verify_verdict 携带活进程身份（pid + git head/generation），同时环境回执显示运行在限制性沙箱（进程/系统级探测可能被拒）时，判断是否仍需 OS 级独立核验。

## Discriminator
回执 detail 中 'verify=confirmed_ok <target>[ok pid=… head=<目标commit>]' 表明控制面已读取活进程自身的 runtime manifest 完成身份核验——这正是想用带外探针获得的那个事实，且先于任何探针就已出现；同时每条 shell 回执的沙箱 banner（仅允许写工作区/缓存目录）预示 ps 类系统级探测大概率被拒。

## Short path
- 每个目标重启后只查终态回执：status=succeeded 且 verify_evidence 的 pid 非空、head==目标 commit → 该目标核验完成，记录 action_id，不发起 OS 探针
- 逐目标重复上一步，全部通过即进入报告与遗留事项裁决（如意图冲突确认、待闭合 failed 动作）
- 仅当回执缺 verify 字段或 verdict 非 ok 时才升级带外核验：先一次 status/schema 查询取得控制面声明的 runtime manifest 精确路径，再做一次定点读取；不做进程表枚举或目录扫描
- 带外探针首次被拒（Operation not permitted）或返回与 code_root 无因果的信号（如 cwd 指向仓库根）→ 立即放弃该分支，以回执 verify 为最终证据并如实标注证据来源

## Stop conditions
- 每个目标都有 succeeded 终态回执且 verify_evidence 的 pid/head 与目标 commit 完全一致
- 带外探针首次被沙箱拒绝或被判定信号无效后，不再重试同类探针
- 用户所需的『已上线且运行目标代码』事实已有权威来源支撑

## Verification
- 逐字段核对 verify_evidence：pid 非空、head 与期望发布 commit 完全一致、verify_verdict=confirmed_ok
- 报告中明确区分证据来源（控制面自检回执 vs 独立探针），不把 lsof cwd 等弱信号当作 code_root 证据

## Counterexamples
- 回执 succeeded 但 verify_verdict 为空/failed，或自检只回显 desired 状态而非活进程身份 → 带外核验是必要的，不能以回执为满足
- 历史上该控制面自检曾失真（核验的是 desired 而非 running 进程）→ 必须独立探针，但选 manifest/cmdline 等能证身份的探针，cwd 不算
- 无沙箱的低约束环境里一次 ps 成本近零，顺手确认无妨，成本收益反转
