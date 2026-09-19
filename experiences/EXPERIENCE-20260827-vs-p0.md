---
title: 修复提交≠修复生效：部署验证须核对进程启动时间 vs 修复落盘时间（紧急压缩空转 P0 复盘）
scenario: "用户报告\"紧急压缩承诺缩小历史但下轮仍超限\"类 P0，或修复提交后用户仍报告旧症状时——先判定运行进程是否含修复，勿直接深挖代码逻辑"
root_cause: "修复已提交但运行进程未重启（进程启动 22:28 早于修复提交 00:38），旧代码按 content 口径判预算，reasoning_content 占 40%+ 的会话压缩空转；修复本身（3ddd74a wire 口径）测试通过无缺陷"
solution: "三步快速判定：① git log -1 --format='%h %ci' <修复提交> 取落盘时间；② ps -eo pid,lstart,command | grep <进程> 取启动时间；③ 进程启动 < 修复落盘 → 跑旧代码，重启即生效（restart_mirror.sh all，注意按端口杀勿 pkill）。空转旁证：cache_breaker.jsonl 同会话短间隔连续 emergency_compact 且 chars_total 钉死不降。"
evidence: "cache_breaker.jsonl: fb8f8987 会话 16:07:46/16:08:00/16:13:08 三次 emergency_compact chars_total 恒 300000；git log 3ddd74a 2026-08-27 00:38:06 +0800；ps: mirror feishu pid 21319 启动于 Wed Aug 26 22:28:29（早 2h10m）；.venv pytest test_cache_prefix.py 全过"
tags: [deployment-verification, emergency-compact, process-restart, mtime-vs-lstart, P0-triage]
source:
  goal_id: GOAL-20260825-b4e96546
  session_id: 2b534e51-a68f-4e13-b3c1-290eb6602bb7
status: active
created_at: "2026-08-27T01:18:14.098687+08:00"
updated_at: "2026-08-27T01:18:14.098687+08:00"
---

诊断链：①守卫拦截日志（guarded_requests.jsonl 无 overlimit BLOCK → 走 routing_override 路径）→ ②breaker 审计（cache_breaker.jsonl: 同会话 14s 内连续 emergency_compact、chars_total 钉 300000 不降 = 空转特征）→ ③代码定位（engine.py:569-600 承诺文案 + history.py:24-46 wire 口径修复）→ ④时间线对齐（git log -1 --format=%ci 3ddd74a = 08-27 00:38 vs ps -eo pid,lstart 运行进程 22:28 启动 = 早于修复 → 跑旧代码）→ ⑤修复验证（.venv pytest test_cache_prefix.py [100%]）。修复生效三步：提交→重启进程→观察 breaker 审计 chars_total 是否下降。