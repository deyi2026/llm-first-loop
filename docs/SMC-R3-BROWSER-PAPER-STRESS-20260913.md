# SMC v0.1 — R3 Browser Paper Stress Test — 2026-09-13

> Baseline: `a433b57925d89ba67edcf601910867700ab22bb6` (`a433b579 docs(smc): close Domain-0 adaptation result`)
> Normative contract: `docs/SMC-CONTRACT-v0.1.md`
> Prior result: `docs/SMC-ADAPT-SMX-v0.1-RESULT-20260913.md/json`
> Nature: **paper/adversarial contract stress only** — no Browser production adapter, no model run, no service restart.

## 1. 裁决

R3 得到的不是“现合同原样全过”，而是一个更有价值的结果：

1. **发现 1 类真正跨域合同缺口**：多感官冲突此前只有文字 MUST、没有公共 wire。DOM/AX/vision 对 `enabled/visible/name` 或 object mapping 冲突时，各 adapter 若只塞私有 extension，模型仍需猜结构。
2. 已做最小 docs-only 修订 **C28**：`SemanticObject.coverage.conflicts` 成为公共冲突事实；未被预声明、任务无关、可复算规则机械消解时，canonical field 必须 `null`，同时保留每个 `source/value/grounding_ref`；identity mapping 不唯一时禁止强行融合。
3. **没有发现第二个必须扩张六对象 core schema 的 Browser Phase 1 反例。** 多 tab/iframe/navigation、DOM churn、TOCTOU、non-idempotent click、partial side effect、Predicate sampling、snapshot-vs-event diff、async receipt 等均可由现有 `scope_ref / grounding / version_scope / idempotency_class / atomicity_class / diff_semantics / receipt_seq / completeness` 承载。
4. 上游 `DESIGN-20260911` 有数处早期强假设已经被后来的 SMC 合同推翻但正文未同步；本轮一并对齐，不改变生产代码：删除“主按钮/关键状态/任务相关自动裁剪/最相似候选/语义动作天然幂等/默认可回滚/任意时刻无条件回验”等错误暗示，改成现合同的机械事实边界。

**修订后 R3 纸面裁决：**

> **SMC v0.1 + C28 已具备 Browser Phase 1 的规格充分性；但尚未通过 Browser implementation conformance。Phase 2 vision-only actionability 与 Phase 3 native UI 仍 DEFERRED。**

这不是成熟度分数，也不是 Browser 已实现。

## 2. 当前 Browser 事实边界

仓库中**没有 SMC Browser adapter**。现有 `playwright_test` / `playwright_exec` 是 legacy E2E/脚本工具，可复用的只是 L1/back-end 机械资产：

- `playwright_exec` 模型面仍接收 Python + CSS selector；每次调用独立子进程、独立 browser session，状态不跨调用持久；
- `axtree_text()` 使用 CDP `Accessibility.getFullAXTree`，随后压成文本；500 行/20,000 字符熔断会显式标截断；
- `click(selector)` / `fill(selector, value)` 直接使用 selector；这违反 SMC 模型面 N15 的目标形态，因此**不能把旧工具改名后宣称 Browser adapter**；
- URL allowlist、AST 门控、审计、截图/AX 获取可以保留为 backend/safety 资产；
- SMC 实验臂上线时，模型直连 `playwright_exec` 必须禁用或记录为 intervention，避免双接口污染。

## 3. R3 对抗矩阵

`合同裁决` 评价的是 **v0.1 是否足以描述正确行为**；`实现状态` 单独记录当前仓库有没有 Browser 实现。两者不能混为一谈。

| ID | 场景 | 合同初始裁决 | 实现状态 | 机械理由 / 反例 |
|---|---|---|---|---|
| R3-01 | SPA reorder preserves physical node | **PASS** | GAP | 同一 backend/DOM identity 在同 document 内仅重排；合同允许延续 ID，要求可水合 grounding。 |
| R3-02 | React rerender replaces node with same role/name | **PASS** | GAP | 相似语义不证明物理同一；新对象或 unresolved，N14 阻止静默继承旧 ID。 |
| R3-03 | duplicate candidates after old node disappears | **PASS** | GAP | 多个相似候选时 identity ambiguous；不得 best-match 自动重绑。 |
| R3-04 | identity task-invariance | **PASS** | GAP | identity policy 必须预声明且与用户任务文字无关；同 DOM 演化在不同任务下结果相同。 |
| R3-05 | two tabs with identical content | **PASS** | GAP | ID runtime/session 唯一且显式 scope_ref，页面内容相同不能导致跨 tab alias。 |
| R3-06 | iframe scope and frame navigation | **PASS** | GAP | frame/document 可作为 Browser domain scope hierarchy；frame 导航导致 scope/version 变化，旧 target 不能穿透。 |
| R3-07 | full navigation on same tab | **PASS** | GAP | 先判 scope_relation/comparability；新 document 不得解释成旧页面对象全删+新页面全建。 |
| R3-08 | adapter/browser restart invalidates old IDs | **PASS** | GAP | v0.1 只要求 runtime/session 生命周期；namespace reset 后旧 ID 必须 expired/unavailable，不得碰巧复用。 |
| R3-09 | DOM vs AX conflict on canonical state | **CONTRACT_CHANGE_NEEDED** | GAP | 原合同只写“冲突必须暴露”但无公共 wire；R3 证明 enabled/visible/name 等冲突会迫使跨域调用方猜 extension。 |
| R3-10 | DOM↔AX object fusion ambiguity | **CONTRACT_CHANGE_NEEDED** | GAP | 同一 DOM node 与多个 AX node、或反向映射不唯一时，不能强行融合成一张卡；原公共 wire 不足。 |
| R3-11 | aria-hidden / DOM-present but AX-absent | **PASS** | GAP | 不是“谁为准”，而是 source-qualified observation + coverage/conflict；是否对任务有用由模型判断。 |
| R3-12 | open/closed shadow DOM coverage | **PASS** | GAP | 可达结构进入声明 sensor coverage；closed/unreachable 区域形成 blind_spot，不得静默空集。 |
| R3-13 | canvas/WebGL structural blind spot | **PASS** | GAP | Phase1 可诚实报告 tree blind spot 与 vision capability/cost；不得自动触发 vision。 |
| R3-14 | vision-only semantic target actionability | **DEFERRED** | DEFERRED | 视觉对象的稳定 identity、坐标接地精度、遮挡/缩放后的动作安全需真实 Phase2 视觉实验，paper test 不能证明。 |
| R3-15 | spatial relations from geometry vs inferred grouping | **PASS** | GAP | 父子/包含/几何 bbox 可机械关系；“看起来同组/更靠近所以相关”仍属模型解释。 |
| R3-16 | projection truncation vs observation completeness | **PASS** | GAP | 对象已捕获但未投影 ≠ sensor 没看到；projection 与 completeness 两轴已能表达。 |
| R3-17 | stale target / TOCTOU before click | **PASS** | GAP | dispatch 前必须重新解析 target identity 并核 expected_version；旧 locator 命中替代节点仍应 rejected。 |
| R3-18 | object/page version granularity | **PASS** | GAP | expected_version + version_scope 能区分 object/resource/snapshot；不支持时明确 unsupported。 |
| R3-19 | click/submit transport ambiguity | **PASS** | GAP | 稳定 ID 不等于幂等；non_idempotent/unknown 不得静默 replay。 |
| R3-20 | click fails after partial side effect | **PASS** | GAP | atomicity_class 必须如实；single_dispatch/best_effort 失败后仍报告已观察副作用，不能声称世界没变。 |
| R3-21 | popup / download / new-window boundary events | **PASS** | GAP | 动作原 scope 不回写；新 window/download/permission 等以 boundary_events + 新 scope/snapshot 表达。 |
| R3-22 | async action receipt revisions | **PASS** | GAP | 同 action_id 的 receipt_seq 单调唯一、旧 receipt immutable；running→terminal 新增 revision。 |
| R3-23 | virtualized list negative predicate | **PASS** | GAP | 未加载/分页区域使“不存在/不可见”缺足够 coverage 时应 indeterminate；正向 witness 可 satisfied。 |
| R3-24 | transient condition between polling samples | **PASS** | GAP | polling unsatisfied 仅表示采样点未见；event_driven 才可声明更强时间语义。 |
| R3-25 | SPA churn snapshot-pair diff | **PASS** | GAP | diff_semantics=snapshot_pair_net 只证明净变化；中间 detach/reattach 不得被说成未发生。 |
| R3-26 | sensor contract differs between snapshots | **PASS** | GAP | diff comparability 必须含 sensor/coverage contract；DOM-only 与 DOM+AX 不可直接做完整对象集合差。 |
| R3-27 | history.pushState URL change in same document | **PASS** | GAP | document 可保持同 scope，URL/state 作为 mechanically changed field；是否代表任务阶段变化由模型判断。 |
| R3-28 | cross-origin iframe partially observable | **PASS** | GAP | 权限/介质限制进入 coverage/completeness；不可达不能冒充空 frame。 |
| R3-29 | native browser chrome / OS permission dialog | **DEFERRED** | DEFERRED | Browser DOM adapter 不能假装覆盖浏览器 chrome/系统对话框；应报告 blind spot/boundary，实际操控属 Phase3 OS/Computer Use 域。 |
| R3-30 | legacy playwright_exec dual-interface contamination | **PASS** | GAP | SMC 实验臂必须禁用模型直连 playwright_exec 或记为 intervention；否则模型可绕过 Semantic ID/receipt contract。 |
| R3-31 | model-facing CSS/XPath/AX index locator | **PASS** | GAP | N15 已禁止 ephemeral locator 作为 target_id；CSS/XPath/CDP/AX index 只允许 adapter 内部解析。 |
| R3-32 | program-generated salient hint / task-relevance filtering | **PASS** | GAP | 核心 P2/P3/N1/N10 已禁止；R3 发现 DESIGN 示例仍有“蓝色主按钮/关键状态/任务相关子集”漂移，已 docs-only 对齐。 |

初始合同计数：**PASS=28 / CONTRACT_CHANGE_NEEDED=2 / DEFERRED=2**。C28 落地后，两条 `CONTRACT_CHANGE_NEEDED` 均转为 PASS；DEFERRED 不因纸面修订冒充 PASS。

## 4. C28 为什么必须进 core，而不是留给 Browser 私有 extension

反例 A：同一对象 DOM `disabled=false`，AX `disabled=true`。如果 core 只有：

```json
{"state": {"enabled": true}, "coverage": {"sources": ["dom", "ax"]}}
```

adapter 必须偷偷选一个 source，或把冲突塞到自己私有字段。前者违反诚实原则，后者让“跨域不变量”退化成调用方按 adapter 猜 schema。

C28 后统一为：

```json
{
  "state": {"enabled": null},
  "coverage": {
    "status": "complete",
    "sources": ["dom", "ax"],
    "blind_spots": [],
    "conflicts": [{
      "field": "state.enabled",
      "observations": [
        {"source": "dom", "value": true, "grounding_ref": "..."},
        {"source": "ax", "value": false, "grounding_ref": "..."}
      ],
      "resolution": "unresolved"
    }]
  }
}
```

`complete=true` 只说明声明的 sensor contract 看全了，**不再被误读成 sensors 达成一致**。

反例 B：一个 DOM node 映射到两个 AX node。若 identity fusion 不唯一，程序不得为了“卡片更整洁”任选一个 AX node；应保留独立对象或 `identity_mapping` conflict/unresolved。哪一个更符合任务，由模型在事实基础上判断。

## 5. Browser Phase 1 必须预先钉死的域规格

### 5.1 Scope 与 identity

- ID 在 adapter runtime/session 内唯一；不能仅“页面内唯一”。
- Browser domain 必须把 page/tab、document generation、frame 作为可解析 scope hierarchy；`scope_ref` 可以是 opaque ID，但 hydration 必须能返回其 domain scope facts/parentage。
- navigation/reload/frame navigation/reconnect 必须让旧 grounding/version 的有效性变化可见。
- 相似性只能产生 identity basis/ambiguity facts；不能因为 role/name/text 很像就继承旧 ID。

### 5.2 Sensors 与 object card

- Phase 1 sensors = DOM + AX；vision 只报告 capability，默认不执行。
- role/name/enabled/visible 等字段必须定义其 source 与机械语义，避免一个模糊 `visible` 同时代表 DOM style、AX exposed、viewport intersection。
- multi-sensor conflict 走 C28；不得用 priority list 静默吞掉冲突。
- shadow/cross-origin 不可达、AX truncation 等进入 coverage/completeness，而不是空对象集合。

### 5.3 Action

- 模型只提交 Semantic ID / semantic root；selector/DOM node id/AX index/坐标为 adapter 内部 locator。
- dispatch 前重新 resolve identity + expected_version/version_scope。
- `click/submit/send/download` 不默认幂等；`single_dispatch` 也不等于下游事务原子。
- transport ambiguity 后 non-idempotent/unknown 动作不自动 replay；任何允许的协议级 retry 都需 receipt 可审计。

### 5.4 Diff / Predicate / Receipt

- Browser snapshot pair 默认 `diff_semantics=snapshot_pair_net`；若有 MutationObserver/CDP event stream，必须单独声明 event coverage/completeness，不能混写。
- diff comparability 至少绑定 domain + scope/document + sensor contract；跨 navigation/frame/sensor-contract change 先降不可比。
- Predicate 只使用预声明 property/operator/value；virtualized list、pagination、blind spot 下的 negative 需要足够 coverage，否则 `indeterminate`。
- ActionReceipt append-only：running/terminal 是同 action_id 的不同 receipt_seq；旧 receipt 不能覆盖。
- new-window/download/dialog/permission 等只有在机械定义的 detector 存在时才能进 boundary_events；探测不全必须标 heuristic/non-exhaustive。

## 6. Browser Phase 1 最小实现资格门

只有下表全部满足，才能从“R3 paper sufficient”进入“Browser adapter implementation candidate”。

| Gate | 名称 | 最小资格 |
|---|---|---|
| B0 | surface isolation | 声明 smc-manipulation-v0.1；实验臂模型面只暴露 SMC Browser surface。legacy playwright_exec 若保留只作内部 backend/独立 E2E，模型直连必须禁用或计 intervention。 |
| B1 | scope model | runtime/session 内 Semantic ID 唯一；显式 page/document/frame scope_ref 与 parent relation；navigation/restart 产生可见 generation/失效事实。 |
| B2 | grounded snapshot | WorldSnapshot 绑定 observed_at、sensor_contract、content/integrity grounding、observation completeness 与 projection completeness；DOM/AX raw grounding 可按声明 retention 水合。 |
| B3 | identity continuity | identity matcher 任务无关；reorder 同物理对象延续 ID；replacement/duplicate ambiguity 不误绑；旧 ID stale/retired 可机械检测。 |
| B4 | multi-sensor honesty | DOM/AX source-qualified；coverage.conflicts 按 C28 输出；未消解冲突 canonical field=null；identity mapping ambiguity 不强融。 |
| B5 | diff semantics | SemanticDiff 显式 snapshot_pair_net/event_stream；比较前核 domain/scope/document/sensor contract；incomplete/changed fields 按 field_completeness 诚实降级。 |
| B6 | semantic actions | click/fill/select/navigate/scroll 等只接受 Semantic ID/semantic root；model-facing 禁 CSS/XPath/coordinate/CDP/AX index；operation_class 固定于 verb contract。 |
| B7 | TOCTOU/version | dispatch 前重新解析 identity + expected_version/version_scope；stale/ambiguous 拒绝，不静默换 locator/target。 |
| B8 | retry/atomicity | 每 verb 暴露 idempotency_class/atomicity_class；non_idempotent/unknown transport ambiguity 不 replay；任何允许 retry 都可审计；失败仍报告已观察副作用。 |
| B9 | append-only receipts | ActionReceipt 持久可回验；同 action_id receipt_seq 唯一单调；running/terminal revision 不覆盖旧 receipt；before/after version 与 boundary_events 齐全。 |
| B10 | predicate honesty | structured Predicate vocabulary；satisfied/unsatisfied/indeterminate；negative 需足够 coverage；polling/event mode、interval/sample/error facts 可见。 |
| B11 | blind spots/boundaries | shadow/cross-origin/canvas/native chrome 等不可达显式；new-window/download/dialog/permission 等固定机械事件可见；Phase1 不自动调用 vision。 |
| B12 | authority lint | 模型面对象/回执无 recommended/best/priority/completion/recovery sequence/“相似候选自动替代”等策略字段；程序不生成任务相关裁剪或重要性摘要。 |
| B13 | deterministic adversarial suite | 至少把 R3-01..R3-32 中 Phase1 非 DEFERRED 场景变成 deterministic fixture；每项有 ground-truth oracle，不依赖 LLM 评分。 |
| B14 | repo qualification | focused + adjacent + schema/authority + security + Pyright/Ruff + full ci_gate committed-state 全绿；不得以 legacy Playwright 通过代替 SMC conformance。 |

### 第一版明确不做

- 不做条件分支 workflow DSL；
- 不做程序自动 recovery/替代 target；
- 不做全屏自动 vision；
- 不把旧 `playwright_exec` 直接包成 SMC；
- 不要求跨 adapter restart/session 永久 ID；
- 不宣称 Browser/OS action transactional；
- 不用 LLM judge 代替上述 deterministic conformance oracle。

## 7. 实施顺序建议

1. **B-SPEC**：先写 Browser domain profile（scope/sensor/property/verb/version/idempotency/atomicity vocabulary），只文档+closed schema test。
2. **B-PERCEPTION**：DOM+AX → WorldSnapshot/SemanticObject + hydrate；先打 R3-01..R3-13、R3-15/16、R3-26..28。
3. **B-IDENTITY/DIFF**：identity lifecycle + scope comparability + snapshot_pair diff；故意制造 reorder/replacement/navigation/sensor-change。
4. **B-ACTION**：最小 `click/fill/select/navigate`，全部 semantic target；先 TOCTOU + version reject，再正向动作。
5. **B-RECEIPT/PREDICATE**：append-only receipts + visible/enabled/url 等 structured Predicate；再做 popup/download/virtual-list/transient event。
6. **B-QUAL**：R3 deterministic suite + authority scan + full repo gate；通过后才允许真实 Browser model A/B。
7. **Phase 2**：vision-only object/actionability 单独 re-open；不借 Phase 1 成功偷渡为已验证。

这样顺序保持 LLM-First：程序逐步补足“看清、指准、动得可审计”，不增加一个替模型选择/判断的策略层。

## 8. 非声明项

本轮没有：

- 实现 Browser SMC 生产代码；
- 启动/操作真实 Browser adapter；
- 调用 8901 或任何模型；
- 重启 8901/8903/Feishu；
- 验证 vision-only 点击准确率；
- 验证 native browser chrome/OS UI；
- 证明 Browser implementation conformance。

因此后续正式用语应是：

> **SMC v0.1 经 R3 Browser paper stress，在 C28 多感官冲突 wire 修订后通过 Browser Phase 1 规格充分性审查；Browser implementation conformance 尚未开始，Phase 2 vision 与 Phase 3 native UI 保持 deferred。**
