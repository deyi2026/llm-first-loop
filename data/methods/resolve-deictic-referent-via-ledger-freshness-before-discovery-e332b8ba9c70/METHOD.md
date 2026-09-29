---
method_id: resolve-deictic-referent-via-ledger-freshness-before-discovery-e332b8ba9c70
name: resolve-deictic-referent-via-ledger-freshness-before-discovery
description: 续跑/恢复会话中用户用指称性短语（"本方案""该文档"）下达收尾指令时，evidence ledger 的最新条目（freshness=verified_current 的 edit，或上一轮 present_files 观察记录）往往已直接指名该 artifact 路径。应把这条 ledger 条目当作指称消解边：直接读取该文件，跳过目录级文件名枚举；后续的格式基准与跨引用核验均由该文件头部"关联"列表导出（定向存在性搜索、命中即止，不展开读取无关命中），修订走最小原子编辑并写后复读校验。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7c2d2cfd-aeec-4302-9540-d52110cadd7a:133:d19f76939e9def3692cc
evidence_refs: learning:learn:a19d19dcf59c
created_at: 2026-09-24T17:45:07.606682+00:00
updated_at: 2026-09-24T17:45:07.606682+00:00
---
## Trigger
会话恢复/续跑时，用户指令含对"当前正在做的 artifact"的指称性引用（本方案/该文档/这条设计），且 list_evidence 可用、其中存在指向候选路径的显式条目

## Discriminator
ledger 中该路径的最新 edit 条目 freshness=verified_current（或上一轮 present_files 观察恰为该文件），且 acquired_at 为全部条目中最近，指称对象已被唯一命名，无需任何发现层

## Short path
- list_evidence：取最新 verified_current edit（或上轮 present_files）条目，直接确定指称对象路径，不发起目录级文件名枚举
- read_file 该 artifact：状态行/头部即给出当前版本、所处阶段（如"待终审"）与关联文档清单
- 以头部"关联"列表为界做定向存在性检查（每条引用一次 targeted search，命中即止），并从同体裁既有文件取格式基准
- 按指令做最小修订/成文，每步有 diff 回执；新建文件写后 read-back 校验，present_files 交付

## Stop conditions
- 指称对象唯一确定并已读到其当前版本（状态行确认所处阶段）
- 头部列出的跨引用存在性核验全部命中即止，未展开读取无关命中
- 每次修订/新建均有 diff 或写后复读回执，交付前完成 read-back

## Verification
- 确认所读文件是 ledger 中该路径的最新版本（无更晚的 edit 条目覆盖）
- 确认指称判断有 present_files 或最近 edit 佐证，而非仅凭文件名语义猜测
- 确认终稿头部引用的每个跨文档在搜索回执中逐一命中，且新建体裁文件与同体裁既有文件结构对齐

## Counterexamples
- 多条不同 artifact 的 edit 均为 verified_current 且时间接近（如同时改了 DESIGN 与 SDD），"取最新"启发式无法消歧，应回退 goal/任务锚或向用户确认，而非直接挑一个
- 用户指称本会话从未触碰的既有文件（含编号的历史 DECISION 等），ledger 无对应 provenance 边，定向文件名搜索才是正确首步
- 相关 edit 条目全部 freshness=stale，盘面可能已被外部改动，须先重读盘面文件确认真值，不能把 ledger 中的路径当作当前内容
