---
method_id: verify-child-report-receipt-invariants-and-event-log-before-acceptance-ce41f7b04729
name: verify-child-report-receipt-invariants-and-event-log-before-acceptance
description: 子代理/child 的结算报告是对“它实际执行了什么”的主张，不是执行证据。采信前先做两层检查：①机械层——报告引用的回执必须通过内部不变量（同会话顺序调用的累计计数单调递增且等于各次之和、时序自洽）；②仲裁层——执行面主张（某调用被拒绝/护栏生效/预算拦截）必须用该 child 的原始事件日志比对 declared 事件与逐字回执来裁决。本集据此从自洽但失真的 1s/1s/5s 三条回执（顺序 1+1+5 应为 1s/2s/7s）实锤 E5 累计预算跨派发失效并定位 copy_context 根因，同时纠正“确定性拒绝回执”的误述（实为发现面投影，范围外调用根本未被派发）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:807:757c83cace25a14bd2a8
evidence_refs: learning:learn:4e0f7163e26c
created_at: 2026-10-12T09:05:40.139629+08:00
updated_at: 2026-10-12T09:05:40.139629+08:00
---
## Trigger
子代理/child 结算并返回含逐字回执引用与执行面主张（被拒绝、护栏生效、预算如何累计等）的最终报告，且父会话的验收结论或后续动作依赖这些主张时。

## Discriminator
无需额外工具、报告内当时即可检验的事实：①引用回执的内部不变量——同一会话顺序调用的累计计数必须非降且等于各次之和，本集三次回执显示 1s/1s/5s，直接违反单调性；②与父会话既有事实的张力——spawn 回执承诺范围外调用将被确定性拒绝，而 child 报告 read_file 零回执。两条足以把报告从“证据”降级为“待仲裁主张”。

## Short path
- 对报告引用的全部回执做算术/时序一致性核查（累计值、次数与自述动作对账）；发现违例即把整份报告降级为主张
- 列出所有执行面主张，逐条与父会话已知事实相容性标注；不相容者需原始日志仲裁
- 读 child 会话原始事件日志（如 data/event_logs/<child_id>.jsonl），比对 tool.execution.declared 集合与报告声称的调用集合（本集：read_file 从未出现在任何 declared 事件）
- 从日志提取逐字回执确认真实行为（累计值每次重置），再沿实现追根因到真实派发边界（ContextVar + registry 的 copy_context 快照）
- 以日志+代码双源结论落修复提案与教训后停止；不向 child 追问叙述、不重派同类验证

## Stop conditions
- 回执通过不变量核查且全部执行面主张被 declared/execution 事件证实 → 采信报告并收口
- 原始日志已裁决所有争议主张（发生了什么/未发生什么）→ 转入根因分析或修复，不再重复取证
- 日志不可得且主张低风险 → 结论显式标注 unverified，不为审计阻塞流程，也不为复核叙事而重派 child

## Verification
- 对每条引用回执检查累计/序号类字段：单调、求和、与自述顺序一致
- 每条争议主张对应到日志中具体的 declared/receipt 事件；禁止以 child 叙述或“看似逐字的引用”作执行证据
- 涉及“护栏/上限生效”类结论至少需要两次顺序调用的证据——单次调用场景无法区分“每次重置”与“正确累计”（本集上一轮单次 E2E 即因此漏检）

## Counterexamples
- child 报告只涉及其推理/方案，不含执行与回执主张 → 无需日志审计
- 真实的单次调用会话中“累计=本次”本就正确 → 不变量通过，不构成疑点
- 报告已附可与父会话可见事件流对账的 event_id/时间戳 → 抽查即可，不必全文解析日志
- 不要外推为不信任 child 的领域结论（如代码分析内容）；审计对象是执行主张，不是其专业判断
- 日志确实不存在且主张无关紧要时，不要为了“拿到原始证据”而反复重试或重跑 child
