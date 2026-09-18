---
title: 真实 LLM 评测管道排障三查：key/provider 匹配 + providers.json 隔离 + 脏环境变量 strip
scenario: "跑 scripts/run_eval.py 真实 LLM 评测时所有样本失败（0/6）：先遇 401 Unauthorized，再遇\"未知 provider: deepseek\"，再遇 reasoning_effort unknown variant 'max   '——三层连环，每修一层暴露下一层。根因分别指向：① .env 切换默认模型时只改了 LLM_MODEL 没同步 LLM_API_KEY/LLM_BASE_URL（key 是 kimi 的、URL 是 kimi 的，模型却是 deepseek → 401）；② 评测脚本 _settings 用临时 data_dir 隔离，无 providers.json → 多 provider 全限定模型名 resolve 失败（L0 合成不认识 deepseek/ 前缀）；③ 工具注入的 shell 环境残留带尾随空格的脏值（LLM_MODEL/LLM_REASONING_EFFORT='max   '），load_env_file\"环境优先\"跳过覆盖 → 模型名/推理档位带空格发送 → API 400。"
root_cause: "配置切换不彻底（改模型没改 key/url）+ 评测隔离目录缺 registry + 环境脏值被\"环境优先\"逻辑保留；三者叠加导致评测失败，且每层错误不同（401→未知 provider→400 变体）掩盖真实路径。"
solution: ① 配置一致性检查：默认模型切换后核对 .env 三元组（LLM_API_KEY/LLM_BASE_URL/LLM_MODEL）指向同一 provider——key 前缀可辨（sk-kimi- vs sk-0f28e）；② 隔离目录复制真实 providers.json：评测/测试用临时 data_dir 时把 data/providers.json 复制进去（保持会话隔离但 registry 可用），否则全限定模型名 resolve 失败；③ 脏环境防御：读取 LLM_MODEL/LLM_REASONING_EFFORT 等 env 时统一 .strip()（工具注入环境可能残留尾随空格，load_env_file 环境优先不覆盖）；排查顺序：先看 report.json samples_detail 的 answer_head 具体错误（401/400/404 各有不同根因），再逐层修复。
evidence: 2026-08-17 实测：eval_run 四次失败（401 kimi key 配 deepseek 模型 → 未知 provider deepseek → reasoning_effort 'max   ' 400），修复 .env 三元组 + 复制 providers.json + .strip() 后 42 样本全场景 ≥ 基线（6/7 满分）。提交 7177d19。
tags: [评测, run_eval, env, provider, 排障]
source: {}
status: active
created_at: "2026-08-17T01:45:57.684052+08:00"
updated_at: "2026-08-17T01:45:57.684052+08:00"
---