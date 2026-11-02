---
method_id: gate-verdict-follows-live-runtime-version-wait-restart-convergence-befor-0ca19ca2931b
name: gate-verdict-follows-live-runtime-version-wait-restart-convergence-before-rerun
description: 部署被受理≠已生效：当回执显示物理重启被推迟、live 服务仍运行旧 head 时，由常驻 runtime 进程执行的准入/审查闸按旧代码语义评判。立即重跑闸得到的 FAIL 描述的是旧码限制（如缺少 vendored 资产特判的单路径大小上限），不是新部署的质量。把 live_git_head / desired generation 收敛作为重跑闸的前置条件；收敛前的失败一律先判为版本偏移，不据此放宽上限、截断材料或改基线去适配旧码。
aliases: 部署没生效就跑准入等于测旧码, 重启还在排队 gate 先别跑, live 还是旧版本 admission 白跑一轮, waiting_for_requester_exit 时要不要重跑审查闸, 旧进程按旧逻辑拒了新提交, 版本没收敛前审查失败算谁的
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:26f09150-ab38-4082-81e9-9a0a7f5b8b6f:0:115a1f509cb9848ac4ac
evidence_refs: learning:learn:32d76e7a6066
created_at: 2026-10-31T21:38:31.177102+08:00
updated_at: 2026-10-31T21:38:31.177102+08:00
---
## Trigger
刚完成部署/服务更新但回执显示物理重启被推迟（重启动作处于 waiting_for_requester_exit 等非终态，live 服务仍跑旧 head），下一步要由同一常驻 runtime 进程执行的准入/审查闸给出官方判定，且闸逻辑或待验证修复本身位于本次部署的代码集内（提交信息/diff 涉及准入逻辑）。

## Discriminator
部署回执同时给出两个可对比事实：desired generation/git_head 已指向新码，而物理重启动作未执行（如 waiting_for_requester_exit，须等会话退出才重启）⇒ live 进程仍是旧 head。由 live 进程执行的闸只会体现旧代码语义，'部署受理成功'后的立即重跑等于用旧码评判新码。

## Short path
- 读部署回执，先回答唯一先决未知量：runtime 是否已载入新码？判据=重启动作终态且 live_git_head==部署回执 head，而非'部署受理成功'。
- 若闸逻辑/目标修复在被部署 diff 内且重启未执行，跳过立即重跑，改为排程有界续跑：先查服务状态确认收敛，收敛后才重跑闸一次。
- 若闸已被提前重跑且被拒，先用版本偏移解释失败（live=旧码），不据此判定产物不合格，也不深挖代码定位'缺陷'。
- 收敛后重跑闸取官方回执；若收敛后仍同因失败，则版本偏移假设证伪，转为按新码语义定位真实问题。
- 全程不按旧码限制改材料：不放宽上限、不截断 diff、不改基线绕过。

## Stop conditions
- 服务状态中 live_git_head / live generation 与部署回执一致且重启动作已达终态，并已取得收敛后的一次官方闸回执（PASS 或可按新码语义解释的 FAIL）。

## Verification
- 对比部署回执的 git_head 与服务状态里的 live_git_head（或 desired vs live generation）完全一致；
- 收敛后的闸回执不再触发仅旧码才有的限制类错误（如新码已特判的 vendored 大文件仍被单路径大小上限拒绝）。

## Counterexamples
- 闸为每次全新拉起的独立进程/CLI，直接从新 code_root 现场执行（闸代码取自待验树而非常驻服务）——闸已是新码，立即重跑有效，无需等重启；
- 部署为同步重启，回执显示服务已在新 head 上运行——直接跑闸，等待无增益；
- 失败原因与代码版本无关（材料本身超限、命令拼写错误、权限/凭据问题）——等收敛不能修复，应按回执原文本身诊断。
