---
method_id: failed-action-keyed-ledger-lookup-then-prescribed-remediation-efed0f93c3f4
name: failed-action-keyed-ledger-lookup-then-prescribed-remediation
description: 当异步控制面操作卡住/失败且其精确 action_id 已知时，直接按键检索该操作自身的台账记录（按 ID find/glob），而不是枚举目录结构或盲目重试。读取 detail/problem_kind/next_step；独立验证记录中陈述的前置条件（如仓库 HEAD 与记录的 actual/desired 是否一致）；再按记录提示或既有成功调用的参数形态执行规定的补救序列，最后才重新发起原操作。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:1347:7f716cb7b028715b057f
evidence_refs: learning:learn:25da715bd205
created_at: 2026-09-24T02:04:49.079500+00:00
updated_at: 2026-09-24T02:04:49.079500+00:00
---
## Trigger
状态/审计结果或先前提交已给出失败异步操作的精确 action_id 及终态（failed），且按该 ID 键存的逐操作记录存在；当前未知量是失败原因与安全重发路径

## Discriminator
在做任何文件系统探测之前，已从状态/审计输出中持有精确的失败 action_id 与终态 failed——该 ID 对应的记录文件是唯一因果下一跳，其中含 failure detail 与机器给出的补救提示（含所需参数提示），无需枚举目录布局来发现它

## Short path
- 从状态输出提取失败 action_id 与终态；未知量=失败原因
- 按键检索：在台账根下按精确 ID find/glob 记录文件（如 'svc-<id>*.json'），读取完整记录的 detail/problem_kind/next_step
- 对独立事实核验记录前置条件：git status/HEAD 须与记录的 actual head 一致且树干净；不一致先调和
- 按 next_step 规定执行补救（先把 desired 推进到当前 HEAD），参数形态取自记录内 argv 提示或先前被受理的调用（如必须的 code_root、合法 target 枚举）
- 以合法参数与新的 expected_generation 重新发起原操作，取得新 action_id，接受两阶段/轮询终态后停止

## Stop conditions
- 已取得含 detail/next_step 的完整记录——停止目录探测与宽枚举
- 前置条件（树干净、HEAD 与记录 actual 一致）已核验后才重发
- 重发操作已被受理（返回新 action_id 与 expected_generation），不再追加探测

## Verification
- 记录中的 actual git_head 与独立检查的仓库 HEAD/status 一致
- 补救结果（publish 的 git_head/generation）与当前代码树一致，且成为重发操作的 expected_generation
- 发布时 tracked 树 0 处修改，无未验证假设

## Counterexamples
- 操作仍处 pending/瞬时超时而非终态 failed——应轮询等待，不要进入补救路径
- 记录的 detail/next_step 均为空——按键记录是死路，应扩大到服务日志/运行时状态
- 控制面提供按 ID 直接查询的 API——应使用该 API 而非文件系统 glob（方法核心是按键检索，不是文件系统本身）
- 工作树脏或 HEAD 与记录 actual 不符——publish-then-restart 不安全，须先调和树/版本
