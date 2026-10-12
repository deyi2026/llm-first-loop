---
title: 本地 mlx_lm 多会话巨大内存/变慢真实根因：模型名未命中别名触发 HuggingFace 在线解析（修复=全名别名+HF_HUB_OFFLINE=1）
scenario: "macOS 上 mlx_lm.server 托管 Ornith-1.5-35B-A3B-MLX（8901 端口），多个会话/客户端访问时机器出现\"巨大内存\"占用、生成速度急剧变慢。曾误判为并发参数问题（2/2→4/4），证伪：当前运行参数为 1/1 且多开恢复正常。"
root_cause: 客户端请求的模型名不在 mlx_lm.server 别名表内（全名 ornith-ai/Ornith-1.5-35B-A3B-MLX、短名 qwen 等写法混用），server 将其当作 HuggingFace repo 转在线解析（stderr 留有 GET api/models/... 401/200 记录），别名不命中时按新模型路径再次加载 → 35B 级第二份内存 → 内存压力/swap → 全局变慢。机制部分为证据推断，未经内存剖析直接证实；修复与效果已获用户确认。
solution: 1) 别名表覆盖客户端所有会用的模型名写法：短名 + HF 全名都显式 --alias 到同一路径；2) 服务环境加 HF_HUB_OFFLINE=1，禁止在线解析，未知模型名直接报错而不是上网拉取；3) 验收方法：ps aux 确认运行参数；grep stderr 中 huggingface.co/api/models 出现即别名未命中，补别名而不是调并发；重启后确认单进程无重载。
evidence: "stderr：09:56:30/11:57:29/13:03:33 全名 revision/main 200 OK，12:20:10-11 短名 qwen 401×2；13:36 plist 变更（+HF_HUB_OFFLINE=1、+全名别名，mtime 实证）；修复后 PID 33380 单进程运行、无重载、rss 68GB、swap 15.4G→9.3G 回收；2026-09-11 14:03 用户确认\"最后一次修复才真正解决巨大内存问题\"。"
tags: [mlx_lm, 模型别名, HF_HUB_OFFLINE, 巨大内存, 多会话, 已确认修复]
source: {}
status: active
created_at: "2026-09-11T14:11:48.733200+08:00"
updated_at: "2026-09-11T14:11:48.733200+08:00"
---