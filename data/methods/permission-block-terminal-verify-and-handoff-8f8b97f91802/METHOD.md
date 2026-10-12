---
method_id: permission-block-terminal-verify-and-handoff-8f8b97f91802
name: permission-block-terminal-verify-and-handoff
description: 当共享/持久状态变更（publish、部署 generation 推进等）被回执拒绝，且回执明确是角色/控制面级权限限制（operator control-plane only，模型只能用受限控制面工具）时，把该回执视为终局：不再枚举脚本/CLI/目录寻找模型侧旁路；转为（1）用只读 status 核实现状，（2）实际验证操作者执行所需前置条件，（3）给出精确交接命令与发布后的接手计划，并在回复中把“技术完成”与“权限阻塞”分开陈述。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:851:b779ee1f714334af7cb6
evidence_refs: learning:learn:9e454de4d77e
created_at: 2026-09-20T17:13:38.632932+00:00
updated_at: 2026-09-20T17:13:38.632932+00:00
---
## Trigger
需要对共享/持久状态做变更（publish、部署、desired-state 推进）时，一次调用被回执拒绝，且回执声明该操作属于 operator/control-plane 专有、模型只能使用某个 action 受限的控制面工具

## Discriminator
当时已可见的两条事实：（a）被拒回执属角色/控制面级限制而非参数错误（原文声明 operator control-plane only，模型调用走 service_control）；（b）模型侧控制面工具的 action enum 仅含 status/restart，不含目标操作。二者足以把“模型还能怎么发布”收敛为“不能，只能交接”

## Short path
- 核对后台任务回执（exit/rc/日志尾部）确认技术部分（如门禁）是否完成
- 用控制面工具 status 或权威部署 store 读 desired/live generation 与 git_head，判断发布是否已发生
- 读控制面工具 schema（或至多一次探测）确认模型 action surface 是否含目标变更
- 若属角色级边界：立即停止入口枚举（不再 ls/grep 脚本找旁路），转而实际验证操作者执行的前置条件（worktree clean、artifact 存在、HEAD 正确）
- 回复分两栏：已完成（带证据）与权限阻塞（引用回执原文），附与实际 usage 一致的精确交接命令，及发布后接手计划（如 restart(web, expected_generation=N) 再复核 pid/git_head）

## Stop conditions
- 已确认模型 action surface 不含该变更，且交接命令的全部前置条件均已实际核验（非假设）
- 或变更已在授权路径内成功，且 live 状态（generation/git_head/pid）复核一致后停止

## Verification
- 最终回复明确区分技术完成与权限阻塞，阻塞结论引用被拒回执原文而非猜测
- 交接命令与实际查到的 CLI usage/schema 参数一致，未凭记忆拼接
- 承诺的后续动作参数（如 expected_generation）取自最新一次 status 读数而非旧值或臆测

## Counterexamples
- 回执仅指出用法错误（如 --data-dir 指向非真实 store、缺必填 flag）——应修正调用而非交接
- 目标操作本就在控制面工具 enum 内（restart/verify）——直接带观察到的 expected_generation 调用并复核，无需操作者介入
- 边界消息未声明排他且存在明确授权给模型的官方包装脚本——先读其 usage 再用，不算旁路
