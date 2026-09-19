---
method_id: authority-gate-drift-map-before-lifecycle-plan-23f0e2d2ae69
name: authority-gate-drift-map-before-lifecycle-plan
description: 在含 operator-only 步骤的共享服务生命周期任务里，排定执行顺序前先从已读 artifact 建立三张图：authority map（模型工具面 enum 里有哪些动作、哪些是 operator-only）、gate map（重启忙闸/run-lock 按 target 的作用范围）、drift map（live manifest vs deployment vs main 的代际差）。若执行体在 spawn 时从 desired 记录加载代码（而非依赖已运行服务），则中间代重启无收益：应先完成代码、一次 publish 到最终 commit，再按闸域排序重启——无闸 target 会话内完成，会吃 requester run-lock 的 target dispatch 后立即结束回合。本集原计划 gen31/gen32 两次 publish 加一次中间代 feishu 重启，中途才修正为一次 publish 收全部；修正所需的全部事实（publish 是 operator-only、feishu 不吃 web run-lock、worker 从 deployment.code_root 加载）在排计划时均已读到，只是未用于计划推导。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:823:9e35528087104eab2c89
evidence_refs: learning:learn:921bcda5db9b
created_at: 2026-09-18T14:34:09.261293+00:00
updated_at: 2026-09-18T14:34:09.261293+00:00
---
## Trigger
任务需要对共享常驻服务执行 restart/publish 类生命周期变更，且动作权限分层（部分动作 operator-only、模型调用会被 guard 拦截）、各服务存在多代代码漂移

## Discriminator
排执行顺序前已可观察的事实组合：(1) 模型工具面 enum 仅 status/restart，模块 docstring 明示 deployment 为 operator-published——每次 generation 变更都消耗一次人工/被拦截的尝试；(2) 重启脚本忙闸只对会检查 requester run-lock 的 target 生效，其余 target 会话内重启安全且无时间压力；(3) worker spawn 代码显示 code_root/runtime_root 取自 deployment 记录——新代码随下次 spawn 生效，先重启服务买不到任何东西；(4) live manifest 显示部分服务落后两代——任何中间代重启必被最终代立即取代。

## Short path
- 从 status/deployment 回执提取 code_root/runtime_root/generation 作为权威路径，后续命令与文件访问一律引用回执字段，不假设默认 workdir（避免 /workspace 类参数失败）
- 读控制面模块与模型工具面定义，产出 authority map：哪些动作我能调、哪些是 operator-only、状态机有哪些态
- 读重启脚本的忙闸作用域 + 最近 experience/失败记录 + 历史 action 终态，产出 gate/failure map：哪些 target 会自锁于 requester run-lock、已知失败模式是什么
- 读各服务 live manifest 与 worker spawn 代码，确认新代码加载时机（spawn 时取自 deployment 记录）与代际漂移范围
- 由三张图推导最小计划：先在 worktree 完成代码与测试 → 一次 publish 到最终 commit（附精确 operator 命令，被拦截即如实移交）→ 无闸 target 会话内重启 → 自锁 target dispatch 后立即结束回合 → 校验全部 runtime_manifest 的 git_head 等于最终 commit

## Stop conditions
- 全部 live runtime_manifest 的 git_head == 最终发布 commit，且无 restart action 终态 failed
- operator-only 边界被拦截时停止尝试并移交精确命令，不寻找绕过路径
- 执行中发现 authority/gate/drift 任一事实与回执矛盾（如闸作用域与预期不符），先重推计划再继续

## Verification
- 逐服务比对 runtime_manifest.<svc>.json 的 git_head 与 deployment 记录的 git_head
- 检查 service-control action 终态，确认无 active_run_precheck_failed / restart rc=1 复发
- 确认全程只发生一次 publish，且没有对中间代的重启动作（无被最终代立即取代的重启）

## Counterexamples
- 运行中的服务本身必须执行新逻辑才能保证下一步安全（worker/执行体不从 deployment.code_root 加载新代码，或工具面需先接受新 target）时，分代暂存重启是必要的，一次 publish 批量化反而错误
- publish 对模型可用且廉价（无 operator 边界）时，最小化 publish 次数不是约束，按需重启即可
- 忙闸对所有 target 生效（共享锁、不分 target）时，不存在'无闸 target 先行'的排序自由度，一切生命周期动作都需回合结束交接或人工执行
- 某服务在旧代码上已崩溃并阻塞当前开发时，立即的中间代重启是正当的，不应为省一次重启而推迟
