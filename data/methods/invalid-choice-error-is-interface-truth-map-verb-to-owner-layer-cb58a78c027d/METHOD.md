---
method_id: invalid-choice-error-is-interface-truth-map-verb-to-owner-layer-cb58a78c027d
name: invalid-choice-error-is-interface-truth-map-verb-to-owner-layer
description: argparse 的 invalid choice 错误是机器生成的完整接口枚举，应视为该 CLI 当前接口真值：先据此修正接口模型（失败动词不存在于这一层），再把操作意图映射到真正拥有该动词的层，agent 自有原生工具、注册+worker 两阶段机制、或文档指定的脚本；需要文件系统事实（code_root/路径布局）时，优先用该 CLI 自己已被错误信息证实的只读子命令（show/verify）取得规范元数据，而不是凭记忆猜路径后做宽泛代码考古。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:890:9124e72f00ab231bbba9
evidence_refs: learning:learn:beb5ee1e8fe6
created_at: 2026-09-19T12:20:24.466041+00:00
updated_at: 2026-09-19T12:20:24.466041+00:00
---
## Trigger
CLI/脚本调用以 usage 类错误失败（argparse invalid choice，并列出全部合法子命令），而非超时/网络等瞬时错误；或某个操作意图（如 restart）在当前 CLI 面上不存在，需要找到权威执行入口时。

## Discriminator
错误文本在当时就枚举出完整合法面（choose from publish, show, verify, worker），直接证明 restart 不是该 CLI 的子命令、且这是确定性接口事实而非瞬时故障；同时任务开始时 agent 工具清单里已存在同名 service_control 原生工具，是最可能的权威变更登记入口，CLI 的 worker 只是异步执行器。

## Short path
- 读 usage 错误：合法子命令={publish,show,verify,worker}，确定 restart 不在 CLI 面；待解未知量是：哪一层拥有 restart。
- 检查 agent 自有工具层：环境内 service_control 原生工具的说明/回执若定义 restart/accept/status 语义，即为权威登记入口，无需先读源码。
- 若因此前给错建议而必须核实：用错误信息已证实存在的只读子命令（show --data-dir data）取得 code_root 等规范路径，再在该根下做一次受枚举约束的定向 grep（add_parser/accept_restart），不猜目录、不扫全库。
- 用原生 service_control 以当前 generation 与 target 发起 restart，取得 action_id 收据。
- 遵守回执协议：本轮不轮询，下一轮按文档化路径 status(action_id) 查终态，并向用户报告 action_id 与正确机制。

## Stop conditions
- 变更已被权威层受理，且收据中 action_id 与预期 generation/target 绑定一致。
- 接口真值已确立（合法子命令已知）且失败意图已映射到确定的执行层。
- 不再向用户推荐任何不在错误枚举内的子命令，或绕过权威层的裸脚本。

## Verification
- 收据的 action_id、generation、target 与 show/verify 观察到的期望值一致。
- 下一轮通过文档化查询路径（status by action_id）确认终态为 succeeded。
- 此后给出的任何命令只使用错误枚举中出现的子命令与已证实的参数。

## Counterexamples
- 失败是超时、连接拒绝或非 usage 类非零退出：接口枚举不适用，应重试或做环境/网络诊断。
- 实际运行的是旧安装版本而仓库源码已有新子命令（模块路径或 pyc 不一致）：错误枚举可能过期，需先确认真正执行的是哪份代码。
- agent 环境没有包装该子系统的原生工具：此时应做受枚举约束的定向源码阅读，而不是默认工具层拥有该动词。
- 某些系统里裸 shell 脚本才是官方重启路径、包装层只是便利封装：只有源码/文档 provenance 能裁决归属，不能一律假设 agent 工具层为权威。
