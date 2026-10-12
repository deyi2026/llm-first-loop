---
method_id: query-by-known-id-before-collection-enumeration-cc2b1d3511b9
name: query-by-known-id-before-collection-enumeration
description: 把已知唯一标识当作第一查询键：当链头 commit id 等标识已可在上下文中直接使用时，先用 containment/ownership 精确查询（如 git branch --contains <id>、git merge-base）定位对象与分叉点，而不是枚举整个集合并扫描。rebase 合入前先做两侧变更路径交集预测冲突、确认新路径在 main 不存在、核对 CI 门禁与环境跳过条件（平台 skipif、gitignore 依赖、pytest pythonpath），再在干净 worktree rebase 并复跑等价门禁。另：复合 shell 命令含进程替换等 bashism 时，从一开始就用 bash -c 包装。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:18:28bdc68d0c5a2dd361cb
evidence_refs: learning:learn:c21b4cc7e62f
created_at: 2026-09-19T11:05:55.244763+00:00
updated_at: 2026-09-19T11:05:55.244763+00:00
---
## Trigger
需要定位/集成一个已有唯一标识（commit hash、路径、错误签名）指向的对象，而下一候选动作是枚举全部分支/文件再人工扫描；典型场景：把旧提交链 rebase 到已前进的 main 并验证门禁。

## Discriminator
标识符当时已可直接使用：本例中链头 hash 在枚举分支之前就已可被无中间发现步骤地使用（下一步命令直接引用它），证明 knowledge-at-time 成立——该事实把'哪个分支持有链、落后多少'从全分支枚举缩为一条 --contains + merge-base 查询。

## Short path
- 已知链头 id → `git branch -a --contains <id>` + `git merge-base main <id>` + ahead/behind，一次解析链归属与落后量（替代全分支枚举）。
- 用 merge-base 与链头做两侧 `git diff --name-only` 并求交集 → 得出文本冲突风险分类（空交集≈纯增量，冲突概率极低）。
- `git ls-tree main -- <链核心新路径>` 确认 main 无同名模块；读 CI workflow 确认门禁构成（pytest marker、ruff、pyright）与触发事件。
- 检查环境门控事实：平台分支（非 Darwin 抛错但测试有 skipif 门控）、node_modules 被 gitignore、pytest pythonpath 相对 rootdir → 判定新 worktree 本地门禁可行性。
- 新 worktree 建集成分支并 rebase 到 main；用 `git log --oneline main..<新头>` 核对 commit 数与消息序列守恒。
- 本地复跑与 CI 等价的门禁；绿则按仓库约定 push/PR/合入；出现冲突或不可跳过的环境依赖即停。

## Stop conditions
- rebase 干净完成（commit 数守恒）且本地等价门禁全绿，并已按仓库约定合入。
- 路径交集非空或 rebase 出现冲突：停止批量推进，逐文件处理或上报人工。
- 发现目标 CI 环境会不可跳过地依赖本地-only 资源（Seatbelt 沙箱、密钥、未安装的 pinned 依赖）：暂停等人工决策。

## Verification
- `--contains` 返回的分支名与链头 id 互相印证；ahead/behind 与 merge-base 数值自洽。
- 交集计算用两侧 sorted name-only 列表复核一遍，确认 diff 范围写法正确（三点 vs 两点范围）。
- rebase 后新链的 commit 数与提交消息序列和原链一一对应。
- 本地门禁命令与 CI workflow 步骤逐项对齐（同一 pytest marker 过滤、ruff/pyright 范围一致）。

## Counterexamples
- 只有语义描述、无任何唯一标识（如'上周那条功能链'）时，按 committerdate 枚举分支正是正确入口，本方法不适用。
- 空路径交集只排除文本冲突：main 可能重命名/重构了链所 import 的模块或配置，语义冲突仍需门禁兜底，不能据此跳过验证直接合入。
- 仓库约定必须走 PR 评审或禁止直推 main 时，本地门禁绿不构成直接合入条件。
- 已知 id 已失效（链被他人重写，旧 hash 不属于任何现存分支）：`--contains` 返回空，应回退到枚举或向用户确认，而不是继续沿该 id 推进。
