---
method_id: verify-restart-claim-via-session-host-continuity-and-pid-anchored-manife-8b0cf7d2f1b1
name: verify-restart-claim-via-session-host-continuity-and-pid-anchored-manifest
description: 用户声称受管服务『已经重启/已生效』时，不把声明当事实，也不在被噪声淹没的 status 回执上反复换 range 找信号。若被声称的服务正是承载当前会话/工具传输的宿主，会话连续性本身即直接证据：宿主真重启会杀死会话、更换 pid。用每服务磁盘 runtime manifest（pid/started_at/git_head）一次读出『何时启动、跑什么代码』，再对 manifest 的 pid 做存活检查以防陈旧快照误导，最后对齐 deployment desired 的 generation/git_head 得出『想跑 vs 实跑』差距，逐服务回报。
aliases: 用户说已经重启了怎么核实, 服务还在跑旧代码 重启到底生效没, 怎么确认重启真的发生了, 会话没断说明宿主服务没重启, 重启声明和 manifest 对不上, 按状态快照里的实名查键 而不是文档叫法
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:fd308b28-18c0-4929-b777-f1783be9298c:2153:94abb5fd9f76a17e77cf
evidence_refs: learning:learn:82828d745e3b
created_at: 2026-10-30T07:03:36.804588+08:00
updated_at: 2026-10-30T07:03:36.804588+08:00
---
## Trigger
用户报告『已经重启/已经生效/已经部署』类状态变更声明，需核验其真实性；且声明指向的受管服务中有一个正是承载当前 agent 会话或工具传输的宿主（其日志正实时接收本会话调用），或权威 status 回执被无关 audit 噪声占满而难以直读。

## Discriminator
当前会话是否仍然连续、且其调用正实时写入目标服务日志——宿主重启必然中断会话或更换 pid，会话活着即反证『未重启』；辅以磁盘 runtime manifest 的 pid 存活性（pid 活且 started_at 未变 = 权威运行态，pid 死 = 陈旧回声不可单独作证）。

## Short path
- 判定被声称的服务是否为本会话宿主；是则先做自证：本会话仍活着且该服务日志正在接收本会话工具调用 → 立即证伪『已重启』，无需读长回执或全量日志
- 读各服务 runtime manifest（pid/started_at/git_head），一次回答『实际何时启动、跑什么代码』
- 对 manifest 中的 pid 做存活检查并核对 started_at/监听端口：pid 活且时间未变 = 权威运行态；pid 死或复用 = 陈旧快照，转查当前实例
- 读 deployment desired（generation/git_head），live 与 desired 的 git_head 差即『未生效范围』清单
- 把磁盘证据与用户声明逐项对表后回报差异与真实阻塞；确认用户动作是否实际落在另一对象（如独立桥进程）上，避免把两件事混为一谈

## Stop conditions
- 每个被声称的服务都有了确认的 started_at 与运行中 git_head，与声明的差异已定位
- 已确认用户所述动作落在另一对象上（非受管服务重启），两者解耦清楚
- pid 存活、started_at 与日志最后一次启动横幅一致，不再从日志全量重推启动历史

## Verification
- manifest 的 started_at 与服务日志最后一次启动横幅时间戳一致
- pid 存活且监听端口/命令行与 manifest 记录一致（排除 pid 复用）
- desired 与 live 的 git_head 差异逐服务列出，作为『未生效』清单交用户
- 若 status 回执可读且已含 per-target live/desired 字段，回执优先于磁盘，磁盘仅作交叉验证

## Counterexamples
- 目标服务不承载本会话（外部主机、本地 CLI 起的进程）→ 会话连续性无信息量，只能走 manifest/pid/日志横幅
- 服务有 supervisor 透明热重启且保会话（socket 继承、状态恢复）→ 会话活着不等于没重启，必须比 pid 与 started_at
- status 回执可读且含所需 live 段 → 直接用回执裁决，不必下磁盘读 manifest
- 核验对象是配置/凭据是否生效而非重启 → 改用进程启动时间 vs 文件 mtime 的链端点检查，本方法不适用
