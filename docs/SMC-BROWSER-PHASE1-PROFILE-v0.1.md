# SMC Browser Phase 1 Domain Profile v0.1

> 上位合同：`docs/SMC-CONTRACT-v0.1.md`
>
> R3 依据：`docs/SMC-R3-BROWSER-PAPER-STRESS-20260913.md/json`
>
> 机器规格：`docs/SMC-BROWSER-PHASE1-PROFILE-v0.1.json`
>
> closed shape schema：`docs/SMC-BROWSER-PHASE1-SCHEMA-v0.1.json`
>
> 状态：**B-SPEC / spec-only / not implemented**。

## 0. 本文解决什么，不解决什么

B-SPEC 的目标不是“把 Playwright 包一层 JSON”，而是先把 Browser Phase 1 的机械合同冻结到足够窄，使后续 adapter 无法靠实现自由度重新长出第二套策略系统。

本版本只定义：

- scope / identity namespace；
- DOM + AX sensor contract；
- Browser SemanticObject 字段与 C28 conflict wire；
- Browser snapshot / diff / grounding；
- structured Predicate；
- SemanticAction verb vocabulary；
- operation / idempotency / atomicity / version precondition；
- append-only ActionReceipt / boundary events；
- legacy Playwright surface isolation；
- R3 B0–B14 的机械资格映射。

本版本**不实现**：

- 真实 DOM / AX observation；
- Browser stable ID tracker；
- click/fill/select/navigate/scroll dispatch；
- Browser receipt store；
- vision-only object actionability；
- browser chrome / native OS UI；
- 模型 Browser A/B。

因此本文的 PASS 只能叫 **spec conformance / schema conformance**，不能叫 Browser implementation conformance。

---

## 1. 双层机器权威：JSON Schema 管形状，Profile 管交叉字段

B-SPEC 故意不把所有语义压进一份巨大 JSON Schema。

### 1.1 Closed JSON Schema

`SMC-BROWSER-PHASE1-SCHEMA-v0.1.json` 负责：

- 六类模型面对象的字段闭合；
- required / type / enum / `const`；
- 每个 object 的 `additionalProperties=false`；
- Browser attributes/state/relations/coverage 的 closed vocabulary；
- action args 的 closed shape；
- raw backend locator / strategy 字段无法混入已知 object shape。

v0.1 **不提供开放 extension bag**。如果将来需要新增模型面字段，必须升级 profile/schema 版本，而不是把任意内容塞入 `extensions` 绕过 Authority 审查。

### 1.2 Machine Profile

`SMC-BROWSER-PHASE1-PROFILE-v0.1.json` 负责 JSON Schema 不适合单独表达的机械交叉约束：

- `verb -> operation_class / idempotency_class / atomicity_class`；
- `verb -> args_schema`；
- `verb -> version_precondition / version_scope`；
- `Predicate.property -> operator / value type`；
- scope generation / namespace 规则；
- active sensor contract；
- C28 conflict 处理；
- retry / receipt / grounding discipline；
- B0–B14 与 R3 fixture obligations。

这两层都是程序可机械验证的**合同事实**，不包含任务相关性、优先级、最佳候选、恢复策略或完成判断。

---

## 2. Surface isolation（B0）

### 2.1 模型面唯一目标形态

Browser Phase 1 qualification arm 声明：

```text
profile = smc-manipulation-v0.1
browser_domain_profile = browser-phase1-v0.1
model_surface = smc_browser_phase1_only
```

模型只看到 Semantic ID / semantic scope / GroundingRef。

模型面禁止：

- CSS selector；
- XPath；
- 屏幕坐标；
- CDP node id；
- AX index；
- native handle。

这些 backend locator 可以在 adapter 内部存在，但不得进入 SemanticAction / Predicate 的 target wire。

### 2.2 legacy Playwright 的定位

现有：

- `playwright_exec`
- `playwright_test`

只属于：

- backend/L1 mechanics reuse；
- 独立 E2E；
- URL sandbox / AST safety / CDP AX / screenshot 等低层能力来源。

它们**不是 SMC model surface**。

未来正式 Browser qualification 若模型直接调用 legacy tool：

- 要么测试 setup 直接禁止；
- 要么该 run 明确记为 intervention / invalid treatment。

不得把 selector/script surface 与 SMC Semantic ID surface 混在同一个实验臂里然后声称“SMC 通过”。

---

## 3. Scope model（B1）

Browser v0.1 scope hierarchy：

```text
runtime
  └─ page
      └─ document
          └─ frame
              └─ nested frame ...
```

机器 profile 固定 scope kinds：

```text
runtime / page / document / frame
```

### 3.1 Namespace

- Semantic ID 的唯一性范围：`runtime_session`；
- `scope_ref` 为 opaque semantic reference，调用方不得靠字符串编码猜 scope；
- adapter restart 产生新的 runtime namespace；旧 runtime 的 ID 不得碰巧复用成“仍有效”；
- 同内容两个 tab 仍是两个 page scope，不能因 DOM 相似而 alias。

### 3.2 Generation

至少必须能机械区分：

- runtime generation；
- page generation；
- document generation；
- frame generation。

规则：

- full navigation/reload → document generation 改变；
- frame navigation → 对应 frame generation 改变；
- SPA `history.pushState` 若物理 document 未替换，不要求 document generation 改变；URL/state 作为普通机械字段变化进入 snapshot/diff；
- identity continuity 只能在声明 lifetime 内延续。

### 3.3 Identity 不由“像不像”裁决

内容/role/name/结构相似性只能产生：

- identity basis；
- candidate facts；
- ambiguity facts。

它不能单独证明物理身份连续性。

若旧对象消失后出现两个相似按钮：

```text
old_id -> unresolved/retired
```

而不是：

```text
old_id -> 自动绑定“最像”的按钮
```

---

## 4. Sensor contract 与 C28（B2/B4/B11）

### 4.1 Phase 1 active sensors

```text
active = [dom, ax]
sensor_contract_id = browser-dom-ax-v0.1
vision = explicit_only_deferred_phase2
```

Phase 1 不自动调用 vision。

程序可以报告：

- vision capability 是否存在；
- 当前 DOM/AX blind spot；
- 未来 vision 的机械成本事实。

是否启用 vision 由模型显式决定，并属于 Phase 2 qualification。

### 4.2 Blind spot vocabulary

v0.1 预声明：

- `closed_shadow_root`
- `cross_origin_frame`
- `canvas`
- `webgl`
- `dom_unavailable`
- `ax_unavailable`
- `ax_truncated`
- `permission_denied`
- `projection_cap`

不可达区域不能被表示成“空”。

### 4.3 C28 multi-sensor conflict

DOM / AX 对同一 canonical field 冲突时：

1. 不得静默选一个 source；
2. 若没有预声明、任务无关、可复算的机械 derivation，canonical field = `null`；
3. `coverage.conflicts` 保留每个 `source/value/grounding_ref`；
4. `complete=true` 只说明声明 sensor contract 看全，不代表 sensors 一致；
5. 若 object mapping 本身不唯一，不强融成一张卡。

示意：

```json
{
  "state": {"enabled": null},
  "coverage": {
    "status": "complete",
    "sources": ["dom", "ax"],
    "blind_spots": [],
    "conflicts": [
      {
        "field": "state.enabled",
        "observations": [
          {"source": "dom", "value": true, "grounding_ref": "..."},
          {"source": "ax", "value": false, "grounding_ref": "..."}
        ],
        "resolution": "unresolved",
        "derivation_basis": null
      }
    ]
  }
}
```

哪一个值对当前任务更有意义，仍由模型判断。

---

## 5. SemanticObject Browser vocabulary

### 5.1 kind

v0.1 closed kind：

```text
document frame region button link input select option checkbox radio
text image dialog list listitem table row cell form heading generic unknown
```

不是为了穷举 Web 平台，而是为了让第一版 conformance 可机械冻结。无法归类时用 `unknown`，不能临场发明新 kind。

### 5.2 attributes

```text
role
name
tag
input_type
value_text
href
dom_region
text
```

没有：

- `hint`
- `recommended_action`
- `importance`
- `best_candidate`
- `task_relevance`

### 5.3 state

```text
exists
enabled
visible
checked
selected
expanded
focused
editable
readonly
required
busy
```

所有 canonical state 都允许 `null`，因为：

- sensor conflict；
- blind spot；
- unsupported observation；
- current grounding 不足。

`null` 是诚实 unknown，不是 false。

### 5.4 relations

第一版只允许可机械接地关系：

```text
parent
child
contains
labelled_by
described_by
owns
```

“视觉上像同组”“更靠近所以相关”不进入 relation。

---

## 6. WorldSnapshot（B2）

Browser profile 在 core requiredness 上额外要求：

- `sensor_contract`
- `projection`
- `content_sha256`
- `objects_ref`
- DOM / AX `grounding_refs`
- Browser scope generations

### 6.1 两种 completeness 必须分开

Observation completeness：

```text
completeness.complete/reasons
```

Projection completeness：

```text
projection.representation
projection.complete
projection.full_ref
```

DOM/AX 已捕获但 overview 没展开：projection incomplete，observation 仍可 complete。

DOM/AX 本身因 cross-origin/shadow/AX cap 没看全：observation incomplete；即使当前 projection 展开了全部已捕获对象，也不能改写为 observation complete。

### 6.2 Integrity

`content_sha256` 是已捕获 snapshot 内容的完整性事实，不证明：

- 世界现在仍没变；
- snapshot 对当前任务足够；
- 该 snapshot 仍在 retention 窗口内。

---

## 7. SemanticDiff（B5）

v0.1 允许：

```text
snapshot_pair_net
event_stream
```

### 7.1 Comparability dimensions

diff 前至少核：

- domain；
- scope_ref；
- document generation；
- sensor contract。

跨 full navigation、跨 frame、跨 sensor contract 不能直接解释成页面对象大规模 created/removed。

### 7.2 snapshot_pair_net 的时间边界

空 net diff 只证明两个采样端点没有净变化。

它**不证明**中间没有：

- detach/re-attach；
- modal 闪现；
- transient enabled；
- 短暂 URL/state change。

只有真正的 event stream 且 event coverage 完整时，才能给更强的时间断言。

### 7.3 Incomplete diff

- `created/removed` 若可能受 coverage 裁剪影响 → `null`；
- `changed` 可以保留已观察到的真实 lower-bound；
- `field_completeness.changed=false` 明确它不是全集。

---

## 8. Predicate vocabulary（B10）

Predicate 是 structured mechanical assertion，不是自然语言入口。

v0.1 properties：

| property | value | operators | negative coverage |
|---|---|---|---|
| exists | boolean | eq | 需要足够 coverage |
| enabled | boolean | eq | 对已接地对象判定 |
| visible | boolean | eq | 对已接地对象判定 |
| checked | boolean | eq | 对已接地对象判定 |
| selected | boolean | eq | 对已接地对象判定 |
| expanded | boolean | eq | 对已接地对象判定 |
| focused | boolean | eq | 对已接地对象判定 |
| editable | boolean | eq | 对已接地对象判定 |
| url | string | eq/contains/prefix/suffix | 当前 scope 属性 |
| name | string | eq/contains/prefix/suffix | 当前对象属性 |
| value_text | string | eq/contains/prefix/suffix | 当前对象属性 |
| document_ready_state | string | eq | enum: loading/interactive/complete |
| object_count | integer | eq/ge/le | 需要足够 scope coverage |

Evaluation：

```text
satisfied / unsatisfied / indeterminate
```

Modes：

```text
single_sample / polling / event_driven
```

polling 必须暴露：

- interval_ms；
- sample_count；
- observer_error_count；
- observed_at；
- deadline。

polling 的 `unsatisfied` 不证明样本间隙中从未短暂成立。

---

## 9. SemanticAction verb contract（B6/B7/B8）

第一版 verb 闭合为：

```text
observe hydrate diff wait assert click fill select navigate scroll
```

| verb | operation | idempotency | atomicity | version precondition |
|---|---|---|---|---|
| observe | observe | read_only | best_effort | not_applicable |
| hydrate | observe | read_only | atomic | not_applicable |
| diff | observe | read_only | atomic | not_applicable |
| wait | observe | read_only | best_effort | not_applicable |
| assert | observe | read_only | best_effort | not_applicable |
| click | mutate | unknown | single_dispatch | required |
| fill | mutate | unknown | single_dispatch | required |
| select | mutate | unknown | single_dispatch | required |
| navigate | mutate | unknown | single_dispatch | required |
| scroll | mutate | unknown | single_dispatch | required |

### 9.1 为什么 fill/select/scroll 也先写 unknown

第一版不因“最终值看起来一样”就声明幂等：

- fill 可触发 input/change handler；
- select 可触发网络请求；
- scroll 可触发 lazy load / observer side effect。

以后若某个 backend/verb 能给机械 exactly-once / idempotency proof，再升级 profile；不能先乐观宣称。

### 9.2 v0.1 retry 裁决

```text
automatic_protocol_retry = disabled_v0.1
```

这意味着：

- 不因 read_only 就先偷偷重试；
- 不因 Semantic ID 稳定就重放 click；
- polling sample 是 Predicate evaluation，不是 action retry；
- 模型显式再次操作 = 新 `action_id`；
- 未来开放 protocol retry 需升级合同，并带 attempt/reason/mechanism + 机械幂等依据。

这是一个故意保守的 Phase 1 边界，先把“发生一次动作意味着什么”钉死，再讨论优化。

### 9.3 Version / TOCTOU

所有 mutate verb：

- `expected_version` required；
- `version_scope` required；
- dispatch 前必须重新 resolve Semantic ID；
- stale/ambiguous → rejected；
- 禁止静默换 selector/target。

第一版 version scopes：

```text
object / resource / snapshot
```

具体 verb 允许哪些 scope 由 machine profile 固定。

---

## 10. Action args closed shape

### observe

```json
{"projection": "overview|objects|full", "object_cap": 1000}
```

### hydrate

```json
{"grounding_ref": "..."}
```

### diff

```json
{"from_version": "...", "to_version": "..."}
```

### wait

```json
{"predicate": {...}, "timeout_ms": 5000, "interval_ms": 200}
```

### assert

```json
{"predicate": {...}}
```

### click

```json
{}
```

### fill

```json
{"text": "...", "mode": "replace|append"}
```

### select

```json
{"value": "..."}
```

### navigate

```json
{"url": "https://..."}
```

### scroll

```json
{"delta_pages": 1}
```

Phase 1 v0.1 的 `scroll` target 仅为 `semantic_object`。早期 Profile 草案曾把
`page / document / frame / region` 一并列为 target kinds，但这些 semantic root
没有与 `object | snapshot` version scope 自洽的 dispatch guard：`object` guard
只对 SemanticObject 有定义，而 strict `snapshot` guard 在 pre-dispatch fresh
observation 后必须把不同 snapshot identity 判为 stale。B-QUAL 因此收窄这一
机械类型错误，不通过放宽 B-STALE 语义来伪造 root-level scroll 支持；后者若要
开放，必须单独冻结 scope/resource version contract 后重新资格化。

没有任何一个 args shape 接受 selector / XPath / x/y / node id / AX index。

---

## 11. ActionReceipt（B8/B9/B11）

Receipt 固定：

```text
append_only = true
receipt_seq = strictly_monotonic_per_action_id
terminal_overwrites_prior_receipt = false
status_is_task_completion = false
silent_recovery_sequence = false
```

状态：

```text
running / ok / failed / rejected
```

### 11.1 Retry facts

即使 v0.1 自动 retry 关闭，Receipt 仍固定保留：

- `attempt_count`
- `automatic_retry_performed`
- `mechanism`
- `reason`

这样未来启用时不需要偷偷扩 wire。

### 11.2 Boundary events

第一版 closed vocabulary：

```text
navigation_started
navigation_committed
scope_changed
new_page
new_window
download_started
dialog_opened
permission_prompt
```

事件只能来自预声明 detector。

若 detector 非 exhaustive，必须在 event/completeness 事实中体现，不能写成“没有事件”。

### 11.3 Predicate Receipt

wait/assert 的 `predicate_result` 使用统一：

```text
result
evaluation_mode
observed_at
deadline
interval_ms
sample_count
observer_error_count
```

Action `status=ok` 与 Predicate `result=unsatisfied` 可以同时成立；前者是执行合同，后者是世界断言结果。

---

## 12. Grounding retention（B2/B11）

可用状态固定：

```text
available
expired
unavailable
unauthorized
```

规则：

- retention 必须声明；
- 同一 GroundingRef 不得重新绑定到新状态；
- expired 不自动重新观察“相似当前状态”；
- unauthorized 不降级成 empty；
- 需要新 observation 时，由模型显式请求新的 observation/action。

---

## 13. Closed-schema Authority lint（B12）

以下内容不能进入 Browser model-facing core object：

```text
recommended_action
best_candidate
priority
completion
task_relevance
recovery_sequence
next_best_candidate
css_selector
xpath
x/y coordinates
cdp_node_id
ax_index
native_handle
```

本轮测试同时验证：

- 上述字段加在 object/action/receipt 顶层会失败；
- `css_selector` 藏入 action `args` 也失败；
- `attributes.hint` 临场添加也失败；
- `verb=click` 却提交 navigate args 会被 machine profile cross-field validator 拒绝；
- action classification/version 与 verb profile 不一致会被拒绝；
- Predicate operator/value type/value enum 错配会被拒绝。

这部分是防止“closed JSON 看起来很严，但语义组合仍能绕过去”。

---

## 14. R3 → B-SPEC / implementation fixture mapping（B13）

R3 有 32 个 adversarial cases：

- Phase 1 非 DEFERRED：30 个；
- `R3-14` vision-only actionability：Phase 2 DEFERRED；
- `R3-29` native browser chrome / OS：Phase 3 DEFERRED。

Machine profile 已把其余 30 个 ID 全部列入 `r3_phase1_fixture_map`，状态为：

```text
deterministic_fixture_before_browser_qualification
```

**重要：这不是声称 30 个 implementation fixtures 已经存在。**

B-SPEC 只锁定 obligation；B-PERCEPTION/B-IDENTITY/B-ACTION/B-RECEIPT 后续必须逐项把 obligation 变成 deterministic fixture，再进入 B-QUAL。

---

## 15. B0–B14 当前状态

| Gate | B-SPEC 当前能证明什么 | Browser implementation 仍需什么 |
|---|---|---|
| B0 | surface isolation 已机器化 | 真实 experiment arm 证明 legacy model surface 不可达 |
| B1 | scope/generation contract 已闭合 | runtime/page/document/frame 实现与 fixture |
| B2 | snapshot/grounding shape 已闭合 | DOM+AX capture/hydration/integrity |
| B3 | identity invariants 已写入 profile | reorder/replacement/duplicate fixture |
| B4 | C28 wire 已闭合 | DOM/AX 冲突/映射冲突真实 fixture |
| B5 | diff semantics/comparability 已闭合 | navigation/sensor-change/event fixture |
| B6 | semantic targets / verb args 已闭合 | adapter dispatch，不暴露 locator |
| B7 | mutation version precondition 已闭合 | stale/ambiguous pre-dispatch reject |
| B8 | idempotency/atomicity/retry 已闭合 | partial effect/transport ambiguity fixture |
| B9 | receipt revision contract 已闭合 | append-only receipt store |
| B10 | Predicate vocab 已闭合 | real observation tri-state fixture |
| B11 | blind spot/boundary vocab 已闭合 | detectors/coverage fixture |
| B12 | closed schema/authority negative tests | implementation surface scan |
| B13 | 30 个 Phase1 R3 obligations 已列出 | 30 个 deterministic implementation fixtures |
| B14 | qualification recipe 已冻结 | committed Browser candidate 全仓门禁 |

因此 B-SPEC 完成后最准确的状态是：

> **Browser Phase 1 的机械语言已经冻结；Browser 世界尚未接入。**

---

## 16. 后续实现顺序

B-SPEC 之后仍按 R3 推荐顺序：

1. **B-PERCEPTION**：只读 DOM+AX → scope/snapshot/object/grounding；
2. **B-IDENTITY/DIFF**：identity lifecycle + comparability + snapshot_pair diff；
3. **B-ACTION**：最小 click/fill/select/navigate/scroll，先 TOCTOU/version reject 再正向 dispatch；
4. **B-RECEIPT/PREDICATE**：append-only receipt + structured predicate；
5. **B-QUAL**：30 个 Phase1 R3 deterministic fixtures + B0–B14 + repo gates；
6. **Phase 2**：vision 独立重新开门。

B-SPEC 不授权下一阶段自动开始。

---

## 17. 验证模型

由于仓库没有 `jsonschema` runtime dependency，本阶段**不新增生产依赖**。

测试 `tests/unit/test_smc_browser_phase1_spec_v01.py` 内含一个只用于规格验收的最小 deterministic validator，覆盖本 schema 使用到的：

- `$ref`
- `oneOf` / `anyOf`
- `type`
- `const` / `enum`
- `required`
- `properties`
- `additionalProperties=false`
- array/items/minItems
- minLength/minimum/pattern

它不是生产 validator，也不会被 Browser adapter import。

未来 adapter 可以选择标准 JSON Schema validator、typed model 或生成代码，但 wire 必须继续满足本冻结 profile/schema。
