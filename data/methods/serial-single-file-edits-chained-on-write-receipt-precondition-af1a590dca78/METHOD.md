---
method_id: serial-single-file-edits-chained-on-write-receipt-precondition-af1a590dca78
name: serial-single-file-edits-chained-on-write-receipt-precondition
description: 对同一受版本前提保护（expected_snapshot_ref/sha256 校验）的可变文件做多处独立编辑时，不要基于同一快照并行发多个写请求：任一成功写入都会改变文件字节，使同批其它请求的前提失效（版本冲突）；凭记忆重构的 old_string 也易因缩进/属性差异 0 匹配。改为串行链式执行——old_string 只从最近一次权威读取/回执中逐字复制，每次成功写入后直接用回执返回的新 artifact ref 作为下一次编辑的 expected_snapshot_ref；编辑区域不重叠时无需整文件重读，冲突后只需窄范围重读目标区域。本集 5 次工具失败（2 次 old_string 不匹配、3 次版本冲突）全部由并行批写+记忆重构产生，串行链式可全部消除。
aliases: old_string 差个缩进就匹配不上, 同一文件多处改动排队改, 失败后只重读那段区域, sha256 校验的前提写串行, 第二处就写不进去
status: candidate
source_model: minimax/MiniMax-M3
source_episode_refs: episode:ae5b131c-d837-4549-8a3b-9f8d7168745d:65:6f871509d1ac5831ae2b
evidence_refs: learning:learn:bfa81f13b7ab
created_at: 2026-10-17T17:16:56.277049+08:00
updated_at: 2026-10-23T05:53:14.667019+08:00
---
## Trigger
准备对同一个带乐观并发前提的文件（file_contract / snapshot_ref / sha256 校验）执行 2 处以上独立编辑，且手上已有该文件某版本的读取快照

## Discriminator
每次写回执都已显式返回新的 artifact ref + sha256（identity=immutable_snapshot），且每次调用要求 expected_snapshot_ref 等于当前文件字节——这证明同一文件的多个写互为版本前提、不能共享一个快照并行；同时 read_file 输出中已含目标行逐字文本，old_string 应复制而非凭记忆重构

## Short path
- 读取文件（可分段、跳过重复区域）确定全部修改点，记录每个目标区域的逐字文本
- 逐个串行执行编辑：old_string 逐字复制自最近读取/回执；不确定时可先 dry_run 验证匹配
- 每次成功写入后，用该回执返回的 artifact ref 作为下一次编辑的 expected_snapshot_ref；区域不重叠时不必重读整文件
- old_string 0 匹配时只重读目标区域取逐字文本，重试一次；版本冲突时用上次成功回执的 ref 重发
- 全部改动回执确认（替换处数与预期一致）后停止，可做一次结构/渲染终检

## Stop conditions
- 全部计划编辑的回执均确认成功且替换处数与预期一致
- 精确重读后 old_string 仍无法匹配 → 停止重试，向用户报告该区域原文
- 前提持续冲突且无己方中间写入 → 停止并重新读取评估并发写者

## Verification
- 每次成功回执的 expected_snapshot_ref 等于上一次成功写入返回的 artifact ref
- 各 diff 的替换处数与该编辑预期一致（如双踏板应为 2 处，opacity 不同的元素须分开处理）
- 最终文件行数/大小增量与已应用改动累计一致

## Counterexamples
- 编辑工具提供多 hunk 原子事务时，在单次调用内批量即可，无需拆成串行多次写
- 多个编辑目标分布在不同文件：前提按文件隔离，可安全并行
- 无版本前提的追加型写入（如 cat >>）顺序无关，不必串行
- 后续编辑的 old_string 依赖前一次改动产生的新文本：必须在前次成功后重读该区域，仅沿用回执 ref 不够
