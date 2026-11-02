---
method_id: stable-ref-embeds-stem-read-canonical-file-directly-fa1af50e378a
name: stable-ref-embeds-stem-read-canonical-file-directly
description: 记录检索命中目标经验/方法卡但只回元数据与 stable ref（正文未随回执返回）时，不要重复同一检索通道，也不要在含发布快照镜像目录（.releases/<sha>/ 等）的文件型仓库里做全域文件名搜索——镜像副本会刷屏截断甚至超时。ref id 通常就是权威文件的名称主干：剥掉前缀得 stem，按仓库知识档案目录约定拼出唯一权威路径（如 experiences/<stem>.md）直接 read_file；推导不出才退回一次词干搜索并只取顶层权威目录命中。读到的文件 frontmatter 与 ref 回环一致即停，进入执行。
aliases: 水合不回正文直接读文件, 经验卡原文最快取法, 检索只给编号怎么拿全文, 镜像目录刷屏找权威原件, 发布快照副本干扰搜索
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:7e91da8b-4d11-4df5-84fc-7666790cb2fb:66:41339f0bbd269edc4e64
evidence_refs: learning:learn:032721b93a8a
created_at: 2026-10-31T19:25:55.291485+08:00
updated_at: 2026-10-31T19:25:55.291485+08:00
---
## Trigger
记录检索（如 search_records）命中目标卡，但回执未含正文、只逐字打印 stable ref（形如 experience:<id>），且 id 本身编码了记录标题/文件名主干；仓库为文件型知识库，且存在 .releases/<sha>/ 等镜像/快照副本树会污染文件名搜索结果

## Discriminator
回执已逐字给出与文件名主干相同的 ref id、且正文缺失——这一当时可见的事实把『在全仓几十份镜像副本中找原文』缩成『由 ref 推导唯一权威路径』；镜像目录的存在进一步证明文件名搜索是低效路径（结果截断、工具超时）

## Short path
- 检索命中目标卡但无正文 → 用 exact stable ref 水合一次；仍无正文则判定该通道只返回元数据，不再重复同措辞检索
- 剥去 ref 前缀得 stem，按仓库知识档案目录约定（规则文本/目录布局已示，如 experiences/）拼出权威路径并直接 read_file
- 若目录约定确不可知：做一次词干级文件名搜索，只取顶层权威目录的首个命中，显式忽略 .releases/<sha>/ 等镜像副本
- 读到正文且其 frontmatter 的 ref/标题与检索回执逐字一致 → 停止一切取数动作，进入执行阶段

## Stop conditions
- 已从顶层权威目录读到与 stable ref 回环一致的卡正文
- 水合通道已直接随回执返回全文（无需二次取数）

## Verification
- read 到的文件 frontmatter（experience_ref/title）与检索回执打印的 stable ref 逐字一致
- 最终读取路径位于顶层权威目录而非 .releases/ 等镜像/快照目录

## Counterexamples
- store 是数据库或远端服务而非本地文件树：ref 不映射任何路径，必须走水合/API 通道，直读文件不成立
- ref 是 opaque hash（不含可读标题主干）：推不出文件名，应先读存储设计文档解命名方案，而非猜路径
- 检索回执已随结果返回卡正文：无需任何二次取数，重复动作即浪费
- 多个顶层目录存在同名文件且无权威性约定（如 fork/工作区并存）：直读前必须先裁决权威目录，否则可能读到陈旧副本
