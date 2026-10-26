---
title: Apple Silicon 本地实时语音栈落地：mlx-audio 统一运行时 + Tier A 三件套实测打通（ASR→LLM→TTS 端到端 12.23s）
scenario: 在 Apple M5 Max / 128GB / macOS 26.5.1 上为 LFL Web 实时语音会话寻找全本地（无云端语音 Provider）的实时语音栈；此前只知道云端 Realtime/ASR/TTS 选项，未验证本机可行性。
root_cause: macOS 26.5 + Apple Silicon 上没有经验证的本地实时语音运行时；mlx-audio 同时提供 MLX 权重与 OpenAI 兼容接口，使 LFL 侧只需换 Provider 层而无需自建推理服务。
solution: "选定 mlx-audio（MLX 原生）作统一运行时（venv: ~/Project/research/voice-stack/.venv，python3.12，HF_HOME 在同目录 models/）。Tier A 四件套：nemotron-3.5-asr-streaming-0.6b-8bit（增量流式 ASR，首字 1.23s）、Qwen3-ASR-0.6B-8bit（终稿校正，逐字全对）、Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit（流式 TTS，RTF 0.66）、silero-vad。mlx-audio server 暴露 OpenAI 兼容 /v1/audio/speech、/v1/audio/transcriptions、WS /v1/realtime（仅转写语义，无 response.create/音频输出）、/v1/audio/transcriptions/realtime。端到端脚本 08：WS 流式 ASR → Ollama qwen3.5:35b-a3b-q4_K_M（必须 think:false）→ HTTP TTS，6.96s 中文语音输入端到端 12.23s。安装坑：mlx-audio 依赖 pkg_resources 需 setuptools<81，server 还需 uvicorn[standard]/fastapi/python-multipart/webrtcvad。"
evidence: 实测日志：~/Project/research/voice-stack/logs/local_voice_loop.json（ASR first_char 1.231s/final 7.14s、LLM ttft 0.66s、TTS first_byte 4.433s、end_to_end 12.23s）、smoke_result.json（TTS 首包 3.34s/RTF 0.658；Qwen3-ASR 推理 1.45s 转写逐字正确）、realtime_latency.txt（WS 增量时间线）、download_models.log（20GB 下载完成）；文档：~/Project/research/docs/本地实时语音模型下载推荐-20261023.md
tags: [本地部署, 实时语音, mlx, AppleSilicon, ASR, TTS, OpenAI兼容接口]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-23T13:26:58.919356+08:00"
updated_at: "2026-10-23T13:26:58.919356+08:00"
---