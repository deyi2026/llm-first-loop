---
title: "LFL provider 配置:providers.local.json 硬覆盖并早退,providers.json 是死文件"
scenario: "在 LFL 仓库改 data/providers.json 增加 provider 后,refresh_config 报告 provider/模型数不变,改动完全未生效。"
root_cause: ""
solution: "读 src/llm_loop/llm/providers.py 的 load_registry():优先级链为 MODEL_PROVIDERS env > {data_dir}/providers.local.json > {data_dir}/providers.json > LLM_* env 合成。关键是 providers.local.json 分支在 providers.py:1204 做 `providers = _parse_providers_dict(data); return finalize(...)` —— 硬替换并 return,providers.json 分支永远走不到。诊断动作:refresh_config 后对比 provider/模型计数,不变即说明改错了文件;再用 model_catalog 看 base_url 确认实际生效的是哪份。修 data/providers.json 后仍无效时不要继续加内容,先查 data_dir 下是否有 providers.local.json(本机 data_dir=/Users/<user>/Project/llm-first-loop-mirror/data,来自 runtime.toml 的 lfl_data_dir)。注意本机 data/providers.json 不在 git 跟踪内,git checkout 无法回滚,须手工按 sha256 复原。"
evidence: "evidence://v1/fad2635b76667b110ba43fb544e360dcaa259f54d02027379d130f9cd583e39c (providers.json 定位) ; execute_command 探明 data/providers.local.json 存在(7148B, 2026-09-28, 含 cognilocal/deepseek/glm/minimax) ; read_file providers.py:1196-1229 读到 _parse_providers_dict + return 早退 ; refresh_config 前后计数 6/12 → 7/30 ; model_catalog 确认 [workbuddy] base_url=http://127.0.0.1:8904/v1 已加载 18 个模型"
tags: [lfl, providers.json, 配置加载, 遮蔽, refresh_config, model_catalog]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T08:33:34.715269+08:00"
updated_at: "2026-10-13T08:33:34.715269+08:00"
---