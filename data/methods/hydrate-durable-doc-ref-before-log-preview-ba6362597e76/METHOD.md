---
method_id: hydrate-durable-doc-ref-before-log-preview-ba6362597e76
name: hydrate-durable-doc-ref-before-log-preview
description: 续跑一个回执被截断的执行中任务、需要取全文/清单时，evidence 检索回执常同时列出日志类 ref（source=event_stream，freshness=unknown，match_char=0，内联预览已在句中截断）与文档类 ref（source=edit_file:<path>，freshness=verified_current，match_char>0）。日志条目本身是截断预览，对它连续 hydrate 拿不到全文；应先按回执里已有的 ref 元数据排序，直接读取 durable 文档 ref 拿全文与剩余执行清单，日志 ref 只用于时间线/动作顺序查询。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b73b9f9b-96fe-44f5-a9a7-3a450b409a7f:343:1934f4781e5bd8e68367
evidence_refs: learning:learn:3b66864589d5
created_at: 2026-10-02T12:33:59.631754+08:00
updated_at: 2026-10-02T12:33:59.631754+08:00
---
## Trigger
已知某内容（如执行中演进的全文/执行清单）存在但首次回执被截断，需取全文；evidence 检索返回多个 source 类型与 freshness 各异的候选 ref。

## Discriminator
选择读取对象前，每个 ref 的元数据当时已可见且可比较：source=edit_file:<path> + freshness=verified_current + match_char>0 指向 durable 工作区文档；source=event_stream + freshness=unknown + match_char=0，且其内联预览已可见地在句中截断——表明它是日志预览而非全文来源。

## Short path
- 明确未知量：目标全文/剩余执行清单落在哪个 artifact？
- 按回执元数据排序 refs：优先读取 source=edit_file（或同类 durable 写入）+ freshness=verified_current + match_char 高的文档 ref
- 沿该文档内的引用/相邻命名约定（如 ELIG-<同一 artifact id>）定位执行清单文档，读取剩余步骤与占位符
- 检查清单涉及产物的既有落盘位置（如 results/ 目录、已提交的代码表面），已完成步骤不重跑；需要长文件尾部时用回执中的 range/next_start 偏移读取，而非重复同一读取
- 日志类 ref 仅在需要动作时间线/顺序时读取，预期为截断预览，不作为全文来源

## Stop conditions
- 已从 durable 文档取得执行所需全文/清单，且文档正文含目标 artifact id
- 所有 durable refs 均被证伪（不含目标内容）时，才降级到日志类 ref 或宽搜索

## Verification
- 读取回执 range.complete=true，且内容主体不是由句中截断的日志条目构成
- 目标 id（如演进编号）出现在所读文档正文中，与 provenance 边一致

## Counterexamples
- 需要重建历史动作的时间线/先后顺序时，event_stream 正是权威源，freshness=unknown 不构成否决理由
- 目标内容只存在于运行时回执、从未落盘为文档时，日志类 ref 是唯一来源，应直接 hydrate
- 检索结果缺少 source/freshness/match_char 等元数据（扁平列表）时，无法按本方法排序，应逐个验证而非假设优先级
