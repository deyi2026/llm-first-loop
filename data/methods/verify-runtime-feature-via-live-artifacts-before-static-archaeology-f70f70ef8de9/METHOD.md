---
method_id: verify-runtime-feature-via-live-artifacts-before-static-archaeology-f70f70ef8de9
name: verify-runtime-feature-via-live-artifacts-before-static-archaeology
description: 验证『刚重启的常驻服务是否真的启用了某功能』时，先用该功能自身在运行时产出的工件（输出/journal 的存在性、mtime 晚于重启时刻、持续增长）或活进程的实际解析环境（端口→PID→打开文件/environ）做直接观测；把源码默认值、候选 code root、config 文件副本的静态推断留作事后解释。因为部署记录/venv editable 可能让『你在读的代码』≠『在跑的代码』，且缺失日志行是弱证据，先做静态推断曾得出被运行时证据推翻的中间结论。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:177:7f99a3ffe4c2e3fd9ec9
evidence_refs: learning:learn:1d9c03ca38eb
created_at: 2026-09-17T14:59:32.076686+00:00
updated_at: 2026-09-17T14:59:32.076686+00:00
---
## Trigger
服务重启或配置变更后，需确认某功能在运行时是否真正生效；观察到缺失预期日志行或行为疑似未变，开始想排查『服务跑的是哪份代码/读的是哪份 .env』时。

## Discriminator
问题本质是运行时状态而非代码内容，且当时已知：(a) 重启回执/部署记录显示服务从记录的 code_root 运行，当前工作区代码默认值按构造到不了运行时，唯一差异通道是启动环境变量；(b) 端口在服务（health 200 可见），监听 PID 可经端口属主直接定位，其打开文件即揭示真实 data 目录与 .env；(c) 缺失『已装配』日志行可能只是日志级别问题，非决定性（自己也在后续承认）；(d) 作为该功能的实现者，其运行时工件输出位置是已知事实。这四条把候选从『枚举各 code root×.env 组合』缩成『直接观测活进程与其新鲜工件』。

## Short path
- 从重启回执读出 deployment/code_root 与时间戳：当前工作区代码默认值与运行时无关，唯一可变通道是启动环境 → 待测未知量坍缩为『进程实际拿到的开关值』与『功能是否产出新鲜运行时工件』。
- 直接检查该功能的运行时工件目录：文件存在、mtime 晚于重启时刻且在增长 → 功能已挂载并运行，停止。
- 若工件缺失或过期：端口属主 → PID → lsof/proc environ 读该进程实际打开的 data 目录与解析到的开关值，判断配置通道是否生效。
- 仅当运行时证据与预期矛盾时，才做 venv editable 目标/worktree 默认值等静态考古来解释原因（解释性步骤，不改变『是否生效』的结论）。

## Stop conditions
- 功能工件新鲜（mtime > 重启时刻）且持续增长，或进程 environ/打开文件显示开关已生效且数据目录一致 → 已验证，停止发现，进入汇报。
- 进程 environ 显示开关未生效 → 已定位到配置通道问题（如启动器未加载该 .env），修复后重测该项，不再枚举代码根。

## Verification
- 工件 mtime 严格晚于重启时间戳，且内容显示预期活动（如 queued/admitted 事件流）。
- 工件出现的位置与活进程打开文件指向的 data 根一致（同一数据目录）。
- 最终『生效/未生效』结论不依赖任何一份未被该进程实际读取的 config 文件或代码默认值。

## Counterexamples
- 功能完全无运行时工件、无启动日志（纯内存开关）→ 工件优先不可行，应改用探针端点或进程 environ，必要时才退回静态检查。
- 任务是根因分析『为什么没生效』而非确认『是否生效』→ 静态考古本身就是目的，顺序应反转。
- 工件存在但 mtime 早于重启（陈旧残留）→ 仅看存在性会误判，必须校验新鲜度与增长。
- 该启动日志行由已知良好的 logger 保证必然打印 → 其缺失即是决定性反证，无需再找工件佐证。
