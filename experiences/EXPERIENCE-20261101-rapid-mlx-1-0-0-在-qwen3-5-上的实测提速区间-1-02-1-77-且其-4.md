---
title: "rapid-mlx 1.0.0 在 Qwen3.5 上的实测提速区间 1.02×–1.77×，且其\"4×\"依赖的推测解码在本机为 OFF"
scenario: "需要判断是否把本机 MLX 推理从 mlx-lm 换成 rapid-mlx，官方声称\"up to 4× faster than Apple's MLX (mlx-lm), 1.5× on a typical task\"。"
root_cause: 提速主要来自 rapid-mlx 自己的 kernel 融合与调度优化，而非对所有模型生效的通用路径；推测解码（其最大卖点）在 hybrid 架构模型上不启用。
solution: 本机 M5 Max/128GB 实测结论：提速高度依赖模型与场景，而非普遍 4×。(1) MoE 收益最大——Qwen3.5-35B-A3B-4bit 短 prompt decode 1.77×、e2e 1.76×；密集 4B 仅 1.02×（decode），e2e 1.09×（优势来自 TTFT 0.12s vs 0.24s）。(2) 长上下文收益更大——4B 在 2000 词上下文达 1.60× decode / 1.49× e2e。(3) 对照基线版本很关键——rapid-mlx 硬依赖 mlx-lm<0.32（实测装到 0.31.3），而最新 mlx-lm 0.32.2 在 4B 短 prompt 反而更快（0.31.3 的 0.96×）；官方对比未声明对手版本。(4) 其日志显示本机两个 Qwen3.5 模型均 spec decode OFF / MTP disabled（hybrid 架构），即 4× 卖点依赖 MTP 推测解码的路径在本机条件未启用。安装注意：brew install rapid-mlx 因 /opt/homebrew 属主不可写而失败，改用 PyPI 1.0.0 装独立 venv；Homebrew 公式为 0.15.7，与 PyPI 1.0.0 版本线不一致。
evidence: "本机实测：4B 短 prompt n=8 decode A=115.73/B=117.97；4B 2000词 n=6 A=35.82/B=57.40；35B 短 n=6 A=90.64/B=159.97；35B 长 n=5 A=67.54/B=93.22。rapid-mlx 服务日志原文：\"Model profile: qwen3.5-4b-4bit → dense GatedDeltaNet ... spec decode OFF\"、\"qwen3.5-35b-4bit → hybrid (linear-attention/Mamba), spec decode OFF\"；info 输出 \"supports_spec_decode=False\"。原始日志与报告见 artifacts/rapidmlx-ab-20261101/。"
tags: [rapid-mlx, mlx-lm, apple-silicon, local-llm, benchmark, tooling-eval]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-01T20:04:02.401635+08:00"
updated_at: "2026-11-01T20:04:02.401635+08:00"
---