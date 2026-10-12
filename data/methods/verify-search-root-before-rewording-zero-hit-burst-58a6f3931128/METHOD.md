---
method_id: verify-search-root-before-rewording-zero-hit-burst-58a6f3931128
name: verify-search-root-before-rewording-zero-hit-burst
description: 当用户问题指向一个本应有本地工件的具体主题，而针对该主题连续多次换措辞的搜索（文件名glob、内容匹配、归档）全部零命中、且回执不含被搜范围信息时，累积证据指向『搜索范围/根目录失效』而非『工件不存在』。此时应停止换措辞，先用一个确定性动作锚定真实根目录，再做仓库原生发现并按绝对路径直读权威文档；只有锚定根下的定向搜索仍零命中，零命中才可当作 absence 证据。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:537:773a6aa39b4f014268b8
evidence_refs: learning:learn:3c87a527c637
created_at: 2026-09-28T19:49:52.819267+08:00
updated_at: 2026-09-28T19:49:52.819267+08:00
---
## Trigger
用户提问点名词题（如某个能力缩写）且按会话语境应有本地工件；随后对同一主题连续≥3次零命中搜索、回执均无 scope/root 说明，甚至特征子串的文件名搜索也零命中。

## Discriminator
knowledge-at-time：会话 evidence 库已被 list_evidence/search_archive 证实为活跃（245条记录）却『当前会话无该主题 Evidence』，与用户仍以进行中话题口吻提及该主题相矛盾——说明真正的未知量是『我的搜索到底覆盖了哪个根』，而不是『主题是否存在』；特征子串文件名零命中（话题工件必然含该子串）直接证明搜索范围无效。

## Short path
- 首次零命中后立即停止换措辞，先锚定根：一条确定性命令（pwd / git rev-parse --show-toplevel / 探测一个已知存在的文件）
- 在锚定根下做仓库原生发现：git status、docs/ 近期列表或 docs index，定位主题工件的准确路径
- 按绝对路径直读权威文档（本集为同日 ANALYSIS 评估文档 + 相关 EXPERIENCE/ARCHITECTURE 文档）
- 读完已有结论后，才开展回答用户真实未知量所需的增量工作（实测、治理数据核对）
- 只有锚定根下的定向搜索仍零命中，才扩大搜索或下『无本地工件』结论

## Stop conditions
- 已读到与主题直接对应的权威文档且内容确认匹配用户问题
- 锚定根下的定向搜索仍零命中：主题确无本地工件，转入第一性分析而非继续搜
- 搜索回执显式声明了范围、且该范围=已验证根：此时零命中是有效的 absence 证据

## Verification
- 做一个阳性对照：搜索一个已知存在于锚定根文件中的字符串，确认 search 工具范围=锚定根
- 确认最终直读的文件位于锚定根下且内容与主题匹配（本集中后来读到的 ANALYSIS 文档文件名含 'codebase'，反证先前 *codebase* 文件名搜索的范围无效）

## Counterexamples
- 首次搜索回执已显式列出范围与替代入口（如 docs_search 附带『最近文档参考』列表）且范围正确：应沿该指针走，不要重验根
- 全新话题、会话中也确无相关历史（store 为空属正常态）：零命中是有效信息，按正常方式放宽搜索即可
- 单次、范围明确的搜索零命中：一次 miss 不足以推断范围失效，不应每次搜索前都做根验证
