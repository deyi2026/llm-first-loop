---
title: 镜像操作者 6 项自测协议处理（RULE-AI-19 报告规范）
scenario: 操作者经 8903 API 在镜像环境（llm-first-loop-mirror）发来 6 项自测请求：RULE-AI-19 行为自测/必读指令验证/方法层执行报告/缓存观测/工具修复验证/环境盲区声明，要求只读+自测+报告。
root_cause: 自测请求含交叉验证项（必读指令=read_file 行为本身），需把验证动作与数据采集合并到最少工具轮；镜像环境数据与主区隔离，观察结论须标注来源域。
solution: ①第一步并行 read_file(full=true) 规则文件 + architecture_status()，同时完成必读指令与版本感知验证；②RULE-AI-19 无真实粘贴输入时如实声明不可实测，改用规则文本逐条对照+本会话首句行为实测+构造样例演示（标注推断）；③缓存观测需跨轮积累，单轮只能给基线+机制推断（缓存按模型独立预热，切换后命中率重新统计）；④architecture_status 带 dimensions 数组正常传参不报假错误；⑤镜像态观察（CWD/action_trace/进程 pid/记忆注入）只属镜像，不作主区事实；⑥save_experience 会真实落盘经验库，报告中须明示。
evidence: "本会话实测：read_file docs/ai_rules.lite.md 返回 version=3；architecture_status(dimensions=[\"architecture_config\"]) 与 ([\"rules_version\",\"evolution\"]) 均 success 无假错误；model_catalog 确认模型 deepseek-v4-flash；EVO-20260820-6857bf41 记录 dimensions 传参假错误历史。"
tags: [自测, 镜像, RULE-AI-19, 报告规范, 缓存观测]
source: {}
status: active
created_at: "2026-08-20T16:26:51.696801+08:00"
updated_at: "2026-08-20T16:26:51.696801+08:00"
---