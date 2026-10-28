---
method_id: truncated-hit-follow-author-persistence-provenance-877574075533
name: truncated-hit-follow-author-persistence-provenance
description: 检索命中目标记录（evolution/action_trace/日志条目）但回执在显示上限处截断、且任务需要全文时，不要拿预览尾部可见词去其它存储造复合查询词重搜，也不要先做目录级宽枚举。先利用命中及邻近事件暴露的溯源键（提交者 session id、时间戳、scope）查事件流中该 session 在记录产生后的落盘动作（edit_file/checkpoint/artifact 引用）——作者提交后持久化的配套 artifact 就是全文的耐久载体，沿这条链一步定位。链断（无后续持久化动作）才退回按记录 id 取全文或最后才宽搜。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a997d0bf-003d-4335-ade1-4f3981aa79e1:299:c73c9147dc0880ed2098
evidence_refs: learning:learn:09fefdd186fe
created_at: 2026-10-17T09:30:35.827333+08:00
updated_at: 2026-10-17T09:30:35.827333+08:00
---
## Trigger
一次检索命中了目标记录，但 payload 在回执处被截断，而任务需要完整内容；回执本身或同源事件流已暴露提交者 session id / 精确时间戳等溯源键。

## Discriminator
截断的是显示上限，不是内容缺失：命中记录携带（或一步事件查询即可得到）作者 session 与时间戳；该 session 在记录之后若有 edit_file/checkpoint 等持久化动作，其参数中的文件路径/artifact ref 即全文所在。存在这条显式溯源边时，跨存储换词重搜与目录枚举都是搜索空间扩散。

## Short path
- 接受命中：记录 id/kind/时间戳已入手，标记截断点；未知量=全文的耐久载体在哪。
- 以溯源键查事件流：限定提交 session（或 since=记录时间戳的短窗口），查记录之后的持久化动作。
- 读取动作参数中点名的耐久 artifact（配套文档/evidence）→ 全文到手。
- 若该窗口无持久化动作：改按记录 id 取全文/调大事件 limit 取原始调用参数；仍无果才目录级宽搜。
- 在全文上继续任务，不再回读截断副本。

## Stop conditions
- 全文来自与截断命中同 session/同 goal/同记录 id 链的 artifact，且内容越过截断点、与可见前缀衔接一致。
- 溯源窗口查询与按 id 取全文均无果后，才转入宽发现，并把这处全文缺口显式登记，而不是用自造查询词的 miss 当作'不存在'。

## Verification
- 最终 artifact 的 provenance（session/goal/记录 id）与截断命中的溯源键一致。
- 全文覆盖截断点之后的内容，且与截断前缀语义连续、无冲突。

## Counterexamples
- 截断点之后的内容与当前决策无关，可见部分已足够 → 直接使用并停止，不做溯源考古。
- 检索系统提供按 id 取全文/调大 limit 的原生途径 → 直接取，事件流考古反而绕远。
- 作者 session 在记录后无任何持久化动作，全文只存在于记录存储本身 → 溯源链死路，应走记录存储的取全文接口而非继续追 session。
- 查询对象是从未落盘的瞬态状态 → 其他存储的检索 miss 是真实信息，不应换词继续追。
