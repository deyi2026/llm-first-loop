---
method_id: audit-context-token-leaks-across-rejection-early-returns-fe7c8efd74ed
name: audit-context-token-leaks-across-rejection-early-returns
description: 在多阶段资源预留序列中，contextvar token / 临时 scope 在 set 之后、唯一 cleanup finally 之前的任何提前 return（拒绝/失败路径：prepare 失败、fleet/深度/scope 拒绝等）都是泄漏点，会永久污染父上下文；成功路径恢复测试通过不能证明无泄漏。做法：实现前枚举 set 之后全部退出边，用单一 try/finally 收拢所有提前返回（结构性修复优于逐点补 reset），并为每条拒绝路径补『父上下文未污染』回归断言。本集 P1（scope_token 在 prepare/fleet 两条拒绝路径泄漏）由首轮对抗评审抓出后才返工二轮通过，验证了此判别式的价值。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:78fffae1-3786-4a53-9158-71e2847e5ab7:856:06a113497882482f03af
evidence_refs: learning:learn:d8b585710b11
created_at: 2026-10-16T21:14:03.777250+08:00
updated_at: 2026-10-16T21:14:03.777250+08:00
---
## Trigger
编写或修改这样的代码：先 set/acquire contextvar token、临时 scope、句柄等每调用态资源，随后存在多条提前 return/raise 的 fail-fast 拒绝路径（校验拒绝、资源预留失败、配额/深度超限）；或为这类代码编写回归测试、或自查送审前。

## Discriminator
token 的 .set()/acquire 点与唯一 cleanup finally 之间存在的提前退出边数量：只要任一拒绝路径位于 set 之后、finally 之前，它就是确定的可枚举泄漏点（源码控制流当时即完全可见），无需等运行期症状或评审发现。

## Short path
- 实现 cleanup 前先枚举资源 set/acquire 之后的所有 return/raise 边，形成拒绝路径清单（每个 fail-fast 分支一行），这是本步要解决的唯一未知量：泄漏面有多大
- 结构性优先：把全部提前返回收拢进同一个 try/finally，使控制流图保证不存在绕过 finally 的退出边，而不是在每个泄漏点手工补 reset
- 为清单上每条拒绝路径写一条回归断言：拒绝返回后父线程 contextvar/scope 恢复调用前取值；成功路径的恢复测试仅作对照
- 提交/送审前自检：在 set 与 finally 之间 grep return/raise 应计数为零，且测试矩阵覆盖退出边全集而非只有成功路径

## Stop conditions
- 所有 set() 之后的控制流边均经唯一 finally，且每条拒绝路径都有对应『父上下文干净』的测试
- 评审不再出现『仅成功路径被测』或『拒绝路径泄漏』类发现，即可停止该审计

## Verification
- 逐条拒绝路径运行测试并断言：拒绝后父线程读取的 contextvar 值等于调用前快照值（而非仅断言成功路径恢复）
- 静态检查：token set 与 finally 之间无裸 return/raise；新增拒绝分支时该清单必须同步加一行测试

## Counterexamples
- 若全部拒绝判定先于 token set（先完整 fail-fast 再获取资源），成功路径测试已足够，不必为收拢而重构
- 框架为每次调用新建独立 context、无共享父 context 可污染时，泄漏机制不存在，不适用
- 进程退出即释放、无跨调用污染语义的一次性资源（非 contextvar/scope 类）不适用本判别式
