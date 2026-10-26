---
title: "Ollama 的 qwen3.5 默认 thinking 模式会让流式 content 为空：语音链路必须显式 \"think\": false"
scenario: "把本地 Ollama 的 qwen3.5:35b-a3b-q4_K_M 接进实时语音闭环做文本主脑，按 OpenAI 习惯只读 message.content。"
root_cause: thinking 模型的 token 先进入 message.thinking 字段，message.content 为空；只读 content 的客户端会误判为「模型无输出」。
solution: "请求体加 \"think\": false；或把客户端改为同时消费 message.thinking 并把 num_predict 留足。实测加 think:false 后首字 0.66s、总 1.09s、20 段流式正常。所有本地流式接入都要先确认所选模型是否默认 thinking。"
evidence: "curl 实测：/api/chat 默认模式首行 {\"message\":{\"role\":\"assistant\",\"content\":\"\",\"thinking\":\"Thinking\"}}，num_predict=80 时 done_reason=length 且 content 仍为空；加 \"think\":false 后 ttft 2.279s、eval_count 49、文本正常输出。写入 /Users/yyj/Project/research/voice-stack/scripts/08_local_voice_loop.py"
tags: [Ollama, thinking, 流式, 实时语音]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T13:27:16.878651+08:00"
updated_at: "2026-10-23T13:27:16.878651+08:00"
---