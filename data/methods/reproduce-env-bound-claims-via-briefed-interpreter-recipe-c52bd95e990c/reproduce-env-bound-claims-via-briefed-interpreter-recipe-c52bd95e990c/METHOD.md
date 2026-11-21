---
method_id: reproduce-env-bound-claims-via-briefed-interpreter-recipe-c52bd95e990c
name: reproduce-env-bound-claims-via-briefed-interpreter-recipe
description: 任务书把待核数字（全量测试通过数、Ruff/Pyright 等）显式绑定到某个指定环境（主仓库完整解释器 + 指向候选 src 的 PYTHONPATH）并给出可执行路径时，独立核验的第一未知量是『我的核验命令是否运行在配方环境里』：先把该解释器与环境变量设为所有核验命令的默认运行时并逐条复现声明，而不是自拼临时环境（uv --with、--noconftest、挑测试子集）。子集/绕过 conftest 的运行只能算补充证据；在配方未试尽前不得把可复现声明降格为『未核』，也不得把环境差异误报为代码问题。
aliases: 复核别人报的测试通过数, 用户给了 python 路径还要自己 uv 装依赖吗, 绕过 conftest 的子集测试算不算复现全量, 评审复现该在哪个环境跑, 协调者数字怎么独立核验
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bd90fc9e-ca00-4e5e-a9df-bc6dc4b19f43:70:845db793dff638d33a8e
evidence_refs: learning:learn:f3d39d30099f
created_at: 2026-11-17T00:48:26.608116+08:00
updated_at: 2026-11-17T00:48:26.608116+08:00
---
## Trigger
独立核验/评审任务中，任务书开头即给出可执行环境配方（权威解释器绝对路径 + PYTHONPATH/环境变量指向待验源码），待核声明被显式绑定到『在该环境完成』，且任务书同时警告不要走某条已知弯路（如反复自建装包）

## Discriminator
任务书文本在时刻零就含两条事实：(1) 待核数字与指定环境的绑定表述；(2) 完整解释器绝对路径已交出。二者把『核验命令在哪个环境跑』从多候选（worktree .venv、临时 uv env、系统 python）缩为唯一答案——先用给定配方；配方跑通即可对协调者数字直接对账复现

## Short path
- 从任务书机械提取两份清单：环境配方（解释器路径、PYTHONPATH、禁用项）+ 绑定该环境的待核声明（全量测试数、linter、类型检查、门禁 checker）
- 用配方环境跑一次 probe（该解释器 import 待验源码关键模块），确认配方可用
- 在配方环境内逐条复现声明：全量 pytest → linter → 类型检查 → 门禁，每条记『复现/证伪/环境性缺失』三态
- 只有配方环境自身缺某工具或路径失效时才记环境性未核；不在配方试尽前构造平行环境
- 终态裁决 + 已核/未核清单；子集或 --noconftest 运行仅作补充证据标注，不冒充全量复现

## Stop conditions
- 待核声明在配方环境内全部复现或证伪
- 配方解释器不存在/启动失败且无其他授权环境 → 如实记环境性未核，不用子集通过冒充复现
- 复现数字与声明数字完成精确对账，差异按差值报告

## Verification
- 核验命令回显中的解释器路径与环境变量逐字等于任务书配方
- 每条『未核』项都能指出配方环境具体缺什么工具，而非自己没试
- 最终报告中已核项的运行环境与声明绑定环境一致

## Counterexamples
- 待核声明不绑定环境（如『第 X 行存在 P0』）→ 任何能解析源码的解释器都行，配方只是偏好
- 任务书为防交叉污染明确禁止跨 worktree 共享解释器 → 平行隔离环境才是正解
- 配方解释器路径已失效 → 一次 probe 失败即回退上报，不要反复修补配方
