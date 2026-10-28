---
method_id: zero-delta-push-quantify-residual-refs-then-scope-decision-e14e25e80269
name: zero-delta-push-quantify-residual-refs-then-scope-decision
description: 『push github』类请求在 preflight 即零增量（目标 ref SHA == 本地 HEAD、双向 divergence 0）时，不要直接报 done，也不要静默扩大推送范围。零增量本身是判别信号：用户预期有东西要推，但它不在具名 ref 上。此时把未知量改写为『多少工作只存在于本地』，用一两条聚合计数命令量化残余缺口（目标远端缺失的本地分支数、其中含未合入默认分支提交的分支数与提交数），连同推送范围选项交用户拍板；向远端推送具名 ref 之外的 WIP 分支属扩大授权且披露难以收回，必须等显式选择。计数优先于全量列表打印；受保护推送命令单条执行。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:1450:ae10b8640e209950c4dd
evidence_refs: learning:learn:9475a6de8bc2
created_at: 2026-10-21T20:17:47.954579+08:00
updated_at: 2026-10-21T20:17:47.954579+08:00
---
## Trigger
用户请求把仓库推送到具名远端（push github 类模糊指称），钉定远端后 preflight 显示目标 ref 与本地完全一致（SHA 相等、双向 divergence 0），请求动作将成为 no-op（Everything up-to-date）

## Discriminator
零增量事实本身：权威远端目标 ref SHA == 本地 HEAD 且 divergence 0/0。它把『用户想推什么』从『仓库任意内容』缩成『不在该 ref 上的残余本地工作（或确实无事可推）』，且该残余量可用差集计数命令一次得出，不需要先打印全量分支清单

## Short path
- 枚举 remotes 把用户指称的名字钉到具体 URL，fetch 后对目标 ref 做 ls-remote SHA 对比；若存在真实增量，走正常 gate+push+verify 后结束
- 若零增量：将未知量改写为『多少工作只存在于本地』，用一条差集计数命令统计本地 heads 中目标远端缺失的分支数，不打印全量分支列表
- 再统计其中含未合入默认分支提交的分支数与提交总数（rev-list --all --not <default> 计数），仅列最近若干未合入 tip 供决策参考
- 残余缺口≈0 → 报告『目标已同步』即止；缺口>0 → 报告具名目标已 up-to-date + 缺口数字 + 范围选项（只推具名 ref／只推含未合入提交的分支／全量镜像），等待用户选择，不自行扩大推送范围
- 用户选定范围后按闸门规则逐 ref 推送并 ls-remote 逐 SHA 复核；受保护命令一律单条执行，复合 shell 会被准入门确定性阻断

## Stop conditions
- 目标 ref 经 ls-remote 验证与本地一致，且残余缺口量化为 0：报告完成并停止
- 缺口已量化并连同范围选项提交用户：停止一切超出原请求范围的推送，直到获得显式选择

## Verification
- 推送后对每条已推 ref 做 ls-remote 逐 SHA 比对，divergence 双向为 0
- 缺口数字可独立复算：远端缺失分支数、含未合入提交分支数、仅本地提交数三条命令结果相互一致

## Counterexamples
- 目标 ref 与本地存在真实增量：直接走正常推送与核验流程，无需发起范围询问
- 用户已显式指明 ref 与范围（如『push main to origin』）：报 up-to-date 即止，枚举其他分支是噪音
- 私有备份远端且有既定『全量镜像』常设指令：范围已获授权，量化与询问均不必要
- 仓库政策规定只推默认分支：本地存在大量未推分支是常态而非异常信号
