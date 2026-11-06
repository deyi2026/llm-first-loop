---
title: LFL 用户级 Linux 部署切换到 MiniMax（Anthropic 兼容端点）
scenario: 需要把用户级安装的 LFL（~/.local/share/lfl，0.6.37）从 GLM/OpenAI 协议切到 MiniMax 的 Anthropic 兼容端点（用户给的 platform.minimax.cn/docs/api-reference/text-anthropic-api），且 API Key 来自另一台机器的 .env。
root_cause: ""
solution: "1) 端点与协议：MiniMax 国内站 Anthropic 兼容 base 为 https://api.minimax.cn/anthropic（最终 URL 为 /anthropic/v1/messages，x-api-key + anthropic-version 头）；兼容模型仅 MiniMax-M3.1-Flash / MiniMax-M3；SSE 为标准 Anthropic 事件（thinking_delta + signature_delta + input_json_delta）。2) LFL 配置写 ~/.local/share/lfl/.env（= LFL_ENV_FILE，CLI/Web/飞书共用，env 优先）：LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_WIRE_PROTOCOL=anthropic；模型名写裸名（不带 provider 前缀），否则 registry 会用 providers.json 里的 https://api.minimax.chat/v1 覆盖 base_url。3) 改完必须重启进程才生效（Settings 启动冻结），用 `lfl doctor --online` 做有界真实连通性检查，再 `lfl chat ...` 跑一次带工具的多轮对话。4) 换密钥时用 `ssh host 'cat > file' < 本地env文件` 通过 stdin 传输，避免 key 出现在远端 argv/ps 与本地临时文件残留。"
evidence: 192.168.3.x 上 LFL 0.6.37 实测：doctor --online 通过；CLI chat 2 轮含工具调用成功；运行中的 Web 服务 POST /api/v1/chat 返回 model_used=minimax/MiniMax-M3.1-Flash、tokens_cache_hit=12160；data/audit/guarded_requests.jsonl provider=minimax。
tags: [lfl, minimax, anthropic, linux, provider-config]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T18:20:02.309546+08:00"
updated_at: "2026-11-06T18:20:02.309546+08:00"
---