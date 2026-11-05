---
method_id: audit-ignored-layer-before-deleting-clean-worktrees-98fe8cfb5c2e
name: audit-ignored-layer-before-deleting-clean-worktrees
description: 当工作树/快照树的『可删』判定只来自 status 干净（+已合入/无独立提交）时，这只是 tracked 层谓词：整目录删除会把 ignored 层一并抹掉。用一条聚合 git status --ignored 暴露每棵树的 ignored 清单与体积，分桶『可再生缓存』(__pycache__/node_modules)与『不可再生运行数据』(audit/observability/e2e/日志/状态文件)，再区分软链指向主树 vs 真目录；对不可再生的真目录先 tar 归档并校验条目数>0 才动手。本集 44 棵『干净』树每棵约 100 个 ignored 条目、审计/e2e/观测数据合计 92MB，且全是真目录非软链。
aliases: 删 worktree 前要检查 ignored 文件吗, status 干净不等于能安全删, 工作树清理前先归档运行数据, 删树会不会丢审计日志, 整目录删除前看被 gitignore 的数据
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:576:84e2711c8750eab9b119
evidence_refs: learning:learn:d5a677d5c49e
created_at: 2026-11-05T16:36:48.959109+08:00
updated_at: 2026-11-05T16:36:48.959109+08:00
---
## Trigger
准备成批删除 git worktree / 快照目录，且每棵的删除依据主要是 status clean（配合 merged/ahead=0），删除方式是整目录移除（worktree remove / prune / rm）

## Discriminator
status clean 是 tracked 文件谓词，对 ignored 层不可见；对每棵候选跑一次聚合 status --ignored --porcelain 即暴露 ignored 条目与体积：若出现不可再生的运行数据目录（如 data/audit、observability、e2e、日志），且这些目录是 REALDIR 而非指向主树的软链，则『干净=可安全删』不成立

## Short path
- 删除集按 clean/ahead 分类定出后，先对每棵候选跑一条聚合 status --ignored 脚本，统计 ignored 条目数与体积
- 把 ignored 明细分桶：可再生缓存（__pycache__、node_modules、.pytest_cache 等）vs 不可再生运行数据（audit/e2e/observability/日志/状态文件）
- 对不可再生数据目录做软链 vs 真目录判定：软链指向主树则该树无独有内容可跳过，REALDIR 才需要处理
- 把含不可再生 REALDIR 数据的树先 tar 归档到备份目录，逐包校验条目数>0、体积非平凡，全部通过后才执行删除
- 删除后验证：路径零残留、worktree 注册数与执行数一致、依赖这些目录的工具（如方法索引）解析计数不降

## Stop conditions
- 某棵树的 ignored 层只有可再生缓存且无不可再生真目录 → 免归档直接删
- 所有含不可再生数据的树均完成条目数>0 的 tar 归档校验 → 归档环节停止，进入删除
- 删除后注册数、路径残留、依赖工具计数三项验证通过 → 整个流程停止

## Verification
- 每份归档 tar 经列表核验条目数>0（本集 21 棵有数据、共 8.2M，23 棵确认无数据目录）
- 删除后 worktree 注册数变动与执行数一致（270→222）、被删路径零残留
- 依赖被删目录的工具输出不降（本集 krate 索引仍解析 1856 条方法、13 条种子完好）

## Counterexamples
- ignored 层只有 __pycache__/node_modules/.ruff_cache 等可再生缓存 → 无需归档，直接删
- 树内 data/ 是指向主树的软链 → 树里没有独有数据，删树不丢数据，归档属浪费
- 删除操作只针对 tracked 文件（如不带 -x 的 git clean，保留 ignored）→ ignored 层不会被破坏，本方法不适用
- 目标是 CI 可从脚本重建的临时沙箱 → 一切运行数据可再生，无需归档
