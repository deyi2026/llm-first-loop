---
method_id: establish-actor-authority-before-remediation-path-17da98049b61
name: establish-actor-authority-before-remediation-path
description: 当动作被 fail-closed 的合同闸拒绝（如部署绑定 git_head/generation 不匹配 + 脏 worktree）时，先确认'谁有权推进被钉记录'，再重建修复路径。闸门模块自身的文档与命令分层往往在首次定向读取时已声明记录的发布角色（operator-published / operator control-plane only）。若发布者是操作员而非模型，终态动作应是 handoff：备齐前置条件（清理 tracked worktree 并记录改动去向、留存审计快照、确认构建产物是否需重建）并给出精确命令与验收计划；而不是枚举脚本目录、深读 CAS 内部、为'自己执行'重构整条发布流程后撞终态硬拦。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:2515:660bdd923496cc971174
evidence_refs: learning:learn:c251c6199ff8
created_at: 2026-09-22T16:41:23.981703+00:00
updated_at: 2026-09-22T16:41:23.981703+00:00
---
## Trigger
控制面动作在 fail-closed 闸门失败，回执指向被钉定的 managed 合同/记录（pinned head、generation、clean-worktree 校验），修复需推进该记录；且对闸门模块的首次定向读取已暴露该记录的发布者角色声明。

## Discriminator
失败回执本身给出确切闸门与被比较字段（desired/actual head、generation、dirty 标志），而闸门模块首次 grep 输出即含角色声明（如 'ManagedServiceDeployment is operator-published desired deployment identity'）与 operator 控制面子命令——这把'如何修'缩成'谁来修'：发布者非模型时，终局是准备移交而非执行。

## Short path
- 解析失败回执，命名闸门与比较字段（desired/actual git_head、generation、tracked dirty），未知量：哪条被钉记录在拒绝我。
- 读被钉记录本体与闸门模块头部角色声明，未知量：记录如何合法推进、哪个 actor 有权推进。
- 用一次廉价授权确认（grep 控制面专属闸字符串/只读查看命令分层）替代为'自己执行'重建全流程；确认 operator-only 后立即把目标改为移交。
- 只备移交所需前置：stash 脏改动并记录去向、审计快照、检查新 head 是否改动 tracked 构建产物以决定是否需重建。
- 输出与当前 generation/roots 一致的精确发布命令，附发布后自己要跑的验收（回执 head/代数、pid 更新、健康检查），到授权边界即停，不绕闸不重试同参数。

## Stop conditions
- 授权归属已由可验证事实证明；若 operator-only，移交包（命令+前置+验收计划）已交付。
- 不以相同参数重试被拒动作，不寻找旁路入口执行控制面专属命令。

## Verification
- 移交命令的 expected-generation/code-root/runtime-root 与当前被钉记录逐字段一致。
- 闸门将检查的前置（tracked clean、head 匹配）在移交前已满足或已在包中显式说明。
- operator 发布后重签动作，回执 git_head/generation 与新记录一致，服务 pid 与健康检查更新。

## Counterexamples
- 失败闸门针对模型自己拥有且可写的状态（自身工具的配置/数据文件）：直接修复即可，先查授权是多余一步。
- 源码角色声明过期，或存在模型可调用的等价子命令：授权检查必须落到可验证事实，不能因一句文档就假设 operator-only 而停手。
- 失败是瞬态（锁竞争、超时）而非合同不匹配：走重试/退避路径，不应推进 generation 或做移交。
