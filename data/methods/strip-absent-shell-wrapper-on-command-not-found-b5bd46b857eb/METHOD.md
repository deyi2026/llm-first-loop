---
method_id: strip-absent-shell-wrapper-on-command-not-found-b5bd46b857eb
name: strip-absent-shell-wrapper-on-command-not-found
description: 在 macOS 主机（工具回执持续带 sandbox-exec/darwin 环境标记）给长命令加 GNU coreutils 前缀（如 timeout 300 pytest）会以 `command not found` 失败，失败点被精确命名为 wrapper 命令本身，核心命令根本没跑。正确响应：剥掉缺失前缀、原样重发核心命令一次（shell 执行工具自带时长预算）即恢复；不安装 coreutils、不诊断核心命令、不误判为沙箱拒绝。若缺的是核心命令本身则另走项目运行环境定位法。
aliases: mac 上 gtimeout 才有吗, coreutils 缺失的坑, 给测试命令加时限跑不了, 沙箱里找不到 Unix 命令, 苹果系统 shell 兼容性
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:212bbc07-73ca-4b2a-af34-769842c6d47d:3332:a00fb0ca4d888c125f4b
evidence_refs: learning:learn:64230934e7ba
created_at: 2026-10-30T16:04:14.620275+08:00
updated_at: 2026-10-30T16:04:14.620275+08:00
---
## Trigger
在带 darwin/sandbox-exec 环境标记的主机上用 shell 执行可能超时的命令、准备加 GNU-only 前缀工具（timeout/flock 等），或已收到形如 `bash: timeout: command not found` 的失败回执

## Discriminator
失败回执精确到 `<wrapper名>: command not found`——缺失的是外围 wrapper，核心命令（如 .venv/bin/python -m pytest）尚未被执行；且回执同屏显示沙箱正常启用，排除沙箱拒绝。发令前先验：每条回执的 macOS sandbox-exec 标记 ⇒ GNU coreutils 默认不在 PATH

## Short path
- 发令前看环境标记：回执带 macOS/sandbox-exec ⇒ 默认 GNU-only wrapper 缺失，直接运行核心命令，或先确认 gtimeout 存在再用前缀
- 若已失败且回执为 `<wrapper>: command not found`：判定为 wrapper 缺失而非核心命令/沙箱问题，剥掉前缀原样重发一次
- 以核心命令自身退出码与输出收口（本例 pytest 154 passed），不为 wrapper 做安装、替换等额外动作

## Stop conditions
- 核心命令已执行并返回退出码与完整输出
- 回执是 permission denied / operation not permitted 等沙箱拒绝 ⇒ 换沙箱策略分支，剥前缀无效
- command not found 命中的是核心命令（解释器/测试器本身）⇒ 转入项目权威运行环境定位，不再剥前缀

## Verification
- 重发后回执为核心命令本体输出且退出码正常
- 同一 wrapper 缺失失败在本任务内不再重复出现

## Counterexamples
- Linux 容器或已装 coreutils 的主机：timeout 前缀合法且提供超时保护，剥掉反而丢失保护
- 缺失的是核心命令（如 python 本身）：属项目运行环境问题，应走环境定位法而非剥前缀
- 回执为沙箱写拒绝（operation not permitted）：与命令缺失无关，剥前缀无效
