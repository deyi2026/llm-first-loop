---
method_id: owning-live-dimension-adjudicates-prior-state-claims-before-archaeology-c6e375fd1169
name: owning-live-dimension-adjudicates-prior-state-claims-before-archaeology
description: 上下文重置后复核上轮对系统『当前状态』的断言（如 N 个待确认门）时，若首个状态面回执计数与断言冲突（0 vs N），不要先做事件流/记忆考古去定位『上轮数字的出处』：首个回执自身字段就是判别器——若该 section 的 schema 根本不含断言所需明细字段，说明它管辖的是别的对象类型，冲突是口径错位而非断言过时。下一步应枚举状态工具其余维度、直读『拥有该对象』的 section（回执常自带『详情见 X』交叉指针），一次读数即可裁决计数并拿到逐项明细路径，再沿回执打印的 rel_path 做完整性核对、读被点名的实现文件核语义。仅当无任何活体状态面拥有该对象时才回落历史考古。与 definition-surface 裁断言方法互补：那条裁机制断言，本条裁当前状态断言。
aliases: 0和5对不上先查别的维度, 上轮的数字现在还对不对, 别翻事件流先看现值, 哪个工具管这个数, 现值裁决旧断言, 口径冲突先换管辖面
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:52:d0828f0c7cc054a95664
evidence_refs: learning:learn:908233e0a995
created_at: 2026-11-05T22:55:57.659134+08:00
updated_at: 2026-11-05T22:55:57.659134+08:00
---
## Trigger
上下文压缩/重置或换会话后，需要复核上一轮关于系统自身当前状态（待办门数量、队列深度、账本规模等）的断言，且对状态工具的第一个探测面返回了与断言冲突的数字（如 0 vs N）

## Discriminator
首个回执自身 schema 的字段覆盖情况：若该 section 只返回别的对象类型字段（如 backup 计数 session/memory_stats，完全不含门状态/attempt/manifest 等断言所需明细），则冲突=查错管辖面，而非断言过时；上轮决策记忆中点名的所需字段清单可直接用作覆盖检查表

## Short path
- 从上轮决策记忆/记录中提取待核断言的对象类型与所需明细字段（如门的状态、attempt、manifest SHA）
- 对首个状态面回执做字段覆盖检查：所需字段缺失→该面管辖别的对象，冲突是口径错位，不必追问断言出处
- 枚举状态工具其余维度/回执交叉指针（『详情见 X』），直读拥有该对象的 section，拿到逐项活体清单并就地裁决计数（一致即确认，不一致即报告 delta）
- 沿同一回执打印的逐项 rel_path/ref 做完整性核对；语义问题读状态中点名的实现文件（gate/manifest 扫描逻辑）
- 仅当确认没有任何活面携带该对象字段时，才转为事件流与记录考古

## Stop conditions
- 活体主管面已给出逐项清单，计数可与上轮断言直接对账，且逐项完整性与语义均已核验
- 已确认无任何状态面拥有该对象，断言降级为纯历史问题处理

## Verification
- 主管面计数（如 escalated/pending 各多少）与上轮记忆/记录中的数字可直接对账
- 主管面返回字段覆盖任务所需全部明细，无需再做宽关键词搜索或历史重建

## Counterexamples
- 断言本身是历史事实（『某时刻为何失败』）而非当前状态：没有活面拥有它，事件流/记录考古才是正路，不应硬套状态工具
- 对象只存在于文件或第三方系统、无任何状态工具管辖：主管面=直接文件检查，枚举维度反而绕路
- 首个探测面已包含目标对象全部所需字段：直接继续分析，不为确认而枚举兄弟维度
