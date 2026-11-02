---
method_id: llm-server-ab-benchmark-protocol-805dc9b0316c
name: llm-server-ab-benchmark-protocol
description: 对两个 LLM 推理服务器做公平 A/B 吞吐对比的可复用协议：固定输出 token 窗口、真实 tokenizer 计数、decode/e2e 分离、交错发请求、输出哈希校验、并发内存干扰说明。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:3caec2da-e2d5-42be-80d2-60268ec4cecb:234:267a209b7585fe377198
created_at: 2026-11-01T20:04:24.478050+08:00
updated_at: 2026-11-01T20:04:24.478050+08:00
---
适用场景：比较两个本地 LLM 推理引擎（rapid-mlx / mlx-lm / oMLX / LM Studio）的 decode 吞吐与端到端延迟。

步骤：
1. 固定变量：同一 HF 权重快照（HF_HUB_OFFLINE=1）、同一 prompt、同一 temperature=0、同一 max_tokens；两臂用同一 client 脚本与同一 HTTP 协议路径。
2. 固定生成量：客户端在收到固定数量 SSE chunk 后主动断流（close），保证各臂生成量一致，避免 EOS 时机差异污染比值。
3. 真实 token 计数：用模型自带 tokenizer.json（tokenizers.Tokenizer.from_file）重新编码收到的文本得真实 token 数；SSE chunk 数 ≠ token 数。
4. 指标分离：decode_tps = 真实token /(末chunk时刻−首chunk时刻)（剔 prefill）；e2e_tps = 真实token /(结束−请求开始)（含 prefill）；另记 TTFT。两个口径可能给出相反结论，必须同时报告。
5. 交错发请求：偶数轮 A→B，奇数轮 B→A，消除热漂移；每组重复 ≥5 次取中位数。
6. 一致性校验：对每臂输出算 sha1，同臂各次应一致（确定性）；跨臂若不一致，说明两引擎 chat template/推理解析不同，此时速率可比、内容不可比，须在报告中显式声明。
7. 注意并发干扰：两服务同机并存会争内存带宽，绝对值互有影响，比值仍有效；应在报告的「偏差与限制」中写明。
8. 记录引擎侧能力开关：多数推理服务有推测解码/MTP/量化 KV 等开关，其服务端日志会打印实际生效项（如 spec decode OFF / MTP disabled）——必须核对，否则会把"未启用的卖点"当成已验证的性能来源。

反例（本任务实际踩到）：
- 用 chunk 数当 token 数且不固定生成量 → 结论从"长 prompt 慢 0.84×"翻转为"快 1.60×"。
- 在 /v1/completions 上直接比较不同引擎的输出文本 → 一臂提前 EOS 只出 1 token，另一臂正常生成，速率被系统性低估。
- 只与对手的"某版本"比较却不说版本 → rapid-mlx 依赖 mlx-lm<0.32(实测0.31.3)，而最新 mlx-lm 0.32.2 在密集模型上反而更快，基线版本直接改变结论方向。
