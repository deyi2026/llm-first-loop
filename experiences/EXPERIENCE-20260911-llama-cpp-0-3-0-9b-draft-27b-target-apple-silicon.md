---
title: llama.cpp 0.3.0 投机解码：9B draft 给 27B target 是负优化（Apple Silicon 实测）
scenario: 在 Apple Silicon 统一内存机器上用小模型给大模型（27B）做 speculative decoding 加速，或在 llama.cpp 0.3.0 上做 spec-decoding / MTP draft 测试
root_cause: ""
solution: 用 --spec-type draft-simple 绕过 MTP 自动检测后可正常跑通，但 9B→27B 全面负优化（n-max 3/8/16 = 15/7/5 t/s vs 基线 27.5）。正确方向：同家族 ≤2B draft，或带 MTP 层的 target GGUF。0.3.0 新参数：--spec-type draft-simple、-md、-ngld、--spec-draft-n-max(默认3)、--single-turn；日志在 stdout
evidence: ""
tags: [llama.cpp, speculative-decoding, MTP, apple-silicon, qwen, 性能测试]
source: {}
status: active
qualification: 2026-09-18 batch2/3 per-file review: retained（methodology self-evident：步骤可机械复现或含实测细节；evidence 内嵌正文）
created_at: "2026-09-11T01:16:51.581716+08:00"
updated_at: "2026-09-11T01:16:51.581716+08:00"
---

# llama.cpp 0.3.0 投机解码实测与踩坑（Apple Silicon）

## 结论
9B draft → 27B target（draft-simple）全面负优化：基线 27.5 t/s，spec n-max=3 → 15.2，n-max=8 → 7.3，n-max=16 → 4.6 t/s。ngram-simple ≈ 基线持平。

## 根因
1. **draft:target 成本比过高**：9B Q4(5.9GB)/27B Q4(16.8GB) ≈ 35%。统一内存下 target 单卡打满，verify 批处理不省带宽。投机解码需要 draft ≪ 10% target 成本（0.5B–2B 级别）。
2. **接受率 ~1 token/轮**：n-max 越大越慢 ⇒ 每轮固定只吃 ~1 个。9B 是 Claude-Mythos 不同微调，分布与 Qwen3.8-27B 一两个 token 后就分叉。
3. **MTP draft 的限制**：draft-mtp 路径要求 target 也有 MTP 层（h_nextn），否则 GGML_ASSERT "MTP input row width must match the target h_nextn width"。draft-simple 会忽略 MTP 头，每个 draft token 仍跑全量 9B 前向。

## 0.3.0 参数/行为变化
- `-md`→`--spec-draft-model`（-md 别名保留）；`--spec-draft-n-max`（默认 3）；draft GPU 层数是 `-ngld`（不是 --spec-draft-n-gpu-layers）；`--spec-type none|draft-simple|draft-eagle3|draft-mtp|draft-dflash|draft-dspark|ngram-*`
- llama-bench 已无 draft 参数；spec 测速用 llama-cli
- 日志/perf 全走 stdout（不是 stderr）；默认进对话模式，需 `--single-turn` + `< /dev/null` 防交互挂起
- 参数名错误时 stderr 报 usage 但可能静默退出（后台脚本要 grep Generation 兜底）

## 测试纪律
- 同批测基线（GPU 有快慢相位，观察到 18 vs 27.5 t/s 波动）；单独跑的对照要重测基线再比较