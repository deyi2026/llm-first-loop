# R8.1 / R8.2 Provider Capability Metadata Audit

日期：2026-08-30

## 结论

能力分档继续遵守同一原则：**只写有受控项目证据的 metadata，不按模型名、provider、context、价格或 `thinking` 猜档。**

R8 初验为 11/11 unknown；R8.1 先补本地/可验证模型并按 owner 指令退役不用的 Qwen3.6；R8.2 再通过 credential-safe 远端 A/B 补 5 个云模型。当前脱敏 inventory：

```text
models_total=9
classified=9 (100.0%)
strong=1
weak=8
unknown=0
profile: full=1, minimal=8
canary_ready=true
```

R8.2 结束时唯一 remaining unknown 是 `mxnook/glm-5.3-flash`：受控 A/B 12/12 为 HTTP error，独立最小 prompt 在 thinking 开/关时均返回 HTTP 502。因此它从未被误判为 weak。owner 随后明确表示可忽略 mxnook，本轮已将其从 active provider inventory 退役并保留审计记录。

当前结论是 **metadata gate READY（9/9=100%），behavior canary 尚未启动**。下一门是 R8.3 shadow soak，不进入 R9，本轮也不调用 `refresh_config`。

## 判定规则

- `strong`：同一 R7 legacy/bad-structure A 臂 6-fixture `completion=100%`、`drift=0`、`user dominance=100%`。
- `weak`：无 HTTP/network transport failure 的受控 A 臂中，`completion<80%` 或 `user dominance<90%`。
- `LLMEmptyResponseError` 是仓库定义的“provider 流正常结束但没有 final content/tool call”，按**行为完成失败**计，不属于 transport failure。
- HTTP/network/protocol transport failure 会让该模型保持 `unknown`，不得据此判 weak。
- `reasoning`：strong 模型只有在 provider/runtime 有直接证据时才显式填写；weak 模型不依赖 `reasoning` 才能完成 R8 metadata gate。

## 当前 9 模型审计表

| 模型 | tier | reasoning 更新 | 证据 | 结论 |
|---|---|---:|---|---|
| `cognilocal/qwen3.8-27b-cog` | weak | — | R7 A：1/6，dominance 0 | 可审核 weak |
| `deepseek/deepseek-v4-flash` | weak | — | R8.2 A：2/6；独立 T3/T4 dominance=1/2 | 可审核 weak |
| `deepseek/deepseek-v4-pro` | weak | — | R8.2 A：4/6；独立 T3/T4 dominance=1/2 | 可审核 weak |
| `glm/glm-5.3` | weak | — | R8.2 A：1/6；独立 T3/T4 dominance=0/2 | 可审核 weak |
| `glm/glm-5.3-flash` | weak | — | R8.2 A：3/6；独立 T3/T4 dominance=1/2 | 可审核 weak |
| `local/qwen/qwen3.8-27b` | strong | true | R7 frozen A：6/6、drift 0、dominance 1；6/6 有 reasoning tokens | 可审核 full recommendation |
| `local/qwen3.8-27b-mlx` | weak | — | alias 实际映射 `qwen3.8-27b-mlx@4bit`；R7 frozen A：4/6、dominance 0 | 可审核 weak |
| `local/qwythos-9b-claude-mythos-5-1m@q4_k_m` | weak | — | R7 A：1/6、dominance 0 | 可审核 weak |
| `minimax/MiniMax-M3` | weak | — | R8.2 A：3/6；独立 T3/T4 dominance=0/2 | 可审核 weak |

Qwen3.6 自定义模型与 mxnook GLM 5.3 Flash 均已按 owner 指令从 active inventory 退役，只在 `capability-audit.json:retired_models` 留审计记录，不再参与 coverage 分母。

## R8.2 credential-safe 远端 A/B

可复跑入口：`scripts/injection_r8_remote_ab.py`。证据：`docs/injection-governance/r8/remote-ab.json`。

执行边界：

- 通过项目 `load_env_file -> ProviderRegistry.client_params -> LLMClient` 在一次性子进程内解析已有凭据；
- runner 不打印、不落盘 key、Authorization header、endpoint、raw HTTP body；
- raw model answer 也不持久化，只保存 answer hash/长度、score、token/reasoning 计数和安全错误类型；
- 输入直接使用冻结 R7 A/B `build_arm()`，72/72 prompt SHA 与当前 fixture 重算一致；
- `mode=shadow / applied=false` 不变，runner 不修改 providers.json、不调用 refresh、不改变 prompt。

首轮 6 模型 A/B：

| 模型 | A completion | A dominance | B completion | B dominance | 判定 |
|---|---:|---:|---:|---:|---|
| DeepSeek V4 Flash | 33.33% | 0% | 100% | 100% | weak |
| DeepSeek V4 Pro | 66.67% | 0% | 83.33% | 100% | weak |
| GLM 5.3 | 16.67% | 0% | 33.33% | 0% | weak |
| GLM 5.3 Flash | 50.0% | 0% | 16.67% | 0% | weak |
| MiniMax M3 | 50.0% | 0% | 66.67% | 0% | weak |
| mxnook GLM 5.3 Flash | N/A | N/A | N/A | N/A | unknown / HTTP 502 |

这里的 A/B 有两个不同用途：A 臂决定 capability tier；B 臂只观察当前 R2/R3/R5/R6 治理是否能救回任务，**不参与 strong/weak 判定**。DeepSeek Flash 的 B 6/6 明显受益；而 GLM/MiniMax 在 B 下仍有完成不足，说明后续 weak-profile canary 值得验证，但不能在 shadow 阶段提前应用。

为排除单次采样偶然，T3/T4 dominance 独立复跑结果：

```text
deepseek-v4-flash: 1/2
deepseek-v4-pro:   1/2
glm-5.3:           0/2
glm-5.3-flash:     1/2
MiniMax-M3:        0/2
```

全部低于 strong gate 的 2/2。

## 运行时配置变更

`data/providers.json` 为 Git ignored runtime config。R8/R8.1/R8.2 的配置 SHA 链：

```text
R8 初始:             fc7afbaa...871e1
R8.1 四模型 metadata: e25e7447...749cd
退役 Qwen3.6 后:      bc800ffa...72e8f03
R8.2 五模型 weak 后:  e07be3c4...12e9d31
退役 mxnook 后:        5ae22fa8...6e62fa
```

当前语义变化累计为：

- cognilocal qwen3.8-27b-cog: `capability_tier=weak`
- local qwen/qwen3.8-27b: `capability_tier=strong`, `reasoning=true`
- local qwen3.8-27b-mlx: `capability_tier=weak`
- local Qwythos 9B q4: `capability_tier=weak`
- DeepSeek V4 Flash / Pro: `capability_tier=weak`
- GLM 5.3 / 5.3 Flash: `capability_tier=weak`
- MiniMax M3: `capability_tier=weak`
- Qwen3.6 自定义模型：owner 退役，从 runtime catalog 删除
- mxnook GLM 5.3 Flash：owner 明确允许忽略，从 active runtime catalog 退役；未判 weak

没有修改 endpoint、模型名、凭据引用、预算、K 值或路由。

## 为什么仍不热重载

当前 `MODEL_PROVIDERS` 没有覆盖文件，且 `LFL_DATA_DIR` 指向本 workspace `data/`，所以磁盘文件是后续 refresh/restart 的真实来源。当前 metadata gate 已 `canary_ready=true`，但 `refresh_config` 会重读整套 `.env`，影响面大于本轮“退役 provider”变更；因此本轮继续不热重载。R8.3 应把 live reload/restart 作为受控 shadow-soak 的显式起点。

## 下一门

metadata coverage 已达到 `9/9 = 100%`，`canary_ready=true`。下一阶段应是 **R8.3 shadow soak**：受控 reload/restart 让 live registry 读取当前 metadata，继续保持 `mode=shadow, applied=false`，观察 attribution / alias / fallback / 1210 retry 是否稳定。R8.3 通过前不进入 behavior canary，更不直接进入 R9。

## 验证门

```text
R8.2 focused: 117/117 PASS
remote-runner evaluator: 5/5 PASS（包含在 117）
pyright (R8 production/scripts/tests): 0 errors / 0 warnings
py_compile: PASS
git diff --check: PASS
runtime inventory deterministic byte reproduction: PASS
remote evidence prompt hash: 72/72 PASS
remote evidence secret/endpoint/path scan: PASS
R0-1..R0-4: PASS
R0 tracked output: 0-byte diff
detached clean checkout: PASS（117/117 + static + inventory + R0；status before/after clean）
```

pytest 仍报告仓库既有 21 条 provider URL 人工复核 warning；不是本轮新增且不阻断。
