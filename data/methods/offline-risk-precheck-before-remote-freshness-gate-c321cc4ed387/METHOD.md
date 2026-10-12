---
method_id: offline-risk-precheck-before-remote-freshness-gate-c321cc4ed387
name: offline-risk-precheck-before-remote-freshness-gate
description: 把『确认无风险再执行』类任务拆成独立未知量，按『最便宜的权威来源优先、可降级检查殿后』排序：当本地跟踪引用已完整枚举待并差异时，先离线完成待并内容确认与 merge-tree 冲突预检，再做一次有界远端刷新；刷新超时只降级为显式 staleness caveat，不重试阻塞、不作为合并安全性的门槛。判定以工具回执中的退出码为准，回执已含退出码则不重跑命令。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:1185:6e7e8131412990ae2ae7
evidence_refs: learning:learn:ff585dc78bc9
created_at: 2026-09-23T16:00:50.858723+00:00
updated_at: 2026-09-23T16:00:50.858723+00:00
---
## Trigger
需要确认一个本地操作（合并/同步/应用变更）安全后再执行，而本地 tracking ref 或缓存已完整枚举待处理差异，远端刷新仅用于确认新鲜度

## Discriminator
status 输出给出 `branch...remote [ahead N, behind M]` 且 remote ref 存在：安全判定的两个未知量（待并集合身份、可合并性）均可离线求解（log + merge-tree），fetch 只回答『上游是否又有更新』这一可降级问题，不在合并安全性的关键路径上

## Short path
- 读本地 status/tracking 输出：识别未知量集合 = {待并内容, 可合并性, ref 新鲜度}
- 离线求解前两个未知量：枚举 HEAD..remote 待并提交身份 + merge-tree 零冲突预检（均不依赖网络）
- 再尝试一次有界远端刷新求解新鲜度；首次超时即分类为网络不可达，降级为『本地 ref + 显式 staleness caveat』，不串行重试阻塞
- 预检 clean 后执行本地操作（merge 本地 tracking ref），操作后确认差异计数归零且结果包含预期变更
- 用自带测试验证；以工具回执中的退出码为判定依据，回执已含退出码则不重跑命令

## Stop conditions
- 待并集合已由本地 log 确认、merge-tree 预检零冲突、操作成功、验证命令 exit=0、ahead/behind 差异归零——停止并汇报
- 远端刷新一次超时且本地 ref 已能枚举全部待并差异——停止重试，带显式 caveat 前进

## Verification
- 操作后 status 显示 behind 归零，且结果提交（merge commit）包含预检时确认的全部预期变更
- 验证命令退出码为 0：直接读工具回执头部，不为看统计行而重跑
- 结论中显式记录所用 ref 的来源/时间戳，使 staleness 假设可被下游审计

## Counterexamples
- 本地无 tracking ref 或为 shallow/grafted 克隆，log/merge-tree 结果不可信——必须先 fetch 才能宣称安全
- 远端历史被 force-push 重写：本地 ref 计数看似一致但内容错位，需 fetch 比对 ref 身份而非仅看 ahead/behind 计数
- 用户意图显式要求拿到『此刻最新上游』（如几分钟前的热修）：用 stale ref 合并虽零冲突但不满足意图，fetch 成为关键未知量，不可降级
- 待并改动是纯语义/API 变更：merge-tree 零冲突不代表安全，测试验证步骤不可省略
