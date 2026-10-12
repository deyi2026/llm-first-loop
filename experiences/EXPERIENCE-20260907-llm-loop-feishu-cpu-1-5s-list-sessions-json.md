---
title: llm_loop.feishu 持续吃 CPU：跨端同步 1.5s 轮询 × list_sessions 全量 JSON 解析
scenario: llm-first-loop 飞书桥（python -m llm_loop.feishu）长期稳定占用 10-25% CPU，日志无输出，需要定位根因并修复；新旧两个工作区（llm-first-loop 与 llm-first-loop-mirror）同时运行时 CPU 叠加
root_cause: ""
solution: "用 macOS sample 抓热点帧（scan_once_unicode = json.loads 热循环），定位到 feishu/cross_sync.py 每 1.5s 轮询 SessionStore._list_sessions_in，而后者对 275 个会话文件（108MB）逐个全量 json.loads（实测单轮 0.363s ≈ 24% CPU）。修复：给 _list_sessions_in 加 (mtime_ns, size) 键的模块级元数据缓存，未变化文件直接复用解析结果（0.0022s/轮，165 倍），落盘必改 mtime 保证失效正确性；重启桥后 CPU 降至 <1%。同时停掉旧工作区已断连（websocket 自 9/4 SSL 失败后未重连成功）的同款 feishu 桥。"
evidence: "evidence://v1/562f34dae2d7cf29679548336987b8fd557d231a54cc82a31ee2d9f2cd20e97f"
tags: [llm-first-loop, cpu, feishu, cross_sync, session-cache, macos, sample, performance]
source: {}
status: active
created_at: "2026-09-07T00:23:04.371758+08:00"
updated_at: "2026-09-07T00:23:04.371758+08:00"
---

现象：macOS 上 llm_loop.feishu 进程持续 15-25% CPU，ps 看无异常，日志静默。定位步骤：1) sample <pid> 3 看 C 帧热点（scan_once_unicode=json.loads 即高频 JSON 解析）；2) 顺着 json.loads 调用点找轮询方；3) 本例根因：feishu/cross_sync.py 每 1.5s poll_once() → SessionStore._list_sessions_in 对目录内全部会话文件全量 json.loads（275 个/108MB，单轮 0.363s ≈ 24% CPU，与观测吻合）。修复：_list_sessions_in 加模块级 (mtime_ns,size) 缓存，文件未变复用 SessionMeta（0.363s→0.0022s），落盘必改 mtime 天然失效，删除文件随轮回收。附带发现：进程在代码更新间隙启动会缓存旧 llm_loop.event_log.model（缺 EVENT_HISTORY_COMPACTION_STATE_RESET），import 永久失败刷 fail-open 日志，重启即愈。诊断工具链：sample→grep scan_once；py-spy 在 macOS 需 root（无 sudo 时不可用）；lsof -a -p <pid> -i TCP 看连接（注意 -p 与 -i 是 OR 关系）。