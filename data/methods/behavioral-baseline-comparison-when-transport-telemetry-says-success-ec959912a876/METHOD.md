---
method_id: behavioral-baseline-comparison-when-transport-telemetry-says-success-ec959912a876
name: behavioral-baseline-comparison-when-transport-telemetry-says-success
description: 当传输层回执全部 success（settled/committed 零失败、收割 100%）而用户报告远端模型输出异常（空回复、失忆式重复取数）时，不要从 outcome 计数或旧证据库关键词检索里找答案——settle 类事件只携带 outcome 字段，成功计数不含质量。直接解析落盘会话记录，对比失败期与历史好基线的行为签名：空回复比例、退化式重复调用（反复 fetch 同一 URL=远端看不到上下文）vs 递进式工具序列；再用本方 ingress/limit 字段排除己方截断，用部署 manifest+进程启动时刻+重启回执确认故障窗口内实际 serving 构建（commit 时刻≠serving build）。己方全清后，远端侧变化只能输出为显式标注的最佳假设。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:592:45b86af73bf13c250711
evidence_refs: learning:learn:fea7affc7c2e
created_at: 2026-10-11T18:34:32.693979+08:00
updated_at: 2026-10-11T18:34:32.693979+08:00
---
## Trigger
传输层指标全部 success 但用户报告远端模型行为异常（空回复/上下文失忆/循环重取），疑似远端回归，且存在历史正常期的落盘会话记录可比。

## Discriminator
本集可机械确认：provider.call.settled 仅含 {call_id,outcome,settled_at}——成功计数不承载内容质量；而 message.appended 与工具调用记录承载空回复比例与调用形态，是行为证据的唯一载体。用户纠正（'之前一直能用'）在动手前就确定历史落盘会话即为好基线。

## Short path
- 先枚举事件类型词表（一次类型计数）定位承载消息内容的记录类型，不猜字段名。未知量：质量数据在哪。
- 解析失败期会话消息，量化空回复比例（如 72/74 零文本）。未知量：输出是否真异常。
- 解析历史同规模会话的消息与工具序列，对比行为签名：基线回复长度分布 vs 空、重复同 URL 调用 vs 递进序列。未知量：同输入以前是否正常。
- 读本方 request.meta 的 ingress/limit 字段与 truncation 标记，排除己方截断。未知量：是否我们截的。
- 用部署 manifest+进程启动时刻+重启回执锁定窗口内实际 serving 构建，diff 窗口内变更核行为影响；己方全清则输出标注为假设的远端侧结论并停止。

## Stop conditions
- 失败期与历史基线行为签名无实质差异，或本方截断字段确有触发——转入本方修复路径，停止远端归因。
- 本方 ingress/limit 无触发、窗口内部署 diff 无行为改动、行为签名指向远端——归因已到可观测边界，输出带'最佳假设'标签的结论并停止，不再追本方证据。

## Verification
- 空回复比例与退化调用模式由落盘消息/工具记录直接统计复算，而非由 telemetry 计数推断。
- serving 构建由 runtime manifest、进程启动时间、重启回执三方交叉一致确认。
- 最终回复中远端侧归因显式标注'最佳假设而非已证事实'。

## Counterexamples
- 失败伴随真实传输错误（timeout/4xx/收割失败）——settle 回执本身即判别证据，直接走传输排障，无需行为基线对比。
- 无历史落盘会话或首次部署——没有好基线可比，改用受控最小重放/A/B 实验（属 method-root-cause 路径）。
- 本方 ingress/limit 字段显示截断确有触发——先修本方上下文策略，此时远端假设是误导。
- 少量空回复属正常工具轮间隙（历史基线同样存在）——须按比例与序列形态判别，不能见空轮即判故障。
