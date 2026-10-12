---
method_id: exact-canonical-id-lookup-key-not-keyword-mashup-4b96fc6a2b01
name: exact-canonical-id-lookup-key-not-keyword-mashup
description: 在 records/evidence 等可键控检索的持久层中定位一条已知具体存在的记录时，检索键应取权威回执中逐字显示的规范 ID 全串（或已列出的 source class），而不是把其语义要素重组成自然语言关键词混拼。本集目标回执已逐字给出 EVO-20261012-bb3022f4 / EVO-20261012-65475c5a，首次却用『requires spawn_subagent 工具白名单 bb3022f4』式关键词查询导致 miss 后重试；证据门阶段对 search_evidence 用『tool_scope=wait spawn_subagent E4 强制白名单』查询同样 miss，而命中条目均来自按 source/class 键的查询。精确键 miss 只说明键形式或持久化时点待核，不得解读为记录不存在（本集回执亦显式声明不伪造结果）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:779:4cab4fe6747aec638c8d
evidence_refs: learning:learn:9a254b26ba7d
created_at: 2026-10-12T07:03:56.605515+08:00
updated_at: 2026-10-12T07:03:56.605515+08:00
---
## Trigger
需要在一类可检索持久层（search_records / search_evidence / 登记库）中精确取回一条已知存在的记录，且最近一条权威回执已经逐字显示其规范 ID 或 source class。

## Discriminator
回执中已出现带前缀的完整规范 ID（如 EVO-日期-hash）或明确 source class，且当前检索目标是『取回这条记录』而非开放探索——此时规范 ID 本身就是确定性查找键，语义关键词重组是严格更弱的键。

## Short path
- 从最近一条权威回执中复制规范 ID 全文，不缩写、不做语义重组（本集：goal 回执已含两案完整 EVO ID）。
- 以该 ID 原文为键各发起一次精确查询；确无依赖的独立动作（如本集 E2E child spawn）保持并行。
- 命中即读取内容并停止对该库的重试，把命中条目直接用于下一步（登记、引用、收口）。
- 若精确键 miss：先怀疑键形式或持久化时点，再降级为语义/宽查询；不得把一次 miss 当作『不存在』的证据。

## Stop conditions
- 检索回执命中条目的 ID/source 与查询键逐字一致，目标记录内容已取得，未知量已解决。
- 精确键一次命中后，不再对同一库换措辞重试同一目标。

## Verification
- 比对命中条目的 ID 字符串与查询键逐字相等（本集改用完整 EVO ID 后立即 1/1 命中，证实前次 miss 源于键形式而非记录缺失）。
- 证据门场景：最终引用的 evidence:// ref 必须逐字取自 search_evidence 回执原文，而非手写或转述（本集 unsupported_ref 被拒后，换用检索所得 evidence://v1/... 引用即通过终局门）。

## Counterexamples
- 无任何规范 ID 可用的真正探索型检索（如本集末尾『docs 中哪些规则与 E4/E5 语义相关』的内容扫描）：关键词/内容检索才是正确工具，本方法不适用。
- 记录可能尚未持久化（刚发生、落盘滞后）：精确 miss 是合理状态，应宽查、换 source class 或延后重查，而不是断言缺失或伪造结果。
- 目标是模糊概念、多候选枚举或语义相关性排序，而非单条已知记录的取回。
