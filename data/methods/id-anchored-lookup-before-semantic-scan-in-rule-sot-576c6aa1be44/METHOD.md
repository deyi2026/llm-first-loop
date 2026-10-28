---
method_id: id-anchored-lookup-before-semantic-scan-in-rule-sot-576c6aa1be44
name: id-anchored-lookup-before-semantic-scan-in-rule-sot
description: 任务需要判断某条已命名规则/闸/条款/错误码是否适用或内容是什么时，若其稳定标识符与真相源线索已出现在当前上下文（技能清单同时打印了闸名、规则编号 RULE-AI-28 第 2 条、专门 SKILL.md 路径），先把该标识符当作一次可达的定位锚：作用域受限 grep 编号/定义标题，只读命中定义段。语义文档搜索、从第 1 行顺序分页读大 SoT、空 hydration 补读都是后备手段。本集为确认文稿闸是否覆盖 PPT 交付，先后走了 search_docs 未命中→读 ai_rules.md 前 120 行（目标规则不在其中）→空 hydration→grep→读 446-496 才拿到规则全文，前三次试探本可由一次 grep 或直接读已给路径的 SKILL.md 替代。
aliases: 查规则先按编号grep, RULE-AI-28 这类规则编号直接定位, 规则适用性先读定义段, 别拿语义搜索查规则编号, 按规则号找SoT原文, 闸门条款原文去哪找
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:7a55ef15-90c4-4fd3-b70f-68887bc24e18:105:e35527c350e29317c711
evidence_refs: learning:learn:f43700cd9b98
created_at: 2026-10-26T08:52:26.508345+08:00
updated_at: 2026-10-26T08:52:26.508345+08:00
---
## Trigger
出现『某命名规则/闸/条款/错误码是否适用于当前任务、原文是什么』类未知量，且该标识符（规则编号、技能名+文件路径、错误码）已在当前上下文回执中打印，或目标文件是按编号/标题组织的大型真相源文档

## Discriminator
标识符是否稳定且已被打印：技能清单回执已同时给出『article-review-gate（RULE-AI-28 第 2 条）』与 SKILL.md 精确路径，且规则 SoT 用『## 规则二十八：…（RULE-AI-28…）』式编号标题组织——这已把『规则说了什么/是否适用』从全 docs 语义搜索或 658 行全读缩成一次 grep 可达的定义段

## Short path
- 从已打印的标识符出发：优先直接读已给出精确路径的专门文档（如 SKILL.md），否则对 SoT 文件做作用域受限的编号 grep
- 在命中行里选定义点（编号标题行），排除散落的交叉引用行
- 只读定义段所在有界区间，取得适用范围、豁免边界与回执要求
- 据此判定本次任务是否触发该闸；仍不明确才升级为语义文档搜索或全文件分段通读

## Stop conditions
- 已读到该条规则完整定义段（含适用条件与豁免），可作出适用/不适用判定并引用行号
- grep 未命中且已核对文件为当前版本 → 转语义搜索/索引或通读，不再换措辞重复 grep

## Verification
- 选中的命中行是定义标题（如『## 规则N：…（ID…）』）而非 inline 引用
- 所读区间覆盖该条规则全文（下一规则标题之前无截断）
- 最终适用性判定能引用所读定义段的具体行号/原文

## Counterexamples
- 查询是概念性/政策性问题且无稳定编号（如『文档对 X 的总体立场』）→ grep 无锚点，应语义搜索或通读
- 标识符在文档中被大量交叉引用（本集 6 处命中仅 1 处是定义）→ 不区分定义点会读到零散提及而非规则全文
- 目标文件很短（一两屏）→ 直接全读更快，grep 反而多一步
- 编号可能随版本重命名 → grep 未命中应先核对文件版本，而非断言规则不存在（负存在性判定须守部分覆盖边界）
