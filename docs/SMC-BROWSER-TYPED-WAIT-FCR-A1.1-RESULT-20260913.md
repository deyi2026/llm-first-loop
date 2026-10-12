# SMC Browser Typed Wait FCR A1.1 — Result — 2026-09-13

## 裁决

**A1.1 Frozen Gate：PASS（2/2）。**

- A0.1 mechanical/type/sensor qualification：**PASS**；
- A1.1 real-model read-only FCR：**PASS**；
- A2 main matrix：**尚未运行；现仅具备重新冻结独立 A2 protocol 的资格**；
- cloud canary：**NOT RUN**；
- bounded Semantic Operation：**未启动**。

本轮最重要的结论不是“多写了工具说明”，而是两条 v0.6-A1 真实失败都由程序机械辅助层关闭：live sensor 现在真实提供 `document_ready_state`，对象布尔条件在 lazy provider schema 中直接是 JSON `boolean`，模型不再维护 Predicate 固定关系或猜测字符串 `"true"` 与布尔 `true`。

## 冻结身份

- implementation：`8df9067a194a85aea158dbd57726cedbaec98569`
- protocol：`d8d807901633278b8f3c55e41340d4fcaeb23dbf`
- measured HEAD：`d8d807901633278b8f3c55e41340d4fcaeb23dbf`
- frozen plan SHA256：`f0ad447d90ff16674afe0343869195de9439e5d61ae5410cabc340c9148c4db2`
- provider surface SHA256：`b3604a7699c42d6b3900c2d6dff7c3d563967ef46f0efc5014107abb7fa4558b`
- provider surface chars：**4557**
- model：`cognilocal/ornith-1.5-35b-a3b-mlx`，Thinking ON，184K input / 16K output，temperature 0，max iterations 8，strict serial，无 fallback。

## 程序承担了什么

1. **感官事实补真**：Browser host 内部只允许一个固定的 `document.readyState` 机械探针；generic/model-supplied `Runtime.evaluate` 仍由硬边界拒绝。该事实进入已有 canonical observation，不新增语义判断。
2. **值类型机械化**：默认模型面从 generic scope/object wait 改为 `scope_url / scope_ready / scope_count / object_state / object_text` 五个 typed wait。`object_state.value` 是 machine schema 的 boolean；`scope_count.count` 是 integer；ready-state 是 closed enum。
3. **固定关系由程序编译**：例如 ready-state/operator=`eq`、object-state/operator=`eq`、scope target=`scope_ref`、object Semantic ID/scope 都由程序机械派生，再委托原 canonical Predicate evaluator / polling path。
4. **能力不虚报**：真实 live sensor 当前不提供 canonical `visible`，因此它没有进入 `object_state` model-facing enum。

明确**没有**加入：字符串到布尔值的隐式 coercion、自动 target selection、latest/snapshot、retry/replay、rebind、mutation、程序侧任务完成判断、provider-specific semantic rewrite 或 universal prompt 扩张。

## Surface 成本

旧 A1 exact read-only surface 为 **2938 chars / 4 tools**；A1.1 为 **4557 chars / 7 tools**，绝对增加 **1619 chars**。这是有意接受的机械合同成本：增加的是已经被真实失败证明 load-bearing 的类型/能力约束，不是装饰性提示。

## 两条真实 Ornith 结果

| Row | Task | Result | Rounds | Tools | First wait | Value type | Wait result | Wait failures | get_schema |
|---:|---|---|---:|---:|---|---|---|---:|---:|
| 1 | `scope_ready` | **PASS** | 3 | 2 | `browser_wait_scope_ready` | `str` | `satisfied` | 0 | 0 |
| 2 | `object_enabled` | **PASS** | 4 | 3 | `browser_wait_object_state` | `bool` | `satisfied` | 0 | 0 |

### Row 1 — `scope_ready`

轨迹只有：`snapshot → browser_wait_scope_ready`。首次 wait 4 个 required 字段完整，call value type=`str`，canonical Predicate value type=`str`；`predicate_result=satisfied`、observation reason=`null`、sample_count=1、observer error=0。typed failures、legacy wait、snapshot(predicate)、old generic wait、scope-target mismatch、mutation、fallback、SecurityAgent 全为 0。

这直接关闭旧 A1 的同任务失败：旧接口在 117 samples 后仍为 `indeterminate / property_unobserved`；A1.1 的真实 sensor 已能给出该机械事实。

### Row 2 — `object_enabled`

轨迹为：`snapshot → hydrate → browser_wait_object_state`。首次 wait 5 个 required 字段完整，call value type=`bool`，canonical Predicate value type=`bool`；`predicate_result=satisfied`、reason=`null`，typed failures=0，且模型没有调用 `get_tool_schema`。

旧 A1 在同一语义任务中连续 6 次把 `true/false` 作为字符串提交，并被正确 fail-closed；A1.1 通过 provider machine schema 让模型第一次就提交真实 JSON boolean，根因关闭。

## 关于动态 polling 的边界

A1.1 的 Row 2 在模型完成 snapshot/hydrate 后才调用 wait，因此不能仅凭该行声称模型一定经历了 disabled→enabled 的多采样转换。冻结实现前另有一次**真实隔离 Chrome、无模型**验证：同一按钮从 `enabled=false` 开始，`browser_wait_object_state(value=true)` 经 31 次只读采样后 observed `true` 并 satisfied；`scope_ready` 同样走真实 CDP sensor satisfied。该证据用于证明机械 polling 链路，而 A1.1 Row 2 用于证明模型 FCR / boolean contract。

## Gate 零错误项

两行共同满足：surface exact、infra valid、no fallback、no SecurityAgent、snapshot-before-wait、expected typed wait、结构完整、root cause closed、typed wait failures=0、old generic wait=0、legacy wait misuse=0、snapshot(predicate)=0、missing-Predicate=0、scope-target mismatch=0、mutation=0。

## Evidence SHA256

- results: `cc0e000a84d6e277c610a6bdc4139db35c158380af2ed41f1578f82ce6a7f80d`
- smoke gate: `0443e7012aa72552bb4f2f016c8f02f928c334dbe216403b5f6cb4bffffa8b5b`
- execution manifest: `233a31231907bd4a53a70fa3df63cf68c386130aeccf4ab4ec7ddc3d56c55bcd`
- measured plan file: `8474497332d23d0d6176bc9f855f6027760ca0492838fc6e60237628944de18d`

## 正式边界

A1.1 PASS 只证明**当前 mechanically typed read-only wait interface 已关闭 A1 的两个特定首调失败，并在两条冻结任务上可被 Ornith 正确使用**。它不自动证明主任务矩阵稳定，不自动开放 cloud，也不等于 Semantic Operation 已资格化。

因此下一步若继续，应新冻结 A2 main matrix；不能把 A1.1 2/2 直接外推成 A2 PASS。
