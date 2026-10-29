---
method_id: source-truncated-receipt-bounds-all-echoes-void-and-regenerate-7b25dcef642e
name: source-truncated-receipt-bounds-all-echoes-void-and-regenerate
description: 逐字绑定的一次性凭证（如提权 token）返回时，若其绑定的命令原文已被上下文压缩吃掉，第一未知量是『是否有任何存储曾持有全文』，而不是『去哪里找』。只做两件事：查自己提交时写入的持久产物（文件/state）；并水合一次该提交回执的权威快照读 range 元数据。快照 complete:true 且带源内省略标记⇒截断发生在生产者，event_stream/search_records/evidence 等下游只是同一快照的再分发，换措辞重查不会多出一个字；自有产物又无逐字版本⇒立即作废凭证、带全文经原通道重新生成。与『提交前归档全文』卡互补：那张防丢失，这张在丢失后一次判定不可恢复、免去跨库扫荡（本集省~8次无效检索）。
aliases: token批了但命令原文丢了, 逐字命令被压缩吃掉要不要重批, 回执截断还能找回全文吗, 搜遍记录找不到提交的命令, 一次性令牌配不上原文
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1418:94f988ab1e8eff91a1d7
evidence_refs: learning:learn:b010ab8cc023
created_at: 2026-10-29T17:05:01.014466+08:00
updated_at: 2026-10-29T17:05:01.014466+08:00
---
## Trigger
逐字绑定的一次性凭证已获批返回，但绑定原文不在当前上下文（被压缩/收割），正要发起跨存储查找时；或泛化：任何必须逐字恢复的关键载荷，其唯一权威记录出自只回显截断摘要的护栏/回执类生产者。

## Discriminator
权威提交回执快照的 range 元数据 complete:true 且 count 为固定小预算（约400-500字符）、正文带源内省略/命中标记且命令在标记处戛然而止——截断在源头而非检索层；下游 event_stream/search_records/evidence 水合均只是同一快照的再分发。全文唯一可能持有者是自己提交时写入的文件/state；两者皆空即证不可恢复。

## Short path
- 凭证返回后先核对：逐字全文是否已在手（当前上下文、任务 state、自己写入的脚本/文件）？在则直接配对执行。
- 不在手→水合该凭证对应提交回执的权威快照一次，读 range/complete 与正文截断标记，判定截断发生在源头还是检索层。
- 源头截断且自有产物无逐字版本→判不可恢复：停止对 event_stream/records/archive 换措辞重查，它们只会再返回同一截断快照。
- 立即作废凭证，经原通道带全文重新生成；重新提交那一刻把全文写入持久文件，再等待人工审批。
- 若 complete:false（读取窗口截断）或自有文件确有逐字版本→按翻页/读文件恢复，与快照未截断前缀逐字符比对后使用。

## Stop conditions
- 权威快照 complete:true 带源内截断标记，且自有持久产物无逐字全文：检索终止，唯一正确动作=作废+重交
- 全文已恢复且与快照截断点之前的前缀逐字符一致：停止检索，配对执行
- 新申请已提交且命令全文已写入持久文件：等待审批，不再改动命令文本

## Verification
- 用权威快照中未截断的前缀对恢复文本做逐字符比对，任何差异即非原文，禁止猜着补全
- 重交后确认新回执/自有文件中命令全文完整在握，再进入等待审批

## Counterexamples
- 快照 range 标 source_partial/complete:false：截断可能只在读取层，翻页即可取全文，不得判不可恢复
- 原文生产者是自己（提交前写过脚本或 state 文件）：文件系统持有全文，读文件即恢复，无需作废重交
- 回执回显预算大于命令长度且无省略标记：回执即全文，直接配对执行
- 命令非逐字绑定（允许等价改写）：重建语义等价命令即可，不存在找回问题
