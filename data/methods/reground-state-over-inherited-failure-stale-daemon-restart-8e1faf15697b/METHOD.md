---
method_id: reground-state-over-inherited-failure-stale-daemon-restart-8e1faf15697b
name: reground-state-over-inherited-failure-stale-daemon-restart
description: 接手一个先前尝试被报告为『更新失败』的守护进程更新+重启任务，或用户以更正式指令点名目标实体（『重启的是X不是Y』）时：先用当前磁盘 ground state（磁盘版本==registry 目标 tag、安装 mtime 晚于运行进程启动时间、bin symlink 完好、--version 正常）检验继承的失败前提；若已被证伪，跳过复盘旧失败日志、检索先前会话与全量目录枚举，剩余动作仅是 kill 旧进程并按原参数重启。核心判别：CLI --version 只反映磁盘不反映运行中进程，运行代码陈旧性只能由 进程启动时间 < 安装 mtime 判定；后台拉起须脱离会话以免工具超时被误判失败，随后以新 PID/加载路径/日志/端口独立验证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b4651548-9342-4b65-bd99-85aba9b1f7a9:180:2d99e538b5706ab7ec50
evidence_refs: learning:learn:e15fa85befb6
created_at: 2026-09-24T17:41:33.701135+00:00
updated_at: 2026-09-24T17:41:33.701135+00:00
---
## Trigger
用户以更正式指令点名目标实体与动作（如『重启的是dsh，不是lfl』），或续跑一个先前会话结论为『安装/更新失败、未完成』的长驻服务运维任务

## Discriminator
安装前缀处一次可读的事实组：磁盘版本==registry 目标 tag 最新发布、安装文件 mtime（今天 23:13）晚于运行进程启动时间（更早日期）、bin symlink 解析正常、CLI --version 输出新版本。四者同时成立即可把『诊断旧失败/重装/重启』三个候选缩为仅『重启』；且 --version 反映磁盘而非运行进程，进程陈旧性只由启动时间与安装时间之差判定

## Short path
- 用户更正已点名实体 → 直接 pgrep -fl <name> + lsof -iTCP:<port> 定位运行进程、PID、启动时间、监听端口（未知量：现在跑的是哪个进程、多旧）
- which/readlink <bin> + ls 安装前缀 + --version → 安装位置、磁盘版本、安装 mtime（未知量：磁盘代码是否已是目标版）
- 一次 registry 查询（如 npm view dist-tags）确认磁盘版本==目标 tag（未知量：更新本身是否还需执行）
- 进程启动时间 < 安装 mtime 且无热重载证据 ⇒ 运行代码陈旧，kill 旧 PID 并确认端口释放（未知量：重启是否即全部剩余工作）
- 以原参数脱离会话（nohup/&/disown）拉起新进程；工具超时不视为失败（未知量：新进程是否已起来）
- 独立核验：新 PID 启动时间、lsof 显示模块路径指向新安装目录、日志 ready、端口监听 → 满足即停止，不再枚举安装内容

## Stop conditions
- 磁盘版本落后于 registry 目标 tag → 先补安装，重启分支不适用
- 进程启动时间 ≥ 安装 mtime，或服务具备 HMR/热重载 → 不能凭时间差断定运行旧代码，改查实际加载模块路径或运行时版本端点
- 新 PID 已验证（模块路径=新安装目录、日志 ready、端口监听）→ 停止，不再展开 node_modules 全量枚举或复盘旧日志

## Verification
- lsof/ps 确认新 PID 监听端口，且其打开的模块/文件位于新版本安装目录
- 服务日志出现启动 ready 行；旧 PID 干净退出且端口在拉起前曾释放
- 对照 registry dist-tags 复核磁盘版本即用户所需目标版本

## Counterexamples
- 磁盘版本低于目标 tag（如用户要 latest 而磁盘是 next）→ 重启不能完成更新，必须先安装
- 守护进程带热重载/HMR（本例 dsh 自身依赖 dsh-hmr）→ 进程早于安装不等于运行旧代码，时间差判别失效，须以实际加载路径判定
- 用户目标本身包含解释先前失败原因（postmortem）→ 读旧 npm 日志在任务范围内，不算绕路
- 先前失败涉及配置/数据损坏而非代码安装 → 磁盘版本事实无法清除该前提，仍需诊断
