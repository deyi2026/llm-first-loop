---
method_id: supervisor-provenance-before-kill-3e335d5da864
name: supervisor-provenance-before-kill
description: 在不熟悉的 Unix/macOS 主机上做进程清理时：命令 exit 127 / illegal-option 是平台不匹配信号，应先用一条身份探针（uname -s）确定工具集，而不是继续换同平台语法试错。判定『孤儿』时，PPID=1 + 长期空闲在 supervisor 体系（launchd/systemd）里意味着『被 init 收养/受管』而非『无人认领』：kill 前必须先跑监管溯源查询（launchctl list、grep LaunchAgents/LaunchDaemons plist），溯源为空且经确认才动手；kill 后复验进程、端口与数秒内是否重生。受管进程的治理应指向 supervisor 配置而非进程本身。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:162f3bbd-790a-45ae-8850-5e2227c88455:0:5cc70104ff478253c04e
evidence_refs: learning:learn:67dbb8e38f07
created_at: 2026-09-17T15:37:42.650322+00:00
updated_at: 2026-09-17T15:37:42.650322+00:00
---
## Trigger
在不熟悉的主机上执行系统巡检/清理（内存、孤儿进程、僵尸、泄漏端口），且出现以下任一情形：命令以 exit 127 或 illegal-option 失败；或一个『PPID=1 + 长期空闲/无连接』的进程即将被判为孤儿并 kill

## Discriminator
kill 决策前已可见的事实：① ps 的 stderr 打印的是 BSD usage、PID1 是 launchd → 这是 macOS；② PPID=1 枚举结果里已包含 Chrome/Safari/Terminal/Lark 等显然在用的 GUI 应用 → 本平台上 PPID=1 根本不等于孤儿；③ vite 的 elapsed 时间与 logd/fseventsd 等开机守护进程几乎相同（18-15:44:2x）→ 开机即启动，符合 LaunchAgent 特征。三者任一都足以把『可能是孤儿』缩成『先跑一次 launchctl list | grep / 检索 LaunchAgents·LaunchDaemons plist 再说』，无需动用事后才发现的 plist 内容

## Short path
- 首条命令 exit 127 / illegal-option 时，把失败当作平台信号：先 uname -s（+内核版本）确定平台，再选平台正确的工具（macOS: memory_pressure/vm_stat/sysctl + ps -axo 含 stat 字段；Linux: free + GNU ps）
- 进程普查：ps -axo pid,ppid,user,rss,etime,stat,command；用 stat=Z 找僵尸并溯源其父 PID（本例：5 个僵尸 → 父进程 MCP Console.app，报告即可，不代杀 GUI 应用）
- 把 PPID=1 中的 GUI 应用直接归类为『平台常态』剔除，不进入孤儿候选
- 对每个拟 kill 候选先跑监管溯源查询：launchctl list | grep -i <name>；grep -rl <exe绝对路径或端口号> ~/Library/LaunchAgents /Library/LaunchAgents /Library/LaunchDaemons —— 解决未知量『它是否被托管』
- 分支：受管 → 不 kill，治理指向 supervisor 配置（本例 local.tdx-vite）；溯源为空 + 空闲 + 用户确认 → kill，随后复验 ps -p、lsof -iTCP:<port>，并观察 ≥10 秒是否重生（本例 KeepAlive 重生窗口 11 秒）
- 若 kill 后同名进程以新 PID、PPID=1 重现 → 立即推断 KeepAlive/supervisor 存在，切换治理目标到其 plist/服务定义，而非继续杀进程

## Stop conditions
- 所有 kill 候选均已被溯源证据分类为：受管 / 在用 / 真孤儿，且用户所需事实（内存健康度、僵尸父进程、各监听端口归属）已验证
- 任何 kill 之后：进程消失、端口实际释放、观察数秒无重生，才视为完成
- 僵尸的父进程已定位并报告；GUI 应用交由用户处置，不代替用户执行

## Verification
- kill 前：launchctl list 或 LaunchAgents/LaunchDaemons plist 中是否存在匹配该 exe 绝对路径或监听端口的条目
- kill 后：ps -p <pid> 与 lsof -nP -iTCP:<port> 双重复验（本例教训：只看进程表会漏掉端口仍被占用），并等待一个 KeepAlive 周期确认无重生
- plist 的 ProgramArguments 与候选进程的绝对 exe 路径逐字匹配，防止同名误配

## Counterexamples
- 无 supervisor 的普通 Linux 主机：溯源查询返回空，此时 PPID=1 + 长期空闲确实可能是真孤儿，应照常清理——方法只增加一条查询，不阻断行动
- 进程正在造成急性危害（内存 runaway、抢占关键端口、被入侵迹象）：应先 kill止血再调查重生来源，时间临界性反转『先溯源』顺序
- 用户明确点名要杀的进程：无需溯源门槛，直接执行并按常规复验
- 容器环境：PID1 即应用本身，PPID 语义完全不同，本方法不适用
