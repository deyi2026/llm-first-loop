---
method_id: preflight-no-override-gates-before-issuing-managed-restart-280963e0d9b7
name: preflight-no-override-gates-before-issuing-managed-restart
description: 受管重启前，状态回执自带的 gate_classification 与 compat/audit 信号就是预检结论：exit_action 为空的门是不可 override 的结构性硬门；compat_retirement 等信号若点名本次动作将调用的脚本（如 restart_mirror.sh），就是必须先解决的阻断未知量。先在回执内完成门筛选并做一次环境身份比对再决定是否发起；只有全为可 override 运营门（waiting_for_idle 等）才走『发起→查终态』。对硬门直接发起只会新增挂起的 failed 动作债（本集 2 个）。具体的跨仓 worktree 身份门机制与修复属既有卡 precheck-async-restart-identity-gate…，本卡只管通用的『先读门再发射』判断。
aliases: 重启前先看门有没有出口, exit_action 空的门别硬发, 回执预检不可覆盖门禁, 点名重启脚本的旗标要先解决, 别往硬门里发动作攒 failed
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:826:7b938f437bf23c0945f7
evidence_refs: learning:learn:60720df383eb
created_at: 2026-10-27T23:20:47.043471+08:00
updated_at: 2026-10-27T23:20:47.043471+08:00
---
## Trigger
用户要求重启/使受管服务生效，手中已有一份含 gate_classification（gate→exit_action 映射）与 compat/audit 信号的 desired-state 状态回执，正准备发起 managed 动作时

## Discriminator
发起前回执里已存在两类可筛事实：(1) gate_classification 中与本次动作路径相关的 precheck 行 exit_action 为空（无 override 出口，身份/端口类物理门）；(2) compat_retirement/audit 信号点名了本次动作要执行的脚本路径。任一命中即把未知量从『会不会忙碌超时』缩成『结构上能不能执行』——本集 dual_root 身份门与 restart_mirror.sh 旗标均在发起前已被读到

## Short path
- 从状态回执只抽决策字段：admission_barriers、idle/目标 generation、既有 action 终态；跳过 generation_lag 等纯遥测段落，不通读全 blob
- 发起前解析回执自带的预检未知量：列出与重启路径相关的门，标出 exit_action 为空的硬门；检查 compat/audit 是否点名 restart 脚本
- 命中硬门（如 dual_root 身份门）→ 先做一次环境比对：code_root 的 .git gitdir vs runtime_root 的 git-common-dir，据此决定是否发起
- 身份不一致且无 override 出口 → 不发动作；实测沙箱写边界（write probe）后，交付带预期校验输出的最小沙箱外修复清单，保持 failed 台账不增
- 无硬门、只有可 override 运营门 → 按 exit_action 发起，等待后按 action_id 查终态；succeeded 且 live 身份匹配 desired 即停

## Stop conditions
- 目标服务 terminal=succeeded 且运行态身份与 desired 绑定一致
- 或：硬门已实证阻断 + 已交付含 rev-parse 预期输出的沙箱外修复步骤，且未新增挂起 failed 动作

## Verification
- 发起前：本次动作路径触及的每个 gate_classification 行都有非空 exit_action，或其硬门已被一次环境比对显式排除
- 发起后：以 action_id 查 terminal 状态，不以 accepted 当完成（受理≠完成）
- 修复后：git -C <release> rev-parse --git-common-dir HEAD 第一行指向 runtime 仓 .git、第二行为目标 commit

## Counterexamples
- 回执信号只是历史遥测（generation_lag 长列表）：无动作含义，逐段通读反而是浪费
- compat_retirement 点名的脚本已被托管执行器取代、本次动作不再调用它：旗标与当前路径无关，可直接发起
- 相关门全部有 override 出口（waiting_for_idle、precheck:knowledge_store 等）：按出口规则发起并跟踪终态即可，预诊断仓库身份属多余开销
- 失败是单次瞬时忙碌超时且门带 exit：等待/携证 override 重试即可，不需要结构性诊断
