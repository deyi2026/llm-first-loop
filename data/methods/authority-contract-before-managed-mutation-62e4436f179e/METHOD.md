---
method_id: authority-contract-before-managed-mutation-62e4436f179e
name: authority-contract-before-managed-mutation
description: 在受管 desired-state 控制面执行变更前，先从契约（工具 schema、源码注释、清单字段）确认动作权限归属：若 desired 状态被明确标注为 operator-published，且自己的工具面只暴露只读/重启类动词，则把'发布'归为 operator 手工步骤，而不是先假设自己能跑全部 CLI 再靠拦截报错学习边界。自己的职责收敛为：只读核验前置（HEAD、工作树干净、绑定产物新鲜度，源码有变更则先测试再重建产物）→ 从源码提取 CLI 签名，组装带 CAS expected-generation 的精确命令与预期输出交给 operator → 待确认后用自己拥有的 restart 动词执行并轮询愈合、canary 收尾。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:1853:e70f7ac470984a1eafa5
evidence_refs: learning:learn:81ce1a230be4
created_at: 2026-09-19T08:20:23.014479+00:00
updated_at: 2026-09-19T08:20:23.014479+00:00
---
## Trigger
用户要求在带 CAS generation 的受管生命周期/desired-state 服务上执行发布、重启等状态变更，且模型只通过受限工具面（或共享拦截层）操作该系统

## Discriminator
尝试变更之前已经在工具输出里读到的角色归属事实：源码注释明确写着 'desired: operator-published deployment'（且工具契约只提供 status/restart）。这一条当时就足以把候选动作从'我自己执行 publish'收缩为'备齐前置+精确命令交 operator 执行'，无需等拦截报错

## Short path
- 调控制面只读 status，取当前 desired generation 与绑定（未知量：现状与 CAS expected-generation）
- 读工具 schema 与关键源码注释，确认角色归属与自己的动词集（未知量：publish 归谁、发布绑定哪些字段）
- 若发布属 operator：只读核验 HEAD/工作树干净；diff 上一 desired 提交..当前 HEAD 判断绑定构建产物是否过期，过期则跑相关测试后重建（未知量：前置是否全部满足）
- 从源码提取发布 CLI 签名，组装含 expected-generation 与根路径的精确命令，附预期成功输出（新一代号、当前 HEAD、新产物哈希），一次性交给 operator
- operator 确认后：用自己工具面的 restart 动词携带新 expected_generation 执行，轮询 status 至新 PID、live 绑定与 stable 收据愈合到新一代，canary 验证后收尾

## Stop conditions
- 契约显示发布动词在自己的工具面内 → 直接自行执行 CAS，不做 handoff
- 无任何角色标注且无拦截证据 → 允许一次廉价探测；被拦截即转 handoff，不重复尝试同一路径
- 前置核验失败（工作树脏、产物无法重建、门禁测试红）→ 停止并上报，不把命令交给 operator
- restart 后 status 显示各进程新 PID、live git_head 等于 desired、收据愈合 → 任务完成，停止轮询

## Verification
- operator 命令的预期输出：generation = expected+1、git_head = 当前物理 HEAD、新的构建产物哈希
- restart 后 status：live 绑定与 desired 一致、restart_required 归 false、stable 收据 generation 匹配新一代
- canary：健康端点鉴权行为正常，build 标识包含新提交的 short sha

## Counterexamples
- 工具 schema 本身向模型暴露 publish/deploy 动词 → 应直接用工具执行 CAS 发布，做 operator handoff 反而增加摩擦与延迟
- 无共享拦截层的单机脚本环境（单用户、无权限边界）→ 直接执行是默认正确动作，先查权限契约纯属浪费
- desired 状态由 CI/外部系统自动发布 → 没有人工 publish 步骤，应等待并轮询外部发布者推进 generation，而不是交命令给 operator
- 源码中的 operator-published 只是历史惯例描述、CLI 实际对本地所有进程开放 → 一次探测即可澄清边界，不应零探测直接 handoff
