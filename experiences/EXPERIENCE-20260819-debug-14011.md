---
title: 调试停滞时先读源码而非继续加 DEBUG 打印（14011 教训）
scenario: django__django-14011 调试：ThreadedWSGIServer._close_connections 调用 conn.close() 后 conn.connection 仍非 None。前两轮调试都是加 print 重跑（stagnation_rate 0.58 的主因），第三轮才定位到根因：sqlite3 backend 的 close() 对 in-memory 数据库有保护（is_in_memory_db() 为 True 时直接跳过 BaseDatabaseWrapper.close，防止误销毁内存库）。
root_cause: "调试中\"加 print→重跑\"是低信息增量循环；源码读取是更高信息密度的路径"
solution: "调试时第一轮复现拿到\"现象 A\"，若第二次仍需确认现象，应直接读实现代码（本例：sqlite3/base.py 的 close() 开头就有 is_in_memory_db 保护，read_file 10 秒即可确认），而非反复加 print。规则：连续 2 轮相同调试动作后必须切换路径（读源码/查文档/换思路），禁止第 3 轮重复。修复方向：对 in-memory 共享连接需绕过保护关闭（如直接操作底层 connection 或按官方语义设计），待继续。"
evidence: SE-20260819-001-1935 stagnation_rate=0.58；14011 三轮 DEBUG 打印后经 is_in_memory_db=True 打印确认根因
tags: [调试, 停滞, sqlite, in-memory, django]
source: {}
status: active
created_at: "2026-08-19T10:19:25.940811+08:00"
updated_at: "2026-08-19T10:19:25.940811+08:00"
---