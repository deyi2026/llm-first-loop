---
title: Docker Hub 429 限流：SWE 批量镜像拉取须串行+间隔，429 后等待 30 分钟恢复窗口（已验证）
scenario: SWE 批量评测需拉取 swebench 官方 docker 镜像（每实例 3.5GB，x86_64/arm64 双架构），批量拉取时 docker pull 返回 429 Too Many Requests 导致 harness completed=False。
root_cause: Docker Hub 匿名拉取有 IP 级速率限制（约 100 pulls/6h 窗口）；先前 batch7/8 大量拉取耗尽配额，batch9 批量拉取触发 429。manifest inspect 轻量探测不耗配额，但 docker pull 拉取大镜像（3.5GB）消耗配额快。
solution: 1) 批量拉取前先用 docker manifest inspect 探测可用性（不耗配额）；2) 正式拉取必须串行 + sleep 5s 间隔（禁止并发批量拉）；3) 遇 429 时注册 30 分钟循环提醒等待恢复（IP 级限流窗口，短等无效）；4) 拉取用后台任务（前台 60s 超时不够拉 3.5GB 镜像）；5) 恢复后先拉 1 个验证，再串行拉全。落地：batch9 恢复后串行拉取+重跑 10/10 resolved。
evidence: batch9 官方 harness 首次 0/10：docker pull swebench/sweb.eval.x86_64.* 全部 429 Too Many Requests；等待 5/15/30 分钟各重试一次仍 429；30 分钟后恢复（IP 级限流窗口）。恢复后串行拉取+5s 间隔成功，重跑 10/10 resolved。
tags: [Docker, 429限流, SWE, 镜像拉取, 批量]
source: {}
status: active
created_at: "2026-08-19T21:31:53.409972+08:00"
updated_at: "2026-08-19T21:31:53.409972+08:00"
---