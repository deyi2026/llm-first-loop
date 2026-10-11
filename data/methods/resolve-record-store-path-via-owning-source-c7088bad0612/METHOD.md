---
method_id: resolve-record-store-path-via-owning-source-c7088bad0612
name: resolve-record-store-path-via-owning-source
description: 当记录检索工具已命中目标记录（kind+ID 明确）但正文截断、需要全文/状态/授权范围时，不要用'猜文件位置'扩大搜索空间：同一标识符在文件索引 miss 恰是正面证据——记录的权威副本在子系统拥有的 record store 里，而 store 落盘路径是代码定义的事实。做一次定向 grep 该子系统实现模块（store/path/dir/jsonl 常量），解析出 canonical 路径后按 ID 过滤直读全文。以此替代措辞变体反复检索、pwd/ls/find 全树扫描和 submissions/drafts 逐个猜测（本集浪费约 8-10 次调用含 1 次 timeout，store 实际在 data/audit/ 而非猜测处）。要点：miss 是判别证据而非换词理由；截断片段与 drafts 目录均非权威正文；拿到全文立即停止。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7c423f8-5e37-404b-a6b3-9631910a54d7:11:fcb0fe39d6fb92bf77f5
evidence_refs: learning:learn:b9f1401c5a19
created_at: 2026-10-11T00:19:05.852261+08:00
updated_at: 2026-10-11T00:19:05.852261+08:00
---
## Trigger
search_records/event_stream 已命中某条目标记录（kind、ID 明确）但回显正文被截断，后续执行需要全文内容/状态/scope；同一标识符在 search_files/content 检索中无匹配。

## Discriminator
记录已被 record 检索证明存在（命中+ID+kind），而文件索引对同一 ID 返回 no match ⇒ 权威副本不在工作区文本索引覆盖面内，而在拥有该 record kind 的子系统的专用 store 中；store 路径是实现源码中的常量事实（_path/落盘文件名），目录树枚举与措辞变体检索都无法产生它。

## Short path
- 从首次命中确认记录存在及 kind+ID，并注明仅正文截断（未知量：权威全文）。
- 最多做一次文件索引核查（search_files 按 ID）；miss 记为判别证据，不换措辞重搜、不进目录枚举。
- 一次定向 grep 拥有该 record kind 的子系统实现（store 类/工具模块）找持久化路径常量（未知量：store 写到哪个文件）。
- 读 store 模块头注释/_path 行确认文件名与目录（如 data/audit/evolution_suggestions.jsonl）。
- 按 ID 过滤直读 canonical 文件（python -c 行过滤），取得全文+status/scope，与原命中核对一致后停止。

## Stop conditions
- canonical store 按 ID 过滤已取得全文（含 status/scope 等决策字段）且与原命中 ID/kind/时间戳一致。
- 命中片段本身已包含当前决策所需的决定性字段时，跳过取全文直接行动。
- 定向 grep 得到的 store 路径不存在或不可读 → 此时才回退为目录枚举 fallback，并说明降级原因。

## Verification
- canonical 文件中读到的记录 ID、kind、时间戳与最初 search_records 命中一致，排除读到 drafts/旧副本。
- 所用路径与 owning 源码中定义的路径常量（_path/store 文件名）一致，而非目录猜测所得。
- 取得全文后不再有任何变体检索或枚举动作（无 post-sufficiency actions）。

## Counterexamples
- 文件索引本身命中记录的完整副本（如 docs/ 下的导出或提交稿）→ 直接读该文件即可，不必进源码找路径。
- record 检索工具自身提供按 ID 的 detail/fetch 检索 → 用官方接口直取，不做路径考古。
- 记录属于外部系统或本仓库无其源码 → 应沿 API/文档找数据面，本方法（grep 本仓实现）不适用。
- 决策只需命中片段中已有的字段（如 status、ID 已完整）→ 提前停止，取全文本身就是 post-sufficiency 动作。
