---
method_id: attribute-and-reuse-in-flight-validation-via-scheduler-record-2e1f5c1ceba3
name: attribute-and-reuse-in-flight-validation-via-scheduler-record
description: 在跑的重型验证（全量回归/扫描）归属不明、甚至被口头状态误归为“对方会话”时，不要接受口头归属去猜测或另起一轮重复的昂贵验证；用调度器/runner 的持久 job 记录（job id、完整命令行、起跑时间、exit code）一跳定归属与覆盖，并在其 done 后直接取最终回执作权威仲裁。覆盖判定只看记录可查事实：起跑时间晚于两套改动落盘、scope 为超集（tests/ ⊇ tests/unit）即构成合并仲裁，本集由此省掉一次 300s 级重复回归。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:419:ada80e841e958e78bb2b
evidence_refs: learning:learn:0bf4a356d61a
created_at: 2026-10-07T11:39:18.427579+08:00
updated_at: 2026-10-07T11:39:18.427579+08:00
---
## Trigger
环境中存在在跑的重型验证/回归进程，其启动者或覆盖范围不确定（口头状态报告称‘不是我启动的/大概是别人的’），且合并或终局裁决正等待一个权威全量结果时。

## Discriminator
调度器存在持久 job 记录且命令行与描述进程逐字匹配（pytest tests/ -q -x --ignore=tests/perf，job-e799f3a4d4124c93908a，exit=0，7529 passed）：字符串匹配定归属，起跑时间(9:09)晚于两套改动落盘 + scope 超集定其结果可仲裁——均为当时可查的记录事实，而非会话记忆或口头归属。

## Short path
- 明确未知量：在跑回归是谁启动的？其结果能否作合并权威仲裁？
- 按命令行+起跑时间查调度器 job 记录，找到匹配 job id，不采信'大概是对方的'这类口头归属
- 只 poll 该 job 至 done，取最终回执（exit code、pass/skip 计数）
- 回执确认覆盖（时间顺序 + scope 超集）→ 直接用它作合并仲裁并停止，不另起重复回归

## Stop conditions
- 已取得该 job 最终回执：exit=0 且计数可读，归属与覆盖由记录确立，仲裁完成
- 回执显示该 run 不覆盖当前 delta（起跑早于改动落盘或 scope 不含目标面）→ 才启动自己最小范围的验证

## Verification
- 回执命令行与描述进程字符串一致；比对回执起跑时间与各改动落盘先后顺序
- 读取 exit 语义而非只看 job 状态：-x fail-fast 下 'job done' 不等于全绿，必须读到 pass/skip 计数
- 归属结论表述为'调度器记录显示'而非'我记得'

## Counterexamples
- 进程无调度器记录（对方在 job 体系外 ad hoc 跑的裸 PID）→ 无法定归属也无法取回执，只能协调或自己跑
- 在跑 run 早于你的改动落盘或 scope 不含目标面 → 其绿不构成你的仲裁，复用即伪验证
- 验证本身秒级便宜 → 重复跑比查归属+等待回执更省，方法不适用
- 回执显示被 -x 提前中止或失败 → 只证明某点红，不构成全量仲裁，仍需补跑
