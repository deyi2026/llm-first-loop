---
title: MiniMax 中国站（TokenPlan Ultra）接入 LFL 的正确配置形态
scenario: Linux 主机（Ubuntu/glibc，LFL 0.6.37 wheel 安装）要把模型切到 MiniMax 中国站，账号为 TokenPlan Ultra 年度会员。
root_cause: ""
solution: "端点与模型：OpenAI 兼容 https://api.minimax.cn/v1（模型 MiniMax-M3.1-Flash，另有 MiniMax-M3）；Anthropic 兼容 https://api.minimax.cn/anthropic（POST /anthropic/v1/messages，支持 MiniMax-M3 / MiniMax-M3.1-Flash）。LFL 侧配置：.env 设 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_WIRE_PROTOCOL=openai / LLM_REASONING_EFFORT；档位元数据不在 .env，而在 data/providers.local.json 的 provider 条目（reasoning_control=always_on_effort，reasoning_efforts=[low,medium,high,xhigh,max]，reasoning_default_effort=high）。档位经 registry.resolve(LLM_MODEL) 进入默认 client，Web 端 /api/v1/providers 可查 reasoning_efforts；LLM_MODEL 带 provider 前缀（minimax/xxx）时 runtime 也能解析，但 doctor 在线探针会 400。"
evidence: "主机 192.168.3.x：doctor --online「模型在线检测：一次最小请求成功」；/api/v1/providers 返回 minimax/MiniMax-M3.1-Flash、reasoning_efforts=[low,medium,high,xhigh,max]、context=1000000；出站抓包见 reasoning_effort=max 下发；直连 reasoning_effort=low 返回 reasoning_tokens=0。"
tags: [minimax, provider, linux, reasoning-effort, anthropic-compat]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T18:54:13.534484+08:00"
updated_at: "2026-11-06T18:54:13.534484+08:00"
supersedes: [EXPERIENCE-20261106-lfl-用户级-linux-部署切换到-minimax-anthropic-兼容端点]
---

当前性验证：复现 = ssh <user>@192.168.3.x 'export PATH=$HOME/.local/bin:$PATH; timeout 45 lfl doctor --online' 应出现「模型在线检测：一次最小请求成功」；再 curl -s http://127.0.0.1:8903/api/v1/providers 应能看到 provider minimax 的 reasoning_efforts=[low,medium,high,xhigh,max] 与 base_url=https://api.minimax.cn/v1。若 doctor 报 400 unknown model，说明 LLM_MODEL 又被写成了带 provider 前缀的形式。