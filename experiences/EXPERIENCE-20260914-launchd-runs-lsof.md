---
title: 多实例共写日志的 launchd 服务核验法：实例边界切分 + runs/lsof 交叉定位当前进程
scenario: "核验 launchd 迁移交付报告：doctor 报 1 个自愈型 WARN（log_errors），交付叙述称其为\"上一个手动进程被 kill 时的关闭 Traceback，在启动行之前\"。日志文件 qwen8901.stderr.log 被手动实例与 launchd 实例共写，无法凭叙述直接归因。"
root_cause: ""
solution: "①用 \"fork config 行+Starting httpd\" 切出实例边界（本次 4 次启动：20:47/20:49/20:53/21:01），把每条 Traceback 按时间戳归属实例——最后一条实为 20:49:50 的 OSError Address already in use（交接期二启撞端口），非旧进程关闭记录；②launchctl print 的 runs=1/never-exited 与 lsof 端口归属交叉证明当前 8901 主人=launchd 的 pid 52430（21:01:47 起为 launchd 首拉）；③Prompt Cache 条数清零可作为进程更替的旁证。"
evidence: "evidence://v1/512f568390be969bd25ad67e83be861b1fd18528693f85f0668f58f829a9491e (Traceback=Address already in use @20:49:50, line 52616-52641); evidence://v1/a12f1abf63cf2c308772628438b8301d8a0edc3ed01162e4ccebf7e8bc3cf1b1 (lsof: Python 52430 yyj TCP 127.0.0.1:8901 LISTEN); evidence://v1/8daa07bb948751775e446b9c89db8e1a09b981ac844c44d195cd0d687a2832b7 (launchctl print: pid=52430 state=running runs=1 never exited)"
tags: [launchd, log-attribution, lsof, verification, service-migration]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-14T21:10:23.504573+08:00"
updated_at: "2026-09-14T21:10:23.504573+08:00"
---

macOS launchd 服务排障时：(1) 以日志中 "fork config" 行 + "Starting httpd" 作为实例启动边界，把每条 Traceback 按时间戳归属到具体实例——同文件被多实例（手动交接期 + launchd）共写时，叙述里的 WARN 归因（"关闭Traceback" vs "端口冲突启动失败"）必须钉死而非采信。(2) `launchctl print` 的 runs/never-exited 与 `lsof -nP -iTCP:PORT -sTCP:LISTEN` 的端口归属交叉，是确认"当前服务进程=launchd管理的pid"的最强组合（本例 ps 定向查询被沙箱拦而 lsof 可用）。(3) "自愈型WARN"判定三要素：Traceback 性质、与启动行的先后、之后无复发。