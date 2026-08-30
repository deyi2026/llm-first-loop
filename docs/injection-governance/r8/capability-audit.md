# R8.1 Provider Capability Metadata Audit

日期：2026-08-30

## 结论

本轮只补**有项目内实测证据**的能力元数据，不按模型名、provider、context、价格或 `thinking` 猜档。`data/providers.json` 仅新增 5 个 metadata 字段，未改 endpoint、模型名、凭据引用、预算或路由。

当前脱敏 inventory：

```text
models_total=11
classified=4 (36.36%)
strong=1
weak=3
unknown=7
profile: full=1, minimal=10
canary_ready=false
```

因此结论是 **metadata coverage improved, behavior canary still NOT READY**。不进入 R9，不调用 `refresh_config`。

## 判定规则

- `strong`：同一 R7 legacy/bad-structure A 臂 6-fixture `completion=100%`、`drift=0`、`user dominance=100%`。
- `weak`：受控 A 臂 `completion<80%` 或 `user dominance<90%`。
- 介于两者或无受控证据：`unknown`。
- `reasoning`：strong 模型只有在 provider/runtime 有直接证据时才显式填写；weak 模型不依赖 `reasoning` 才能完成 R8 metadata gate。

## 11 模型审计表

| 模型 | tier | reasoning 更新 | 证据 | 结论 |
|---|---|---:|---|---|
| `cognilocal/qwen3.8-27b-cog` | weak | — | 现跑 R7 A：1/6，dominance 0 | 可审核 weak |
| `deepseek/deepseek-v4-flash` | unknown | — | 当前审计 shell 无 provider credential | 不猜 |
| `deepseek/deepseek-v4-pro` | unknown | — | 当前审计 shell 无 provider credential | 不猜 |
| `glm/glm-5.3` | unknown | — | 当前审计 shell 无 provider credential | 不猜 |
| `glm/glm-5.3-flash` | unknown | — | 当前审计 shell 无 provider credential | 不猜 |
| `local/qwen/qwen3.8-27b` | strong | true | R7 frozen A：6/6、drift 0、dominance 1；6/6 有 reasoning tokens | 可审核 full recommendation |
| `local/qwen3.6-27b-fable-fusion-711-uncensored-heretic-nm-dau-neo-max-mtp` | unknown | — | 当前 catalog 不存在；配置 ID chat=HTTP 400 | 不猜 |
| `local/qwen3.8-27b-mlx` | weak | — | alias 实际映射 `qwen3.8-27b-mlx@4bit`；R7 frozen A：4/6、dominance 0 | 可审核 weak |
| `local/qwythos-9b-claude-mythos-5-1m@q4_k_m` | weak | — | 现跑 R7 A：1/6、dominance 0 | 可审核 weak |
| `minimax/MiniMax-M3` | unknown | — | 当前审计 shell 无 provider credential | 不猜 |
| `mxnook/glm-5.3-flash` | unknown | — | 当前审计 shell 无 provider credential | 不猜 |

## 配置变更

`data/providers.json` 为 Git ignored runtime config。原始 SHA-256：`fc7afbaa...871e1`；更新后：`e25e7447...749cd`。语义变化严格只有：

- cognilocal qwen3.8-27b-cog: `capability_tier=weak`
- local qwen/qwen3.8-27b: `capability_tier=strong`, `reasoning=true`
- local qwen3.8-27b-mlx: `capability_tier=weak`
- local Qwythos 9B q4: `capability_tier=weak`

原文件已在本次执行环境中做可逆备份；tracked evidence 不记录主机本地备份路径。

## 为什么不热重载

当前 `MODEL_PROVIDERS` 没有覆盖文件，且 `LFL_DATA_DIR` 指向本 workspace `data/`，所以文件是后续 refresh/restart 的真实来源。但 `refresh_config` 会重读整套 `.env`，其影响面大于 metadata-only 变更。由于 `canary_ready=false`，本轮没有理由为了 shadow telemetry 立即扩大 live 变更面。

## 下一门

剩余 7 个 unknown 中，6 个云端/远端模型需要在不暴露凭据的受控运行环境补同一 A/B；Qwen3.6 配置需要先恢复可调用性。只有 `metadata_complete_coverage=100%`，才讨论 R8 behavior canary；在此之前 R9 继续保持未开始。

## 验证门

```text
runtime registry parse: PASS (11 models, classified 4, unknown 7)
R8/provider/event focused: 112/112 PASS
inventory deterministic byte reproduction: PASS
pyright (R8 production/tests): 0 errors / 0 warnings
py_compile: PASS
R0-1..R0-4: PASS
R0 tracked output: 0-byte diff
```

pytest 仍报告仓库既有 21 条 provider URL 人工复核 warning；不是本轮新增且不阻断。
