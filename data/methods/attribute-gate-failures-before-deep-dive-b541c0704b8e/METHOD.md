---
method_id: attribute-gate-failures-before-deep-dive-b541c0704b8e
name: attribute-gate-failures-before-deep-dive
description: 当作为提交门禁的验证运行（全量测试等）报失败时，先用两个机械可查的事实归因——失败工件与改动文件集的路径重叠、运行 workdir/分支与改动所在 worktree 是否一致——再决定是否深挖失败内部；改动位于独立 worktree 时，门禁运行必须在该 worktree 内启动或重跑。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:4d6c551c-a50d-4ef1-90cf-b0af9f557745
created_at: 2026-09-09T23:21:34.060845+00:00
updated_at: 2026-09-09T23:21:34.060845+00:00
---
trigger:
  - 作为 commit/merge 门禁的后台验证运行（全量测试/构建/lint）报告失败
  - 本次改动有明确文件清单，且位于独立 worktree/分支/checkout（其路径在既往命令中已出现）
  - 或：即将启动门禁级验证，而默认 cwd 与改动所在树可能不一致
discriminator:
  - 失败测试/工件路径与改动文件清单是否有交集（零重叠⇒改动几乎不可能直接致败）
  - 验证运行的 workdir/分支是否等于改动所在 worktree/分支（不一致⇒该运行对本次改动不构成有效门禁）
  - 仓库是否已有已知红登记（known-reds 文档、近期 commit message 提及）
short_path:
  - 失败到达时先做集合比较：失败节点 ∩ 改动文件清单，解决'我的改动可能致败吗'
  - 再核对运行环境：job workdir/当前分支 vs 改动 worktree/分支，解决'这次运行见过我的改动吗'
  - 若零重叠或环境错位：不深挖 traceback；查一次已知红登记/基线复现，确认存量属性
  - 在改动所在 worktree 内重跑门禁（deselect 已登记存量红）
  - 正确树内全绿即进入提交流程并停止归因
branch_on_evidence:
  - observation: 失败与改动零重叠 且 运行树=改动树
    next: 查登记确认存量红后 deselect，门禁照常；未登记则在基线 commit 复现一次确认预存
  - observation: 运行 workdir/分支 ≠ 改动所在 worktree
    next: 判定该运行为无效门禁，不解读其失败细节，直接在改动树内重跑
  - observation: 失败与改动有路径重叠或疑似共享 fixture/import 因果
    next: 才进入常规深挖（-x、traceback、最小复现）
stop_conditions:
  - 改动所在树内门禁全绿（已排除登记预存红），或失败已在不含改动的基线复现为预存
  - 出现与改动有真实因果链的新失败，转入正常调试流程
verification:
  - 失败节点 ∩ 改动文件 = ∅；重跑时 workdir 与分支正确且改动文件全部在位
  - 存量红能在不含本次改动的基线复现或已有登记条目
anti_patterns:
  - 在不包含本次改动的树里对失败测试跑 -x 深挖、逐条读 traceback
  - 把另一分支/主仓的全量运行结果当作本次 feature 的提交门禁
  - 在默认 cwd 启动门禁级验证而不核对改动所在 worktree
programizable:
  - 失败节点集合 vs git diff --name-only 改动集的交集计算
  - 后台 job workdir/branch 与改动 worktree 路径的等值校验
  - known-reds 登记/registry 的一次 grep 查证
model_owned:
  - 判断零路径重叠之外是否存在共享 fixture/导入等隐性因果
  - 判断存量红证据（登记或基线复现）是否足以豁免调查
why_shorter: 用两个已存在的机械事实（重叠=∅、运行树错位）先行归因，避免在错误树里深挖不可能由本次改动引起的失败，并把无效门禁运行替换为正确树内的一次重跑。
