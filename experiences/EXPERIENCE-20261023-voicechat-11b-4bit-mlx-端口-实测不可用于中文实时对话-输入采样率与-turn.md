---
title: VoiceChat-11B-4bit（MLX 端口）实测不可用于中文实时对话：输入采样率与 turn 收尾未核对，且中英文输入返回同一段英文人格寒暄
scenario: 把 NemotronLabs-VoiceChat-11B-4bit（mlx-community MLX 移植）当作 LFL 中文实时语音会话的全双工底座，评估时只看了「全双工 + function calling」的宣传，没有先验证本机可用性与中文效果。
root_cause: MLX 移植 + 会话配置未调通：输入采样率/turn 收尾/系统提示任一不对都会静默产生跑偏输出；且该模型对非英语内容的理解在本机未体现。
solution: 暂不采用，保留为观察项。若要继续排查，按序做三件事：(1) 确认输入采样率——config.source_sample_rate=16000、target_sample_rate=22050，push_audio 传错采样率不会报错只会被当成 16k 解释（我第一次喂 24k 导致输出完全跑偏）；(2) 用 create_session().generate(audio=...) 做离线一问一答基线，再用 create_duplex_session() + flush() 做双工；(3) 再看是否需要系统提示/语言设置/VAD 分段与 turn 收尾。若要第二个全双工对照样本，先下 kyutai/moshiko-mlx-q4 或 Qwen3-Omni AWQ 4bit。
evidence: "实测：/Users/yyj/Project/research/voice-stack/logs/voicechat_offline_result.json（zh 33.36s、en 16.29s，同一英文人格寒暄）；voicechat_duplex_result.json（assistant_text \"The novel was written by Chinese author Mo Sheng.\"，first_text 6.18s，无 function_delta）；sts_voicechat_result.json；源码 mlx_audio/sts/models/nemotron_voicechat/{config.py:source_sample_rate=16000,target=22050,streaming.py:push_audio(sample_rate=...) 校验, flush()}"
tags: [VoiceChat, 全双工, MLX, 踩坑, 采样率]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-23T13:27:16.657244+08:00"
updated_at: "2026-10-23T13:27:16.657244+08:00"
---