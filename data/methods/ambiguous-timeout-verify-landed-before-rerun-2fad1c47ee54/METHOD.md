---
method_id: ambiguous-timeout-verify-landed-before-rerun-2fad1c47ee54
name: ambiguous-timeout-verify-landed-before-rerun
description: 当状态可变命令（fetch/ff/同步等）超时且回执为'未完成'而非明确失败码时，副作用可能已落地：先用廉价幂等观察（fetch 后看本地 ref/ahead 数/status）判定哪些子步骤已生效，只补做确认缺失的最小部分；观察输出顺带给出的 commit/ref 即当作'详情查询'的结果，不整条重跑、不另发独立查询。同时避免把只读查询与变更操作捆绑进同一条易超时的复合命令。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:826:d4ab33e106ac3fecbb01
evidence_refs: learning:learn:849345bcb5d2
created_at: 2026-09-19T23:44:30.851250+00:00
updated_at: 2026-09-19T23:44:30.851250+00:00
---
## Trigger
工具回执为 timeout/状态不明（无退出码或退出码未知），且该命令包含会改变仓库或系统状态的操作；或正准备把'读取详情'与'执行变更'捆绑进同一条长复合命令。

## Discriminator
回执标签是'超时/未完成'而非错误码（进程可能已完成主体副作用），且该副作用可由幂等、近乎只读的命令直接观测（如本地 main ref 是否已等于远端 merge commit、ahead 是否为 0）。

## Short path
- 收到超时回执后先不整条重跑：判断该命令是否含状态变更，其结果是否可被廉价观察。
- 跑幂等观察命令（fetch + ref/ahead/status），解决未知量：副作用落地了吗、还差哪一步。
- 若观察显示目标状态已达成（如本地 main=远端 merge commit 且 ahead=0），该步视为完成，并直接采用观察输出中的 commit/ref 作为详情结果，不再单独查询。
- 只对观察证明缺失的子步骤补做最小操作。
- 状态闭合后沿新暴露事实（如 dirty=N）单链继续排查，不回头重试旧命令。

## Stop conditions
- 观察输出证明目标状态已达成：本地 ref 与远端权威一致、ahead=0 等。
- 回执明确为失败码或对象不存在（如 'is not a working tree'）：改走失败分支，不做'已落地'假设。
- 剩余事项均为需用户拍板的决策项，无自动动作可做。

## Verification
- 用幂等观察复核最终状态：本地 ref 与远端权威一致、tracked 层 0 M/D。
- 确认每个补做动作都是观察证明缺失的最小操作；任何重跑的操作必须幂等无害。
- 最终汇报中的每个状态均来自刚才的权威观察，而非假设。

## Counterexamples
- 非幂等变更（push/force-push/删除/外发请求）超时：不能假设已落地，盲重跑可能双重生效，应先查目标端状态或使用幂等键。
- 超时根因是挂起锁（如 git index.lock）：观察只会显示卡住状态，正确动作是清锁/诊断，而非'验证已落地'。
- 纯只读查询超时：无副作用可验证，应缩小查询范围或提高预算后重试。
- 回执带明确失败退出码：属确定失败，直接按错误处理，不需要落地验证。
