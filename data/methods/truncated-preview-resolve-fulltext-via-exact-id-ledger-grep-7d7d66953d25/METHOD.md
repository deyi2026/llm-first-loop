---
method_id: truncated-preview-resolve-fulltext-via-exact-id-ledger-grep-7d7d66953d25
name: truncated-preview-resolve-fulltext-via-exact-id-ledger-grep
description: 审批/治理类记录（演进建议、变更单）在各检索面只返回同一截断预览、而继续实施需要全文时：对同一记录库换 scope/换措辞重查、按业务域同名目录枚举（如 data/evolution/）、甚至水合提交回执的 evidence:// 引用都补不全——回执 blob 在捕获时即已截断。权威全文持久化在按唯一 ID 键控的 append-only 审计账本（audit/*.jsonl 类 sink），一次精确 ID 内容 grep 即得全文与实施条款。判别信号：同一 ID 在 ≥2 个检索面返回内容一致且同位置截断，说明截断在预览层，重查无效。
aliases: 回执截断去哪找全文, 预览只给半条记录, 审批单全文查原始账本, 按编号 grep 出完整记录, 事件流里建议看不全
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8ce6aa41-bb36-4a43-9e62-65b65cd6bd74:1618:73292965b33520db34bc
evidence_refs: learning:learn:c8a777f12528
created_at: 2026-11-08T09:24:15.738683+08:00
updated_at: 2026-11-08T09:24:15.738683+08:00
---
## Trigger
持有治理/审批类记录的唯一 ID（审批回执、记录搜索、事件流均已逐字给出），下一步实施需要其全文（建议正文/影响面/验收与红测试条款），但已试过的每个检索面（records 搜索、事件流各 scope、回执水合）都只返回同一截断预览

## Discriminator
同一 ID 在 ≥2 个检索面返回内容一致且在同一字符位置截断——截断发生在预览/捕获层而非记录缺失，换 scope 重查构造性无效；且业务域同名目录里并没有该记录，真正的持久化 sink 是 audit 类 append-only 账本，按该唯一 ID 键控可一步定位

## Short path
- 用 ID 查一次记录库/事件流：确认状态（完成『核实』），同时记下预览截断位置；同一内容已见两次即证明再换 scope 无效
- 把未知量收敛为『全文持久化在哪』：对数据根或先 audit/archives 目录做精确 ID 内容搜索（grep -rl），一步命中账本文件，跳过按业务域命名的目录枚举
- 抽取该 ID 的完整行，核对与预览前缀逐字段一致、且覆盖截断点之后的建议正文/影响面/红测试要求
- 由记录自身条款驱动实施（worktree、红测试、门禁），不再回头枚举目录、重查事件流或二次水合回执

## Stop conditions
- 账本行字段完整（ID/时间戳/状态/建议全文/影响面）且与预览前缀一致 → 停止检索，进入实施
- 若任务只需核实状态、不需全文 → 第一步即可停止
- 账本精确 ID grep 无命中 → 停止该分支，转向提交者或上游记录系统索取全文，不继续目录枚举

## Verification
- 账本行的时间戳、状态、ID 与检索面预览逐字段一致，确认是同一记录而非同名旧版
- 行长度显著超过预览截断长度，且截断点之后的关键内容（建议方案、影响面、验收要求）均已取得

## Counterexamples
- 预览已包含实施所需全部字段（状态+全文）→ 直接实施，不查账本
- 存在按 ID 直取的专用查询工具/API → 用它，不做文件级 grep
- 系统只持久化事件流、不落全文账本 → 精确 ID grep 是死路，应向提交者或上游索取全文
- ID 非唯一（短后缀在归档中高频撞车）→ 命中分布需按时间戳/上下文分流，不能盲取第一行
