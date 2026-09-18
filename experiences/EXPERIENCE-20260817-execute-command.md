---
title: 批量合并确认类小动作：避免 execute_command 碎调用推高停滞率
scenario: 排障/验证过程中需要反复查看状态（stats/心跳/日志/git）时，如果每次单独 execute_command，会积累大量同指纹重复动作——自我评估 stagnation_rate 高达 0.78（最近 50 条动作中 execute_command 18 次、同指纹多条重复），既消耗轮次又污染指标。
root_cause: 习惯性逐个确认状态（查一次心跳、看一次日志、跑一次 pytest），未意识这些是同指纹重复动作；execute_command 每次独立 shell 无法复用，重复成本被低估。
solution: "把多个\"查看/确认\"类小动作合并为一次批量命令（一个 execute_command 内用 && / 分段 echo 依次输出多项状态），或在需要轮询时用后台脚本 + 结果文件一次启动、定时读一次。本会话后期改为后台轮询（poll_stats.py nohup + 结果文件）后效果显著：从每轮 sleep+cat 碎调用变成一次启动+一次读取。规律：查询类动作 2 个以上就合并；等待类动作一律后台化。"
evidence: SE-20260816-004-43cd stagnation_rate=0.78；action_trace 最近 50 条 execute_command 18 次（36%）、去重后仅 13 个指纹；本会话 pytest 输出获取反复尝试 5+ 次不同管道写法
tags: [工具效率, execute_command, 批量, 停滞率, 轮询]
source: {}
status: active
created_at: "2026-08-17T00:56:29.262166+08:00"
updated_at: "2026-08-17T00:56:29.262166+08:00"
---