---
method_id: lifecycle-reap-three-gate-default-69e7cd0f68b2
name: lifecycle-reap-three-gate-default
description: 收尾/回收类工具的三闸安全默认：判据只筛候选不判死（超时≠死亡）、liveness 谓词必须注入式且缺失即不可达、不可逆删除与状态收口解耦并需显式二次确认；实测必须用副本对象，真实对象只做只读探测。
aliases: 收尾工具 超时自动回收 误删, 判据成立就删除 不可逆动作, liveness 谓词 注入式 fail-closed, 收口不等于清理, 回收类工具 二次确认
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:1a7bb31d-f3da-497f-9322-336483f4435a:979:0b0f0706f0a423fd94a9
created_at: 2026-11-14T15:03:19.700495+08:00
updated_at: 2026-11-14T15:03:19.700495+08:00
---
## Trigger
实现任何「长期不动的对象自动收尾/回收」的工具时（lane、worktree、任务、租约、临时目录）。

## Discriminator
设计里出现下列任一表述：按超时自动回收、超时即判死、收口后顺手删目录/删分支、探针自选优先级。

## Short path
- 判据分工：时间只用于筛候选，不用于判死。判死只认注入的权威谓词；谓词缺失 / unknown / False 一律不收口（fail-closed）。
- 谓词注入式：宿主注入，实现不自备探针。进程内 registry 的否定结果在跨进程与重启场景不构成死亡证据；弱证据（最近活动时间）只能用作「活着」的反证，不能用作死亡证据。
- 收口≠清理：状态收口（可追溯、可解释）与对象删除解耦；删除是不可逆的第二步，需显式二次确认（如 remove_worktree=true 且 confirm=true），删除失败只记事实、不回滚收口。
- 实测用副本：账本跑副本、对象指向临时目录，真实对象只做只读探测；破坏性分支不得指向真实对象。
- 实测口径（RULE-AI-35）：逐条列「应拦输入」——dry_run 零写、谓词缺失零动作、脏树不收口、删除需确认——并留可引用的证据文件。

## Pitfalls
- 把探针的 False 当成 dead → 跨进程误杀他人在跑的会话。
- 收口与删除放进同一次调用 → 判据成立直接变成破坏，且不可逆。
- 用真实对象跑破坏性分支 → 测试变事故（即便无产物丢失，也会破坏他人在途 lane 的现场）。
- 先删目录再收口 → 目录没了但 lane 仍在非终态，等于把在跑的 lane 抽走工作树。
