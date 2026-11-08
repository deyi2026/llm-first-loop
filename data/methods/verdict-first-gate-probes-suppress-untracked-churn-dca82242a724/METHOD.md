---
method_id: verdict-first-gate-probes-suppress-untracked-churn-dca82242a724
name: verdict-first-gate-probes-suppress-untracked-churn
description: 任务书以封闭清单列出放行前必须核验的身份/布尔事实（分支、worktree、HEAD SHA、clean、队列空闲），且核验靠一条只读 shell 探针完成时，把探针输出塑造成判定行优先：每个期望值先比对再回显 OK/FAIL（HEAD_OK、ANCESTOR_OK、WORKTREE_CLEAN 等），tracked 变更只报计数，untracked 噪声压成计数或路径族，决定性行放最前。原因：仓库充满 untracked 运行产物时，原始 git status 全列表会把提交信息、ancestor 判定等闸门事实挤进截断省略区，迫使追加 evidence 恢复轮；且恢复窗口若未锚定关键标记行，仍可能拿不到事实就宣布通过。放行（lane_open/发布类登记）只依据回执里逐项可见的判定行，不依据'没看到失败'。
aliases: 核验命令输出被截断关键信息, git status 太多 untracked 把结论顶没了, 放行前检查先打判定行, 闸门核验探针输出塑形, 回执截断恢复要定位关键行, 只读核验首屏就要见结论
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:94:ff56e0d0a18a492b4631
evidence_refs: learning:learn:7209899b8741
created_at: 2026-11-07T15:51:23.115259+08:00
updated_at: 2026-11-07T15:51:23.115259+08:00
---
## Trigger
封闭清单式放行核验：任务书枚举有限个身份/布尔事实（branch/worktree/HEAD/clean/队列），全部满足才允许一次状态改变型登记调用；核验由单条只读 shell 命令完成，而仓库存在大量与任务无关的 untracked 运行产物

## Discriminator
放行判定只需要清单上那几个原子事实，而拟用探针（如含 untracked 的完整 git status）会把无界噪声列表放在决定性行之前——这一点在组织命令时即可从任务书的封闭字段清单预判，不必等截断发生

## Short path
- 并行发起互不依赖的只读步骤（get_goal / 队列状态），照常互不阻塞
- 把 git 核验探针塑造成判定行优先：期望 SHA/分支先比较再回显 HEAD_OK/BRANCH_OK；git status --porcelain -uno 只报 tracked 计数；worktree 空输出即 CLEAN_OK；git log -1 --format=%s 与 git merge-base --is-ancestor && echo ANCESTOR_OK 各占一行；untracked 只报计数或路径族，不逐行列举
- 首屏逐项比对判定行：全部 OK 才进入登记调用（lane_open），任一 FAIL/缺失即停
- 若截断已发生：恢复窗口必须锚定关键标记行（提交主题/ANCESTOR_OK/worktree 段），且恢复正文确认包含每个闸门事实后才可宣布通过，不得以首个省略偏移窗口顶替
- 登记成功后按任务书 checkpoint 并停在边界

## Stop conditions
- 任务书枚举的每个事实都以显式判定行出现在回执中且与期望值一致
- 任一判定行 FAIL 或缺失即停止报告，不进入登记调用
- 登记与 checkpoint 完成后立即停止，不派生相邻工作

## Verification
- 回执首屏包含每个被枚举字段的期望-实际比对（OK/FAIL），无一项靠'未见异常'推断
- 若走了恢复路径：能在恢复正文中指认该闸门事实的具体行，而非仅恢复了一个偏移区间
- 登记回执回显的 branch/HEAD/goal/paths 与判定行所用期望值逐项一致

## Counterexamples
- 收编/抢救在途工作类任务：untracked 清单本身就是决策面（inventory-driven salvage），过滤 untracked 会丢掉必需事实，必须完整列举
- 任务书对 clean 的定义严格包含 untracked 文件时，不能把 untracked 压成计数了事，必须显示为 0 或列出请示
- 探索式诊断尚不确定哪些字段是闸门时，无法预塑判定行，先原始列举再收敛是合理的
- 输出体量小且无截断风险的环境（字段级 API 回执），塑形收益趋零，按工具原生回执裁决即可
