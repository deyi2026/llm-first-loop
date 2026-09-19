---
method_id: bind-tree-reading-gates-to-artifact-ref-worktree-ece00051f244
name: bind-tree-reading-gates-to-artifact-ref-worktree
description: 多分支/linked-worktree 仓库中，凡以当前工作树为输入的门禁或校验脚本，运行前先绑定执行上下文到 artifact 的归属 ref：状态核查若已显示『artifact 只提交在某分支的树中，而当前 cwd 在另一分支』，则在当前 cwd 运行只会得到 'working tree 找不到文件' 类伪 FAIL。同一原则覆盖两点延伸：引用既有产物（如后台测试日志）前先确认生产 job 的终态；在 worktree 内跑测试时警惕宿主 shell 环境变量渗漏造成伪红。核心判断：失败若源于上下文错配（错 ref、无终态产物、污染环境），先修上下文再信结论，不要把伪失败当成真实信号去逐个诊断。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:306:070f96ff2440913a57d7
evidence_refs: learning:learn:06f892a91a2c
created_at: 2026-09-19T02:08:03.414004+00:00
updated_at: 2026-09-19T02:08:03.414004+00:00
---
## Trigger
准备运行一个会读取工作树的门禁/校验/测试，而目标 artifact（manifest、提交物、diff）只存在于某个特定分支或 commit 的树中；或准备引用一个由后台 job 产生的日志/报告；且仓库存在多分支并行或 linked worktrees。

## Discriminator
状态核查输出中已同时存在两个可观察事实：① 目标 artifact 仅在分支 X 的树中存在（如对该分支 tip 的 git show --stat 可见新增文件）；② 当前分支 ≠ X，且校验脚本的失败模式是『working tree 中找不到文件』。这两个事实在运行前就足以判定：在当前 cwd 运行必然伪 FAIL，必须先定位/创建分支 X 的 checkout。

## Short path
- 从已有状态输出对齐两个事实：artifact 的归属 ref 与当前分支；若不一致且脚本读工作树，禁止直接在 cwd 运行
- git worktree list 定位（缺失则创建）归属 ref 的 checkout，把命令 cwd 绑定到该 worktree
- 在该 worktree 内以显式 --base/--head 运行门禁，取得该 ref 的权威 PASS/FAIL
- 若在正确 worktree 内仍失败，视为真实信号，按门禁自身错误文本定位根因，而不是换位置重跑
- 引用后台 job 产物前先查其终态：仅 terminal-success 且日志含最终统计行才可引用；否则重跑于正确上下文或转交权威 CI 复跑，不阻塞已授权的推进动作

## Stop conditions
- 已在 artifact 归属 ref 的 worktree 内取得门禁 verdict，且与该 ref 提交内容一致
- 门禁脚本接受显式 ref 参数并直接读 git 对象、不依赖 cwd 工作树时，无需 worktree 绑定
- 对产物引用：生产 job 处于 terminal 成功态且产物含最终结论行，否则不引用

## Verification
- 在正确 worktree 复跑同一门禁，确认原先 'not found' 类失败消失、verdict 变为有意义
- 记录运行时的 git branch --show-current（或 worktree 路径）作为 verdict 的上下文 provenance
- 对被引用产物：job 状态查询结果为 terminal success 且日志存在 summary/统计行；环境敏感测试在清理渗漏变量后复跑通过

## Counterexamples
- 门禁通过显式 --base/--head 直接读 git 对象、不依赖 cwd——在任何位置运行都有效，绑定 worktree 是多余步骤
- 当前分支已包含目标 artifact（单分支变更）——直接在 cwd 运行即正确，套用此法反而增加往返
- 不存在可用 worktree 且创建成本高于校验本身——应改用 git show ref:path 式对象级验证或临时 checkout，而非强行建 worktree
- 命令因 shell 包装层破坏 heredoc/引号而失败——那是传输层问题，应换写入方式（printf/文件），与本方法的 ref/上下文绑定判断无关
