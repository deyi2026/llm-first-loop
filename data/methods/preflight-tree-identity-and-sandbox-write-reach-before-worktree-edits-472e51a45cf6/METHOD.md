---
method_id: preflight-tree-identity-and-sandbox-write-reach-before-worktree-edits-472e51a45cf6
name: preflight-tree-identity-and-sandbox-write-reach-before-worktree-edits
description: 在带沙箱写限制的多工作树仓库里做 lane/分支修复，开工第一个未知量不是改什么，而是『我的编辑会落在哪棵树、这个 cwd 能否完成 git 写』。开工前通常已同时具备两个判别事实：lane 账本表明工作应在专属 worktree 进行（而当前 cwd 是主树），且每条命令回执都印着沙箱写作用域。首次编辑前用 git rev-parse --show-toplevel / git worktree list 核对树身份，再用一次廉价 git 写探针（stash create→drop 或 add --dry-run）测 worktree 的元数据写是否放行；被拒则预先定型『编辑与提交分离』拓扑：补丁任意处生成、提交一律从沙箱允许的主 cwd 执行。不靠第一次 git 写失败才发现拓扑，被拒后也不在原层反复重试。
aliases: 改错工作树怎么提前发现, worktree 里 commit 被沙箱拦, index.lock Operation not permitted git, 动手前先探沙箱写权限, 先确认编辑落在哪棵树, lane 树上 git 写不进去
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:2452:6012c2b9189da1e69fc4
evidence_refs: learning:learn:89a438c53527
created_at: 2026-11-10T23:43:21.311098+08:00
updated_at: 2026-11-10T23:43:21.311098+08:00
---
## Trigger
沙箱化仓库中执行 lane/分支修改任务，且可见环境线索表明存在多棵 git 工作树（state 卡或 lane 账本提及分支/lane worktree、回执 cwd 指向另一棵树），即将进行首次内容编辑或 git 写操作。

## Discriminator
编辑前已可见的两条事实：①每条命令回执都标注沙箱写作用域（仅允许写工作区与缓存目录）；②已核实事实/lane 账本表明本次工作有专属 worktree，而当前 cwd 位于主树。二者合起来即证明『编辑落点』与『git 写可达性』都是未验证前提，且可用两条廉价命令在动手前收敛。

## Short path
- 从 state/lane 账本读出本 lane 的 worktree 路径；未知量：编辑应落在哪棵树。
- 在拟编辑 cwd 执行 git rev-parse --show-toplevel 与 git worktree list 核对树身份；未知量：当前编辑目标是否就是 lane 树。
- 在 worktree 做一次廉价 git 写探针（git stash create 后立即 drop，或 git add --dry-run，失败再 touch+rm 试 .git 元数据路径）；未知量：沙箱是否放行该处的 git 元数据写。
- 探针被拒 → 直接定型分离拓扑：内容编辑/补丁在任意可写处生成，一切 commit 从沙箱允许的主 cwd 执行，不再在 worktree 内尝试 stash/add/commit。
- 按 state 已给出的 file:line 直改目标文件，进入原有验证与合并管线。

## Stop conditions
- 树身份与 lane 期望一致且写探针通过：按普通流程直接在 worktree 内编辑提交。
- 治理流程已明文规定提交位置（如补丁一律在主 cwd 提交）：拓扑已由政策决定，只核对树身份即可。
- 任务为只读（审查/裁决/检索）：无写拓扑可钉，跳过 preflight。

## Verification
- 首个编辑落地后，分别在主树与 lane 树各跑一次 git status --porcelain，确认改动只出现在预期树。
- 首次 commit 后在两树各查 git log -1 --oneline，确认提交落在预期分支与树。

## Counterexamples
- 单工作树、无沙箱的普通仓库：preflight 是纯开销，直接编辑。
- 流程政策已固定『编辑与提交均在主 cwd』：写拓扑无需探测，探测反而是绕流程信号。
- 沙箱对整个工作区（含 worktree 与 .git 元数据）全放行：写探针必绿，只有树身份核对这一步有价值。
