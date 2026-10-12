---
title: 镜像自重启翻车与正确姿势：launchctl submit 无限复活循环 + restart_mirror.sh 标准链路
scenario: "镜像 AI 需要重启自己所在的镜像区常驻服务（web :8903 + 飞书桥）。第一次尝试 setsid 脱离执行重启脚本——失败（execute_command 的 shell 退出时清理后台子进程，重启从未真正发生）；改用 launchctl submit -l lfl.web.restart -o /tmp/lfl_web_restart.log 把重启命令交给 launchd——命令确实每次都跑通（RESTART_OK），但 launchd 在作业每次退出后立刻重新拉起 → web 陷入每 ~30s 一轮的「启动→health 200→Shutting down」循环（data/web.log 累计 100 次 Shutting down，/tmp/lfl_web_restart.log 248 行），健康检查单次看永远绿、时间线上服务持续抖动。"
root_cause: "launchctl submit 语义陷阱：它等价 KeepAlive 常驻作业——任务每次退出 launchd 立即重拉，不是一次性执行器；用它跑 restart 命令必然形成无限重启循环。叠加认知误区：把「命令执行成功（RESTART_OK）」当成「重启完成且稳定」，未观察进程存活时间线（Shutting down 计数持续增长才是循环铁证）。"
solution: "1) 止血：launchctl remove lfl.web.restart 拆除作业（label 用 launchctl list | grep lfl 找；-o 日志文件行数异常增长是循环旁证）。2) 正确重启姿势：bash scripts/restart_mirror.sh {web|feishu|all|status}——脚本已内置全部关键项：按端口杀 8903（绝不 pkill -f llm_loop.web，防误杀主区 8902）、source .env、PYTHONPATH=镜像 src（共享 venv 的 editable 指向主区 src）、WEB_PORT=8903、DSH 环境隔离 _prep_dsh_env（DSH_HOME 重定向 + unset 继承残留 + LFL_DATA_DIR 清空）。3) nohup+& 起的进程在 agent shell 正常退出后存活（本次实证：web pid 12396 / feishu 12412 稳定运行），自重启无需 setsid/launchd——restart_mirror.sh 本身就是正确答案。4) 验证四件套：① restart_mirror.sh status 全绿；② 飞书心跳 data/feishu_heartbeat.json state=connected（脚本「未见 feishu.cn 连接」告警是 lsof 时序误报，以心跳文件为准）；③ web.log 的 Shutting down 计数冻结（间隔 20s 两次取样不变=循环已止）；④ 主区 8902 健康不受影响。5) 自重启铁律：会话宿主要重启宿主，唯一路径是 restart_mirror.sh；严禁 launchctl submit（无限复活）、setsid 经 execute_command 会被 shell 清理。"
evidence: "2026-08-28 22:44-22:46（UTC+8）镜像会话 9d27d9ee change_log 实录：setsid 失败 →「换 launchd 接管（完全脱离本进程树，唯一可靠路径）」launchctl submit -l lfl.web.restart。故障期：web.log Shutting down 86→100 持续增长；ps 抓到 bash -c 'cd /Users/yyj/Project/llm-first-loop-mirror && scripts/restart_system.sh web restart && echo RESTART_OK' PPID=1（launchd 直接派生）每 ~30s 一条。拆除：22:51 launchctl remove 后计数冻结 100。干净重启后：22:52 web pid 12396 health ok、feishu 12412 心跳 connected/reconnect=0、主区 8902 全程健康。"
tags: [镜像重启, launchctl-submit, 无限复活, restart_mirror, 自重启, 飞书心跳验证, 运维]
source: {}
status: active
created_at: "2026-08-28T22:54:59+08:00"
updated_at: "2026-08-28T22:54:59+08:00"
---

## 镜像重启速查（AI 自用）

### 标准命令

```bash
bash scripts/restart_mirror.sh status   # 先看现状（web 8903 / feishu / 主区 8902）
bash scripts/restart_mirror.sh all      # 全量重启（web + feishu）
bash scripts/restart_mirror.sh web      # 只重启 web
bash scripts/restart_mirror.sh feishu   # 只重启飞书桥
```

### 重启前二查（沿承 EXPERIENCE-20260816 三查一验）

1. 查飞书心跳 `data/feishu_heartbeat.json`：`processing_msg_id` 非空 = 有任务在跑，等完成或确认可中断再重启；
2. 查 `launchctl list | grep lfl`：确认无遗留 launchd 作业（本次事故源头）。

### 重启后四验

1. `restart_mirror.sh status` 全绿（web ✅ + feishu ✅ + 主区 8902 ✅）；
2. 心跳文件 `state=connected`（脚本 lsof 告警「未见 feishu.cn 连接」多为时序误报，别据此反复重启）；
3. `grep -c "Shutting down" data/web.log` 间隔 20s 两次取样不变（增长=仍有外部循环在杀 web，追 PPID=1 的派生者 + 查 launchd）；
4. 主区 8902 健康（镜像操作零外溢）。

### 事故时间线（2026-08-28）

- 22:44 镜像 AI 会话（宿主 web pid 57288）要自重启：setsid 脱离失败（execute_command shell 清理后台子进程）
- 22:46 改 `launchctl submit -l lfl.web.restart` → 命令跑通但 launchd 无限重拉
- 22:47-22:51 web 每 ~30s 被循环重启（web.log Shutting down 累计 100 次），单次健康检查看不出异常
- 22:51 `launchctl remove lfl.web.restart` 止血
- 22:52 `restart_mirror.sh all` 干净重启，四验全过

### 一句话结论

**restart_mirror.sh 就是镜像自重启的唯一正确工具（nohup 已足够脱离会话）；launchctl submit 是"看起来能跑实际无限复活"的陷阱，永远不用它执行一次性命令。**
