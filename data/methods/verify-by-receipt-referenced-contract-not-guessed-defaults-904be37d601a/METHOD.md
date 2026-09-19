---
method_id: verify-by-receipt-referenced-contract-not-guessed-defaults-904be37d601a
name: verify-by-receipt-referenced-contract-not-guessed-defaults
description: 验证自动化/服务控制动作的实际效果时，先从动作回执自身引用的东西（detail 中点名的执行脚本、deployment_id、状态存储目录）推导验证契约——canonical 端口、就绪端点、停止判定源、状态文件位置——再按契约定向探测运行时。若发现运行时比被验动作更新，切换为验证当前运行血统是否包含目标变更。避免先猜默认端口/文件名、失败后全量扫描再逐个排除可疑进程。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:010fcc8e-3ba8-4948-9ae5-66a30cc8ea6e:642:be7121ee5cdb09fdd9f2
evidence_refs: learning:learn:a57c9dbab168
created_at: 2026-09-17T15:07:00.103474+00:00
updated_at: 2026-09-17T15:07:00.103474+00:00
---
## Trigger
手握一个自动化/服务控制动作回执（含执行脚本名、deployment_id、generation 等字段），需要验证该动作对运行时的实际效果

## Discriminator
回执 detail 已明确命名执行脚本（如 restart_mirror rc=0），且同批探测中已知状态文件路径（如心跳文件）解析成功——说明端口/端点/判定源可由该脚本与 data/runtime 状态目录权威导出，当时就无需猜默认端口或猜文件名

## Short path
- 读动作回执终态（status/generation/deployment_id），明确本次要验证的未知量
- 读回执 detail 点名的执行脚本，提取 canonical 端口、就绪端点、停止判定源、状态文件位置
- 按契约定向探测：目标端口 lsof + 就绪端点 GET + manifest/心跳，取得 pid/worktree/head/启动时间
- 若运行时 generation/时间戳晚于被验动作：查动作历史与 git log，验证当前运行 head 是否包含目标提交（血统包含而非动作终态）
- 端点状态码、manifest、进程实况三者交叉一致即停止

## Stop conditions
- 就绪端点在契约端口返回预期状态，且 manifest 的 pid/head 与进程实况一致
- 世界已前进时：当前运行 head 已确认包含目标变更提交
- 回执引用的脚本/状态存储不可得：停止契约推导，转入服务发现分支

## Verification
- 端点探测必须打在从脚本/配置解析出的端口上，而非扫描到的任意监听端口
- 交叉核对三源：manifest.git_head ↔ ps 进程启动时间 ↔ service-control-action 记录
- 血统验证用 git log 包含性检查，不能只看 generation 数字

## Counterexamples
- 回执不引用任何本地脚本或状态存储（远程编排系统）→ 无契约可推导，必须回退到端口扫描/服务发现
- 脚本声明的端口被环境动态覆盖（如 WEB_PORT 经 resolver 解析，注释只给默认值）→ 仍需以实际解析值/实际监听确认，不能只信注释
- 只需回答'是否有服务在监听'这类无身份要求的问题 → 宽扫描更便宜，先读脚本反而绕远
- 状态文件由 runner 写入但可靠性存疑（可能滞后或不更新）→ manifest 不能当唯一真值，需进程级探测佐证
