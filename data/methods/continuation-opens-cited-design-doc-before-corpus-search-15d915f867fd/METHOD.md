---
method_id: continuation-opens-cited-design-doc-before-corpus-search-15d915f867fd
name: continuation-opens-cited-design-doc-before-corpus-search
description: 阶段续跑时，若上下文（goal 头/退出条件/checkpoint）已点名权威计划文档的 ID 与章节锚点（如 DESIGN-YYYYMMDD-* + §N + T 编号），第一步就是定向打开该 artifact 并按锚点读区间，而不是先做语料级语义搜索。命名引用本身是显式 provenance edge，把候选空间从“全库哪篇文档有答案”缩成“这个命名文件的指定章节”。本集 goal 状态文本已写明 “DESIGN-20261009 插件生态” 与 “退出条件按设计 §11/§12.2”，但模型先对语料库 search_docs、miss 后才改用 search_files 定位；最短路径是一次 content search 直接命中阶段表行（492 行 P2-B 行），按行号只读相关区间即得范围与退出条件。若锚点一次核验失败（文档缺失/被重构），再扩大到语料搜索，不要换词重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8edca76a-022e-442c-9819-960bcdff7f8a:411:88a05e33e7dcd897f463
evidence_refs: learning:learn:729bffb082fa
created_at: 2026-10-10T07:01:51.891180+08:00
updated_at: 2026-10-10T07:01:51.891180+08:00
---
## Trigger
用户要求“继续/进入下一阶段”，且当前上下文已显式引用权威计划文档的 ID/文件名与章节或条目锚点（§N、T 编号、阶段代号如 P2-B），而该阶段的确切范围尚未读入上下文。

## Discriminator
在发起任何检索之前，goal 状态文本本身已包含文档 ID 与章节锚点（“DESIGN-20261009 插件生态…退出条件按设计 §11 与 §12.2”）。这是当时已可见的窄化事实：目标阶段表必然在该命名文档内，无需先枚举语料库。

## Short path
- 1. 从上下文提取文档 ID、阶段代号与章节/测试锚点（不发起任何库级搜索）。
- 2. 用一次文件名或 content 定向检索定位该文档；content search 直接返回阶段表行号（如 492 行的 P2-B 行）。
- 3. 只读被引行及其章节区间（§3/§5.2/§11/§12.2），抽出阶段范围与退出条件，避免全读后再补读尾部。
- 4. 按范围触达的模块做代码基线核查（如 mcp_*、extensions/），然后实施与测试。

## Stop conditions
- 已从被引章节取得阶段范围与退出条件（阶段行 + T 条目逐条对应）→ 停止检索，转入代码基线与实施。
- 定向检索未找到被引文档或锚点对不上 → 此时才允许扩大到语料级搜索或 git delta 重建。

## Verification
- 实施清单与被引阶段行、T 条目逐条对应（本集：492 行 P2-B 行 ↔ resources/prompts、旧 SSE、Git/归档、目录服务）。
- 读取的代码模块与设计文档引用的模块一致后才动手实施。

## Counterexamples
- 上下文只有“继续”而无任何 ID/锚点、且无活动 goal：不适用，应走既有的 miss 回执/wakeup 备忘/git delta 续跑方法。
- 被引章节内容已在上下文中且未变更：直接使用，不要重读文件。
- 命名文档存在但目标内容不在被引章节（锚点过期、文档重构）：一次定向核验失败后立即转向语料搜索，不要反复换关键词。
