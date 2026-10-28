---
method_id: set-diff-zero-loss-proof-for-mass-deletion-audit-669ac2cef578
name: set-diff-zero-loss-proof-for-mass-deletion-audit
description: 审计大规模破坏性清理（批量删分支/refs）是否丢内容时，把『逐项是否被覆盖』的遍历换成整集重建差分：在 scratch 空间恢复基线+全部备份（mirror-clone、unbundle），用对象可达性计数差（如悬空提交 1758→21）一次性证明整类覆盖，仅对差分后的残集逐条判定。信任聚合工具输出前必须核对输出基数=输入基数：超时静默只处理 1/N、或按猜测格式解析得到空结果集，都会产生假阴性/假未覆盖结论。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:1941:3cf41de9f473efce7dcb
evidence_refs: learning:learn:6071181ed127
created_at: 2026-10-21T22:56:47.607301+08:00
updated_at: 2026-10-21T22:56:47.607301+08:00
---
## Trigger
已执行批量删除类清理后需证明零内容丢失；被删对象类基数大（数百上千提交/对象），存在备份工件（bundle/归档/快照）但覆盖面未知；或逐条判定工具在大批量输入下超时、静默只处理部分输入

## Discriminator
当前仓 fsck/对象清单已给出该类对象总数（基数已知），备份 bundle 已通过 verify；且逐条判定工具返回条数与输入条数不符（N 条输入只出 1 条结果）——输出基数不匹配本身就是结论不可信的即时信号，应先怀疑静默截断或解析格式错误，而不是采信『未覆盖』读数

## Short path
- 未知量=被删类对象是否全部被 main∪备份覆盖：先取当前仓 fsck 悬空对象计数作基线，类别基数即已知
- 在 scratch 空间 mirror-clone → unbundle 全部备份 → 再 fsck；悬空计数大幅下降即整类覆盖的单次可测证据（覆盖证明不依赖逐条遍历）
- 仅对差分残集（小基数）逐条判定归属（如逐条 cherry/patch-id 判是否已在基线），每条记录处置
- 被删对象 tip 单独核对 IN-MAIN/IN-BUNDLE（tip 数通常远小于提交数，是独立且便宜的第二覆盖证明）
- 任何聚合判定先核对返回条数=输入条数；结果集为空时先怀疑解析格式或静默截断，重导出格式后再下结论

## Stop conditions
- 悬空残集每条均有处置：内容已在基线 / 在备份 / 确认丢失并如实上报
- 全部被删 tip 均判定 IN-MAIN 或 IN-BUNDLE，无一例外
- 用作覆盖证据的备份自身已通过 verify；两套覆盖证明（计数差分 + tip 判定）相互一致

## Verification
- 差分前后计数变化与被删类别规模一致（大幅下降而非不变；不变说明备份未含该类，需换证据）
- 逐条判定处理条数=残集条数，无静默丢项
- 备份 bundle verify 通过后才可作为覆盖证据；对空结果集先做一次格式/基数复核

## Counterexamples
- 对象数很少（如删 3 个分支）：逐条 merge-base/patch-id 更便宜清晰，mirror 差分属过度工程
- 不存在可恢复备份工件：unbundle 差分不可行，应改用远端 refs、reflog 或归档清单作证据
- 备份未验证或已损坏：在其上做差分会得到虚假覆盖结论，必须先 verify 再恢复
- 工具对超量输入大声报错而非静默截断：基数陷阱不成立，但聚合前后仍应核对计数
