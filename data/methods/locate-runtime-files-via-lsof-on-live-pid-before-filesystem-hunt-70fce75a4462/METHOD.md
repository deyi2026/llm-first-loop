---
method_id: locate-runtime-files-via-lsof-on-live-pid-before-filesystem-hunt-70fce75a4462
name: locate-runtime-files-via-lsof-on-live-pid-before-filesystem-hunt
description: 已知目标服务的 live pid（如刚用 ps 验证过重启/存活）而需定位其真实运行时文件（日志/数据/套接字）时，先 lsof -p <pid> 读取进程当前打开的文件表，直接拿到权威路径（常在 /private/var/log 等非显眼位置），再读该文件提取目标事件标记；不要先做全盘 find、大目录 ls、Spotlight 或 evidence 检索。进程 fd 表就是『该进程实际使用哪些 artifact』的权威索引，可把『哪个目录是权威』的多候选枚举缩为一次查询。仅当 lsof 无果（目标文件无持久句柄/无权限/进程已退出）才回退到目录 mtime、定点路径搜索。本集代价：找向日葵运行日志先经历 60s 超时全盘 find、50 行 Library/Logs 枚举、陈旧 app-support log 目录、mdfind 空结果、两次 evidence 检索落空，最后 lsof 一步命中 /private/var/log/AweSun/。用已持有的 pid 这条因果边先走，搜索空间从『全文件系统』缩成『该进程当前打开的几个文件』。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:ef2eae2c-dfe1-4a01-8c66-440fa10c9637:78:a4a37f1fa112c9faae45
evidence_refs: learning:learn:09c342756230
created_at: 2026-10-15T19:36:35.428101+08:00
updated_at: 2026-10-15T19:36:35.428101+08:00
---
## Trigger
已持有（或刚通过 ps/pgrep 获得）目标服务的运行中 pid，且需要定位该进程实际读写的运行时文件（日志/数据/套接字），路径未知或存在多个候选目录、应用支持目录里的 log/ 目录内容陈旧

## Discriminator
存在 live pid，且日志/数据文件通常被服务进程持续持有打开句柄——进程 fd 表直接给出真实路径。这条判别事实在开始找日志那一刻就已存在（ps 已显示新实例 pid），足以把『哪个目录是权威』缩成一次 lsof 查询，即使全盘 find 已超时、Spotlight 无索引也不受影响

## Short path
- 用 ps/pgrep 确认新实例 pid（验证重启/存活本身就需要这一步，不额外花费）
- lsof -p <pid> 过滤 REG 且写模式的条目，得到进程实际打开的日志/数据文件路径
- 只进入 lsof 指向的那个目录，读最新被写入的文件，提取目标事件标记（如上线/登录/P2P 连接成功）
- 权威来源命中即停止发现，把用户所需结论（如『重启是否成功』）与该来源对齐后收束

## Stop conditions
- lsof 已给出当前打开的运行时文件，且读取内容含目标事件标记（如 express login、P2P_CONNECTED）
- lsof 无输出或权限不足（目标文件无持久句柄、root 进程受限、进程已退出）→ 停用本方法，转目录 mtime 排序、定点路径或 Spotlight 等文件系统层发现

## Verification
- lsof 输出中的 pid 与 ps 中目标 pid 一致，且文件 mtime 与进程启动时间吻合
- lsof 指向的目录内存在按启动时间戳轮转的旧日志文件，佐证该目录是该服务的权威输出位置而非应用支持目录里的陈旧 log/

## Counterexamples
- 目标文件仅在进程启动时读取一次后即关闭（如配置文件）→ fd 表看不到它，需改用 cmdline、默认路径约定或启动跟踪
- 目标进程已退出的事后取证场景 → 没有 live pid，文件系统/目录时间线搜索是正当且必要的手段
- 对他人或 root 进程无权执行 lsof（macOS 权限限制）→ 先查自己用户名下的进程实例，或请求用户授权，而不是强行全盘搜索
- 按轮转关闭旧句柄的日志 → lsof 只显示当前活跃文件；若需历史日志仍要列该目录，但此时列出的是 lsof 指定的窄目录而非整个文件系统
