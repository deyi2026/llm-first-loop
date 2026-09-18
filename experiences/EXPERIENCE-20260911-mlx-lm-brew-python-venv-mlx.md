---
title: mlx-lm 本地服务重启崩溃：brew python 与 .venv 的 mlx 版本不匹配
scenario: "重启 /Users/yyj/Project/research/mlx-lm 的 mlx_lm.server（8901 端口）时，沿用旧进程的启动命令（brew python@3.14）立即崩溃：AttributeError: module 'mlx.core' has no attribute 'new_thread_local_stream'（mlx_lm/generate.py:220 模块级代码，导入即执行，与并发参数无关）。"
root_cause: mlx-lm 代码更新（2026-09-11 前）在 generate.py 引入 mlx 0.32 新 API；brew python 环境的 mlx 0.31.1 无此 API，模块导入即崩。错误信息看似与并发参数相关，实为解释器环境选择错误。
solution: 用 .venv/bin/python（mlx 0.32.2，含 new_thread_local_stream）启动，而非 brew python（mlx 0.31.1 缺该 API）。launchd plist 本来就配置 .venv python；手动启动若照抄 ps aux 里的旧进程命令行会踩坑，因为旧进程是在代码更新前用旧解释器起的。多并发路径验证：--prompt-concurrency 2 --decode-concurrency 2 双请求时间重叠执行、各自 ~22 tok/s 无排队。
evidence: "evidence://v1/88ec9bd10dcea08f13502ec86a47d7aa30f45fbd37dc4b410b177da1bd687308；崩溃日志 /Users/yyj/Project/research/runtime/logs/qwen8901.stderr.log 2026-09-11 07:31-07:33 三次 AttributeError；.venv mlx 0.32.2 vs brew python mlx 0.31.1"
tags: [mlx-lm, python-环境, 版本不匹配, launchd, 并发]
source: {}
status: invalid
created_at: "2026-09-11T07:36:25.207794+08:00"
updated_at: "2026-09-11T14:11:48.720587+08:00"
---