---
title: 改 LaunchAgent plist 的三个坑：全局 sed 误伤 env 值 / 未加载≠不生效 / 模型别名会触发在线换模型
scenario: macOS LaunchAgent 管理 mlx_lm 本地推理服务（~/Library/LaunchAgents/local.mlx.qwen8901.plist），服务当前由 nohup 手动运行、agent 未加载
root_cause: ""
solution: "1) 先 cp -p 留备份并 ls 验证存在；2) 修改用按 key 定点的 sed（/<key>X<\/key>/{n;s|...|...|}），禁用裸值全局替换；3) 改完 plutil -lint + diff 备份逐行核对，diff 出现计划外 hunks 立即回滚重做；4) 判断 agent 重启影响用 launchctl print-disabled（不在禁用列表=登录时会自动加载），不能只看 launchctl list；5) MLX_LM_MODEL_ALIAS 里所有新旧别名统一指向当前运行模型，防止请求触发在线换模型或 HF 拉取。"
evidence: ""
tags: [macos, launchd, plist, mlx-lm, sed, sed-collateral-damage, launchagent, model-alias]
source: {}
status: archived
archived_at: 2026-09-18
archived_reason: lifecycle-batch1: invalid 标记收尾（已判失效，归档保留全文可追溯）
created_at: "2026-09-11T07:44:21.275804+08:00"
updated_at: "2026-09-11T14:11:48.724265+08:00"
---

排查/修改 ~/Library/LaunchAgents 下的 plist 时：1) 不要用 `<string>1</string>`→`<string>2</string>` 这类全局 sed——plist 里环境变量值(如 MLX_LM_COGNITIVE_CACHE=1、PYTHONUNBUFFERED=1)同样匹配，会误伤；应按 `<key>X</key>` 上下文定点改，改完必须 diff 备份逐行核对。2) `launchctl print` 报 service 不存在 ≠ 该 agent 无害：只要没被 `launchctl disable`，重启/登录时 launchd 会按 plist 原文自动加载。本次 local.mlx.qwen8901.plist 里模型还是旧的 Qwen3.8-27B+并发1，若不修，重启后 8901 端口会静默换成错模型。3) mlx_lm.server 的 MLX_LM_MODEL_ALIAS 映射会在请求时触发在线换模型(_load 先卸载再加载)，别名必须全部指向当前运行模型路径，且要包含历史客户端可能还在用的旧别名，否则旧名请求可能触发 HF 远端拉取。4) 上次会话报告"plist 已改并发2+有备份"与事实不符(mtime/内容/备份都不存在)——跨会话声称已完成文件修改的结论，必须用 mtime+内容+备份存在性三重验证后再采信。