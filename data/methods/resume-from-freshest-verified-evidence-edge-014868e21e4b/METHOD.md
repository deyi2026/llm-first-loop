---
method_id: resume-from-freshest-verified-evidence-edge-014868e21e4b
name: resume-from-freshest-verified-evidence-edge
description: 会话恢复（如收到“继续”）时，把 evidence ledger 的最新 verified 条目当作恢复锚点：最新一次被读取且 freshness=verified_current 的具名 artifact（文件名即编码当前工作主题）应直接重读以恢复任务上下文与待办项；随后用 git status/diff 确认实现是否已落盘，再只读该 artifact 明确点名的代码区域后实施。search_docs/search_files 等关键词全库枚举降级为回退手段，仅当 ledger 近期条目均为不可解析快照或与恢复意图无关时才启用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:114:5a747e45afd6cf7caf82
evidence_refs: learning:learn:4c30882f245e
created_at: 2026-09-22T17:25:48.806324+00:00
updated_at: 2026-09-22T17:25:48.806324+00:00
---
## Trigger
收到会话恢复/续作指令，且存在可查询的 evidence ledger，需要先恢复上一会话的任务上下文（目标、进度、待办项）再继续实施。

## Discriminator
friction 发生前已可见：list_evidence 顶部最新条目 source=read_file 指向具名 spec 文档、freshness=verified_current、acquired_at 最新，且文件名本身编码当前工作主题；其余条目多为 execute_command 快照。该事实当时就足以把“去哪恢复上下文”从全库/全 docs 缩小为该单一 artifact，关键词搜索（未命中 + 30 条无关 receipt 命中）不增加信息。

## Short path
- 收到“继续”后调 list_evidence，取最新 freshness=verified_current 且 source 为具名 artifact 的条目作为恢复锚点（未知量：上一会话在做什么）
- 直接完整重读该锚点 artifact，恢复目标、R1/R2/R3 式路线图与影响路径（未知量：待办项是什么、改哪些文件）
- git status + git diff --stat 只作用于 artifact 点名的影响路径，判断实现是否已部分落盘（未知量：从头写还是续写）
- 只读 artifact 点名的代码区域（rc≠0/_mark_action 分支、回执落盘函数、对应测试文件头部），取得精确插入点与 schema
- 实施待办项并运行 artifact 点名的测试文件，绿了并完成 artifact 内 TODO 核实后停止，不再做额外发现式搜索

## Stop conditions
- 锚点 artifact 已完整回答'任务是什么、下一步做什么、改哪里'
- 工作区状态已确认（无未预期未提交改动，或已识别为上轮半成品）
- 实现已通过 artifact 点名的目标测试集，且 artifact 列出的附带核实项已完成
- 此后不再发起关键词式 docs/files 全库发现调用

## Verification
- 确认所跟随的 artifact 确为 ledger 中 acquired_at 最新且 freshness=verified_current 的具名来源
- git status/diff 结果与'从头实施/续写'的假设一致，未覆盖任何已有未提交工作
- 最终改动与测试只落在 artifact 点名的路径/标记上（provenance 一致），无来自无关搜索结果的素材

## Counterexamples
- ledger 近期条目全部是 freshness=unknown 的命令快照、无具名任务 artifact：provenance 边太弱，此时关键词/语义发现是正当的第一步
- 恢复指令显式指向不同目标（如'继续 R2'）而 ledger 顶部是 R1 的总结：应锚定指令中的唯一 token 而非 ledger 时间序
- 顶部 artifact 是已被更新定稿文档取代的 draft（新文档尚未进 ledger）：仅按 acquired_at 跟随会误导，需结合 git status 的未跟踪文档列表核查后继版本
- 顶部条目只是顺手读过的无关报告（如 eval 报告），与恢复意图无因果：该边视为噪声，回退到发现式搜索
