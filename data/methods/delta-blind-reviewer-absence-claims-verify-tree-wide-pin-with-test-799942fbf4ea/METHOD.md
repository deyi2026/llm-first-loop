---
method_id: delta-blind-reviewer-absence-claims-verify-tree-wide-pin-with-test-799942fbf4ea
name: delta-blind-reviewer-absence-claims-verify-tree-wide-pin-with-test
description: 范围受限的评审者（只见本批 diff/delta）常把『不在我可见的改动里』误报成『未实现/只改了注解』。收到这类缺失型 finding 时，第一未知量不是怎么改代码，而是缺失是否全仓成立：对 finding 点名的符号做 delta 之外的检索并直读定义与调用点；若实现确在更早提交中，不要改代码迁就审查，而是把 finding 隐含的契约写成反证测试（缺陷真在则测试必红）钉住行为，连同测试重新提交审查。核心是把『按 finding 逐条返工』的大空间缩成一次符号检索的真伪二分加一条测试。
aliases: 审查说没实现怎么反驳, 评审只看diff误报缺失, 被审查冤枉别急着改代码, 拿旧提交里的实现自证, 反例测试钉住契约再重审
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:8337:7547b6f7a62941b0e2d1
evidence_refs: learning:learn:0cada385d9e9
created_at: 2026-11-02T15:52:56.559438+08:00
updated_at: 2026-11-02T15:52:56.559438+08:00
---
## Trigger
独立审查/自动评审以某批 delta/diff 为唯一可见材料，返回『只改注解、读写未实现、缺少某逻辑』类缺失型 finding 并要求返工，而被点名的符号很可能实现于 delta 之外的更早提交

## Discriminator
finding 引用的证据行是否全部落在被审查 delta 内，且其点名符号在 delta 外可检索到真实定义与调用点——收到 finding 当时即可用一次全仓 scoped 符号检索区分『真缺失』与『审查可见窗盲区』

## Short path
- 收到缺失型 finding：先定未知量『缺失是否全仓成立』，禁止先改代码 appease
- 对点名符号做全仓/跨提交 scoped 检索，直读定义与调用点，判定是盲区误报还是真缺失
- 若实现确在 delta 外：不改动实现，把 finding 隐含契约写成反证测试（该缺陷存在时必红、不存在则绿）
- 连同反证测试重新提交同一审查；原 finding 消失且 PASS 即停止

## Stop conditions
- 检索证实 delta 外确有实现、反证测试通过且重审 PASS
- 检索证实全仓确无实现（真缺失）→ 立即转修复路径，本方法终止
- 符号虽存在但定义与调用已漂移不匹配 → 按 finding 实质成立处理，终止

## Verification
- 反证测试断言精确对应 finding 所指契约（如不同 digest 不得复用 PASS），人为破坏实现时必红
- 重审回执中原 finding 不再出现，且本次 diff 无迁就性实现改动
- 确认审查方可见范围确为受限 delta（如批审材料清单/冻结范围），否则盲区假设不成立

## Counterexamples
- 审查范围本就是全仓/整树审计 → 缺失断言大概率真实，直接修而非检索反驳
- 调用点虽存在但签名/路径已漂移（老调用对不上当前定义）→ finding 实质成立需修
- 契约全仓无任何强制（无代码也无测试）→ 应实现功能本身，不能只加测试
- 主观风格/命名类 finding 无可测契约 → 反证测试不适用
