---
method_id: locate-live-service-runtime-via-process-table-first-490c83c76eda
name: locate-live-service-runtime-via-process-table-first
description: 已知某受管服务当前 live（状态查询刚确认 generation/PID）而需要定位其安装根/worktree/runtime_manifest 时：活进程表里的真实启动命令行是一跳可得、零猜测的权威 provenance。先 pgrep/ps 解析可执行绝对路径与 '-m <module> <target>'，由 venv 路径推出安装根，再按固定相对路径读 runtime_manifest 交叉验证后停止。禁止在服务已确认 live 的前提下，先对家目录做 parent/maxdepth 全为猜测参数的 find 枚举再逐次改参重试。与『已完成任务回执命令行定位 workdir』同族但触发不同：见证源是活进程表而非终态回执，可在任何失败发生前主动使用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:520:fd3d390e1f88a9eeb1fe
evidence_refs: learning:learn:4e5c22f0e84e
created_at: 2026-10-09T20:08:55.251098+08:00
updated_at: 2026-10-09T20:08:55.251098+08:00
---
## Trigger
需要定位一个已知正在运行的受管服务（web/learning/feishu 等）的 code_root/worktree/runtime_manifest，且上下文中没有现成 job 回执或 manifest 绝对路径；尤其当刚完成的状态查询已确认该服务 live/stable。

## Discriminator
知识时刻成立的事实：状态查询已确认目标服务 live ⇒ 进程表必然存在该服务的真实启动命令行（可执行绝对路径 + -m 模块 + target），一跳即得权威安装根；而任何 find 的 parent/maxdepth 都只是未经证实的参数猜测，命中与否取决于是否猜对目录深度。

## Short path
- 写明未知量（安装根/manifest 位置）与已知事实（服务 live，来自刚完成的状态查询）
- 一次 pgrep -fl 或 ps aux | grep 按 launch 模块与服务名取真实命令行（如 .venv/bin/python -m llm_loop.runtime.launch web）
- 由可执行路径解析安装根（venv 上级即代码根），按固定相对路径读取 data/runtime/runtime_manifest.<svc>.json，取 workspace_root、release SHA、config_file
- 将 ps 解析结果与 manifest 字段、状态查询的 generation/SHA 交叉一致后，立即停止定位，转入目标版本契约核对

## Stop conditions
- ps 命令行与 manifest 的 python_executable/workspace_root 相互印证 → 定位完成，不再做文件系统搜索
- pgrep 无命中（服务已停/处于重启窗口/PID namespace 隔离）或多实例无法按 target/PID 消歧 → 本方法不适用，改走任务回执命令行或已知目录内的窄检索

## Verification
- manifest 的 python_executable、workspace_root、git_head 与 ps 解析结果及状态查询报告的 SHA/generation 三方一致
- 最终采用的每条路径都能回溯到 ps 输出或 manifest 字段，不含任何未经验证的猜测参数

## Counterexamples
- 服务未运行、正处于两阶段重启等待窗口、或进程在容器/不同 PID namespace 中：进程表查不到或非真实视图 → 不适用，转回执或 manifest 检索
- 同机多实例并存（shadow 与生产、多个 target 并行）：第一条命中可能不是目标 → 必须按 target/generation/PID 消歧后再采用
- 目标是历史/已完成任务的 workdir：进程已消失 → 用任务回执中的命令行定位，而不是 ps
- manifest 绝对路径已在上下文中给出：直接读取，无需 ps 一跳
