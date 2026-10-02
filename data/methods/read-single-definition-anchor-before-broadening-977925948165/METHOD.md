---
method_id: read-single-definition-anchor-before-broadening-977925948165
name: read-single-definition-anchor-before-broadening
description: 当继续型设计任务的首次内容搜索只返回一条命中、且该片段本身就是目标概念的权威定义时，不要先叠加更多宽域关键词搜索，而应立即读取该锚点文件，再从其导出符号推导定向的 usage/import 搜索。把发现顺序从“关键词枚举→事后解释命中”改为“定义锚点→因果边→消费者”。本集若按此路径，可省去读锚点前的 3 轮宽搜索（50/3/11 条混合命中），且后续最有效的 importer 搜索本就以锚点符号为词根，本可更早、更窄地执行。
status: candidate
source_model: chatgpt-web/web-gpt
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:31:37fd332321e266d59c71
evidence_refs: learning:learn:0db5cba53845
created_at: 2026-10-01T22:41:00.085257+08:00
updated_at: 2026-10-01T22:41:00.085257+08:00
---
## Trigger
继续型任务（如设计/定位类交付物）中，第一轮内容搜索回执只有单条精确命中，片段包含目标概念的 self-describing 定义（模块 docstring 或 class 定义），该文件尚未被读取，而任务仍需确认该概念的生命周期与调用面。

## Discriminator
首轮搜索 hit==1 且命中文本是定义性陈述而非顺带提及：provider_settlement.py 第 3 行模块 docstring 明确写着“A ProviderCall is one logical model invocation owned by an execution surface”——这条当时已可见的事实足以把“整个代码库都可能相关”缩成“先读这一个定义文件，再沿其符号找调用面”。

## Short path
- 识别首条回执为单条精确命中且含定义性文本 → 直接 read 该锚点文件；未知量：目标概念已记录哪些字段与生命周期
- 从锚点导出符号（如 ProviderCallSettlementJournal 等）做一次针对性 import/usage 搜索；未知量：谁在运行时写入/读取这些记录
- 只读取与生命周期直接相关的少量消费者文件（coordinator/调用引擎/持久化 projection）
- 若仍有跨切面语义边界未知（如 reasoning replay 边界），做一次窄域文档搜索后停止发现，进入综合设计
- 交付第一轮定位结论或设计草案，明确剩余未知量

## Stop conditions
- 锚点文件与其直接 import/写入方已读，足以回答“现状已有什么、边界在哪”，停止发现进入综合
- 后续搜索命中开始重复出现已知文件（无新信息），不再沿同方向继续枚举
- 用户本轮只要求状态确认且已握有足够证据，如实汇报部分进度即可

## Verification
- 核对单条命中确为定义性文本而非碰巧同名/顺带提及（读文件头部 docstring 即可确认）
- 核对后续宽搜索中与目标直接相关的关键文件能否全部由锚点符号的 import/usage 边推导出来（本集 provider_calls/transport_observation/ledger_projection/engine 均是 provider_settlement 的 importer）
- 最终交付引用的是锚点+消费者这条因果链，而非零散关键词命中

## Counterexamples
- 首轮搜索命中多且分散、无单条定义（如用通用词搜索）→ 宽域三角定位才是正确动作，不应固守第一条命中
- 单条命中只是 changelog/旧文档中的顺带提及而非定义 → 读取它不构成锚点，仍需宽搜索
- 目标未知量是无单一定义的跨文件行为边界（如敏感字段清单、配置面盘点）→ 按面枚举比锚点优先更合适
- 锚点读取后发现其声称职责与目标内容无关（锚点断裂）→ 立即转宽搜索，不继续沿该文件走
