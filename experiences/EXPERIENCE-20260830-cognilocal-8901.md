---
title: cognilocal（8901）标准启动脚本与挂死处置
scenario: "cognilocal 本地认知运行时服务（localhost:8901，模型 qwen3.8-27b-cog）挂死/需重启时。症状特征：/v1/models 秒回 200 但 /v1/chat/completions 推理无限挂死（探针 curl -m 300 不返回）。"
root_cause: ""
solution: 标准启动脚本：~/Project/research/mlx-lm/scripts/start-cog-server.sh（用户 2026-08-30 明示，勿自创重启方式）。重启后先短探针验证 chat/completions 推理恢复（非仅 models 接口），再进行全链路测试。
evidence: 用户 2026-08-30 明示：这是重启脚本：标准启动脚本 ~/Project/research/mlx-lm/scripts/start-cog-server.sh。此前 2026-08-29/30 两次实测 8901 推理挂死（lsof 监听正常 + models 200 + chat 挂死），job-1/job-4/job-7 全链路测试被阻塞。
tags: [cognilocal, 8901, 重启脚本, start-cog-server, 本地模型, 推理挂死]
source: {}
status: archived
created_at: "2026-08-30T01:22:47.229223+08:00"
updated_at: "2026-09-06T00:19:02.697933+08:00"
---

## cognilocal（8901）服务标准启动脚本

标准启动脚本：`~/Project/research/mlx-lm/scripts/start-cog-server.sh`

背景：cognilocal provider（base_url=http://localhost:8901/v1，模型 qwen3.8-27b-cog）是本地认知运行时服务。2026-08-29/30 两次出现"服务进程活着（/v1/models 秒回 200）但 chat/completions 推理无限挂死（curl -m 300 不返回）"症状，只能重启服务恢复。

要点：
- 用户明确指示（2026-08-30）：重启 cognilocal 用 `~/Project/research/mlx-lm/scripts/start-cog-server.sh`，勿自创方式
- 挂死特征：models 接口正常 + 推理路径无响应 → 判定服务侧推理管线问题，非 LFL 侧
- 重启后探活：短 curl chat/completions（max_tokens 小值）确认推理恢复，再跑全链路测试

## 2026-09-06 lifecycle review

该 SOP 指向的 start-cog-server.sh 当前已不存在；当前 research/mlx-lm/scripts 只有 start-ornith-server.sh，cognilocal:8901 默认模型也已是 ornith-1.5-35b-a3b-mlx。旧启动脚本/旧 qwen3.8-cog SOP 退出 active；现行启动事实以当前 operator script 为准。

