---
method_id: session-evidence-before-broad-search-14dfe01a6c75
name: session-evidence-before-broad-search
description: 当任务要再次处理本会话早前已完整读取过的具体工件（如刚评审过的设计稿）时，先查会话 evidence 账本：按 label/主题过滤，核对 complete、version_token、freshness，直接 hydration 或按记录路径复读取得原文，随即进入任务本体。宽泛的关键词/文件名枚举只作为回退。关键在于：搜索类工具通常只覆盖工作区/docs 范围，工作区外的工件（如 Downloads 路径）宽搜索注定空转，而证据账本不受该范围限制。此法把'目标工件在哪、内容是什么'从全库枚举缩为一次证据命中；若工件路径本来就明确且在工作区内，直接 read_file 更短，不必绕道账本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6e0fb83b-03af-44ff-be33-c3498380b42f:21:0a67fec9188206a50274
evidence_refs: learning:learn:00ece772011e
created_at: 2026-09-20T17:46:27.936310+00:00
updated_at: 2026-09-20T17:46:27.936310+00:00
---
## Trigger
任务引用一个本会话早前已读取/处理过的具体工件（设计稿、报告、代码文件），需要重新取得其当前权威文本再继续操作（拷问、修订、比对）

## Discriminator
会话 evidence 账本中已存在对该工件的完整读取记录：label 给出精确路径、range.complete=true、带可探测的 version_token 且 freshness=verified_current——该事实在发起任何搜索之前就已存在并可检查，足以把'工件可能在全库任何位置'缩成'沿这一个证据引用取回'。本例中该记录（acquired_at 14:32，complete，verified_current）先于全部 5 次宽搜索（14:37 起）存在。

## Short path
- 过滤本会话 evidence 账本：是否存在目标工件的 read_file 记录（按 label/文件名/主题词匹配）？未知量：是否已持有权威原文。
- 命中且 complete=true：核对 version_token 与 freshness；可信则直接 hydration（或按记录中的精确路径复读一次）。未知量：当前合同原文的确切内容。
- 拿到原文后立即进入任务本体（本例为拷问评审与修订落盘），不再做任何定位性搜索。
- 仅当账本无该记录、freshness=stale/unknown、或 hydration 失败时，才回退到关键词/文件名宽搜索。

## Stop conditions
- 已从与任务所指一致的证据引用/原文取得所需文本，且版本未被证伪（version_token 相符）
- evidence 账本确认无该工件的先前记录——此时宽搜索是正确起点，停止翻账本
- hydration 成功且原文完整（range.complete=true），不再追加确认性搜索

## Verification
- hydration/复读返回的 label 与任务所指工件完全一致，行数与版本 token 与账本记录相符
- 后续产出（修订本、结论、引用片段）中的原文引述确实出现在取回的文本中
- 若最终走了宽搜索路线，需能说明为何证据路线被排除（无记录/失效/hydration 失败），而不是默认跳过

## Counterexamples
- 工件是很久之前或上一条会话读的，无 version_token 或 freshness=unknown：旧证据可能已过期，应先探测当前版本，不能直接信任，必要时重新定位
- 任务目标是发现一类未知工件（如'找出所有关于重启的设计文档'），没有已读记录可沿：宽搜索本身就是正确第一步，套用此法只会拖慢
- evidence 记录存在但 hydration 失败或文件已移动/改名：证据边已断裂，应立即回退到定位搜索，而非反复重试 hydration
- 工件路径本来就明确且在工作区内：直接 read_file 比查账本再 hydration 更短，此法不适用
- 需要的是工件的当前最新版本而证据标记 stale，或任务要求跨会话持久来源（审计链）：单会话账本不足以作权威
