---
method_id: chain-write-receipt-ref-for-same-file-edits-f8272f8a4618
name: chain-write-receipt-ref-for-same-file-edits
description: 在带乐观并发校验的文件契约下（写入需 expected_snapshot_ref 前置匹配），每次成功写入的回执本身就返回了该文件的新 snapshot_ref/sha256，它就是下一次同文件写入应使用的版本 token。对同一文件连续多次 edit 时应串行下发并逐次接力回执 ref，而不是让多个 edit 共用编辑前的 read 快照 ref（除第一个外必然版本冲突），也不必在无冲突信号时插入额外重读。只有当链式 ref 仍被拒（外部写者介入）或无先前回执时，才回退到重读快照。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:473:f2cec58e6b084806178b
evidence_refs: learning:learn:19afb839b9c3
created_at: 2026-10-06T01:38:41.623346+08:00
updated_at: 2026-10-06T01:38:41.623346+08:00
---
## Trigger
需要对同一契约管控文件连续执行多次原子编辑（写前有 expected_snapshot_ref 校验），且上一次对该文件的成功写入回执已返回新 snapshot_ref/sha256。

## Discriminator
最近一次成功写入回执已显式给出该文件的新 ref/sha256（本集：标题 edit 回执 ref=072d0499…/sha256=e1646bcc…），此事实在后续 edit 之前就已可见；任何沿用编辑前 read 快照 ref 的同文件 edit 必然冲突，无需试错验证。

## Short path
- 首次接触文件：read 取快照 ref，仅作为第一次写的前置。
- 每次成功写入后，立即把回执返回的 ref/sha256 记为该文件当前版本 token。
- 下一次同文件 edit 直接以该 token 为 expected_snapshot_ref，串行提交剩余 hunk；不重用旧 read ref，不并行下发多个同文件 edit。
- 仅当链上 ref 仍报版本冲突（外部写者介入）时才重读最新快照、重建链后继续。
- 全部 hunk 落盘且末次回执 sha256 与预期一致 → 停止，不再读该文件。

## Stop conditions
- 剩余 hunk 全部写入成功，末次回执 sha256 即文件最新版本，任务该环节结束。
- 按回执链传入的 ref 仍被拒 → 判定存在外部并发写者，切换为重读权威快照（另一方法管辖），不再重试旧 ref。

## Verification
- 编辑序列中版本冲突错误数 = 0，且每个 edit 的 expected_snapshot_ref 等于前一次成功写入回执的 ref。
- 最终文件 sha256 与末次写入回执一致（本集反事实：三次 edit 零冲突，终态 b33df6e1… 与 §10 回执一致）。

## Counterexamples
- 写入被拒且失败并非由本人上一笔写入引起（其他会话/进程改了文件）：不能盲接旧链，必须重读最新快照。
- 首次写一个从未读过、无任何回执的文件：无链可接，先 read 取 ref。
- 同时编辑多个不同文件：各文件版本链相互独立，不得跨文件复用 ref。
- 契约要求整文件相对同一已审阅快照单次原子替换时：应合并为一次 edit，而非链式多次写入制造中间态。
