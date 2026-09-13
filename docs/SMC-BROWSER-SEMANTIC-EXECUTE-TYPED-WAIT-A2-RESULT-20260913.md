# SMC Browser Semantic Execute + Typed Wait A2 — Result — 2026-09-13

## 裁决

**A2 Frozen Main-Matrix Gate：FAIL。**

正式状态：

- v0.6-A.1 mechanically typed wait：**继续 PASS**；
- `browser_semantic_execute` + typed wait 主任务重复稳定性：**NOT_QUALIFIED_BY_A2**；
- external task oracle：**2/6**；
- cloud canary：**NOT_RUN_BY_GATE**；
- bounded Semantic Operation：**尚未实现/资格化**。

这轮最重要的新结论是：**A1/A1.1 已经修掉的 wait sensor / JSON type / generic Predicate 首调问题没有重新成为主故障；A2 的失败中心已经迁移到多步骤语义轨迹管理。** 当前原子接口仍要求模型自己维护 `observe → ground → navigate → re-observe → wait → execute → verify` 的过程节奏，Ornith 会在 target_ref、navigate args、snapshot/hydrate 选择以及 wait 选择之间消耗轮次或陷入自我循环。

## 冻结身份

- typed-wait implementation：`8df9067a194a85aea158dbd57726cedbaec98569`
- A1.1 qualification report：`901fc8ed`
- A2 protocol / measured HEAD：`01710b49bd82be99fbb5c946adbd9074d4344760`
- frozen plan SHA256：`490c1e2cd1b9377468eb07dc06d05b8950faf10db4b61748ff89af1005b8f878`（与 v0.5 confirmatory plan 保持一致）
- fixture SHA256：`87696076cea84d4e93f172d07a1499755dbc647f396ff115a9d64571740b72a3`（与 v0.5 fixture 字节身份一致）
- provider surface SHA256：`fb9df22ee8aded2fa1e2cc6a0448fe0a9d7cae4dea24c5afc28f5bced39128f3`
- provider surface chars：**5525**
- model：`cognilocal/ornith-1.5-35b-a3b-mlx`，Thinking ON，184K input / 16K output，temperature 0，max iterations 12，240s worker timeout，fresh session/data/Chrome profile，严格串行，无 fallback。

模型 surface 恰 8 个工具：`browser_perceive`、5 个 mechanically typed wait、`browser_semantic_execute`、`get_tool_schema`。旧 generic `browser_wait_scope/browser_wait_object` 不在 surface。

## 预注册 Gate 结果

| 条件 | 结果 |
|---|---:|
| 完整 rows | 6/6 已执行 |
| infra valid | **FAIL**（2 行 worker timeout） |
| surface exact | **Gate=False**（timeout 行无 terminal worker payload；见下方边界） |
| no fallback / no SecurityAgent | PASS |
| external task oracle | **2/6 FAIL** |
| `click_commit` | **1/2** |
| `fill_submit` | **1/2** |
| `delayed_wait` | **0/2** |
| every-row navigate/object receipt | **FAIL** |
| terminal typed-wait tool failures | **0** |
| terminal old generic wait calls | **0** |
| terminal legacy `browser_perceive(action=wait)` | **0** |
| terminal `snapshot(predicate)` | **0** |
| terminal scope/version blockers | **0** |
| terminal automatic retry | **0** |

`infra_valid=false` 与 `surface_exact=false` 不能解释成 provider surface 漂移：Rows 4/5 timeout 后没有 terminal worker payload；跑前 committed preflight 的 exact 8-tool surface 已通过，所有完成 worker 也都看到同一 frozen surface。冻结 gate 不对 timeout 行补造 terminal facts，所以保持 FAIL。

## 六条真实结果

| Row | Task | Repeat | Result | Rounds | Tools | Navigate ok | Object ok | Typed wait failures | bad target_ref |
|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `click_commit` | 1 | **PASS** | 12 | 12 | 1 | 1 | 0 | 1 |
| 2 | `fill_submit` | 1 | **PASS** | 10 | 9 | 1 | 2 | 0 | 1 |
| 3 | `delayed_wait` | 1 | **TASK_FAIL** | 12 | 12 | 0 | 0 | 0 | 1 |
| 4 | `delayed_wait` | 2 | **TIMEOUT** | — | — | — | — | — | — |
| 5 | `fill_submit` | 2 | **TIMEOUT** | — | — | — | — | — | — |
| 6 | `click_commit` | 2 | **TASK_FAIL** | 12 | 12 | 1 | 0 | 0 | 1 |


## 失败分型

### Row 3 — `delayed_wait/r1` — TASK_FAIL

typed wait 本身没有失败：4 次 typed wait 都是工具级 success，结构完整；旧 generic wait、legacy perceive-wait、scope blocker、automatic retry 都为 0。但模型在初始 invalid `target_ref` 后没有形成合法 navigate，反而反复对当前 fixture scope 做 `scope_ready / scope_url`，并两次把 `grounding_ref` 错塞给 `browser_perceive(snapshot)`。12 rounds 用尽时 navigate/object receipt 都还是 0。

### Row 4 — `delayed_wait/r2` — TIMEOUT

partial durable evidence 显示：模型已经从初始 invalid `target_ref` 恢复，完成了合法 navigate，并 hydrate 到 `Readiness status` 对象。之后模型长期在“应该用 `object_text`、object state 还是再 snapshot”之间自我反复，明确多次形成“要调用 `browser_wait_object_text(value_text contains Ready)`”的计划，却迟迟没有真正发出该工具调用，最终 240s timeout。

这不是 typed wait contract rejection；它是**计划已形成但动作没有提交**的轨迹停滞。

### Row 5 — `fill_submit/r2` — TIMEOUT

partial durable evidence中 `browser_wait_scope_ready` 已 `satisfied`，typed wait 无 failure。随后模型错误地给 `browser_perceive(snapshot)` 附加 `grounding_ref`，之后 semantic navigate 产生 rejected receipt，再读取 `browser_semantic_execute` schema；推理进入重复“navigate failed / check schema”循环直到 240s timeout。没有进入 fill/save。

### Row 6 — `click_commit/r2` — TASK_FAIL

真实 navigate 最终成功，typed wait 2 次 / 0 failure、scope blocker=0、auto retry=0；但 semantic execute 出现两次 `args_contract_mismatch` rejected receipt。12 rounds 结束前只完成 navigate，没有进入最终 Commit click。

## 与 v0.5 confirmatory 的关系

v0.5 同一 plan/task/fixture 在旧 semantic surface 上是 **3/6**，每个任务 1/2；其中 wait contract failures 总计 7，失败任务占 6。A2 改为 mechanically typed wait 后，terminal gate 中 typed-wait failures 降到 **0**，旧 generic/legacy wait/snapshot(predicate) 也都是 0，但任务成功反而只有 **2/6**。

因此不能宣称“typed wait 已提高整个任务成功率”；它证明的是更窄但更可靠的事实：**wait 的 sensor/type/schema 机械错误已被移出主要故障面。** 剩余不稳定性现在更清晰地集中在连续操作组织、semantic_execute args 首调以及有限轮次内的步骤推进。

## 架构判断

这轮结果支持前面的架构裁决：下一步不应继续给原子工具堆更多参数说明，也不应让程序偷偷 auto-target / auto-latest / auto-retry / auto-rebind。

更合适的是设计 **Bounded Semantic Operation Contract v0.1**：

- 模型一次声明一段有边界的语义操作（对象、目标状态、动作顺序/条件、期望观察）；
- 程序只把**模型已经声明的 semantic clauses**机械展开成 observe / exact ground / typed wait / single-dispatch execute / re-observe；
- 程序可以做 constrained re-grounding，但只能回到模型预先声明的同一语义身份；0 个或多于 1 个精确匹配立即停并交回模型；
- 程序不能新增模型未声明的目标、动作、业务选择或“任务已完成”判断；
- atomic `browser_semantic_execute` 与 typed waits 继续保留，作为底层原语、异常处理和可审计 receipt 层。

这样要解决的不是“模型不会 click/fill/wait”，而是**模型不应承担本可由程序可靠完成的微观过程控制**。

## Evidence SHA256

- `results.jsonl`: `eb55c3eafbdf25916848aabcb12f812c6374c52091bbd00fa311437ab28bf0f4`
- `smoke-gate.json`: `e5a6e3fbb16c26fe056e5de2d00b051af86c0b262741f1d15e1157a32a493da1`
- `execution-manifest.json`: `715fdbb93fbf0b2ca264bb0e207215019c9b24eb2d712ede617ee1b9ed7686f0`
- `plan.json`: `c5be20eabb7c33ae948a1347e01b94ce7cde61f15cc8500e0e603e1426019401`

## 证据边界

Rows 4/5 的 event log partial evidence 只用于失败取证，**没有被偷偷写入 terminal worker aggregate 或 frozen gate**。因此 gate 中 timeout rows 的 navigate/object/typed-wait terminal统计保持缺失；报告中明确分开写。

本轮不资格化 cloud provider，不资格化 Bounded Semantic Operation，也不改变 Browser Phase 1 已冻结的 version/staleness/single-dispatch/receipt 安全边界。失败行不重放，A2 gate 不事后修改，本证据集内不修 production。
