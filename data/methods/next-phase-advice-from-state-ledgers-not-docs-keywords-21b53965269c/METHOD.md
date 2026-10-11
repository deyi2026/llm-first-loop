---
method_id: next-phase-advice-from-state-ledgers-not-docs-keywords-21b53965269c
name: next-phase-advice-from-state-ledgers-not-docs-keywords
description: 为『下一阶段/接下来做什么』类规划请求取证时，优先从按构造就在追踪状态迁移的账本取材：版本库 tag..HEAD delta（刚落地未验证）、records 的 status/age 字段（积压/超龄）、运行代匹配标志（已收口/未收口）；而不是在 prose docs 语料库中换词反复检索 todo/遗留/roadmap。首次关键词未命中的回执若已枚举该语料库最近文档清单，这本身就是『此处无活待办账本』的负证据，继续换词属可预见空转。每条建议锚定一条可验证 ledger 事实（commit/record 状态+卡龄/状态标志），锚不全的条目降级为推测并标注。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:40eeca85-e561-4f26-9faf-efda5823cb4b:251:f3497407bcb99d78ac56
evidence_refs: learning:learn:9501c2933f3b
created_at: 2026-10-11T01:38:38.967691+08:00
updated_at: 2026-10-11T01:38:38.967691+08:00
---
## Trigger
用户要求基于系统当前真实状态给出『下一阶段/接下来建议』类回答，且事前没有可直接引用的活 roadmap 或待办文档

## Discriminator
docs 首次 todo/roadmap 类关键词未命中且回执已枚举语料库最近文档清单（其中无待办账本）——此刻该语料库对『待办』这一未知量的信息量已耗尽；而 git tag..HEAD delta 与 records 的 status/age 字段按构造就分别回答『刚落地但未在运行态验证』与『积压了多久』两个未知量

## Short path
- 先读当前终态快照（屏障/服务状态/运行代与期望代是否匹配），确认建议锚在新鲜事实上
- 取版本库 tag..HEAD delta 回答『刚落地但尚未验证的是什么』，每条此类变化直接生成一条『真实验证』建议
- 查 records 的 status/age 字段回答『哪些事项正积压/超龄』，按收益排序生成主线建议
- docs 检索至多一次；若未命中且回执给出语料库最近文档清单，把该清单当负证据，立即转 ledger 而非换词重搜
- 每条建议映射到一条具体 ledger 事实（commit、record ref+status+卡龄、generation 标志）后即收敛作答

## Stop conditions
- 每条建议均可指出唯一支撑事实（commit hash / record 状态与卡龄 / 服务状态标志），已知 ledger 覆盖完毕即停止取证
- docs 首次检索未命中且回执已枚举语料库文档清单 → 判定该语料库无活待办账本，不再发起第二次关键词变体检索

## Verification
- 逐条建议回查来源：能给出 commit hash、record ref+status+卡龄或状态回执字段；给不出的条目删除或显式标注为推测
- 机械检查：同一语料库在『miss+清单』回执之后的关键词变体检索次数为 0

## Counterexamples
- 仓库确实维护活的 ROADMAP/TODO 文档且首次检索即命中：直接读该文档作答，不绕道 ledger
- 用户目标是『找出我们把下一步计划写在哪个文档』：找文档即任务本体，miss 后应继续换词/换范围检索，而非宣告语料库为空
- 待办事实既不在 git delta 也不在带 status 字段的 records 中（如仅存在于会话约定或口头承诺）：此时才需要更宽的发现式检索
