---
method_id: git-content-hash-canonicalize-before-reading-41a3a7d6b702
name: git-content-hash-canonicalize-before-reading
description: 当用户给出的 basename 出现在多个 git worktree/branch/checkout 中时，先用 `git hash-object` 在副本间比较 content hash 锁定 frozen/canonical 副本，再只读那一份并独立 sha256sum 验证，避免对每个副本都打开读 + 全文比对 + 人工判断哪个是冻结版本。
status: candidate
source_model: minimax/MiniMax-M3
source_episode_refs: episode:e25ab65e-c8e1-413a-89e4-f5983daab0b3:56:71cb151c3d55713ad10b
evidence_refs: learning:learn:0911ac07c6eb
created_at: 2026-09-19T15:06:53.494825+00:00
updated_at: 2026-09-19T15:06:53.494825+00:00
---
## Trigger
用户给出文件 basename 列表（可能无完整路径），且同一 basename 出现在多个 git worktree / branch / checkout / 镜像目录中。

## Discriminator
不同 worktree 的同名文件可能因 uncommitted modification、rebase、cherry-pick 而内容不同；git 的 content-addressed storage（`git hash-object` 输出 40-char SHA-1）唯一标识内容，能在打开文件之前机械区分 frozen 副本与脏改副本。

## Short path
- 对每个用户给出的 basename，直接 `find . -name "EXACT_BASENAME"` 精确匹配，不用 wildcard pattern 试探 search_files
- 若 find 返回多个路径，对每个候选跑 `git hash-object <file>` 得到 content hash
- 在多副本间找多数一致的 hash（或与 freeze commit `git rev-parse <hash>` 指向的 tree 比对）
- 仅在出现 hash drift 的 worktree 上额外读 README/状态说明，判断是否为 intentional re-freeze（看 RESULT 文档 §3-§5 的 hash 重绑声明）
- 只打开 canonical 副本一份；其他副本的存在仅用于 hash 比较，不再读全文
- 独立 `sha256sum -a 256 <file>` 验证所读文件与冻结注册表 byte-identical 后再开始分析

## Stop conditions
- 已读到一份其 sha256 与 freeze 文档 §2 表格完全匹配的副本
- 至少 2 个 worktree 的 `git hash-object` 输出相同 ⇒ 确认 frozen；剩余 1 个不同 ⇒ 该 worktree 已脏改，跳过

## Verification
- `sha256sum -a 256 <file>` 输出与 RESULT / QUALIFICATION 文档 §2 表格逐项 byte-identical
- 在多个 worktree 上重复 `git hash-object` 一致性检查；输出一致 ⇒ frozen；不一致 ⇒ 锁定 hash 一致的工作树为 canonical
- 若 freeze 文档声明了 hash 重绑纪律，验证新 hash 在文档中有登记，否则视为漂移

## Counterexamples
- 副本都在同一 worktree 且 `git status` clean，没有跨 worktree 重复——无需 canonical resolution，直接精确 basename find 后读即可
- 用户明确指定 '读 worktree X 里的 <path>'——已限定路径，跳过 canonical resolution
- 文件是 untracked 新建（无 git object hash 可用），但用户已指明完整路径——按路径直接读，不做 hash 流程
- 用户描述的是概念性文件（如 '找 schema 文件'）而非精确 basename——wildcard + 内容搜索仍然合理
