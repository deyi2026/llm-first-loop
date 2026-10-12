---
title: 直构 LLMClient 的测试须走 registry 路由（与 engine 同源），否则 provider 切换时 base_url/key/model 三元组错配 → 400
scenario: 多 provider（deepseek/glm/minimax）+ providers.json registry 路由架构下，集成测试直接构造 LLMClient 读取 LLM_BASE_URL+DEEPSEEK_API_KEY：当 LLM_MODEL 切换 provider（如 glm/glm-5.3）而 LLM_BASE_URL/key 链未同步时，测试与生产路由分叉。
root_cause: ""
solution: "测试内构造 client 时与 factory 同源：load_registry(Settings(llm_model=model_ref)).resolve(model_ref) → client_params()（base_url/key 按 provider 的 api_key_env 同源取）；registry 降级才回退旧 env 直读链。模型解析失败响亮抛错（防静默换路由），key 缺失转 pytest.skip（保 CI 无 secrets 不假红）。配套: 冒烟脚本补导出各 provider key env。"
evidence: "tests/integration/test_cache_hit_smoke.py（_client registry 路由）；scripts/run_real_smoke.sh:42-50（三 key 导出）；三场景实测 [cache-gate:glm] 97.7/97.7、[cache-gate:minimax] 6.6→92.6（宽容档）、[cache-gate:deepseek] 96.9/96.9；factory.py:176 registry 优先路由对照。"
tags: [provider-registry, integration-test, routing-divergence, env-hygiene, bash32-quirk]
source: {}
status: active
created_at: "2026-09-09T23:17:53.103519+08:00"
updated_at: "2026-09-09T23:17:53.103519+08:00"
---

## 症状
tests/integration/test_cache_hit_smoke.py 直构 LLMClient 读 LLM_BASE_URL+DEEPSEEK_API_KEY+LLM_MODEL。.env 中 LLM_MODEL 改为 glm/glm-5.3（2026-08-30）但 LLM_BASE_URL 仍指 deepseek → 裸跑冒烟 = deepseek key 调 deepseek 端点的 glm 模型 → HTTP 400。此前非 deepseek 门禁全靠手工覆盖 env 才能跑。

## 根因
生产路由（factory.py）对 provider/ 前缀模型名走 registry.resolve + client_params（base_url/key 按 providers.json 同源解析），Settings 里的 llm_base_url/llm_api_key 不参与；测试直接构造 LLMClient 绕过了这条路由真相。

## 修复（2026-09-09）
1. 测试 _client() 与 factory 同链路: load_registry(Settings(llm_model=model_ref)) → resolve → client_params；registry 降级时回退旧直读 env 链。未知模型仍响亮抛错（不静默换路由）；key 缺失转 pytest.skip（保 CI 无 secrets 不假红）。
2. scripts/run_real_smoke.sh 补导出 GLM_API_KEY/MINIMAX_API_KEY（load_env_val 同链），硬门 key 检查放宽为三家任一。

## 验证
冒烟裸环境（零手工覆盖）三场景: glm 97.7%/97.7% ✓、minimax 冷 6.6%→宽容档 best_of_pair 92.6% ✓、deepseek 96.9%/96.9% ✓；无 key 环境 SKIPPED（含 env 名）；未知模型 ValueError。

## 教训
- 测试直构组件时必须复用生产装配路径，否则配置漂移只在特定 provider 组合下爆。
- macOS 自带 bash 3.2 `source <(进程替换)` 赋值不生效（文件 source 正常）——写 env 验证 harness 用临时文件中转，勿用进程替换。