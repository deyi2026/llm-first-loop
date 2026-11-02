---
title: LLM 推理服务器 A/B 基准：必须固定输出 token 窗口并用真实 tokenizer 计数，否则比值会被 EOS 时机污染
scenario: 对比两个 LLM 推理服务（rapid-mlx vs mlx-lm）的 decode 吞吐时，误把 SSE chunk 数当 token 数、且未固定各臂生成量，导致结论反复翻转（先测得长 prompt 下 B 臂慢 0.84×，修正后为快 1.60×）。
root_cause: chunk 数与 token 数不等价；不同引擎 chat template/推理解析差异使各臂自然结束长度不同，短输出臂的 e2e 窗口被压缩，速率被系统性低估。
solution: "三个必要条件：(1) 各臂生成量严格一致——客户端在收到固定数量的 SSE chunk 后主动断流，且用模型自带 tokenizer.json 重新编码输出文本得真实 token 数（chunk≠token）；(2) 区分 decode_tps（真实token/(末chunk时刻−首chunk时刻)，剔prefill）与 e2e_tps（含prefill），两者结论可能相反；(3) 交错发请求（偶数轮 A→B，奇数轮 B→A）消除热漂移，并做同臂输出哈希一致性校验确认确定性。附：不同引擎的 /v1/completions 可能套用不同 chat template 与推理解析，导致 EOS 时机不同、输出文本不可直接互校——速率可比但内容不可比，需在报告中显式声明。当前性验证：先执行 `grep -n \"real_tokens\|decode_tps\|sha1\" artifacts/rapidmlx-ab-20261101/bench_client.py` 确认测量脚本仍在且包含真实 token 计数与哈希校验逻辑；再跑 `python3 artifacts/rapidmlx-ab-20261101/bench_client.py '<arms-json>' <ctx_words> <reps> <label> 128 <snapshot_path>`（需两臂服务已起）复算，期望输出同格式的 SUMMARY 与 RATIO 段。"
evidence: 本机 M5 Max/128GB 实测：mlx-community/Qwen3.5-4B-MLX-4bit 与 Qwen3.5-35B-A3B-4bit，rapid-mlx 1.0.0 vs mlx-lm 0.31.3/0.32.2。修正前（按 chunk 计数、未固定生成量）长 prompt 结论为 B/A=0.836；修正后（真实 token 计数 + 固定 400 chunk 窗口 + 交错顺序）为 4B 长 prompt 1.60×、35B 短 prompt 1.77×。原始日志见 artifacts/rapidmlx-ab-20261101/。
tags: [benchmark, ab-test, llm-inference, mlx, methodology, measure-first]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T20:04:16.501880+08:00"
updated_at: "2026-11-01T20:04:16.501880+08:00"
---