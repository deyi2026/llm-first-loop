# SMC-CONTRACT-v0.1：语义操控跨域契约（Semantic Manipulation Contract）

> 状态：**DRAFT v0.1**，待用户评审。
> 定位：跨域最小契约规范——六对象 schema + 不可越界项 + conformance 定义。不含实现，不含驱动选型，不含视觉语义化细节。
> 上游设计：`docs/DESIGN-20260911-semantic-manipulation-framework.md`（五支柱 P1–P5、四契约①–④、SLA-1..6、反模式清单）。
> 实证来源（本文引用的全部"已实现"断言）：
> - SMX Domain-0：`tools/smx/smx.py`@`2aa66aa6`、`src/llm_loop/tools/builtin/smx_perceive.py`@`2a528386`（两者今日实测 SHA 与 **SMX focused v1.1 30-run** A/B 冻结锚定一致）；
> - LFL 文件域：现行工具 schema（`edit_file`/`read_evidence`/`read_file`/`source_synopsis`，一手契约文本）。
> 本文同时裁决 DESIGN-20260911 §九-5：框架定位为 **LFL 的工具域扩展**（契约与 Evidence/回执基建同仓），非独立框架——这是 09-12 opt-in 并入的既成事实的正式化。
> 规范用语：MUST / SHOULD / MUST NOT 按 RFC 2119 语义；违反 MUST = 该实现对应合同面不合规格约。对明确不承载的合同面应标 `NOT_APPLICABLE`，不能假装 PASS。

---

## 0. 目的与范围

**一句话**：定义模型与可操控世界（shell/FS、文件、浏览器、OS）之间的统一语义 I/O 层——模型面对「对象 + 动作 + 变化 + 断言」，程序负责物理接地、状态维护、硬边界与诚实回验，且程序永不替模型做任务策略。

三条目的：

1. **跨域不变量**：换介质不换核心语义。任何域的适配器（adapter）都从同一套对象类型与 MUST/MUST NOT 中声明自己的 capability surface；域内可增加 namespaced 字段/能力，但不得改变核心字段含义或借扩展绕过合同。
2. **可验证的抽象**：用 conformance 探针机械区分"真跨域架构"与"从 Domain-0 抄出来的 shell 特化抽象"（§5、§6）；探针允许产出 GAP，GAP 是现状事实而不是失败包装。
3. **策略免疫**：契约本身禁止程序推荐/排序/纠偏/裁决完成——框架不可能长成小模型（违 P2/P3）。

范围外：执行驱动实现（Playwright/CDP/UIA/AXAPI 选型）、视觉补盲的具体成本预算公式（继承 DESIGN §九-4）、超出 v0.1“纯线性逐步回执”的条件分支/事务工作流 DSL。

### 0.1 Capability / Conformance Profile

六对象是**统一类型系统**，不等于每个早期 adapter 必须同时暴露全部六面。adapter MUST 在其规格/manifest 中显式声明支持能力；未声明的面可记 `NOT_APPLICABLE`，声明支持的面则必须满足本合同对应全部 MUST。

v0.1 定义两个最小 profile：

- **`smc-perception-v0.1`**：至少承载 WorldSnapshot / SemanticDiff / Predicate（若该域有可枚举对象则同时承载 SemanticObject）+ §2.0 GroundingRef。允许使用 SemanticAction + ActionReceipt 承载 `operation_class=observe|probe` 的 wait/assert/hydrate 等可审计操作，但 **MUST NOT 暴露 `operation_class=mutate`**。
- **`smc-manipulation-v0.1`**：承载 perception profile，并额外允许 `operation_class=mutate` 的 SemanticAction + ActionReceipt；这是 Browser Phase 1 / 后续 OS adapter 的目标 profile。

adapter 可以声明更窄的 capability（例如只有 `hydrate` precedent）供 R2 对照，但不得称为“完整 SMC adapter”。**没有声明却偷偷提供动作面，比明确 NOT_APPLICABLE 更严重：它绕过了 conformance 与安全边界。**

profile 只规定允许/要求的能力边界，不强迫每个 adapter 实现所有域内 verb。未支持 verb 必须可发现地 absent/unsupported；不得静默转路由到另一执行通道来“帮模型完成”。

capability declaration 还 MUST 标注所实现的 SMC contract/schema version；升级版本不得静默改变既有字段语义。同一 runtime 同时支持多版时，返回对象必须自描述其实际 `schema`，不能依赖调用方猜测。

---

## 1. 核心原则（继承自 DESIGN，逐条合同化）

| 原则 | 合同表述 | 判据归属 |
|---|---|---|
| P1 语义是 LLM 原生介质 | 模型面使用 SemanticObject / semantic scope / Predicate / SemanticAction，不要求模型操纵坐标、临时 locator、native handle；raw grounding 只作为按需回验层 | SemanticObject / SemanticAction / N9/N15 |
| P2 程序是感官/手脚，非大脑 | 感知层输出事实；动作层只做翻译与执行；任何对象/回执 MUST NOT 携带策略字段 | §4 MUST NOT 表 |
| P3 语义层只给事实 | 机械服务按 §1.1 的任务无关判定原则；可做结构排序、显式查询过滤、缓存/解析/等待等，禁止重要性/意图/策略/完成判断 | §1.1 判定原则 |
| P4 解释必须可回验 | 每个语义表示绑定接地版本；在声明 validity/retention + 权限范围内可水合原 observation，失效必须显式；盲区如实标注；降级不静默 | §2.0 + 六对象 MUST |
| P5 增量不压缩 | 默认增量/diff 与按需投影；模型显式请求时可全量水合/原始接地。预算截断必须如实标注且不得制造伪 diff | SemanticDiff / WorldSnapshot / §2.0.1 |

**1.1 程序机械服务判定原则**（开放类，不是穷举白名单）：

程序可以提供任意机械服务，但必须同时满足（这些条件本身也属于 conformance 可审计面）；“机械”指任务无关、输入输出契约可预先说明、结果可由事实/协议复算，不等于“写成代码就天然机械”：

1. 输出由**显式输入 + 当前可观测 grounding + 硬边界状态**机械决定；
2. 不判断任务价值、对象重要性、操作优先级或任务完成性；
3. 不替模型选择 semantic target / action / recovery strategy；
4. 不隐瞒 provenance、completeness、权限/预算/时效边界；
5. 若内部存在重试/去重/缓存，只能建立在可证明的协议/幂等/无副作用条件上，不得改变模型声明的语义动作；相关机制事实必须可审计。

典型合法机械服务包括（非穷举）：结构排序；按模型显式查询过滤；缓存与去重；semantic ID → 物理寻址解析；稳定 ID 生命周期 bookkeeping；等待与断言轮询；快照与 diff；预算计量与截断标注；锁/并发/幂等控制；事件订阅；canonical serialization；stale handle invalidation；持久化、水合与完整性校验。

重要性判断、意图推断、策略排序、自动选择目标、生成操作序列、任务完成裁决、基于任务语义的静默裁剪/纠偏/重试仍为越界，见 §4。

---

## 2. 六对象 schema

通用字段语义约定（适用于全部对象）：

- 每个序列化对象 MUST 带 `schema`（例如 `smc.semantic_object.v0.1`）与 `domain`；接收方不得靠字段形状猜对象版本/物理域。域内扩展应放入 namespaced `extensions`（或等价明确命名空间），不得覆盖核心字段语义；**§4 的全部 MUST NOT 同样约束 extensions，不能把策略字段藏进扩展面绕过合同。**
- `completeness` 专指 **observation completeness**，统一为对象：`{"complete": bool, "reasons": [...]}`。`complete=true` 表示**声明 scope 内、声明感官与声明预算下**物理/结构观察完整；`false` 表示存在预算/权限/介质/采集异常等已知缺口。
- 字段级 `null` ≠ `false`/`[]`：`null` 是诚实断言"此维度不可知"；`false`/空集仅在该维度已被完整观察后表示机械否定/空结果。
- `completeness=false` 时，任何**受该缺口影响**的集合/计数字段 MUST 为 `null` 或显式带独立 completeness；未受影响且仍可机械确定的字段可以保留真实值。不得把未知维度以空集/0 冒充"没有变化/没有元素"。
- 所有带时间语义的字段用单调时钟或 ISO 时间戳，二者 MUST 显式区分。

### 2.0 Cross-cutting Grounding Reference Contract

`grounding_ref` / `objects_ref` / `full_list_ref` / `raw_grounding_ref` 等不是独立第七对象，而是横切六对象的回验引用。凡实现声明某引用可持久回验，MUST 满足：

1. **作用域明确**：引用绑定 domain + adapter/runtime scope，不能跨 scope 静默解析；
2. **版本绑定**：引用绑定确切 observation/version；若声明 immutable，MUST 暴露可校验的内容/版本 token；
3. **可水合**：在声明的 validity/retention window 内可取回对应原始接地或 canonical contract projection；
4. **不静默重取**：原引用失效/过期/权限不足时必须返回 `unavailable` / `expired` / `unauthorized` 等事实，不得悄悄获取一个"相似的新状态"冒充原引用；
5. **完整性可见**：水合结果必须继续携带原 observation 的 completeness/coverage，不得因 hydrate 而丢失盲区信息。

GroundingRef 的字符串编码由各 adapter 自定；合同约束的是上述语义，不规定统一 URI 形式，也不要求把大体积 raw grounding 永久内联到模型上下文。域内扩展字段若影响 GroundingRef 解析/有效期，也必须进入可回验 adapter spec。

### 2.0.1 Observation Completeness vs Projection Completeness

SMC 必须把“感官有没有看全”和“这次给模型展示了多少”分开：

- **Observation completeness**：由核心 `completeness` 表达。budget 截断、权限、传感器盲区、遍历异常会让它下降。
- **Projection completeness**：只描述一个已捕获 observation 在当前 model-facing representation 中是否全部展开。overview/display cap/pagination/token budget 可以令 projection 不完整，但**不能反向修改 observation completeness**。
- 任何省略已捕获数据的 model-facing 表示 MUST 携带等价于 `projection_complete=false` 的事实，并给出 cursor / GroundingRef / hydrate 路径；若完整内容本来就因 observation gap 不存在，不能把它伪装成“只是没展开”。
- 反之，`projection_complete=true` 也只证明这次投影覆盖了**已捕获内容**，绝不证明物理世界 observation complete。

SMX 当前 `display_truncated` 与 LFL Evidence `projection_complete` 是这一分层的既有先例；未来 SMC adapter 应统一字段语义而不是混用二者。

### 2.0.2 Core requiredness（v0.1）

本文示例不是“仅供参考的任意 JSON”。以下是 v0.1 核心最小字段；adapter 可增加域内扩展，但缺少核心必填字段即对应对象不 conform：

| 对象 | 核心必填字段 |
|---|---|
| SemanticObject | `schema, domain, scope_ref, id, kind, attributes, state, relations, coverage, grounding_ref, observed_version` |
| WorldSnapshot | `schema, domain, snapshot_id, scope, observed_at, completeness, budget, grounding_version`；若 model-facing payload 未内联全部已捕获对象，还需 `projection` + 可水合 `objects_ref/full_ref` |
| SemanticDiff | `schema, domain, from_version, to_version, diff_semantics, comparable, scope_relation, created, removed, changed, completeness, field_completeness` |
| SemanticAction | `schema, domain, scope_ref, action_id, verb, target_id, args, operation_class, idempotency_class, atomicity_class`；支持版本前置时 `expected_version + version_scope` 成对出现，否则显式声明 `version_precondition` 状态 |
| ActionReceipt | `schema, domain, scope_ref, action_id, receipt_id, receipt_seq, verb, operation_class, idempotency_class, atomicity_class, target_id, status, before_version, after_version, observed_effects, boundary_events, grounding_refs, completeness`；无法取得版本时字段仍存在并为 `null`，原因进入 completeness；`wait/assert` 等 Predicate verb 额外 MUST 有 `predicate_result` |
| Predicate | `schema, domain, scope_ref, target, property, operator, value`；evaluation 结果由 wait/assert 回执携带，不修改 Predicate 本身 |

空对象/空数组可以是合法真实值，但不能用来代替 unknown；具体遵守本节 `completeness/null` 纪律。

### ① SemanticObject —— 语义元素卡片（= DESIGN 契约①）

```json
{
  "schema": "smc.semantic_object.v0.1",
  "id": "el_a3f2",
  "domain": "browser",
  "scope_ref": "page:checkout-tab-1",
  "kind": "button",
  "attributes": {"name": "提交订单", "dom_region": "form/footer"},
  "state": {"enabled": true},
  "relations": [],
  "coverage": {"status": "complete", "sources": ["dom", "ax"], "blind_spots": [], "conflicts": []},
  "grounding_ref": "snap_9c1d#el_a3f2",
  "observed_version": "snap_9c1d"
}
```

- `id`：adapter-issued 稳定语义 ID，在该 ID 声明的 lifetime/scope 内，同一物理对象跨轮 observation 保持不变并可水合回接地（= 契约②，SLA-1）。ID 的域内分配/回收算法属适配器实现自由，但稳定性是 MUST。**若物理身份连续性无法机械唯一确认，MUST NOT 把旧 ID 静默重新绑定给相似新对象；必须返回 identity ambiguous/unresolved 或分配新 ID。**
- `scope_ref`：对象所属 runtime/page/window/workspace 等语义作用域的稳定引用。ID 即使在 runtime/session 内全局唯一也 MUST 显式给 scope_ref，避免调用方靠 ID 编码猜作用域；scope 迁移若改变对象身份语义，必须产生新 observation/identity 事实。
- adapter 的 identity 追踪策略 MUST 预先写进域规格并与任务语义无关；若使用结构相似性等 heuristic，只能输出可回验的 identity basis/ambiguity facts，不能因为“这个对象对当前任务看起来更像”而复用旧 ID。
- `attributes`：只描述**是什么**（位置、外观/可访问性语义、机械属性），MUST NOT 出现"该不该操作"类字段。Browser v0.1 SHOULD 避免程序生成自由文本 `hint`；若确需保留，只能来自可追溯接地的原始标签/描述或模型显式保存的解释，并携带 provenance。程序不得把“主操作”“最相关”“更值得点击”等视觉显著性/任务判断伪装成事实 hint。
- `state`：机械事实（enabled/disabled/checked/visible/size/exists…），来源必须是 adapter 规格预先声明的可程序判定接地信号，不得按任务临场选择更“合意”的来源或掺入推断。若多个已声明 sensor 对同一 canonical field 给出冲突值，MUST NOT 静默择一：未能按预先声明、任务无关且可复算的规则机械消解时，该 canonical field MUST 为 `null`，并在 `coverage.conflicts` 保留每个 source 的 value + grounding_ref。若 DOM↔AX/vision 的对象对应关系本身无法唯一确认，MUST NOT 为了合并卡片而猜测 identity；应保留独立对象或显式 identity unresolved/conflict。
- `coverage`：对象级**接地覆盖事实**，统一结构为 `status=complete|partial|unknown`、`sources=[...]`、`blind_spots=[...]`、`conflicts=[...]`。`conflicts` 在无冲突时可为空；当已声明的多个 sensor 对同一 canonical attribute/state/identity mapping 产生不一致时 MUST 非空，每项至少给 `field`（或 `identity_mapping`）、`observations=[{source,value,grounding_ref}]` 与 `resolution=unresolved|mechanically_derived`（若为 mechanically_derived，还必须说明预先声明的 derivation/basis，且不得丢掉原始冲突 observation）。`complete` 只表示满足该 adapter 预先声明的 sensor/coverage contract，**不表示各 sensor 相互一致，也不等于掌握物理世界全部真相**。来源名由 adapter 规格固定（FS 可为 `stat`，Browser 可为 `dom/ax/vision`）；不得把 `not_found` 之类观察结果混成 coverage，也不得把“某来源存在”自动等同于 `complete`。canvas/WebGL 等结构盲区若只由视觉接地，可表示 `sources=["vision"], status="partial"` 并列出结构盲区。这是 SLA-5 的对象级落点。
- `relations`：由接地结构机械支持的关系事实（父子/同组/包含等），无策略含义。视觉上“看起来靠近/像同组”若需模型解释，不得由 adapter 冒充机械 relation。
- `grounding_ref` / `observed_version`：回验寻址与版本绑定（P4-1）。对象卡片一旦发布，其 `id + observed_version + grounding_ref` 语义必须固定；后续状态变化通过新 observation/version 表达，不允许就地改写旧卡后仍宣称旧引用有效。

**三域映射（当前事实/纸面目标，不等于三域都已 conform）**：

| 域 | id | kind/state 示例 | coverage 现状 |
|---|---|---|---|
| Shell/FS（SMX） | 当前实现只有绝对路径 **location key**，尚非合同意义的物理对象 stable ID（rename/path reuse 会破坏同一性） | `file` / `{size, mtime, type}`（smx 快照 entries `{t,s,m}`） | `sources=[stat]`；预算/遍历错误由 snapshot completeness 表达 |
| LFL 文件域 | path 是 location；`snapshot_ref` 是 immutable content/version grounding ref，二者组合提供版本前置先例，但不是跨 rename 的物理对象 ID | 文件内容行 | `sources=[file_bytes]` |
| Browser（纸面） | `el_a3f2`（仅在物理身份连续性可机械唯一确认时延续；相似性只能提供 basis/ambiguity facts） | role/name/state | DOM/AX/vision 多源 coverage/conflict 是本对象的主战场 |

### ② WorldSnapshot —— 世界快照

```json
{
  "schema": "smc.world_snapshot.v0.1",
  "snapshot_id": "snap-20260912T21:30:00-9c1d",
  "domain": "shell",
  "scope": {"roots": ["."], "depth": 2, "filters": []},
  "observed_at": "2026-09-12T21:30:00+08:00",
  "objects_ref": ".smx/runs/<run_id>/before.json",
  "completeness": {"complete": true, "reasons": []},
  "projection": {"representation": "overview", "complete": false, "full_ref": ".smx/runs/<run_id>/before.json", "age_ms_at_emit": 0},
  "budget": {"entries": 111, "budget_cap": 5000, "est_tokens": null},
  "grounding_version": "9c1d"
}
```

- `scope`：返回值中 MUST 显式。scope 可由模型显式声明，也可来自授权/runtime 已机械确定的 ambient scope（如当前 workspace/current page/current window）；程序 MUST NOT 根据任务意图擅自扩大 scope。任何 scope 扩大必须来自模型显式请求或新的机械授权/环境事实，并在回执中可见。
- `completeness.reasons`：逐根/逐区域标注截断或异常原因。SMX 现行可观察事实包括 `budget_exhausted_before_start` / `not_found` / `lstat_error:<errno>` / `walk_errors` / `truncated`；其中 `not_found` 本身是对该 root 的机械观察结果，不自动意味着观察不完整；只有当合同/adapter 预期该 root 应存在且因此导致声明 scope 无法覆盖时，才作为 completeness reason。
- `budget`：**预算可见**（DESIGN 三-6）：条目数/预算上限/token 估算随快照返回；程序只报告成本事实，是否下钻由模型决定。
- `projection`：当前 model-facing 展开层级与投影完整性；它和 `completeness` 正交。完整 observation 可以只给 overview；不完整 observation 即使把已捕获内容全部展开，也仍然是 observation incomplete。
- 快照时效以 immutable `observed_at` 为真值；`age_ms_at_emit` 之类年龄可作为每次 response/projection 的派生事实返回，但 MUST NOT 改变 snapshot grounding identity/version，也不得写回原快照冒充原始字段。
- `snapshot_id` MUST 可水合：给定 ID 能取回该次 observation 的对象集/接地投影，并遵守 §2.0 GroundingRef。`snapshot_id` 本身可以只是 opaque identity；只有当实现把它同时宣称为 version/integrity token 时才必须内容绑定。**SMX CLI `smx.py::write_snapshot` 当前已有内容 sha12；模型面 `smx_perceive.snapshot` 当前只有唯一 snapshot_id + 落盘 JSON，没有独立内容 integrity/version token，属于 §6 G6 已知 gap，合同不得把两条链混写成已统一。**

### ③ SemanticDiff —— 语义变化

```json
{
  "schema": "smc.semantic_diff.v0.1",
  "domain": "shell",
  "from_version": "snap-...-9c1d",
  "to_version": "snap-...-b7e2",
  "diff_semantics": "snapshot_pair_net",
  "comparable": true,
  "scope_relation": "same",
  "created": null,
  "removed": null,
  "changed": [{"path": "src/app.py", "changed": ["s", "m"]}],
  "completeness": {"complete": false, "reasons": ["budget_truncation_on_either_side"]},
  "field_completeness": {"created": false, "removed": false, "changed": false},
  "reason": "budget_truncation_on_either_side",
  "full_list_ref": ".smx/runs/<run_id>/changed.json"
}
```

- **可比性先于差分**：adapter MUST 先机械判断 from/to 的 domain、scope、sensor/coverage contract 与版本语义是否可比，并返回 `comparable` + `scope_relation=same|compatible|changed|unknown`。不可比时不得把 scope 切换/页面跳转/不同 roots 伪装成大量 created/removed；受影响字段 MUST 为 `null`，除非 adapter 有显式且可回验的 scope mapping。
- `diff_semantics` MUST 明示差分证明的是什么。v0.1 至少区分 `snapshot_pair_net`（只证明两个 observation 的净状态差，**不证明中间没有瞬时变化**）与 `event_stream`（只有底层确有完整事件捕获时才可声明）。空的 `snapshot_pair_net` 只能解释为“已声明维度上无净差”，不得解释为“期间什么都没发生”。
- 核心纪律（**SLA-2 diff 忠实**）：任一侧观察不完整时，`created`/`removed` 差集可能只是预算裁剪伪影，MUST 降级为 `null`（unknown）并置 `completeness.complete=false`；磁盘上没有的删除绝不能被报为 `removed`。
- `field_completeness` 逐维说明列表是否 exhaustive。对 `changed` 这类“已观察项可确认、但可能漏项”的维度，允许在 `field_completeness.changed=false` 时返回**真实 lower-bound partial list**；模型必须知道它不是全集。对 `created/removed` 这类在截断下可能出现假阳性的维度，不能仅标 partial 后照报候选，必须 `null`，除非 adapter 能额外机械证明该项。
- **现状两层差异（必须如实记录）**：冻结 CLI `smx.py` 的 `finish_receipt` 无条件给出 `counts{created,deleted,modified}`，仅以 `scope.truncated_any=true` 标注；LFL 模型面 `smx_perceive.py::_diff` 已实现完整纪律（`incomplete → created/deleted/total_changes=null`，`diff_complete=false`，抑制 ± 显示行，06738a22 P1 修复 + 回归测试 ×2）。**合同基准以模型面为准**；CLI 层计数在截断场景只作参考，不作为契约输出。
- `changed` 粒度：域内**已声明**的最小机械可观维度（FS：type/size/mtime；browser 可为 state/attribute 字段级）。若 adapter 只观察粗粒度 hash/version，就只能报告该粒度变化，不得反推更细语义。
- `full_list_ref`：全量**canonical contract diff** 的水合地址——概览显示与全量之间的桥。若 `completeness=false` 导致某类变化不可判，则 canonical full list 也 MUST 对该类保持 unknown；若底层仍保留未经过 completeness 归一化的 raw diff，MUST 使用不同的 `raw_grounding_ref` 并标明 `canonical=false`；不得让 hydrate `full_list_ref` 绕过 `created/removed=null` 的完整性纪律。
- 纯观察动作（如 wait）本身不负责证明世界“无变化”；若没有为该 scope 建立 before/after observation，SemanticDiff MUST 显式 `applicable=false` + reason（SMX 现行：`wait 为纯观察动作，不修改世界状态`），不得报空 diff 冒充"没变化"。

### ④ SemanticAction —— 语义动作

```json
{
  "schema": "smc.semantic_action.v0.1",
  "domain": "browser",
  "scope_ref": "page:checkout-tab-1",
  "action_id": "act_20260912_2130_ab12",
  "verb": "click",
  "target_id": "el_a3f2",
  "args": {},
  "operation_class": "mutate",
  "expected_version": "snap_9c1d",
  "version_scope": "object",
  "idempotency_class": "unknown",
  "atomicity_class": "single_dispatch"
}
```

- `verb` 枚举域内可扩；`wait` 是一等动词（见⑥）。
- `operation_class` MUST 为 `observe|probe|mutate`：`observe` 不以改变外部世界为目的；`probe` 为取得事实允许发生预先声明且有界的探测交互（如 loopback TCP connect）；`mutate` 明确意图改变世界。分类由 adapter verb contract 机械预声明，不得按任务语义临场改类。perception profile 不得执行 mutate。若实际执行过程中发生超出声明 operation class 的效果，ActionReceipt 必须如实暴露并视为 adapter contract violation 候选，不能靠改写回执隐藏。
- `action_id`：动作声明自身稳定 ID，供一个或多个 ActionReceipt 引用；同一 runtime/session 内不得复用给不同动作，异步动作不得靠可变 receipt 内容反推身份。
- `scope_ref`：动作解析/授权/版本核对的显式语义作用域，必须与目标对象/semantic root 的当前 scope 一致；跨 scope 动作必须由 verb/authorization contract 明示，不能靠 locator 穿透。
- `target_id`：目标必须是 adapter-issued SemanticObject ID 或 adapter 正式声明的 semantic scope/root object；MUST NOT 要求模型直接提供坐标、CSS/XPath、CDP node id、AX index/native handle 等 ephemeral backend locator。对 `navigate/create/launch` 等天然没有既存对象的动作，可把 adapter 正式定义的 semantic root/scope 作为 target，并把目的参数放进 `args`；不能借“无 target”重新暴露物理定位原语。程序负责把 semantic target 解析为物理寻址。
- 动作真正 dispatch 前，adapter MUST 从 `target_id` 当前 identity/grounding 重新解析或验证已有 handle，并在同一执行前置阶段核对 identity ambiguity + `expected_version`。缓存 locator/handle 可以用于性能，但不能跳过 stale/identity 检查；无法确认仍是同一对象时必须 `rejected`，不能“最相似候选”自动替换。
- `expected_version` + `version_scope`：乐观并发。`version_scope` 至少允许 `object | resource | snapshot`，由 domain/adapter 机械事实决定粒度；不强迫所有域共享同一版本粒度。状态与预期不符 → 拒绝执行 + 返回当前状态/版本事实。若某动作不具可验证版本前置条件，adapter MUST 明示 `version_precondition=unsupported|not_applicable`，不得伪造 version token。
- **Semantic ID 稳定绝不等于动作幂等。** adapter MUST 为每个 verb/动作实例暴露可机械证明的 `idempotency_class=read_only|idempotent|non_idempotent|unknown`（或等价事实）。只有 `read_only/idempotent` 且底层协议满足对应条件，或显式 idempotency key/exactly-once 机制成立时，程序才可做 N4 允许的协议级重试；`non_idempotent/unknown` 不得自动 replay。
- 若程序在 N4 允许范围内发生协议级重试，attempt count / reason / idempotency mechanism MUST 进入 ActionReceipt/grounding metadata；“对模型不可见的重试”仍然不得成为“不可审计的重试”。
- 动作还 MUST 暴露 `atomicity_class=atomic|single_dispatch|best_effort|unknown`（或等价事实）：`atomic` 仅在 adapter 能机械保证失败不留下部分效果或可完整回滚时使用；Browser/OS 常见 click/send 可能最多是 `single_dispatch`，这不等于下游世界状态事务化。非 atomic 动作失败后必须如实报告已观察到的效果/边界事件，不得宣称“失败所以世界未改变”。
- **Domain-0 现状：canonical SemanticAction wire 尚未实现**——模型面的世界修改执行经安全裁决留在 `execute_command`（正确，见 §6 G2）；SMX `wait` 是 observe/probe action 的 pre-contract 先例。契约的 mutation/version 前置活实例在 LFL 文件域：`edit_file(path, old_string, new_string, expected_snapshot_ref)`，其中 `expected_snapshot_ref` 同构于 `expected_version`，过期拒绝。
- 组合动作：程序可提供批量/线性提交能力，但**步骤序列、目标和参数必须由模型显式声明**；程序只按声明顺序/依赖机械执行并为每步独立回执，不得自动补步骤、生成补偿动作或 recovery sequence，也不得合并掩盖中间失败（DESIGN 四-1；同构 `workflow_run` 的机械依赖执行面）。

### ⑤ ActionReceipt —— 动作回执（= DESIGN 契约④，细化）

```json
{
  "schema": "smc.action_receipt.v0.1",
  "domain": "browser",
  "scope_ref": "page:checkout-tab-1",
  "action_id": "act_20260912_2130_ab12",
  "receipt_id": "rcp_act_20260912_2130_ab12_0001",
  "receipt_seq": 1,
  "verb": "click",
  "operation_class": "mutate",
  "idempotency_class": "unknown",
  "atomicity_class": "single_dispatch",
  "status": "ok",
  "target_id": "el_a3f2",
  "before_version": "snap_9c1d",
  "after_version": "snap_b7e2",
  "observed_effects": {"diff_ref": "grounding:diff/snap_9c1d..snap_b7e2"},
  "boundary_events": {"new_window": false, "download_started": false},
  "grounding_refs": {"before": "grounding:dom/snap_9c1d", "after": "grounding:dom/snap_b7e2"},
  "completeness": {"complete": true, "reasons": []},
  "timings": {"dispatch_ms": 18.4, "post_observe_ms": 31.2}
}
```

- `observed_effects`：程序只陈述在其声明 observation scope/coverage 内机械观察到的变化；MUST NOT 自行判断这些变化是否"符合任务预期"。若动作未声明任何 expected effect，则回执中不得出现 `expected=true/false` 之类伪推断字段。
- `wait/assert` 等 Predicate verb 的 Receipt MUST 带 `predicate_result`，至少包含 `result=satisfied|unsatisfied|indeterminate`、`evaluation_mode`、`observed_at/deadline`（适用时）以及 polling 的 `interval/sample_count/observer_error_count`；这是断言结果，不放进 `status` 伪装成工具成功/失败。工具可 `status=ok` 同时 `predicate_result.result=unsatisfied`。
- Receipt MUST 原样携带/引用动作声明时的 `operation_class/idempotency_class/atomicity_class`，不得在事后根据结果重新分类来掩盖执行前风险边界。
- Receipt 的 `scope_ref` MUST 与已接受的 SemanticAction 一致；若动作本身导致页面/窗口 scope 转移，转移结果通过 `boundary_events/observed_effects` + 新 snapshot/scope 表达，不回写 action 的原始 dispatch scope。
- `boundary_events`：仅记录可机械定义的边界事件，如 requested scope 外观察到写入、打开新窗口、下载开始、权限边界触发。若只能启发式探测，MUST 原样标注 `heuristic/non-exhaustive`。SMX 现行 `out_of_scope_refs` 属此类早期实例。
- 若未来模型在 SemanticAction 中显式声明 expected effects，可机械返回 `declared_effects / observed_effects / effect_match`；expected 不得由程序从任务语义推断。
- `before_version`：动作 dispatch 前实际完成 identity/version 前置核对的 observation/version；若该 verb 无版本能力则为 `null` 并显式说明。`after_version`：**发生 dispatch 后**终态回执对应的后观察版本；无法取得时为 `null`，且相关 `observed_effects`/completeness 必须降级，不得用旧版本冒充新状态。`rejected` 因未 dispatch，`after_version` 应为 `null`（当前状态卡/版本通过 rejection facts 返回），不能伪造“动作后版本”。
- `status` 枚举至少覆盖：`ok` / `failed` / `rejected`（乐观并发/安全/协议前置）/ `running`（进行中）。`failed` 表示动作已尝试但未正常完成，已发生的机械效果仍须报告；`rejected` 表示硬前置在动作执行前拒绝。`running` 时 MUST NOT 附终态 diff（不把半途状态当终态；允许单独提供明确标注为 provisional 的 observation，但不得伪装成完成效果）、MUST NOT 附完成断言。
- `status=ok` 只表示 adapter 按该 verb 的机械执行合同完成，不等于用户任务成功；`status=failed/rejected` 也不等于任务失败。任务推进/完成仍由模型结合目标与回执判断。
- 对 ActionReceipt 的任何“success/failure”命名均遵守上一条：它是**动作执行状态**，不是任务质量标签；不得被 harness 自动升级成 completion signal。
- ActionReceipt 的 `completeness` 描述**效果/边界/grounding observation 是否完整**，不是动作是否成功；`status=failed, completeness.complete=true` 完全合法（失败已被完整取证），`status=ok, completeness.complete=false` 也合法（动作机械完成但后观察存在盲区）。
- `grounding_refs`：与该动作有关且允许持久化的原始 stdout/stderr/元数据水合地址应随回执给出；受权限/隐私/retention 限制时必须显式报告不可持久化/不可访问原因，而不是省略后假装完整（SLA-4）。Grounding 是否可访问属于回执事实，不得影响模型对动作语义的所有权。
- 回执即证据：持久化、按 ID 可查、可审计。**已经发布/可引用的 ActionReceipt MUST immutable；异步动作状态变化用同一 `action_id` 下递增 `receipt_seq` 的新 receipt 表达，或提供等价 append-only/revisioned 语义，不得覆盖旧 receipt 后仍宣称旧引用可回验。** SMX CLI 当前 `bg_launch → collect` 会覆盖同一路径 `receipt.json`，属于 §6 G8 gap。
- 同一 `action_id` 的 `receipt_seq` MUST 唯一且单调递增。`running` 可后继 `running|ok|failed`；`rejected` 表示 dispatch 前拒绝且为终态；`ok/failed` 为该 action 的终态。终态之后世界再次变化属于新的 observation/action，不得回写旧 action 结果。
- `rc_chain`：效果链取证（bash 退出码经 fd3 旁路，stdout 零污染）——FS 域特有字段，展示"分层取证"的域内实例，非跨域必选。
- 上述 `rc_chain/out_of_scope_refs/stdout_path` 等 SMX 字段都是 **Domain-0 precedent/extension**，不得直接复制进跨域 core requiredness；canonical ActionReceipt 只保留跨域机械语义。

### ⑥ Predicate —— 谓词

```json
{
  "schema": "smc.predicate.v0.1",
  "domain": "shell",
  "scope_ref": "workspace:current",
  "target": "file:./app.pid",
  "property": "exists",
  "operator": "==",
  "value": true
}
```

- 谓词 = 程序可机械验证的世界断言。Predicate 描述“要验证什么”，不自己执行；`wait(predicate, timeout)` / `assert(predicate)` 是使用该 Predicate 的一等 SemanticAction（通常 `operation_class=observe`，端口连接等可为 `probe`），执行与审计结果进入 ActionReceipt。条件由模型声明，轮询/订阅由程序执行，**模型不轮询**（DESIGN 契约③）。当前 SMX wait 为这一结构的 pre-contract 先例，尚未使用 canonical Action/Receipt wire。
- `wait/assert` SemanticAction 的 `args` MUST 携带完整 Predicate 或稳定 `predicate_ref`；若使用 ref，遵守 §2.0 GroundingRef 的 scope/version/失效纪律。ActionReceipt 通过统一 `predicate_result` 返回 evaluation，不允许 adapter 自造与三态语义冲突的“timeout=error”状态。
- 每个 adapter MUST 预声明可验证的 `property` vocabulary、允许的 `operator` 与 `value` 类型；Predicate 不是自由自然语言解析入口。未知 property/operator/type 必须机械拒绝，程序不得猜测模型意图。`target` 同样必须是该域合法 Semantic ID / semantic scope / 正式 location key，不得夹带 backend locator 绕过 N15。
- Predicate 的 `scope_ref` 决定 target 的解析/观察边界；同名 location key 在其它 scope 的状态不得被拿来满足本 Predicate。
- Predicate evaluation MUST 是三态：`satisfied | unsatisfied | indeterminate`（等价 wire 可用 `satisfied=true|false|null`）。`indeterminate` 表示权限/读取/感官失败使断言无法机械判定，MUST NOT 混同为普通 false/timeout；若一次 wait 期间先出现短暂 observer error 后恢复并获得充分有效观察，最终结果可按有效观察判定，但回执 MUST 保留 observer-error 事实/计数而不能抹掉。
- **否定需要足够覆盖**：adapter 的 predicate spec MUST 定义什么 observation coverage 足以证明 true/false。部分观察中若已经看到决定性正向 witness，可以返回 `satisfied`；但若要断言“不存在/不包含/未出现”等否定，而搜索范围被 cap/分页/盲区截断，则必须 `indeterminate`，不能用“已扫描部分没有命中”冒充全局 false。SMX `file_contains` 当前 8MiB cap 后尾部未检却继续按 false 轮询，是 §6 G13 gap。
- wait/assert 回执 MUST 暴露 `evaluation_mode=single_sample|polling|event_driven`（或等价事实）；polling 还应给 interval/sample_count/observer_error_count。`unsatisfied` 在 polling 模式只表示“有效采样点未观察到成立”，**不证明采样间隙里条件从未瞬时成立**；只有底层确有连续/事件语义时才能声明更强事实。
- 超时是**事实**不是工具故障：若每次有效采样直到 deadline 都未观察到条件成立 → `unsatisfied`；若关键观察不可得 → `indeterminate` 并携带原因。SMX 当前 `file_contains` 读取 OSError 会被折叠进最终 `satisfied=false`，属于 §6 G7 gap。
- v0.1 同一调用只定义**单谓词**，不定义 AND/OR/NOT/时序 DSL。未来组合若引入，只能是纯 Predicate AST；“A 成立后再等待 B”属于工作流/策略时序，不得下沉成自动程序决策。
- 断言优先（DESIGN 三-4）：能机械验证的交给程序；`satisfied` 也只证明该 Predicate 成立，不自动证明任务完成；`unsatisfied/indeterminate` 的语义解释、恢复与下一步由模型决定。

---

## 3. 接口动词层与三级缩放

六对象是名词面；模型实际调用的是动词面。跨域动词集（域内子集实现，语义不变）：

| 动词 | Shell/FS（SMX 现行） | LFL 文件域（现行） | Browser（纸面） |
|---|---|---|---|
| `observe(scope, filter)` | `snapshot`（roots/depth/budget） | `search_files`/`inspect_code`（cross-domain precedent，非 SMC adapter） | DOM+AX 语义视图 |
| `hydrate(ref_or_id)` | 快照/receipt/object ID 按绑定 scope 取回 | `read_evidence`/artifact snapshot | SemanticObject ID / GroundingRef → 对应 observation/DOM 片段/截图 |
| `act(verb, id, expected_version)` | —（模型面不提供，执行走 execute_command；G2） | `edit_file(expected_snapshot_ref)`（precedent） | click/fill/select |
| `wait(predicate, timeout)` | `wait` 四谓词（当前 G7/G12/G13） | —（schedule/wake 另议） | visible/enabled/url |
| `diff(from, to)` | `diff`（since/current） | 文件/版本 diff（precedent） | 快照对差 |
| `receipt(id)` | `receipt`（run_id 查询；当前异步历史不可变仍有 G8 gap） | Evidence/action_trace（precedent） | 动作回执查询 |

**三级缩放**（DESIGN 三-3）是动词的 `depth`/representation 参数语义，不是第七个对象：

1. **概览**：页面/目录结构概览（类型+区域+机械状态；SMX `display` cap=20）。程序可做确定性结构投影，但不得自行生成任务语义摘要；若需语义摘要，应由模型产生并按 GroundingRef 绑定原始接地。
2. **展开**：区域/元素组卡片（`display_truncated` 提示截断）。
3. **原始接地**：DOM 片段/截图/原始 stdout（`read(depth="raw")`；SMX `full_list_path`/`stdout_path`）。raw 只改变 representation，不改变原 observation/version 的身份。

默认只返回 adapter 已声明的最低成本结构层；是否足以决策、是否继续下钻由模型判断并显式发起。同构 LFL `source_synopsis`（模型自写摘要绑定原文 SHA，程序只存取不生成——L2 语义化层的分工样板）。

---

## 4. 不可越界项（合同级 MUST NOT，N1–N19）

违反任一条 = 该适配器对应 capability/profile 不合规格约，与性能无关，一票否决。来源标注：D=DESIGN 原文，U=09-12 评审裁定新增。

| # | MUST NOT | 违反类别 | 来源 |
|---|---|---|---|
| N1 | 对象/回执携带「推荐动作/最佳候选/建议次序」字段 | 策略伪装成感知 | D-P3, D-反1 |
| N2 | 程序生成/补全操作序列、补偿/recovery 步骤或推断任务意图；批量动作只能执行模型显式提交的序列/依赖 | agency 让渡 | D-P3 |
| N3 | 程序裁决任务完成，或把 action/predicate 的机械 success 自动升级成任务 completion | agency 让渡 | D-P3 |
| N4 | 动作可能已生效后，程序静默 replay / 换 target / 换策略重试。仅当可机械证明首次无副作用，或以 idempotency/exactly-once 机制保证语义动作不被重复执行时，允许协议级重试并须可观测 | agency 让渡 / side-effect 风险 | D-反4, RULE-AI-00.2 |
| N5 | 静默降级（语义化失败→截图/空集，无异常回执） | 诚实违反 | D-反3, SLA-5 |
| N6 | 在**声明 observation scope + completeness guarantee + diff_semantics** 内，实际已观察到/应被该语义覆盖的变化被静默漏报（diff 谎报）；或把 snapshot net diff 冒充完整事件历史 | 诚实违反 | SLA-2 |
| N7 | 截断/不可达侧的差集报为 created/removed | 诚实违反 | 06738a22 P1 教训 |
| N8 | 结构信号可用时自动对整个 screen/page/scope 做 vision 语义化；若当前 scope 本身为结构盲区，仅在模型显式请求 vision 时允许，并须暴露 coverage/cost | 成本违反 | D-反2, P5 |
| N9 | 模型动作对象直接使用坐标（x,y）等物理定位原语而非 semantic target | 范式违反 | D-契约③ |
| N10 | 基于任务语义/重要性替模型丢弃卡片。允许 pagination、retention、cache eviction、budget projection 等机械裁剪，但必须可见且不能伪装为完整世界 | agency 让渡 | D-SLA 后注 |
| N11 | 把进行中状态当终态回执（running 必须显式；不得带终态 diff/完成断言；provisional observation 必须显式标注） | 诚实违反 | U |
| N12 | 在声明的 validity/retention window 内禁用回验，或引用失效后静默重取“相似新状态”冒充原 grounding。过期/权限变化必须显式 `expired/unavailable/unauthorized` | 诚实违反 | SLA-4 |
| N13 | 硬边界越出安全、授权、物理/资源预算、锁与并发、幂等/防重、原子性、完整性、协议兼容等不可替代机械边界去做任务策略 | 边界违反 | SLA-6 + LFL 既定边界 |
| N14 | 物理身份连续性存在歧义时，把旧 Semantic ID 静默重新绑定给“相似”新对象 | 标识/agency 违反 | P4 + SLA-1 |
| N15 | 把 ephemeral backend locator（CSS/XPath/CDP node id/AX index/native handle 等）伪装成模型面的 Semantic ID/target。域内 location key（如 FS path）可作为 semantic target，但必须明确其 identity 语义/局限，不能冒充跨 rename/path-reuse 的物理对象 stable ID | 范式违反 | 契约②③ |
| N16 | 在 adapter 无法机械保证事务原子性/完整回滚时，把动作标成 `atomic`，或因动作返回 failed 就声称世界未改变 | 诚实/副作用违反 | SLA-3 |
| N17 | 在动作 dispatch 前跳过 target identity/staleness/version 前置核对，直接复用旧 locator/handle；或 stale 后静默命中替代对象 | 标识/并发违反 | SLA-1 + DESIGN 四-4 |
| N18 | 把自由自然语言 predicate/target 交给程序做意图解释或“最接近”匹配；未知 property/operator/target 必须机械拒绝或交回模型重述 | agency 让渡 | P2/P3 + Predicate contract |
| N19 | `smc-perception-v0.1` adapter 暴露/执行 `operation_class=mutate`，把有外部交互的 probe 静默伪装成 observe，或实际效果越出声明 operation class 后隐瞒 | capability/诚实违反 | §0.1 + SemanticAction |

---

## 5. Conformance：三层验证矩阵与机械探针

**目的**：证明抽出来的是跨域架构，而不是从 shell 域抄出来的特化抽象。三层各测不同契约面；`PASS` 只对已声明 capability + 已覆盖断言有效，绝不外推成“全框架已验证”（见 §6）。

| 行 | 定位 | 域 | 可验证契约 | 方式 |
|---|---|---|---|
| R1 | **Domain-0 implementation conformance** | SMX shell（现行代码） | 感知/diff/谓词/完整性/预算 | 机械探针 P0–P8（下） |
| R2 | **Cross-domain precedent anchors** | LFL 文件域（已在生产运行） | 标识水合/动作乐观并发/回验通道/摘要绑定 | 已有实例回填；证明模式同构，**不宣称该域已是 SMC adapter** |
| R3 | **Browser design-readiness pressure test** | Browser（Phase 1 前） | 全六对象逐字段 | 纸面压力测试；只证明合同能否落到 browser，不计 implementation conformance |

### 5.1 R1 机械探针（对 `smx_perceive` + `tools/smx/smx.py`，全部可脚本化）

| # | 探针 | 断言 | 对应 |
|---|---|---|---|
| P0 | contract-surface inventory + structural lint | 记录模型面实际 capability/schema 字段，并与 v0.1 core requiredness 对照；wire 名称/类型不一致记 GAP；无隐藏 `command/cmd/exec` 或策略字段。**不得用测试侧 normalize 后把 wire GAP 算 PASS** | §0.1, §2.0.2, N1/N2/N3/N9 |
| P1 | diff-fidelity 正向：非截断双快照间增/删/改文件 | 行为层真实 created/removed/changed 全部如实，无遗漏无多报；测试 oracle 可机械归一当前字段名，但 **wire conform 仍只由 P0 判** | SLA-2 |
| P2 | diff-fidelity 负向：一侧 budget < entries（回归复刻 06738a22 场景：111 条目 > budget 100） | `created/removed` unknown；`changed` 若保留只能明确为 lower-bound partial；整体 incomplete，± 假差行抑制。**当前模型面 modified count 缺字段级 completeness 预期暴露 G14** | SLA-2, N7 |
| P3 | blind-spot honesty：小 budget / 不存在的 root / **机械注入 EACCES/遍历异常** | 截断/不可达/异常逐根标注；绝无静默空集。权限分支优先 monkeypatch `os.scandir/lstat`，不依赖宿主 chmod 语义 | SLA-5, N5 |
| P4 | predicate 三态 + evaluation semantics：满足/有效观察后的超时/observer error/部分覆盖；`port_open` 非 loopback | satisfied / unsatisfied / indeterminate 可区分；polling 回执暴露 interval/sample_count/observer errors；负向结论须有足够 coverage；非 loopback→拒绝。**当前 file_contains OSError、8MiB capped-negative 与 sampling facts 预期暴露 GAP** | ⑥, SLA-6 |
| P5 | lineage/hydrate + integrity：snapshot/receipt ID 水合、before/after 版本绑定、immutable 声明时内容 token 可验证 | 任意有效引用可回验到确切 observation；**当前 smx_perceive snapshot 缺内容 integrity token 预期暴露 G6 GAP** | §2.0, SLA-1, SLA-4 |
| P6 | supporting Domain-0 implementation probe：CLI 后台命令未结束时 collect | `running=true` + note + **无终态 diff**。此探针测 `smx.py` CLI supporting implementation，不代表 model-facing adapter 已具 SemanticAction | N11, G2 |
| P7 | diff scope comparability：用不同 roots/depth/scope 的两张 snapshot 请求 diff | 不可比时 MUST `comparable=false` 且 created/removed 不可判；**当前 `smx_perceive._diff(current=...)` 未核对两端 params，预期暴露 G9 GAP** | SLA-2, N6 |
| P8 | canonical-vs-raw hydration：截断 run 的 `receipt(full=true)` / changed grounding | raw grounding 可取但必须显式 `canonical=false`，不得让 CLI counts/raw changed list 冒充 SMC canonical diff；**当前预期暴露 G16 GAP** | §2.0, G16 |

P0 的静态部分作为 **structural lint，不是完整 agency proof**。至少断言：

- `smx_perceive.py` provider schema 不出现策略性字段 key（recommended_action / best_candidate / priority / completion 等）；
- provider 参数面无 `command/cmd/exec` 执行通道；
- 输出 schema/实现无 semantic ranking/selector 结果字段；
- 这些静态事实只能证明已知策略通道不存在，不能证明所有未来控制流都无 Program Authority。

### 5.2 R2 已有实例回填（LFL 文件域，现行生产事实 → 断言化）

| # | 断言 | 现行实例（一手 schema/observation） |
|---|---|---|
| L1 | 任意有效 EvidenceRef 可水合且完整性可校验（range_sha256/blob_sha256 随回读给出；过期/不可用必须显式） | `read_evidence` evidence_hydration_v2 回执（现行实现） |
| L2 | 动作携带过期版本 → 拒绝（乐观并发拒绝路径存在且被测试固化） | `edit_file.expected_snapshot_ref` |
| L3 | 摘要绑定原文 SHA 与范围，程序只存取不生成 | `source_synopsis` save 契约 |
| L4 | 时效显式：新鲜度是版本断言，由模型结合任务判断（`allow_stale`/`evidence_force_refresh` 语义） | `read_evidence`/`read_file` 参数面 |
| L5 | 回验通道在引用有效/有权限期间可用；截断如实（`range.complete=false` + `next_start`），不可用时显式失败而非换源冒充 | evidence 回执结构 |

### 5.3 R3 纸面压力测试清单（Phase 1 前逐字段过堂）

- `id` 稳定性：SPA 局部重渲染后同 ID；shadow DOM / iframe 内元素寻址；多标签页 ID 作用域（继承 DESIGN §九-2）。
- identity ambiguity：旧节点消失后出现多个相似节点时，旧 ID 必须 unresolved/retired，不能“最相似即继承”；验证 N14。
- identity task-invariance：同一 DOM 演化在不同用户任务描述下必须产生同样 ID continuity 结果；任务语义不得影响 identity matcher。
- `coverage`：canvas/WebGL → `vision-only` 是否足以承载动作（视觉接地的点击精度）；aria-hidden 元素的归类。
- `state` 机械性：DOM 属性与 AX 树冲突时不得静默“选一个为准”；须按 `coverage.conflicts` 暴露 source-qualified observations。仅当域规格预先声明了任务无关、可复算的机械 derivation 时，才可同时给 canonical derived value，并保留原冲突事实。
- `expected_version` 粒度：以 `version_scope=object|resource|snapshot` 显式声明；验证对象级与页面级版本不会被混用。
- `idempotency_class`：`click/submit/send/download` 等 verb 是否可机械分类；`unknown/non_idempotent` 的 transport failure 不得自动 replay。重点验证“稳定 ID”不会被误解成“重复动作安全”。
- `atomicity_class`：页面动作最多是 single_dispatch 还是确有 atomic guarantee；失败/超时时是否仍能报告已观察副作用，避免把“调用失败”误写成“世界没变化”。
- TOCTOU：observe 后目标被重渲染/替换但旧 locator 仍可命中其它节点时，动作必须 stale/identity-rejected，而不是静默点到替代对象。
- `Predicate`：虚拟列表懒加载元素的 visible 判定；URL contains 的编码边界。
- `SemanticDiff`：SPA 局部重渲染的 diff 噪音抑制（不违反 N6 的前提下）；跨页跳转/iframe 切换 = scope relation 变化，必须先判 comparability，不能直接制造巨量 removed。
- `ActionReceipt`：每步独立回执在批量动作下的 token 成本；`observed_effects` 与 `boundary_events` 的机械定义（弹窗/跳转/下载）；异步动作 receipt revision 是否 append-only/可回验。
- 双接口污染（U 裁定）：语义 Browser Adapter 上线后，实验臂 MUST 禁用 `playwright_exec` 直连或将其调用记为 intervention——否则度量失真。`playwright_exec` 定位为 L1 接地/执行 backend（其 URL 沙箱/AST 门控/审计是保留资产，`axtree_text` 是 L1 雏形），不升级为模型面。

---

## 6. Domain-0 conformance 盲区 / 已知 GAP（历史基线，防"全绿"误读）

> **状态注记（2026-09-13）**：本节 G1–G16 表记录的是 2026-09-12 SMC-ADAPT-SMX **之前**的 R1 基线，用于保留合同为何产生这些约束的 provenance；不得把表内“当前实现”措辞当成 09-13 runtime 现状。后续权威状态见 `docs/SMC-ADAPT-SMX-v0.1-RESULT-20260913.md/json`：P0–P8 measured probes 已 9 PASS / 0 GAP；仍未由 Domain-0 证明的核心考场是 G1–G5、G8 与 Browser 跨域充分性。

R1 的 `PASS` **只**证明探针实际覆盖到的合同断言；基线中的 GAP 不等于方向失败，而是当时 Domain-0 与上位合同的真实距离。以下表格保留为历史证据：

| # | 盲区 | 原因 | 真正的考场 |
|---|---|---|---|
| G1 | ID 分配/跨轮追踪/失效回收 | 当前 SMX path 只是 location key：rename 后 key 变化、删后同路径重建可能换物理对象；因此 **没有证明 SLA-1 物理对象 identity continuity** | SMC-ADAPT-SMX；Browser DOM identity 是更强考场 |
| G2 | SemanticAction 端到端 | 执行面经安全裁决留在 execute_command（正确且保留） | Browser/OS 适配器 |
| G3 | 对象级多感官 coverage 分层 | FS 当前主要是 stat/遍历单结构信号；虽已有 scope 级 truncation/walk_error，但没有 DOM/AX/vision 这类对象级多感官 coverage 融合 | canvas/WebGL（Phase 2） |
| G4 | 高频 stale/identity 时效压力 | 当前 Domain-0 探针没有系统施压“observe 后对象快速被替换/重建”的场景；这是测试覆盖缺口，不是说 FS 天然低频 | 高频文件替换 + Browser 重渲染 |
| G5 | 多对象空间关系 | FS 树是显式的；视觉空间关系（"按钮在弹窗内"）非 FS 词汇 | Browser/OS |
| G6 | 模型面 snapshot 内容完整性 token | `smx_perceive.snapshot` 当前只有唯一 snapshot_id + 落盘 JSON；CLI `smx.py::write_snapshot` 才有内容 sha12。两条链尚未统一 | SMC-ADAPT-SMX |
| G7 | Predicate observer-error 三态 | 当前 `file_contains` 读取 OSError 会持续表现为 false，最终与普通 timeout 合并为 `satisfied=false` | SMC-ADAPT-SMX |
| G8 | 异步 ActionReceipt 历史不可变 | CLI `bg_launch` 与最终 `collect` 复用/覆盖同一路径 `receipt.json`；适合 PoC，但不满足 v0.1 append-only/revisioned receipt 语义 | SMC-ADAPT-SMX / Browser async |
| G9 | diff scope comparability | `smx_perceive._diff(current=...)` 当前读取两端 entries/meta 后直接 `diff_pair`，未机械校验两张 snapshot 的 roots/depth/budget/sensor scope 是否可比 | SMC-ADAPT-SMX / Browser navigation |
| G10 | canonical SemanticDiff wire shape | 当前模型面输出 `created/deleted/modified` 计数 + `display_rows`，不是合同的 `created/removed/changed` 结构化集合；行为可单独验 fidelity，但 wire schema 仍未 conform | SMC-ADAPT-SMX |
| G11 | diff semantics 显式性 | 当前 `smx_perceive.diff` 实际是 snapshot-pair net diff，但 model-facing payload 没有 `diff_semantics=snapshot_pair_net`；CLI collect 反而已有“窗口内瞬时变化不可见”说明 | SMC-ADAPT-SMX |
| G12 | Predicate sampling semantics | 当前 SMX wait 是 interval polling，但回执主要给 waited_ms/timeout/detail，未把 interval/sample_count/observer_error_count 作为明确模型事实；容易把“没采到”误读成“从未发生” | SMC-ADAPT-SMX |
| G13 | Predicate negative under partial coverage | 当前 `file_contains` 最多读 8MiB；若未命中且文件更大，detail 会标“尾部未检”但 evaluation 仍按 false 继续，无法诚实证明“不包含” | SMC-ADAPT-SMX |
| G14 | diff field-level completeness | P1 修复已把 created/deleted/total_changes 降为 null，但 `modified=len(d["modified"])` 在截断时仍返回未标注 lower-bound 的数字；真实变化不一定是假，但总数不一定 exhaustive | SMC-ADAPT-SMX |
| G15 | observation vs projection 显式分层 | 当前 `smx_perceive.snapshot` 主要返回 entries 数、roots_meta、store_path；尚未用 SMC 的 `completeness + projection` 双轴说明“物理观察是否完整”与“模型本轮是否看到全部已捕获对象” | SMC-ADAPT-SMX |
| G16 | raw receipt hydrate 可绕过 canonical diff 纪律 | `smx_perceive(receipt, full=true)` 当前可原样返回 CLI `receipt.json`；CLI 截断场景仍含无条件 counts/raw `changed.json`。它们应作为 `raw_grounding_ref, canonical=false` 暴露，不能与 SMC canonical SemanticDiff 混同 | SMC-ADAPT-SMX |

任何"SMX 通过 conformance"的表述 MUST 附带本节引用，并区分 `PASS / GAP / FAIL / NOT_APPLICABLE`：`GAP`=合同要求明确但当前实现尚无该能力/字段；`FAIL`=实现声称支持该合同面但行为违反；`NOT_APPLICABLE`=该域/该实现按 capability declaration 明确不承载此合同面。不得把 GAP 改写成已实现，也不得为追求全绿降低合同。

---

## 7. 与 DESIGN-20260911 的差异/纠偏记录

四契约 → 六对象的主方向仍是把原文动词层混排的关注点各给 schema；本轮评审同时对上游几处过强假设做了合同级纠偏（幂等、原子性、FS path identity、diff/event 语义等）。逐条：

| # | 变化 | 理由 | 依据 |
|---|---|---|---|
| C1 | 契约①感知 拆为 SemanticObject + WorldSnapshot + SemanticDiff | SMX 实证三者独立成面：wait 不产生 diff（applicable=false）、bg running 不取 diff、快照可独立于动作存在 | 09-11/12 实测 |
| C2 | 契约③动作拆为 SemanticAction + Predicate | Predicate 是可复用的“断言声明”，wait/assert 是使用它的 observe/probe SemanticAction；条件语义与执行/轮询机制解耦，但审计仍统一走 ActionReceipt | smx wait 现行 + §0.1 |
| C3 | 契约②标识 不单独成对象 | id + grounding_ref 是 Object 字段、经水合通道实现——横切关注点而非容器 | EvidenceRef 同构 |
| C4 | 契约④反馈细化为 `observed_effects/boundary_events` 分列 | 动作事实与越界/边界事件需要机械可判字段，但程序不得替模型判断“预期/非预期” | SLA-3 + P3 |
| C5 | `completeness` 升为通用字段语义（null=unknown） | 06738a22 P1 修复的直接合同化：截断侧差集不得冒充事实 | 06738a22 |
| C6 | `budget` 可见进 WorldSnapshot（用户草案缺） | DESIGN 三-6 原文要求；SMX scope 已实现（entries/budget/truncated_any） | DESIGN 三-6 |
| C7 | `coverage` 保留进 SemanticObject（用户草案缺） | DESIGN 契约①原文字段；对象级盲区仅 Snapshot 层覆盖不了 | DESIGN 契约① |
| C8 | 三级缩放进动词层 depth 语义而非第七对象（用户草案缺） | DESIGN 三-3 是 observe/read 的参数语义；SMX display cap + full_list_path 已是其雏形 | DESIGN 三-3 |
| C9 | 新增 N11（进行中状态不得当终态） | SMX bg collect 的诚实纪律值得合同级保留（用户草案隐含、未成条） | U + smx 现行 |
| C10 | §九-5 关闭：定位 = LFL 工具域扩展 | 09-12 opt-in 并入的既成事实正式化 | d67748b1 前的并入链 |
| C11 | 增加横切 GroundingRef Contract | 六对象都依赖“回验到同一 observation”但原草案只命名未定义，P4 无法机械验收 | P4 / SLA-1/4 |
| C12 | 明确 effect 分类不得携带“预期内/预期外”任务语义 | 是否符合任务预期需要目标解释；程序只报告 observed effects 与机械 boundary events | P2/P3 |
| C13 | Predicate 升为 satisfied/unsatisfied/indeterminate | observer error ≠ 条件为假；SMX `file_contains` 暴露真实反例 | P4 |
| C14 | 新增 N14/N15 | 防 stable ID 在歧义重渲染时静默错绑；防 CSS/XPath 等 locator 换名后伪装 semantic ID | 契约②③ |
| C15 | expected version 增加 `version_scope` | 文件/元素/页面所需并发粒度不同，统一 token 契约不等于统一粒度 | DESIGN 四-4 |
| C16 | 否定“语义动作天然幂等”的普遍假设，增加 `idempotency_class` | 同一 semantic target 上重复 click/submit/send 仍可能产生双重副作用；稳定寻址 ≠ 重复执行安全 | N4 + side-effect safety |
| C17 | 把 SLA-3 从“默认动作原子”细化为显式 `atomicity_class` | Browser/OS 外部效果通常不可事务回滚；诚实报告能力边界比伪原子性更重要 | SLA-3 + N16 |
| C18 | SemanticDiff 增加 `comparable/scope_relation` | 不同 scope 的集合差不是世界 diff；Browser 导航和 SMX 不同 roots 都会制造伪 created/removed | SLA-2 + P4 honesty |
| C19 | 撤回“FS path 天然满足 stable object ID”的过强表述 | path 是 location identity；rename/path reuse 证明它不能代表持续物理对象 identity。Domain-0 因而也有真实 SLA-1 gap | SLA-1 + N14/N15 |
| C20 | SemanticAction 增加 dispatch 前 identity/version revalidation | stable ID 若最终仍用 stale backend handle 执行，TOCTOU 会绕过整个标识契约；必须在动作前置阶段拒绝歧义/过期目标 | N17 + DESIGN 四-4 |
| C21 | SemanticDiff 增加 `diff_semantics` | snapshot 对差只能证明净状态，不能证明期间无瞬时事件；SMX CLI 已有这一诚实边界，合同上提为跨域事实 | SLA-2 + SMX time_window |
| C22 | Predicate 增加 evaluation semantics | polling 的离散采样不能证明区间内条件从未瞬时成立；必须把采样方式/间隔/错误暴露为事实 | P4 honesty + SMX wait |
| C23 | Predicate 增加“否定需要足够覆盖”规则 | partial search 的正向 witness 可成立，但 negative absence 需要完整或足够 coverage；同一原则适用于大文件、虚拟列表、分页 DOM | P4 honesty |
| C24 | SemanticDiff 增加 `field_completeness` | 全局 incomplete 不代表所有已观察事实都不可用；需要区分“可能假阳性必须 null”和“真实但可能漏项的 lower-bound partial facts” | 06738a22 深化 |
| C25 | 分离 observation completeness 与 projection completeness | token/display 裁剪只影响模型本轮看多少，不能伪装成传感器盲区；真实 observation gap 也不能伪装成“只是没展开” | P4/P5 + LFL Evidence precedent |
| C26 | 增加 `operation_class=observe|probe|mutate` 并修正 profile 边界 | wait/assert 需要可审计 Action/Receipt，但 perception profile 又不应拥有世界修改权；probe（如 TCP connect）也不能假装纯读 | §0.1 + P2 |
| C27 | 回验 raw grounding 与 canonical contract projection 明确分层 | “可回验”不代表 raw 层天然满足高层完整性语义；full hydrate 必须保留 canonical=false/原始边界，不能重新注入已知伪差分 | §2.0 + G16 |
| C28 | `coverage.conflicts` 标准化多感官冲突 wire | R3 Browser 反例：DOM/AX/vision 可对同一 enabled/visible/name/identity mapping 给出冲突；只写“必须暴露”而无公共 wire 会迫使跨域调用方猜 adapter 私有 extension。未机械消解时 canonical field=null，保留全部 source/value/grounding | R3-09/R3-10 + P2/P3 |

---

## 8. 冻结兼容与实施顺序

> **历史治理注记（2026-09-13）**：本节原始顺序记录 09-12 冻结期约束。其后已完成 SMX focused v1.2 re-freeze/正式 30-run、SMC-ADAPT-SMX P4→P7→P2→P8→P5→P0 与 committed-state qualification；当前事实以 `docs/SMC-ADAPT-SMX-v0.1-RESULT-20260913.md/json` 及 R3 Browser 报告为准。本节旧 v1.1 条目保留作 provenance，不重新冒充待执行计划。

- **本文档本身是 docs-only 工件**：不触碰任何冻结代码。2026-09-12 本轮复核：`tools/smx/smx.py`、`src/llm_loop/tools/builtin/smx_perceive.py`、`src/llm_loop/tools/registry.py` 三个 SMX 核心锚当前 SHA 仍与 `dba31bd7:evals/pilot/smx_focused_v1_1.json` 一致；`registry.py` 的 `35fa47c9` 修改早于冻结锚生成，锚定捕获的是修改后状态。
- **但“SMX 三核心锚一致”不等于 SMX focused v1.1 全冻结集一致。** 本文评审过程中 convergence HEAD 被并发推进到 `226a9010`；该提交属于**另一条 AgentPilot v1.1 108-run 治理线**，并修改了 `evals/pilot/analyze.py`。该文件同时也是 **SMX focused v1.1** `source_sha256` 冻结清单成员（冻结值 `33de85e20ae6e42a3336372f8253c543a9504330985f9a80d6cb191a9da5d0c1`）。因此当前 convergence HEAD 已满足 SMX focused 协议 invalidation 条件 `frozen_hash_changed`，**不得直接拿当前 HEAD 执行并称为原 frozen SMX focused v1.1 30-run**。这不表示 SMX 30-run 已执行；只是当前 HEAD 不再等于它的冻结源码集合。
- 若仍执行原 **SMX focused v1.1**，MUST 使用独立 frozen worktree/revision，并在首个模型调用前逐一验证全部 `source_sha256` + execution-plan hash；若希望基于当前 convergence 运行，则 MUST 生成新的 SMX focused 协议版本/新 manifest（例如 v1.2），不能悄悄沿用 v1.1 名称。本文档本身不改变那三个 SMX 核心 source hashes，但也不“恢复”已被并发提交打破的全冻结集。
- **互斥点**：SMX 代码适配本合同（包括 canonical wire、snapshot integrity、Predicate 三态、scope comparability、receipt revision 等任何被锚文件改动）会改变实验 treatment 本体 → **MUST 等待原 frozen A/B 执行完毕/明确放弃，或显式 re-freeze 新协议版本**后进行（任务暂名 SMC-ADAPT-SMX，不在本文档承诺范围）。
- **顺序**：本合同评审通过 → R1/R2 探针脚本化（不动被锚文件，只加测试，允许诚实红/GAP）→ SMX focused v1.1 A/B 裁决 → SMC-ADAPT-SMX → Browser Phase 1 规格（R3 清单转正式设计）。
- 探针脚本（P0–P8、L1–L5 断言化）**可以**先行：SHOULD 放在独立 SMC worktree/branch；原 **SMX focused v1.1** A/B 若执行，必须从通过全部 frozen-hash 校验的独立实验 worktree 运行。第一轮探针目的必须是输出 `PASS/GAP/FAIL/NOT_APPLICABLE` 现状矩阵，**不得先改冻结实现去迎合合同**。

## 9. 开放问题与 v0.1 已关闭裁决

**仍开放**：

- **Q3**（继承 §九-4）：vision 补盲成本闸门的具体预算维度——按请求次数/token/像素或盲区面积如何组合，留到 Phase 2 用实测裁决。v0.1 只固定：程序只报告结构 blind spot + 可用 vision 能力/成本事实，**是否调用 vision 必须由模型显式请求**；cost/coverage 必须可见，程序不得因识别到 blind spot 就自动花费 vision。

**v0.1 已关闭（进入后续版本需显式 reopen + 证据，不得由实现自行改写）**：

- **Q1 组合动作**：只允许模型显式声明的纯线性序列起步；每步独立 SemanticAction + 独立 ActionReceipt，前一步失败按预先声明的依赖合同机械阻断后续依赖步骤；程序不得自行生成补偿/恢复步骤。v0.1 不定义条件分支 DSL，分支策略留给模型。
- **Q2 多标签/多窗口 ID 作用域**：Semantic ID 在 adapter runtime/session 内唯一，并显式关联 page/window/scope；不要求跨 session 永久稳定。若 adapter 重启导致 ID namespace 重置，旧 ID 必须显式失效，不能碰巧复用成另一对象；不允许仅页面内重复 ID 造成模型歧义。
- **Q4 expected_version 粒度**：采用 `expected_version + version_scope`；至少允许 `object | resource | snapshot`，粒度由 adapter/domain 机械事实决定；不支持版本前置的 verb 必须显式声明 unsupported/not_applicable。
- **Q5 Predicate 组合**：v0.1 仅单谓词。未来如需组合，只允许纯 Predicate AST（AND/OR/NOT）；“A 后再 B”属于工作流时序，不下沉为自动程序策略。
- §九-3：OS 排后、Browser 先；§九-5：定位为 LFL 工具域扩展（C10）。

---

## 附：证据清单（本文"已实现"断言的来源；GAP/纸面目标不冒充已实现）

| 断言 | 来源 | 核验时间 |
|---|---|---|
| smx.py receipt 字段全集（diff/scope/counts/truncated_any/applicable/running+note） | `tools/smx/smx.py` L252–345、L285（wait not-applicable）、L461–463（bg 无 after）、L502/520（running 态切换）（SHA 2aa66aa6，与锚一致） | 2026-09-12 21:29 |
| smx_perceive._diff 完整性纪律（null 降级 + diff_complete） | `src/llm_loop/tools/builtin/smx_perceive.py` L231–281（SHA 2a528386，与锚一致） | 同上 |
| 06738a22 = P1 修复 + 回归测试 ×2 + 冻结实现入库 | commit 06738a22（2026-09-12 12:36） | 同上 |
| SMX focused v1.1 `source_sha256` 精确锚定 **18 个文件** + execution_plan_sha256（本轮机械计数复核；另有 manifest 级 tool-surface/runtime 等必填 hash，不混称 source files） | `evals/pilot/smx_focused_v1_1.json`@dba31bd7 | 同上 |
| LFL 文件域 L1–L5 实例 | 现行工具 schema + 本会话 evidence_hydration_v2 回执 | 同上 |
| playwright_exec 定位与安全资产 | `src/llm_loop/introspection/tools_playwright_exec.py`（现行受控 Playwright backend/模型脚本工具；SMC Browser Adapter 尚未实现） | 2026-09-12 本轮复核背景 |
