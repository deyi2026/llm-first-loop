---
method_id: ff-window-first-shared-ref-advance-25c56c2869fa
name: ff-window-first-shared-ref-advance
description: 在多 worktree 并发仓库中决定/执行把 feature 分支合入共享主干时，先用一次标量比较（merge-base vs rev-parse）判定 fast-forward 窗口是否开启；窗口开启且目标 ref 未被任何 worktree 占用时，从侧 worktree 用 git push . HEAD:main 无副作用地推进共享 ref，结构性避开被并发占用的主 worktree。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-10T00:11:19.569818+00:00
updated_at: 2026-09-10T00:11:19.569818+00:00
---
name: ff-window-first-shared-ref-advance
status: candidate
trigger:
  - 被要求决定或执行 feature 分支合入共享主干，且仓库存在多个 worktree、主 worktree 正被其他任务占用或有并发冲突史
Discriminator_Friction:
  - 最早扩散点：未先解决决策关键未知量（主干是否仍停在分叉点），就全量枚举 worktree 与主干/集成分支候选（输出百余行），随后还需多步才拼出拓扑
discriminator:
  - 标量比较即坍缩决策：git merge-base main feature 的 OID 是否等于 git rev-parse main 的 OID；相等 ⇒ 纯 fast-forward 窗口开启，零冲突面、零 merge commit
  - 目标 ref 是否未被任何 worktree checkout（worktree list --porcelain 查 branch refs/heads/main）——决定 ref 推进是否无工作区副作用
short_path:
  - 第一步只解决关键未知量：比较 rev-parse main 与 merge-base(main, feature)，判定 ff 窗口开/关
  - 第二步确认 main 未被任何 worktree checkout，且主 worktree 被其他分支占用（并发风险 ⇒ 不在主 worktree 内操作）
  - 窗口开启且 ref 空闲时，在 feature 所在侧 worktree 执行 git push . HEAD:main（push 默认 ff-only，窗口已关会被自动拒绝，是天然安全阀）
  - 验证 main 已推进、主 worktree 分支与工作区不变，即停
branch_on_evidence:
  - observation: merge-base OID == rev-parse(main) OID
    next: ff 窗口开启，走无副作用 ref 推进
  - observation: 两者不等
    next: 窗口已关，退回常规 merge/rebase 决策流程，禁止 push
  - observation: main 被某 worktree checkout
    next: 放弃 ref 推进路径，改为协调占用方或标准合并
stop_conditions:
  - main 已 ff 推进到 feature tip，且主 worktree 的分支与工作区状态与操作前一致
verification:
  - push 后 rev-parse main == feature tip；主 worktree branch --show-current 与 status 与操作前一致
anti_patterns:
  - 未先做 merge-base vs rev-parse 标量比较，就全量枚举 worktree/分支候选
  - 在被并发占用的主 worktree 里做 checkout/merge（正是历史冲突场景）
  - 对与当前决策无关的分支组合做额外 merge 预演（post-sufficiency 动作，仅当用户明确询问未来冲突面时才做）
  - 对已 complete 的目标强行补写 checkpoint——若事实已由不可变历史（reflog/提交链）承载，以历史为准收口
counterexamples:
  - main 已领先 fork 点（他人推进过主干）⇒ 非 ff，push 会被拒，需走 merge/rebase 与评审
  - 团队策略要求 merge commit、PR 或 CI 门禁 ⇒ 直接 ref 推进绕过门禁，禁用本方法
  - 单 worktree 无并发活动 ⇒ 侧 worktree 推进是不必要复杂度，常规合并即可
programizable:
  - OID 相等判断、worktree ref 占用检测、ff-only push 执行与事后验证均可脚本化
model_owned:
  - 窗口关闭后选 merge 还是 rebase、是否违背合并策略、证据何时算足够
why_shorter: 用一次标量比较把何时/如何合并的多维决策坍缩为开/关二值，并把操作约束在无副作用的 ref 推进上，跳过全量 workspace 枚举与不相关预演。
