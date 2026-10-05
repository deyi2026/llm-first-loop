---
method_id: truncated-receipt-extract-from-originating-call-args-554d8cf45110
name: truncated-receipt-extract-from-originating-call-args
description: 当需要一段本会话此前经工具调用提交/产出的长文本的逐字全文，而查询回执（记录检索/事件流/运行时面板）只在句中截断时：不要换措辞重复查询同一展示面，也不要转入全仓枚举定位；直接定位产生该内容的原始 action_trace 的持久化调用参数（会话事件日志 JSONL），机械过滤提取全文，并与截断回执的可见前缀比对验证同一性。展示层截断是显示属性，逐字载荷保存在发起调用的参数里。本集确认截断后仍走了 search_evidence→search_files→全仓 grep（60s 超时）→pending_actions→约十次目录枚举才落到事件日志，定点提取可省去全部扩散。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:932df416-c651-4aff-9348-962d36f4ff73:54:502aa567839d6e044eee
evidence_refs: learning:learn:c1d58a828f83
created_at: 2026-10-03T06:52:35.512109+08:00
updated_at: 2026-10-03T06:52:35.512109+08:00
---
## Trigger
需要本会话此前经某次工具调用提交/产出的长文本的逐字全文，而检索/事件流回执可观察地在句中截断，且事件流中可见产生它的原始 action_trace（tool_calls=…，带工具名/时间戳/session）条目。

## Discriminator
两条当时已可见的事实：(1) 回执内容句中截断无闭合——说明截断是展示层属性而非数据缺失，重复查询同一面只会得到同样截断；(2) 该文本由本会话经一次明确的工具调用提交（如 submit_evolution），逐字载荷必然持久化在该调用的原始参数/会话事件日志中。二者把候选来源从『全库任何地方都可能』缩到『单条事件记录的 args 字段』。

## Short path
- 确认回执截断（内容句中终止）且该文本源自本会话某次工具调用；逐字需求下禁止凭上下文记忆重写
- 在事件流/记录中定位该次原始调用的 action_trace（工具名+时间戳+session id）
- 按数据目录约定/配置定位会话事件日志（如 data/event_logs/<session>.jsonl），脚本按事件类型与工具名过滤
- 提取该调用参数中的目标字段全文
- 与截断回执的可见前缀逐字比对验证同一性后停止发现，进入执行

## Stop conditions
- 原始参数中的全文已提取且可见前缀与截断回执一致 → 立即停止发现
- 记录库/工具本身提供未截断的按 id 全文读取 → 优先使用并停止
- 事件日志缺该 action_trace（轮转/保留期）→ 此时才升级为档案/宽检索，而非在此之前扩散

## Verification
- 提取文本的可见前缀与截断回执的可见部分逐字一致（同一性检查）
- 后续写入物与提取文本逐字一致（以字符数/sha/锁定测试复核，如本集 380→547 字符与 6 项锁定测试）

## Counterexamples
- 目标文本并非经本会话工具调用产生（用户提供或来自外部文档）→ 事件日志参数里不存在，应直接读权威源文档
- 回执完整未截断 → 直接采用回执，不要挖日志
- 提交后内容被人工审批/流程改写重发 → 提交时的 args 已非权威版本，须取审批后的记录
- 只需语义要点而非逐字文本 → 截断回执+相关文档摘要已足够，不值得解析原始日志
