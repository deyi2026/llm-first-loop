---
method_id: route-diagnostic-logs-by-writer-privilege-and-mtime-779c573f4fc9
name: route-diagnostic-logs-by-writer-privilege-and-mtime
description: 排查常驻服务『连不上/不在线』时，用进程 effective user + 日志 mtime 双重判据选日志源：ps 显示服务以 root 运行、而用户目录下日志 mtime 早于故障窗口（陈旧）时，该日志源即被证伪，应直查 /var/log/<app>、/Library/Logs 等特权 writer 的日志位置。拿到新鲜日志后先提取失败的确切阶段与日志点名的 endpoint，再只对该 endpoint 的路由/链路（如默认路由是否经 TUN）做定向验证；避免枚举账号数据目录、反复截图+视觉识别、泛网络基线测试这类无判别力的搜索空间扩散。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:ef2eae2c-dfe1-4a01-8c66-440fa10c9637:16:531f6bb15833c7c25925
evidence_refs: learning:learn:bed84e8d9f39
created_at: 2026-10-15T19:34:19.129631+08:00
updated_at: 2026-10-15T19:34:19.129631+08:00
---
## Trigger
服务型应用（远控/同步/守护进程）出现『进程活着但连不上/不在线/功能失效』类故障需要取证；ps 已显示核心服务进程以 root 或非当前用户运行，且需要判断设备是否在线、失败发生在哪个阶段。

## Discriminator
早期即可观察的双重事实：特权（root）服务进程正在运行且故障时刻有活动，而当前找到的用户家目录日志 mtime 停在数月前、同目录其他状态/锁文件却在故障时刻刷新——root writer 不会写那份陈旧日志，权威服务日志必在特权位置（/var/log、/Library/Logs 等）。

## Short path
- ps 确认进程、effective user、启动时间；未知量：进程活着但是否上线、失败在哪个阶段。
- 列出候选日志并比对 mtime 与故障时间窗；未知量：哪个日志源是权威且新鲜的。
- 若服务以 root 运行且用户目录日志陈旧、同目录其他文件却在刷新 → 直查 /var/log/<app> 与 /Library/Logs；未知量：特权 writer 的日志位置。
- 读新鲜服务日志中故障时刻的记录，提取 online/认证/连接状态跃迁与失败的确切 endpoint（如 P2P 服务器 IP:port）；未知量：失败阶段。
- 只针对日志点名的 endpoint/协议做定向路由与连通验证（如 default route 是否经 TUN/fake-ip），不做泛 ping/泛 curl 基线扩散。
- 形成单一因果假设后停止取证；若存在只有用户侧可见的症状（远端提示文案），先问用户再决定是否做侵入性验证。

## Stop conditions
- 新鲜日志已显示失败的确切阶段（例：认证通过后 P2P 连接超时）
- 已有一个与路由/环境相关、可用单变量实验检验的假设，且验证方式需用户授权（会中断网络）
- 日志覆盖了用户报告症状的完整时间窗并出现对应事件

## Verification
- 所读服务日志的 mtime/内容时间戳覆盖故障时刻
- 日志中的状态跃迁与用户报告『连不上』的时段吻合
- 定向连通性验证只针对日志点名的 endpoint/协议，且与假设因果一致
- 对中途的临时误判（如『识别码变了』）已用同一权威日志回查否定

## Counterexamples
- 应用完全以当前用户运行且家目录日志就是新鲜的 → 直接读该日志，不做特权位置路由
- mtime 陈旧只是因为日志刚轮转（存在 .1/.gz 兄弟文件）→ 先查轮转文件再更换日志位置
- 故障发生在日志系统初始化之前（进程启动即崩、日志为空）→ 应转查 crash reports/DiagnosticReports 而非继续找日志
- systemd/journald 环境：root 服务日志在 journal 内、/var/log/<app> 不存在 → 应按 unit 查 journal 而非目录
