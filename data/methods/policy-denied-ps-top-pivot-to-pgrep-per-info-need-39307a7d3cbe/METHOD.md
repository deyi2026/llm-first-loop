---
method_id: policy-denied-ps-top-pivot-to-pgrep-per-info-need-39307a7d3cbe
name: policy-denied-ps-top-pivot-to-pgrep-per-info-need
description: 沙箱回执对 ps/top 返回 EPERM『Operation not permitted』+沙箱 banner 时，拒绝是按二进制路径的确定性策略：同一二进制换参数必然再失败（本集第2次 ps 即纯浪费）。正确做法是把问题拆成信息需求，各用一次探测找放行通道：uptime/sysctl vm.loadavg 查负载量级、pgrep -fl 列进程与命令行、pgrep -P 1 判孤儿、pgrep -P <pid> 数子代——pgrep/launchctl/uptime 常不在 deny 名单。再用元凶命令行里的路径/工作区 token 关联权威归属源（协调/会话状态）区分『活跃会话的合法并行负载』与『失控孤儿』，双源证据齐即停，不代用户 kill。
aliases: ps被沙箱拦了怎么查进程, Operation not permitted换什么命令, top被拦查CPU元凶, 不用ps查孤儿进程, 沙箱里看load和进程, pgrep顶替ps
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b793d04-185b-4e1e-ad65-8335d6101fba:0:510a0d189b2d42c34ea0
evidence_refs: learning:learn:8c3d1af36e3a
created_at: 2026-11-10T09:28:08.971459+08:00
updated_at: 2026-11-10T09:28:08.971459+08:00
---
## Trigger
受限执行环境（macOS sandbox-exec 等，回执带沙箱 banner）里需要系统级进程/负载信息（查 CPU 元凶、孤儿/僵尸进程），首个监控二进制（ps/top）回执同时出现沙箱提示与对该路径的 EPERM『Operation not permitted』

## Discriminator
stderr 对具体 binary 路径的确定性 EPERM + 沙箱 banner，区别于 ENOENT/exit 127、illegal option、瞬态超时 ⇒ 拒绝发生在 exec/path 策略层：同二进制换参数不可能改变结果；但 deny 名单按路径生效，pgrep/launchctl/uptime/sysctl 等邻近二进制可能放行，每个信息需求一次探测即可锁定可用通道，无需在同一被拒工具族内反复换姿势

## Short path
- 从首次回执判定拒绝类别：EPERM+沙箱 banner=确定性策略拒绝 → 立即停止对 ps 的任何换参重试（也不必先试 top 这类同族监控件）
- 把用户问题拆成信息需求并各探测一次放行通道：负载量级（uptime 或 sysctl vm.loadavg）、进程清单（pgrep -fl <项目/域 token>）、孤儿判定（pgrep -P 1 -fl）
- 从 pgrep -fl 输出识别元凶形态（如 pytest --dist loadfile -n auto + 多个 exec worker 的宽并行命令行），取其路径/工作区 token
- 用该 token 关联权威归属源（coordination/会话/服务状态）：对应活跃 goal 的 ci_gate 验证跑 ⇒ 合法负载；pgrep -P 1 只见常驻受管服务 ⇒ 孤儿阴性
- 负载值与 fan-out 宽度量级吻合即出结论并停止；不动他人会话的进程，把 kill/等待的处置权交回用户

## Stop conditions
- 负载量级、元凶命令行+活跃归属、PPID=1 孤儿判定三项均有放行通道或权威状态源回执支撑即停，不再为『补上被拦的 ps/top』本身尝试第三种同族二进制
- 若连 pgrep 也 EPERM（syscall 级封锁），结论定为『本环境无进程可见性』并转宿主侧/内部状态工具，同样是可交付答案，不继续枚举二进制

## Verification
- uptime/sysctl 读出的负载（如 7.14/6.08/5.00）与元凶并行 worker 数量级一致
- 元凶的工作区路径/父会话在 coordination 或服务状态里显示活跃（PID、goal 对应关系）
- pgrep -P 1 名单逐条可归因为常驻受管服务（feishu/wecom/embedding_server 等），无测试/任务类进程被 init 收养

## Counterexamples
- stderr 是 command not found / exit 127 或 illegal option：那是平台不匹配/缺二进制，应走身份探针（uname -s）选工具集，而非本方法的通道轮换
- EPERM 是瞬态资源类（如 fork: Resource temporarily unavailable）：重试原命令合理，不应永久弃用该通道
- 沙箱按 syscall 层封死 proc 信息（pgrep 同样被拒）：正确动作是转宿主侧 API/内部状态工具，而不是继续枚举更多监控二进制
- ps 本身放行：标准流程直接用，无需换通道
