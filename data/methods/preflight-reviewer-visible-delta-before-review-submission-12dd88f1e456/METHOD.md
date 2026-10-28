---
method_id: preflight-reviewer-visible-delta-before-review-submission-12dd88f1e456
name: preflight-reviewer-visible-delta-before-review-submission
description: 把本地提交交给以 diff 为审查范围的自动评审门禁前，先本地复现评审器将冻结的 delta（如 merge-base HEAD main...HEAD --stat）。若本次提交直接落在基准分支上，merge-base==HEAD，评审器看到的必然是空产物——此时先修分支拓扑（提交移到侧分支、基准回退到改动前），不要基于空 delta 上的 verdict 去改内容；空 delta 上的 REVISE/PASS 都不构成对变更本身的有效反馈。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:1534:b59da648b6a5b2e8040d
evidence_refs: learning:learn:91edc86b20ef
created_at: 2026-10-18T11:34:22.579268+08:00
updated_at: 2026-10-18T11:34:22.579268+08:00
---
## Trigger
准备将本地已提交的变更送自动评审，且评审器按某个基准 ref（如 merge-base HEAD main）计算审查范围，而本次提交恰好直接提交在该基准分支上（HEAD 与基准 tip 重合）

## Discriminator
提交前可机械判定：git merge-base HEAD <base> 是否等于 HEAD——相等则评审 delta 恒为空，问题在拓扑而非内容；或首轮回执中评审器自注 delta 为空（P2 注记）而本地明知改动了数十文件，同样把候选从『内容不合格』缩到『评审基准失效』

## Short path
- 送审前先确认评审器如何冻结范围：基准 ref、commit 区间还是 patch 文件
- 本地复现该 delta：git diff $(git merge-base HEAD <base>)...HEAD --stat，核对文件数与 +/- 行数是否等于本次意图改动
- 若 delta 为空或明显偏短而提交确实存在：只修拓扑——把提交移到侧分支、基准 ref 回退到改动前；不根据该轮 verdict 修改代码
- 重新冻结 delta，与意图范围逐项一致后才再次送审，并作废旧 verdict
- 评审通过后把基准 ref 快进回被审头提交，恢复原拓扑

## Stop conditions
- 评审回执引用的具体文件/行数与本地复现的 delta 统计一致，verdict 基于真实 diff
- delta 已非空且评审仍指出问题——此时才进入内容修复循环

## Verification
- 送审前确认 git merge-base HEAD <base> 与 HEAD 不同，且 diff --stat 覆盖本次全部改动文件
- 回执中的发现落在该 delta 内，而非空产物上的泛化结论

## Counterexamples
- 评审器直接接收显式 commit 列表或 patch 文件——无需分支拓扑，只需核对 patch 内容本身
- 评审对象是未提交的工作区——merge-base 机制不参与，此法不适用
- 基准分支共享/受保护不能回退——应从一开始就在特性分支工作，而不是事后搬提交
- 评审输出结构完整但零发现且无 delta 注记——那是评审器退化输出（另一故障类，另有方法处理），不是拓扑问题
- merge-base 已不等于 HEAD 而评审仍失败——是内容反馈，照常修复，不要动拓扑
