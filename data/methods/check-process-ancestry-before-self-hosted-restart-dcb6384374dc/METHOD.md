---
method_id: check-process-ancestry-before-self-hosted-restart-dcb6384374dc
name: check-process-ancestry-before-self-hosted-restart
description: 在运行时宿主会话内准备执行或建议 restart/stop 某服务（含『现在重启还是挂定时』类选择）时，第一个未知量应是『我的工具进程是否被重启目标托管』：一次 ps 祖先链 + 端口监听者检查即可判定。若宿主是我的直接祖先进程，重启=终止本会话，决策从技术动作变为带代价的用户三选一（我末尾发出但收不到回执/面板重启可自核/挂定时零成本）；capability 拦截回执（E2_CAPABILITY）应读作策略边界而非待破解谜题。避免先试后台 job、再试 setsid 绕行、最后才查祖先链的绕远路径。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7c026852-7867-4a41-9ab0-1340271874dc:417:890f31f65317ae55e60d
evidence_refs: learning:learn:cb4960359350
created_at: 2026-10-22T12:42:07.840583+08:00
updated_at: 2026-10-22T12:42:07.840583+08:00
---
## Trigger
准备对某运行时服务执行或建议 restart/stop（包括『现在重启还是等定时』的选择），且当前工具调用本身运行在该环境的某进程树内；或后台发起的生命周期操作回执显示『job 意外结束』而命令本身无错

## Discriminator
一次本地检查：对当前 shell 走 ps -o pid=,ppid= 祖先链并核对 runtime 端口监听者。若宿主进程（如 python -m llm_loop.runtime.launch web，监听其端口、etime 可对上）是工具进程的直接祖先，则重启目标=杀死本会话；同时 capability 拦截回执本身即『生命周期只能走专用通道』的设计信号

## Short path
- 第一步只解一个未知量『我是否被重启目标托管』：一次祖先链检查 + 端口 owner 核对，先于任何重启机制尝试
- 若宿主是祖先进程：不自发执行重启；把选项与代价摆给用户（末动作发出但回执不可自核 / 面板重启本会话可存活复核 / 挂定时零成本），明确不替用户默认
- 绕行回执被 capability 拦截即停止枚举更多绕行方式，按策略边界处理
- 只为会话可存活的路径定义重启后验证契约（如 /health 的 git_short 与 pid 变化）

## Stop conditions
- 祖先关系已判定，且重启决策已作为带代价的选项交还用户
- 不再对已被 capability 拦截的生命周期路径发起新的绕行尝试

## Verification
- 重启后仅经会话可存活的路径核对指纹（如 /health 的 git_short、pid 变化）
- 自证声明须注明：自行发出重启的回执本会话收不到，不得标记为已验证

## Counterexamples
- 重启目标不是我的祖先进程（外部服务、独立 CI runner、另一主机）——祖先检查无关，直接执行并常规验证
- 专用生命周期工具契约本身保证会话存续或返回终态回执——按工具契约走即可，无需祖先链推导
- 一次性批处理任务，会话随任务结束本就预期死亡——『重启即自杀』不构成决策约束
