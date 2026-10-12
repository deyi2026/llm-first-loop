# SMC Browser Phase 1 B-PERCEPTION Result — 2026-09-13

> B-SPEC baseline: `fec0c7740252b58be98c166dc1b592ceddd2ce4d`
> Implementation: `c95fd46eff948fb75e689d401f9d125049c7601e` (`feat(smc): add Browser Phase 1 perception`)
> Nature: **read-only Browser perception adapter qualification; runtime host not activated**.

## 1. 裁决

B-PERCEPTION 已把 B-SPEC 的只读 Browser 感知部分从规格推进到可运行实现，并完成 deterministic conformance 与 committed-state repo qualification。

当前最准确结论：

> **DOM+AX 的只读 SMC adapter/store/tool class 已实现并通过确定性资格；真实 Browser host 尚未接入，所以不能宣称 live Browser conformance。**

本阶段结论：

- read-only perception adapter: **PASS_DETERMINISTIC**
- frozen B-SPEC closed wire: **PASS**
- scope/generation/identity: **PASS_DETERMINISTIC**
- C28 DOM↔AX conflict honesty: **PASS_DETERMINISTIC**
- grounding integrity/retention/hydrate: **PASS_DETERMINISTIC**
- Playwright read-only capture backend: **PASS_DETERMINISTIC_FAKE_CDP**
- runtime Browser host: **NOT_ACTIVE**
- factory model-surface registration: **NOT_REGISTERED**
- live external-site DOM+AX qualification: **NOT_TESTED**
- mutation / diff / Predicate / ActionReceipt: **NOT_IMPLEMENTED in B-PERCEPTION**
- Phase 2 vision-only actionability: **DEFERRED**
- Phase 3 native browser chrome / OS UI: **DEFERRED**

这不是 Browser 产品成熟度评分，也不是“Playwright 已经被模型接管”。

## 2. 冻结实现工件

实现提交 `c95fd46eff948fb75e689d401f9d125049c7601e` 精确新增 5 个文件、`+2246`：

| 工件 | SHA-256 |
|---|---|
| `src/llm_loop/browser/__init__.py` | `a3120928e03625f40f6b9ce531f326bec13d16e31f95ce883bf51e4403b196ef` |
| `src/llm_loop/browser/perception.py` | `c948f73269f6614e7db15913b0dfc49c112d9705b2063f84873d6928a345957f` |
| `src/llm_loop/tools/builtin/browser_perceive.py` | `50a0c19713ef64b4b374c8441d63db2562b5cd037d08283667e9dac801fc7f06` |
| `tests/fixtures/smc_browser_perception_v01.json` | `aadbf6077451824f96d9042bbe2c3cd2c6547dbc3b565bf682ba4765b0882dbb` |
| `tests/unit/test_smc_browser_perception_v01.py` | `42bc0e36a33dd66cd92e32f9d9d1a3c918b77cde1b4199b6f4723caaec9f5c73` |

`git show --check` 与 exact file set 已在 committed implementation 上复核通过。

## 3. 架构：感知 backend 与模型 surface 分离

### 3.1 `PlaywrightPageCaptureBackend`

它只读取一个**由 host 已经绑定的 page**。本阶段没有 host，也没有自动打开页面。

允许的 CDP 方法固定为：

```text
Target.getTargetInfo
Page.getFrameTree
DOMSnapshot.captureSnapshot
Accessibility.getFullAXTree
```

明确没有：

```text
Page.navigate
Runtime.evaluate
Input.*
click / fill / scroll
CSS/XPath selector dispatch
任意模型脚本执行
```

如果拿不到真实 `targetId` 或 main `loaderId`，backend **fail closed**；绝不用 URL 作为页面/文档 identity fallback。child frame 若缺 loader identity，则只产生 capture-local identity 并把 `frame_document_identity_unavailable` 写入 completeness，下一 observation 保守失效。

### 3.2 `BrowserPerceptionAdapter`

adapter 不接受 `task/query/relevance/priority`，因此 identity、fusion、projection 不能按任务语义改变。

职责被拆成独立机械层：

- scope/generation；
- DOM/AX sensor preparation；
- source grounding；
- object canonicalization/fusion；
- structural relations；
- snapshot envelope/persistence。

实施中原 `snapshot` 一度超过 430 行；审查后拆为 118 行 orchestration，最长新增 helper `_canonicalize_objects` 245 行、Playwright `capture` 198 行，架构守卫通过。这不是改变语义，而是让感知、融合、持久化边界可独立审计。

### 3.3 `BrowserPerceptionStore`

GroundingRef：

```text
grounding://browser/v0.1/...
```

支持 exact hydrate：

- full objects；
- scope facts；
- DOM/AX sensor grounding；
- canonical object grounding；
- source-qualified object observation。

机械保证：

- immutable snapshot bundle；
- session fence；
- TTL retention；
- bundle SHA-256 integrity；
- tamper → `unavailable / integrity_error`；
- cross-session → `unauthorized`；
- TTL 超期 → `expired`；
- exact ref 不会静默重新抓一个“相似的新页面状态”。

backend physical IDs / AX IDs 只进入私有 audit bundle，模型可水合投影中不存在这些 ephemeral locator。

## 4. Scope / generation / identity

模型可见 `scope_facts` 使用冻结 B-SPEC `browser_scope`：

```text
page → document → frame → nested frame
```

每条 scope 明确：

- `runtime_generation`
- `page_generation`
- `document_generation`
- `frame_generation`
- `parent_scope_ref`

行为已确定性验证：

- 同一物理 DOM node 仅 reorder → Semantic ID 保持；
- 同 role/name 的 replacement → 不复用旧 ID；
- duplicate candidates → 不 force match；
- 相同内容的两个 page → 不 alias ID；
- full navigation / frame navigation → generation 变化，旧 identity 失效；
- pushState 同 document → document generation 与实体 ID 保持；
- adapter runtime restart → runtime generation 变化并 rekey。

`content_sha256` 只覆盖 observation facts，剔除每次 capture 随机生成的 GroundingRef / observed_version，因此**同一机械 observation 在同 runtime/scope 下内容 hash 稳定，而 snapshot_id 仍然唯一**。

## 5. DOM + AX 与 C28

### 字段冲突

若 DOM 与 AX 对同一 canonical field 给不同值：

```text
canonical field = null
coverage.conflicts[].resolution = unresolved
```

并保留双方：

```text
source + value + grounding_ref
```

没有 silent source priority。

### identity mapping ambiguity

若一个 DOM physical node 对应多个 AX candidates：

- 不强融；
- DOM card 输出 `identity_mapping` conflict；
- AX candidates 保持独立 source-qualified SemanticObject；
- raw AX node id 不出现在模型面。

### DOM present / AX absent

像 aria-hidden 这种情形不是 “AX sensor failed”：

- object coverage 可为 `sources=[dom], status=partial`；
- 若 AX observation 本身成功，整个 snapshot 仍可 `completeness.complete=true`。

这保持“对象没有被某 sensor 看见”和“sensor 没工作”两个事实不同。

## 6. Completeness 与 blind spots

当前 deterministic coverage 包括：

- closed shadow root；
- canvas 结构盲区；
- uncaptured cross-origin frame；
- DOM/AX unavailable/truncated；
- child-frame document identity unavailable；
- projection cap 与 observation completeness 正交。

特别地，Playwright backend **不再把 DOMSnapshot layout membership 冒充 `visible=true`**：layout presence 不是用户可见性真值，opacity/clipping/occlusion 都可能反例。

vision 仍为：

```text
explicit_only_deferred_phase2
```

程序不会因为 DOM/AX 有盲区自动调用视觉。

## 7. 模型面：`browser_perceive`

当前类已实现但**没有注册进 factory/config/registry**。

动作只有：

```text
snapshot
hydrate
```

参数只有：

```text
action
projection_limit
grounding_ref
```

不存在：

- URL；
- selector/XPath；
- coordinate；
- CDP node id / AX index / native handle；
- script/code；
- click/fill/navigate/scroll；
- recommended/best/priority/task relevance/completion/recovery sequence。

`snapshot` 没有 host backend 时会明确失败，并且**不会 fallback 到 legacy playwright_exec**。`hydrate` 只对精确 GroundingRef 工作。

B-SPEC 的：

```text
automatic_protocol_retry = disabled_v0.1
```

保持不变。

## 8. R3 deterministic coverage

B-SPEC 冻结了 30 个非 DEFERRED Phase 1 obligations。本阶段只兑现其中与 perception 直接相关的 **20 个**：

```text
R3-01 R3-02 R3-03 R3-04 R3-05 R3-06 R3-07 R3-08
R3-09 R3-10 R3-11 R3-12 R3-13 R3-15 R3-16 R3-27
R3-28 R3-30 R3-31 R3-32
```

未在 B-PERCEPTION 偷跑的 10 个：

```text
R3-17..R3-26
```

它们属于 diff / Predicate / mutation / receipt 后续实现。

继续 DEFERRED：

```text
R3-14 vision-only actionability
R3-29 native browser chrome / OS UI
```

因此不能写成“R3 30/30 implementation PASS”。

## 9. B0–B14 当前裁决

| Gate | B-PERCEPTION 状态 | 理由 |
|---|---|---|
| B0 surface isolation | **PARTIAL** | closed read-only SMC surface 与 legacy isolation 已有；live host/factory 尚未激活 |
| B1 scope model | **PASS_DETERMINISTIC** | runtime/page/document/frame generation + parentage |
| B2 grounded snapshot | **PASS_DETERMINISTIC** | WorldSnapshot、integrity、grounding、projection/completeness |
| B3 identity continuity | **PASS_DETERMINISTIC** | reorder/replacement/tabs/navigation/restart |
| B4 multi-sensor honesty | **PASS_DETERMINISTIC** | C28 field + identity conflict |
| B5 diff semantics | **N/A B-PERCEPTION** | diff 后续阶段 |
| B6 semantic actions | **N/A B-PERCEPTION** | mutation 未实现 |
| B7 TOCTOU/version | **N/A B-PERCEPTION** | mutation dispatch 未实现 |
| B8 retry/atomicity | **PASS_PERCEPTION_ONLY** | auto retry 继续关闭；mutation idempotency/atomicity 未验证 |
| B9 append-only receipts | **N/A B-PERCEPTION** | receipt 后续阶段 |
| B10 Predicate honesty | **N/A B-PERCEPTION** | Predicate 执行后续阶段 |
| B11 blind spots/boundaries | **PASS_PERCEPTION_SUBSET** | perception blind spots 已覆盖；action boundary events 未实现 |
| B12 authority lint | **PASS** | locator/策略/完成判断未进入 model surface |
| B13 adversarial suite | **PARTIAL** | 20/30 non-DEFERRED R3 obligations deterministic PASS |
| B14 repo qualification | **PASS** | committed implementation 全门绿 |

## 10. TDD 与验证

### RED → GREEN

第一轮先写 fixture/conformance，因 `llm_loop.browser` 不存在而 RED；实现最小 perception substrate 后 direct suite 转绿。

随后对实际生成 wire 做 frozen B-SPEC closed-schema 校验，并继续加入：

- nested scope parentage/hydration；
- stable observation content hash；
- URL identity fallback 禁止；
- exact node-cap truncation honesty；
- grounding tamper integrity。

这些 adversarial requirements 在加入时暴露缺口，修复后 direct suite 最终：

```text
44 / 44 PASS
```

### Expanded adjacency

```text
B-PERCEPTION       44
B-SPEC             21
SMC core           15
SMX perception     25
lazy schema        14
architecture       14
---------------------
total             133 / 133 PASS
```

### Static / security

```text
Ruff: PASS
py_compile: PASS
Pyright: 0 errors / 0 warnings / 0 informations
git diff --check: PASS
privacy scan: PASS
whole-tree security: 1636 files PASS
```

### Committed-state full repository gate

在 exact implementation commit `c95fd46eff948fb75e689d401f9d125049c7601e` 上：

```text
Ruff full: PASS
env-pin: 537 test files / 0 undeclared dependents
src Pyright: 0 errors / 0 warnings / 0 informations
tier0: PASS
xdist full: PASS
ci_gate exit: 0
```

## 11. 非宣称

本结果**不**证明：

- LFL runtime 已有 persistent Browser host；
- `browser_perceive` 已经进入 provider tool surface；
- 已对真实外部网站做 DOM+AX 生态 qualification；
- Browser mutation 已实现；
- SemanticDiff / Predicate / ActionReceipt 已实现；
- vision-only actionability 已资格；
- native browser chrome / OS UI 已资格。

本轮也没有：

- 调用任何 LLM / 8901；
- 启动或导航真实浏览器；
- 重启 8901 / 8903 / Feishu；
- 修改 legacy `playwright_exec` / `playwright_test`。

## 12. 下一阶段资格

最安全的下一阶段不是直接上 click/fill，而是 **B-HOST**：

> 建立 opt-in、persistent、read-only 的 current-page host/attach contract，把一个经过授权、已经存在的 Browser page 机械绑定给 `BrowserPerceiveTool`，先做真实本地离线页面 DOM+AX capture qualification；仍不提供 URL/navigation/mutation。

B-HOST 通过后，再决定先做 B-DIFF/PREDICATE 还是 mutation action/receipt。
