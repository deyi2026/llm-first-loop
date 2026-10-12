---
title: llm-first-loop 服务重启三查一验：心跳/端口/guard 连锁
scenario: 需要重启 llm-first-loop 服务（web+feishu）时：直接 restart 可能因端口占用失败、飞书桥处理中任务被打断、或 guard 检测工作区变更自动重启引发飞书重推旧消息。
root_cause: 重启前未检查端口占用/心跳处理中状态/guard 自动重启连锁效应，导致重启失败或中断任务。
solution: "重启三查一验：① 查心跳 data/feishu_heartbeat.json（processing_msg_id 非空=有任务在跑，等它完成或确认可中断）；② 查端口占用 lsof -iTCP:8902（有残留进程先 kill -TERM 再 restart）；③ 查 guard 日志（工作区变更会自动重启——改文件前先想清楚连锁）；④ 重启后触发一次调用验证 request.meta budget 正确。用 bash scripts/restart_system.sh restart（echo y 管道确认），脚本自带优雅停机+健康检查+单实例验证。"
evidence: "本次会话三次重启（21:50/22:35/23:06）：端口 8902 被残留进程占用导致 restart 失败→lsof 找 PID kill -TERM 后成功；飞书桥处理中消息会导致重启打断长任务（心跳 processing_msg_id 486s）；guard 因工作区变更自动重启触发飞书重推旧消息（EVO-38875e81 已修）。"
tags: [运维, 重启, 飞书桥, guard, 端口]
source: {}
status: active
created_at: "2026-08-16T23:51:02.774191+08:00"
updated_at: "2026-08-16T23:51:02.774191+08:00"
---