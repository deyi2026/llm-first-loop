# P5 Exact Provider-Visible Context Integrity Qualification

日期：2026-09-14
分支：`fix/active-run-ingress-1214-20260914`
基线：`170f8833`（P4 State Lifetime 收口）
阶段：State Ownership / Run Ownership / Context Integrity — P5
范围：**deterministic exact provider-visible packet integrity**；真实 GLM-5.3 / Ornith live qualification 留在 P7。

## 1. 裁决

P5 的 authority 边界不是 `Session.messages`、history builder 或 adapter 中间结构，而是：

> **实际交给 provider transport 的最终 JSON packet。**

因此本阶段新增的专用 Gate 均 patch **已经构造完成的 `LLMClient._client.stream` 实例**，直接检查 physical send 参数。不能在 client 构造后再 patch `httpx.Client`，也不能把 `_to_*` 纯函数输出当作 provider wire 资格证据。

本阶段保持 LLM-First 边界：

- 程序只裁决 role / tool-call pairing / exact active-ingress identity / provider replay scope / wire shape 等机械协议事实；
- 不新增 prompt 规则，不判断工具是否“应该”调用，不替模型决定参数语义、任务相关性或完成状态；
- projection 无法机械保持原声明时 fail closed，不能静默改成 `{}`、换工具、换语义或复用旧 provider wire。

## 2. Final Wire Pipeline

最终 provider-visible packet 的主链为：

1. 从当前 durable Session truth 构造 provider-neutral history；
2. active run ingress 以 transport-internal `_active_run_ingress_ref` 精确标记，human / delegated provenance 保持原义；
3. exact provider/model/generation-contract 匹配时才恢复 provider-native replay；scope mismatch 只保留普通可见 history；
4. OpenAI-compatible 路径执行 tool-pair sanitizer + canonical tool-call/arguments normalization；
5. `provider_structure_violations()` 对最终内部 wire 做机械校验；
6. `_validate_and_strip_provider_structure()` 校验通过后剥离 `_active_run_ingress_ref`；
7. Anthropic / Google 再把已验证的 canonical tool declarations 机械转换为各自 native shape；
8. transport retry 仅允许同 provider/model 的**零输出前**重放同一个已验证 packet；已有任意 content/reasoning/tool delta 后禁止重放。

`LLMProjectionError` 在 transport 前失败；Engine 对 final-client projection rejection 同 logical round 最多从**当前 durable Session truth**做一次 conservative rebuild，第二次仍失败即 fail closed，不进入 provider fallback。Availability fallback 则为目标 provider 重新 build history/tools，禁止复用 primary provider 的已投影 packet。

## 3. P5 发现并修复的真实 Wire 缺口

### P5-A — Canonical tool call 在 Anthropic / Google physical wire 丢失 name/arguments

生产主循环持久化的是 OpenAI-canonical nested shape：

`tool_calls[].function{name, arguments}`。

旧 Anthropic / Google converter 测试使用 flat synthetic fixture（`tc.name/tc.arguments`），导致真实 canonical history 在 physical send 时被转换为 `name=""`、`input/args={}`。Google tool receipt 还只读 `tool_name`，而 canonical `Message.to_llm_dict()` 使用 `name`。

修复：新增共享机械解析 primitive `_tool_call_projection_parts()`，同时识别 production nested 与 legacy flat source shape；Anthropic `tool_use`、Google `functionCall` 复用同一解析；Google `functionResponse` 支持 canonical `name` 与 legacy `tool_name`。不修改 durable Session truth。

### P5-B — Fallback rebuild 有正确 active marker，但 fallback GuardContext 未绑定 authority

真实 Engine `500 -> cross-provider fallback -> real LLMClient` RED 证明：fallback request builder 已从 durable Session 重新生成 candidate messages，并携带正确 active-ingress marker；但 `FallbackService` 新建的 `GuardRequestContext` 没有 active ingress ref/kind，final validator 将正确 marker 判为 `active_run_ingress_unexpected_marker`，candidate 在 transport 前自拒绝。

修复：主循环把已经机械绑定的 `_active_run_ingress_ref/_kind` 作为 request-scoped 参数显式传入 fallback；不从 candidate marker 反推 authority，也不读取 recent/shared session state。

### P5-C — OpenAI final validator 只验证 id/pairing，坏 function payload 可穿过

RED 证明三类 canonical call 会到达 transport：

- `function.name=""`；
- `arguments` 为非法 JSON；
- `arguments` 为合法但非 object 的 JSON（如数组）。

修复：final structure validator 与 native converter 共用 `_tool_call_projection_parts()`；只校验 function name 存在、arguments 可机械解析成 JSON object。它不验证业务 schema 或参数是否适合任务。

### P5-D — Legacy flat direct caller 在 OpenAI 路径被 validator 理解，却非 canonical 发送

生产主链不生成 flat shape，但 `LLMClient` 的兼容 public boundary 仍可能收到 `{id,name,arguments}`。旧路径的 validator 能理解它，却会原样发送错误 OpenAI wire。

修复：扩展既有 `_normalize_tool_call_args()`，copy-on-write 把 legacy flat declaration 机械规范化为 `{id,type:"function",function:{name,arguments:string}}`；不改变 id、name 或 arguments 内容。

## 4. Dedicated Physical-Send Matrix — 17/17 PASS

`tests/unit/test_provider_wire_integrity_p5.py`：**17 tests collected / 17 PASS**。

| Gate | Physical wire invariant |
|---|---|
| OpenAI canonical + parallel tool group | exact active ingress 存在；assistant(tool_calls) 与两个 receipts 完整；internal marker 不出 wire |
| OpenAI legacy flat compatibility | physical send 前机械转为 canonical nested tool call |
| Anthropic canonical history | `tool_use.name/input` 保留真实 production declaration；tool_result id/content 配对 |
| Google canonical history | `functionCall.name/args` 与 `functionResponse.name/result` 完整 |
| Provider replay scope mismatch | `_provider_replay` 与 foreign native reasoning 不泄漏；普通 visible history 保留 |
| Anthropic/Google malformed args | invalid JSON / non-object JSON 均在 transport 前 fail closed |
| OpenAI malformed canonical call | missing name / invalid JSON / non-object JSON 均 transport=0 |
| Cross-provider fallback | fallback candidate 重新绑定 exact active ingress 后真实 send；marker 不泄漏 |
| Same-provider zero-output disconnect | 两次 physical JSON byte-structure 等价，只重放已验证 packet |
| Disconnect after output | physical send 仅 1 次，禁止 UI/tool replay |
| Retraction + attachment | 只见 `[RETRACTED]`；原正文、attachment excerpt、attachment_facts 不可见 |
| message_time | 只留下 model-visible mechanical time fact；`_message_time_ts` / ingress marker 均移除 |

## 5. Broad Context Integrity Matrix — 284/284 PASS

同一候选状态下运行 23 个相邻测试文件，共 **284 tests collected / 284 PASS**，覆盖：

- GLM 1214 human/delegated ingress、forced compaction、bad anchor/marker reopen；
- conservative rebuild / provider-authoritative overflow / no stale wire；
- OpenAI / Anthropic / Google / provider replay / reasoning replay；
- GuardRequestContext 隔离、projection guard、orphan/parallel tool pairing；
- history layering、cache compaction replay fidelity、tool working-set projection；
- model fallback / cross-provider rebuild / fallback capability boundary；
- provider call identity/resources/settlement；
- message time、retraction、recent continuity、capability projection；
- continuity / continuity kernel final invariants。

本轮 side-effect audit 与 Starlette/httpx 类 warning 仍为既有非阻断诊断；没有隐藏 warning 换取 PASS。

## 6. Static Qualification

- Ruff touched files：PASS；
- `py_compile` touched files：PASS；
- Pyright touched files：**0 errors / 0 warnings / 0 informations**；
- `git diff --check`：PASS。

最终提交前还需在 staged exact file set 上执行仓库 security scan，并在 commit 后复核 `git show --check` 与 clean worktree。

## 7. 明确未做

- 未发送真实 GLM / MiniMax / DeepSeek / Google / Anthropic 请求；P5 是 deterministic exact-wire qualification，live matrix 属 P7；
- 未重启 Web / Feishu / 8901 / 8903；
- 未启动第二个本地模型；
- 未 push / deploy / tag；
- 未修改 universal prompt、Rule / Experience / Method / Skill 注入；
- 未通过 provider fallback 修 projection bug；projection error 仍先本地 fail closed / conservative rebuild；
- 未进入 P6 legacy shared fallback 删除。
