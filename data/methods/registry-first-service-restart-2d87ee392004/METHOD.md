---
method_id: registry-first-service-restart-2d87ee392004
name: registry-first-service-restart
description: 对“重启/停止/查看某服务”类请求，应以平台单元注册表（launchctl/systemctl/supervisorctl）为唯一权威索引，而不是进程名猜测加反复 ps 扫描。一次按厂商别名过滤的注册表列举即可关闭候选集：unit label 就是重启句柄，live PID 说明谁在跑，列举上下文（用户域还是系统域）直接给出是否需要 sudo。注册表已回答“重启哪些、在哪个域”之后，任何重启前的补充进程枚举都是 post-sufficiency 动作；完整进程核实应折叠进重启后的那一次检查，而不是重启前再做一轮。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d90eb535-04f6-4fbd-a4da-6eac9c0eeabb:0:e6aaceee00ecb5007a94
evidence_refs: learning:learn:1f97f996cf55
created_at: 2026-09-19T12:28:39.332411+00:00
updated_at: 2026-09-19T12:28:39.332411+00:00
---
## Trigger
用户要求重启/停止/查看某个具名应用或服务，且过滤后的单元注册表列举（launchctl/systemctl/supervisorctl）已返回带 live PID 的匹配单元。

## Discriminator
进入补充确认那轮之前，当时已可见三条事实：(1) 用户上下文的 launchctl 列举已给出完整 awesun 单元集——两个在跑的 gui 单元（含 PID）加全部四个厂商 plist（含 root helper），候选集已封闭；(2) 这些单元出现在用户自己的列举里，意味着 gui 域、无需 sudo 即可操作；(3) sudo 探测已返回 SUDO_NEED_PASSWORD，权限边界已定。三者合起来已完整决定“重启什么、怎么重启”，再扫一遍 ps 不可能改变重启动作本身。

## Short path
- 一步发现命令：`uname -a` + `launchctl list | grep -iE '<厂商别名>'` + `ps aux | grep -iE '<厂商别名>' | grep -v grep`。未知量：向日葵在这台机器上以什么形态存在、是否在跑。别名过滤要含注册表 label（厂商 label 常不等于二进制名，纯进程名 grep 会漏）。
- 注册表返回在跑的 gui 域 label（带 PID）和 plist 全集。未知量闭环：重启哪些（在跑的）、在哪个域（用户域，因为出现在用户自己的列举里）、要不要 sudo（不要）。
- 对已知句柄直接行动：对每个在跑的用户域 label 执行 `launchctl kickstart -k gui/$(id -u)/<label>`。分支：若某单元解析为 system 域或权限失败，停止并如实说明，不做提权重试。
- 重启后只做一次核实扫描：`launchctl list | grep <别名>; ps -o pid,user,etime,comm -p <新PID>`。确认新 PID 在跑，并顺带暴露未动的 root 域进程用于如实披露。停止：用户所需事实已由 launchd + 进程表双重验证。

## Stop conditions
- 注册表无匹配单元、也未发现未注册的裸进程 → 停下来询问用户或进入有意的扩大发现，而不是反复换 grep 关键词。
- 目标单元属 system 域且 sudo 不可用 → 披露后停止，不做循环提权尝试。
- 重启后核实确认每个被 kick 的 label 都有新 PID 在跑 → 任务完成，不再追加扫描。

## Verification
- launchctl list 中每个被 kick 的 label 出现新 PID（Status 列 -15 是 kickstart -k 的预期 SIGTERM 痕迹，不是失败）。
- ps 确认每个新 PID 以预期用户、预期二进制路径运行。
- 已发现但未重启的单元（root 域 helper/service）在答复中显式披露，而非静默跳过。

## Counterexamples
- 目标进程未注册在任何单元注册表（nohup/裸后台进程）：注册表返回空，此时应回退到进程表搜索，并按原始命令与环境重建重启，本方法不适用。
- 注册表只暴露 system 域单元且 sudo 不可用：gui 域捷径不存在，正确动作是报告/询问而非 kickstart——关键判别量（域归属）已变。
- 记忆中存在同一服务同一主机的精确先前记录（如本机已知的 launchctl submit 复活循环陷阱）：应先读该记录；本方法禁止的是宽泛预枚举记忆，不禁止能避开已知陷阱的定向查询。
- 该服务正是用户当前远程连接所依赖的通道：注册表句柄只回答“怎么重启”，不回答“该不该现在重启”——切断在线会话的风险判断不适用本方法的直接行动分支。
