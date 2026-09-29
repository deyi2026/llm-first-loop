---
method_id: platform-from-first-receipt-then-switch-dialect-f2e69975a0c3
name: platform-from-first-receipt-then-switch-dialect
description: 在平台未知的主机上执行系统管理类命令时，把第一条回执本身当作环境证据：『/bin/sh: tasklist: command not found』这类 stderr 在失败当下就直接证明解释器是 POSIX shell、当前命令方言整体不可用。正确动作是立即整体切换到该平台工具集（ps/grep/kill/open/launchctl 等），而不是在同一方言内换命令重试；平台完全未知时可先用 uname -s 等廉价探测。该方法把『发错方言→失败→再试』压缩为『读回执中的解释器/错误类→一次换对』。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:cb0ea77f-0b66-4197-80a6-81c0da920b6f:8:c66f31da1120b94a83eb
evidence_refs: learning:learn:dad498d6880c
created_at: 2026-09-28T01:27:54.527748+08:00
updated_at: 2026-09-28T01:27:54.527748+08:00
---
## Trigger
需要对未声明操作系统的主机执行 OS 特定管理命令（进程/服务/应用重启等），或刚收到 command not found / 方言不匹配类回执时。

## Discriminator
首个回执的 stderr 显式给出解释器名与缺失命令：『/bin/sh: tasklist: command not found』——这一当时已可见的事实把平台假设从 {Windows, Unix, ...} 缩到 POSIX/Unix，因为错误由 /bin/sh 抛出且 Windows 二进制缺失。

## Short path
- 未知量：宿主平台。先用 uname -s 廉价探测，或直接发首个命令并把它当作平台证据；若 stderr 是 <posix-shell>: ... command not found，立即判定 Unix 族，禁止再发同方言命令。
- 未知量：用户所指产品对应哪个进程/应用。在正确方言下按厂商关键字（vendor 名而非仅用户可见产品名）搜索：ps aux | grep -i <vendor>。
- 未知量：应用包路径与主进程。列 /Applications 或等价位置，用 bundle id 与 PID 交叉验证目标应用。
- 未知量：能否优雅退出。先试正常 quit；若回执显式给出取消/弹窗类错误码，立即降级为 kill，让系统服务自愈重启守护代理。
- 未知量：重启是否成功。open/等价命令拉起主程序，ps 验证新 PID 与旧 PID 消失后停止。

## Stop conditions
- 首个回执已包含平台判定所需事实（shell 名/错误类）后，不再发出同方言重试。
- 重启后回执显示目标主进程以新 PID/新启动时间运行，旧 PID 消失。

## Verification
- 用 ps 确认目标主进程新 PID 存在且旧 PID 已消失，报告中的每个组件状态都能对应一条可审计回执。
- 最终结论不含未验证断言（如守护进程状态需有对应 ps 行为证）。

## Counterexamples
- 平台已明确声明（任务上下文就是 Windows cmd/PowerShell）：tasklist/findstr 是正确方言，无需探测或切换。
- 回执是 transient timeout 或 permission denied 而非 command not found：这不构成平台证据，不应换方言，而应重试、提权或读取错误详情。
- 命令在两平台同名但语义不同（参数、行为差异）：换方言不解决问题，需查该命令在当前平台的真实签名。
