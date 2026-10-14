---
title: workbuddy2api 桥接层部署与 LFL reasoning_control 实测
scenario: 需要让 LFL (llm-first-loop) 通过 OpenAI 兼容协议使用 WorkBuddy/CodeBuddy 账号的模型。上游 copilot.tencent.com 只有私有 /v2/chat/completions；DSH 插件 dsh-workbuddy-connect 已在进程内注册 workbuddy provider（shim 端口随机、SHARED_SECRET 进程内不落盘），外部不可吃。
root_cause: ""
solution: |
  1) 桥接层真实仓库是 ShouZhuo0413/codebuddy2api（项目对外名 workbuddy2api，Python+FastAPI+uvicorn），不是 Sliverkiss/workbuddy2api——后者已删除，插件注释里的 attribution 指向上游而非可部署物。
  2) 部署：git clone --depth 1 → python3 -m venv .venv → .venv/bin/pip install -r requirements.txt → nohup .venv/bin/python -m core.converter --port 8904 --log converter.log &。不需要 OAuth 登录：converter 直接解密桌面端凭据 ~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info。
  3) 不带 --api-key 启动时对 bearer 不做校验，故 LFL 侧 api_key_env 应设 ""（空串），不是 WORKBUDDY_API_KEY。
  4) 实测判定 reasoning_control=always_on_effort：bridge 的 PASSTHROUGH_BODY_KEYS 只透传 reasoning_effort，不透传 thinking/enable_thinking/thinking_budget（67 个上游请求体中 thinking 出现 0 次，reasoning_effort 出现 30 次）。所以 thinking_type 控制会静默失效，always_on_effort 是唯一正确取值。上游接受任意字符串 effort（low/xhigh 均返回 OK），取合法交集后写 reasoning_efforts。
  5) 验证链路必须逐层核：直接 curl bridge（/v1/models + /v1/chat/completions）→ 用 LFL 自己的 load_registry + LLMClient 打真实请求 → 回查 bridge converter.log 的「上游 REQUEST BODY」确认 reasoning_effort 真的出网，而不是只看 LFL 侧 state。
  6) 判定 LFL 解析是否真的落地用 python 直接调 load_registry(Settings(...)) 打印 spec.base_url/api_key_env 与 reg.reasoning_contract()；model_catalog 只能作二手证据。注意 Settings 需显式传 llm_api_key/base_url/model，否则加载的是另一份配置。
  7) LLMClient.chat(messages, tools) 返回单个 response 对象（不是事件流），逐事件迭代会静默拿到空结果、看起来像"成功但无内容"。
evidence: "bridge /v1/models 返回 35 个模型含 deepseek-v4-pro；POST /v1/chat/completions model=deepseek-v4-pro 返回 200 且 content=\"PONG\"；LFL 侧 load_registry 解析出 base_url=http://127.0.0.1:8904/v1, api_key_env='', 18 模型；reg.reasoning_contract('workbuddy','step-5-preview') -> (True,'always_on_effort')；LLMClient 打 step-5-preview/space-bunny/glm-5.3 均返回 OK，converter.log 上游体分别带 effort=high/max/medium；model_catalog 已显示 [workbuddy] 18 模型 reasoning_control=always_on_effort"
tags: [workbuddy, workbuddy2api, codebuddy, provider-config, reasoning_control, bridge, llm-first-loop]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T08:57:44.074558+08:00"
updated_at: "2026-10-13T08:57:44.074558+08:00"
---