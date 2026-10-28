---
method_id: keyed-in-blob-search-before-linear-receipt-pagination-65ddc0c5ae1f
name: keyed-in-blob-search-before-linear-receipt-pagination
description: 当工具回执是单个分页式大 blob 且开头被与用户问题无关的重复审计数组占据时，不要从 start=0 线性分页读完全文。先把用户问题映射为答案承载字段名（如 stage_facts/status/live/stable/restart_required），对同一 evidence ref 做关键词检索，拿到 match_char 后只读命中邻域。本集开头约 25K 字符全是 generation_lag 噪声，检索一次即命中失败记录与 stage_facts，可省去 3 次以上无效分页和重复读首段。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:1165:8cbaffcc16530fdc9849
evidence_refs: learning:learn:d051fbb0b9fc
created_at: 2026-10-16T21:43:54.648535+08:00
updated_at: 2026-10-16T21:43:54.648535+08:00
---
## Trigger
工具回执为分页式大 blob（complete=false，总量数倍于单次 limit），首段已呈现重复性内容且与用户未知量无直接关系；同时环境提供可对该 evidence ref 的检索工具

## Discriminator
回执头部可见的字段名/内容与用户问题所需答案字段是否匹配：若头部是重复噪声数组（lag/清单类），而答案位于命名状态键（status、stage_facts、live/stable、restart_required、git_head），即可判定应按键检索而非顺序分页；首段内容已在原始回执中可见时也不必从 start=0 重读

## Short path
- 读回执首段，判断头部内容是否与用户未知量相关；若已可见是重复噪声数组，不从 start=0 重读
- 把用户问题转写为答案承载键名/关键词（如 stage_facts、status=failed、restart_required、git_head、pid）
- 对同一 evidence ref 执行检索，取得 match_char 偏移列表
- 只读命中邻域 range，抽齐每个目标的终态字段，并用 live/stable 双记录交叉验证旧部署存活
- 用户的每个未知量均有命名字段证据后停止，不读未命中的噪声段

## Stop conditions
- 用户的每个未知量都由语义对应的命名状态字段回答，且 live/stable 记录一致（git_head/pid 互证）
- 检索无命中且无法从问题派生键名时，退回顺序分页并接受其成本

## Verification
- 确认命中片段来自同一 blob（blob_sha256 一致），且字段名与问题目标一一对应
- 对『之前部署还在』类断言，用 live 进程记录与 stable 成功记录双源交叉确认，而非依赖单点字段

## Counterexamples
- 用户问的就是头部数组本身（如 lag/积压统计），头部即答案，直接顺序读
- 回执总量一两次分页即可读完，检索开销超过直接读
- blob 是无稳定键的自由文本/日志，无法从问题派生检索词，只能采样扫描
