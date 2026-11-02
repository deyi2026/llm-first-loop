---
method_id: classify-gate-failures-verdict-vs-infra-before-redesign-c4b0e86f02e4
name: classify-gate-failures-verdict-vs-infra-before-redesign
description: 门禁/审查类控制连续多轮失败（PASS、LLM 超时、qualification=REVISE、取消混杂）而被问『这设计是不是错了/要不要重新设计』时，先只用结构化回执建逐轮失败画像，把每轮分类为：真裁决失败 vs 基础设施失败（REVISE + reviewer_timeout ⇒ 没人看过，不是被否）vs 取消。再直读闸的输入冻结定义与预算常量，裁决成本/超时是否由无界范围（整棵工作树而非本次 delta）驱动——超时往往是范围的症状而非预算问题。结论保住已被验证有效的控制不变量（fail-closed、独立审查、SHA 绑定）不削弱，只按杠杆列边界修复：范围 bound > 失败语义分离（增 UNAVAILABLE 类）> 重试/模型回退 > 缓存/预算预检。核心是避免把『没裁决』当『要改产物』，也避免把基础设施抖动误判为控制设计错误。
aliases: 闸门反复超时算设计缺陷吗, REVISE但reviewer超时是没裁决不是被打回, 门禁失败先分裁决失败还是基础设施失败, 审查范围整棵树导致token超时怎么收窄, 评审闸该削弱还是只修工程边界, 逐轮失败画像表归因门禁设计
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:4578:34d94ac8a205a7dd10f5
evidence_refs: learning:learn:0d6545cb5fda
created_at: 2026-11-01T22:27:51.062903+08:00
updated_at: 2026-11-01T22:27:51.062903+08:00
---
## Trigger
门禁/审查/准入类控制在同一任务里连续多轮失败（PASS、超时、REVISE、取消混杂），用户问『这设计是不是有问题/要不要重新优化设计』时

## Discriminator
结构化回执自身携带两个正交字段：裁决语义（qualification=REVISE/PASS）与失败原因（reason=reviewer_failed:reviewer_timeout + LLMTimeoutError 错误尾）。REVISE 与 reviewer_timeout 同现 ⇒ 本轮『没人看过』而非『被否』，这一矛盾在第一张失败回执里就可见；再配逐轮回执的输入规模读数（如 208K tokens vs 本次实际改动约 500 行），审查范围是否无界当场可判，无需先扫全代码库。

## Short path
- 用回执读数（不是印象）列逐轮失败画像：输入 tokens、结构化结局、耗时；每轮分类为 真裁决失败 / 基础设施失败(未裁决) / 取消-pending
- 从回执字段本身分离语义：qualification=REVISE ∧ reason=reviewer_timeout ⇒ 未裁决而非被否；任何 while qualification!=PASS 的自动化都会去修不存在的缺陷
- 直读该闸的输入冻结/范围定义（full_test 冻结什么、有无 scope 参数）与预算常量（审查模型、重试集、总时限系数），裁决成本是否被调用方改动 bound
- 归因排序：若最贵的轮恰是超时轮且冻结范围无界（整树而非 delta），超时是范围的症状而非预算调小；按杠杆排修复：范围 bound > 语义分离 > 重试/模型回退 > 缓存/预检
- 结论保住被验证有效的控制不变量（fail-closed、独立只读审查、SHA 绑定，引用其抓到过真 P0 的证据）不削弱，只改工程边界
- 收尾如实暴露未决轮（已取消/未结算），给出『等 provider 重试 vs 用户显式豁免』两条路径，不自我豁免、不替用户选

## Stop conditions
- 每轮结局均已由结构化回执分类，且每个根因（范围无界/语义混淆/重试缺口）都有回执或源码直读证据支撑
- 用户问题（设计对错 + 改哪里）已可回答；不再枚举与该闸失败路径无关的子系统 timeout（如子代理 runner 的等待逻辑）

## Verification
- 复核 REVISE+reviewer_timeout 轮是否真零裁决产出（input tokens=0、review_answer 仅含错误尾）
- 复核最贵 PASS 轮的输入规模 vs 本次实际改动行数，确认膨胀来自无关在途工作而非本次改动
- 逐条检查修复建议未削弱 fail-closed 判据（如 P0/P1=0 才放行、裁决缺失仍不放行）

## Counterexamples
- 失败全是完成审查后的真实 REVISE/BLOCK（带 findings 清单）⇒ 该审的是判据/检查单本身，范围与超时归因不适用
- 闸很便宜、从不超时的单次失败 ⇒ 不值得建逐轮画像表，直接读那张回执即可
- 超时源于合法的超大改动本身（本次 delta 就是巨大）⇒ 正确修法是拆分改动分批过闸，而非给闸加 scope 窄化参数
