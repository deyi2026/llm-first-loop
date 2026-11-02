---
method_id: gate-terminal-verdict-from-dedicated-status-channel-not-stale-running-0b50df22cb73
name: gate-terminal-verdict-from-dedicated-status-channel-not-stale-running
description: 带专用裁决通道（准入/审查 status 工具）的门禁型子代理在轮询期，通用生命周期工具回 child_state=running/尚未结算 不等于仍在运行：child 可能早已终态死亡而读数陈旧，父端就会'一直等'。终态裁决只认专用裁决通道的 qualification 与真实结局；且正确口径一旦在本会话确立，后续轮次不得回退到被证伪的旧通道。用户'怎么还在等/不是完成了吗'类质询的第一动作就是查权威裁决通道，并区分评审模型端无产出与产物被否决。
aliases: 子agent显示running其实早死了, 怎么一直在等 子代理早结束了, 把失败读数当成还在运行, 轮询读数陈旧没翻过来, 审查模型超时算失败还是继续等, 两个状态工具说法不一致信哪个
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:4569:ee2128b03519ef71a97a
evidence_refs: learning:learn:5a0831ad59d5
created_at: 2026-11-01T22:24:56.226056+08:00
updated_at: 2026-11-01T22:24:56.226056+08:00
---
## Trigger
轮询存在专用裁决/准入 status 工具的门禁型子代理：通用生命周期工具（child_state 类）报 running 或尚未结算、或与专用通道读数不一致；或用户质询'怎么一直在等/子代理不是完成了吗'。

## Discriminator
流程中存在专为该 gate 读真实终态与关键计数的专用 status 工具，且本会话早前轮次（同类失败）已经确立它才是正确口径——正确事实当时已暴露，后续轮次只是回退到了旧读数；落盘评审报告文件的 mtime 也是当时即可见的终态旁证。

## Short path
- 需要子代理结局时先定权威口径：有专用裁决通道就查它；child_state 只当调度提示，不当终态裁决。
- 权威回执给出终态（qualification、失败原因、关键计数）→ 立即停止等待，按失败类别分流。
- 评审模型端无产出（timeout/tokens_in=0）≠ 产物被否决：同候选重发审查，并显式锁定后续轮次只用权威通道判定，防止口径回退。
- 用落盘工件（评审报告文件的存在性、mtime、内容）交叉验证终态与时间线。
- 连续多次同为 provider 端失败 → 停止重试，作为基础设施阻塞上报并给出用户可选路径。

## Stop conditions
- 权威裁决通道已给出终态（无论通过与否），不再以任何 running 读数作为继续等待的理由。
- provider 侧失败连续复现达阈值（如 3 次）→ 终止重试循环，如实上报阻塞。

## Verification
- 向用户陈述结论前，把权威通道终态与落盘报告文件（存在性、mtime、内容）核对一致。
- 每轮轮询后自检本轮所用通道是否仍是权威口径；发现回退到旧口径立即纠正。

## Counterexamples
- 无专用裁决通道的普通异步 child：生命周期工具本身就是终态权威，本方法不适用。
- 专用通道自身报 pending/未结算：等待合法，不能把 pending 误判为失败。
- 两通道分歧但 child 确实仍在运行（竞态窗口）：以更新的物理工件（报告文件时间戳）仲裁，而非默认信报失败的一方。
- 需要失败诊断细节（错误原文、用量数据）时仍应读 child 原始终态输出；权威通道只定裁决，不替代取证原文。
