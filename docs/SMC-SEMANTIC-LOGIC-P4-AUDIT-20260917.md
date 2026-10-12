# SMC Semantic Logic P4 — Semantic Compiler A/B 只读审计与协议裁决

日期：2026-09-17
状态：**AUDIT COMPLETE / PROTOCOL FROZEN ONLY**
P3 exact base：`918471bff244eb8406a63eba69cbda1768307855`

## 1. 本阶段做什么、不做什么

P4 的冻结目标不是把 Semantic Logic 接进 production authority，而是验证一个更窄的问题：

> 当模型已经做出语义选择之后，把它没有必要手工维护的机械字段从 provider-facing 参数面移走，是否能提高 First-Call-Ready，同时保持现有 Browser 安全/版本/单次 dispatch 语义完全不变？

本阶段只冻结 A/B 设计。**不实现 P4 Compiler、不加 production consumer、不改 Factory/registry、不跑正式模型 A/B、不部署、不重启 Web/Feishu/8901。**

P3 已经证明当前 Browser Python oracle 与 Semantic Logic shadow 在 14 个同 observation case 上等价；P4 不能把这个“shadow 等价”偷换成生产控制权。

## 2. P3 远端证据锚点

P3 最终本地/结果 HEAD：

```text
918471bff244eb8406a63eba69cbda1768307855
```

已用 ordinary non-force push 保存到正式 `lfl` remote：

```text
review/smc-semantic-logic-p3-20260917
```

push 前该 ref 不存在；push 后独立 `git ls-remote` 核验：

```text
refs/heads/review/smc-semantic-logic-p3-20260917
  = 918471bff244eb8406a63eba69cbda1768307855

refs/heads/main
  = ddd108a2e05897cf4d72cd920e1d7c00a5786a7e
```

因此 P3 evidence anchor 已远端冻结，formal main 没有被改动。

## 3. 当前生产语义面实际是什么

当前 Browser opt-in 路径在 perception 启用时注册：

```text
browser_perceive(snapshot|hydrate|diff)
5 个 narrow typed wait
```

mutation 另有独立 opt-in；开启时还会注册：

```text
browser_action                  # legacy/full mechanical surface
browser_semantic_execute        # atomic semantic compiler surface
browser_semantic_operation      # bounded high-level clause surface
```

P4 A/B **不会**把这三者一起给模型。否则“工具选择变化”和“参数面变化”会混为一个实验变量。

P4 两臂共同固定：

```text
browser_perceive
browser_wait_scope_url
browser_wait_scope_ready
browser_wait_scope_count
browser_wait_object_state
browser_wait_object_text
get_tool_schema
```

`browser_action`、`browser_semantic_operation`、generic wait、Playwright 均不进入任一正式 arm。

## 4. 当前 `browser_semantic_execute` 已经证明了正确的权力划分

当前 atomic surface 要模型提交：

```text
verb
target_ref
args
```

之后程序 exact hydrate 模型已经选择的 ref，并机械派生：

```text
schema
domain
scope_ref
target_id
action_id
operation_class
idempotency_class
atomicity_class
expected_version
version_scope
version_precondition
```

这部分是 P4 应保留的 LLM-First 边界，不需要推倒重来。

### 模型继续拥有

- 选哪个对象/页面；
- click/fill/select/scroll/navigate 哪个 verb；
- 文本、select value、URL、scroll delta 等业务参数；
- 等什么条件；
- 是否需要 re-observe；
- receipt 是否意味着用户目标已经完成。

### Compiler 可以拥有

- exact ref → object/resource、scope、version；
- fixed schema/domain；
- object/resource 对应的 `version_scope`；
- fixed operation/idempotency/atomicity/version-precondition facts；
- exact declared semantic request → deterministic `action_id`；
- typed tool identity → canonical verb/args container。

### Runtime / Adapter 继续独占

- session fencing；
- action reservation / duplicate fencing；
- physical target locator；
- DOM/CDP mutation；
- retry permission；
- post-dispatch capture；
- durable ActionReceipt append/fsync/status。

## 5. 为什么 P4 不继续做更大的 high-level DSL

已有证据不支持。

### Typed wait 的经验

typed wait 把 Predicate 中纯机械的 schema/domain/target/scope 关系拿走后，A2 的 typed-wait contract failure 降到了 **0**。这证明“移除冗余机械字段”有效。

但 A2 总任务仍只有 **2/6**，剩余失败集中到了 navigation ref、semantic args 和有限轮次内的连续操作组织。说明问题不是“再给模型更多 Predicate 字段”。

### Bounded Semantic Operation 的经验

FC2-B 的大 clause grammar 第一调用 **6/6 失败**；模型先发出了 contract 中不存在的 `kind=browser/page/action` 等概念，再依赖 schema hydration 恢复。它还一度因为 contract kind enum 没有 canonical `input` 而无法表达真实 `Project code` 对象。

FC2-C v0.2 证明窄的 required-field guidance 能把 declaration FCR 修到 6/6，但这只证明 schema 可见性，不证明“大 DSL”优于更小的 typed surface。

因此 P4 不把 `browser_semantic_operation` 作为 treatment。

## 6. 当前真实出现过的错误，P4 如何处理

| 错误类 | 现状 | P4 处理 |
|---|---|---|
| navigate 首调把 URL/其他值塞进 `target_ref` | v0.4 treatment 3/3 都出现过 | B 将导航输入名固定为 `resource_ref` |
| object GroundingRef / resource_ref 混用 | unified `target_ref` 天然存在歧义 | B 分开 object/ref 与 resource/ref 工具 |
| `grounding_ref` 错塞 `browser_perceive(snapshot)` | A2 真实出现 | shared negative control；两臂 perception 完全相同，不为此偷偷 auto-correct |
| scope predicate target mismatch | 历史真实出现，typed wait 已处理 | 两臂都必须保持 0；不是 P4 treatment 变量 |
| `version_scope` 猜错 | full action 旧面要求模型维护 | A/B 都不得让模型提交；Compiler 从 exact ref kind 派生 |
| navigate/object args 交叉 / args mismatch | A2/历史 receipt 中出现 | B 用 typed action tool identity 固定 verb，业务 args 展开为直接字段 |
| canonical kind 无法表达真实对象 | FC2-B 的 `input/textbox` mismatch | B 不让模型重述 identity kind；只消费 observation 的 exact object_ref |
| progressive schema reread | FC2-B 7 schema calls / 27 Evidence reads | 作为核心 KPI，不用更长 universal prompt 处理 |

## 7. A/B 裁决

### A — current atomic surface

```text
browser_semantic_execute(
  verb,
  target_ref,
  args
)
```

其底层仍是当前 `BrowserSemanticExecuteTool.compile_request -> BrowserActionAdapter.execute`。

### B — typed minimal semantic surface + compiler

```text
browser_semantic_click(object_ref)
browser_semantic_fill(object_ref, text, mode)
browser_semantic_select(object_ref, value)
browser_semantic_scroll(object_ref, delta_pages)
browser_semantic_navigate(resource_ref, url)
```

模型通过“选哪个 tool”表达 verb；Compiler 不替模型选择 verb。

B 的实验实现只能位于 P4 isolated harness。它把 typed call 机械翻译成与 A 相同的 canonical semantic request，并最终走**同一个现有 BrowserActionAdapter**。因此正式 P4 只改变 provider-facing declaration surface，不改变 dispatch、安全、版本或 receipt 实现。

这也意味着：如果 B 表现更好，不能把收益归因于“换了执行器”；执行器没有换。

## 8. 为什么不先选“两工具：navigate + object_execute”

历史 v0.6-B 曾提出：

```text
browser_navigate(resource_ref,url)
browser_object_execute(object_ref,verb,args)
```

它能消除 resource/object ref 混用，但仍让模型同时维护 `verb + args` 条件关系。A2 已经观察到 `args_contract_mismatch`。P4 的目标既然是检验“移除不必要的机械 cross-binding”，就应该把这个变量一次冻结清楚：typed tool identity 表示 verb，直接参数表示语义值。

代价是 B 的 tool count 比 A 多 4。这个成本**不能提前假定无害**，所以 provider surface tool count/schema chars 是正式 A/B 指标。如果 tool-selection 成本抵消了参数简化收益，Gate 应如实 HOLD。

## 9. 三层资格顺序

### P4-D — deterministic compiler equivalence

不调用模型，不执行 Browser physical mutation。

必须证明：

- click/fill/select/scroll/navigate 五类正例与 A 的 canonical SemanticAction authority fields 一致；
- wrong-kind / expired / unauthorized / cross-session ref fail closed；
- compile rejection 时 physical dispatch=0；
- 同一 exact declaration 的 action_id deterministic。

未 100% PASS 不得进入模型 A/B。

### P4-FCR — declaration-only A/B

五类语义动作：navigate/click/fill/select/scroll，每类每 arm 4 repeats，共 **40 rows**。

模型只能形成第一 semantic call；Browser tool **不执行**。因此不会把恢复能力、网页速度、wait sensor 或物理 side effect 混进 First-Call-Ready。

B hard gate：

```text
20/20 first call structurally valid
20/20 mechanically valid
target/resource/args/identity targeted cross-binding = 0
tool execution = 0
```

### P4-LIVE — full-task paired A/B

连续性任务：

```text
click_commit
fill_submit
delayed_wait
```

另加 3 个**此前设计过程未使用、在实现前冻结**的 task families：

```text
select_choice_confirm
scroll_reveal_activate
stale_ref_reobserve
```

每 task 每 arm 2 repeats，共 **24 rows**；repeat1 A→B，repeat2 B→A。

旧 3-task fixture 用于历史连续性，不单独承担 promotion 结论。新 3 项用于限制对旧失败轨迹的过拟合。

## 10. 正式运行契约

P4 v0.1 首轮只用现有唯一 Ornith：

```text
model=cognilocal/ornith-1.5-35b-a3b-mlx
Thinking=ON
temperature=0
input=184000
output=16000
max_iterations=12
prompt_concurrency=1
decode_concurrency=1
fresh session/data/Browser profile per row
strict serial
no fallback
no second local model
```

Cloud provider 不属于 v0.1 Gate。只有本地 protocol 独立收口后，才能另开 protocol identity。

## 11. KPI 与 Gate

Primary：

```text
first semantic call structural validity
first semantic call mechanical validity
cross-binding error
tool failure
schema reread
external task result
```

Secondary：

```text
rounds
input/output/cache-hit tokens
wall time
provider surface schema chars
provider tool count
```

Safety：

```text
physical dispatch count
automatic retry = 0
silent rebind = 0
stale-ref dispatch = 0
task-completion authority violation = 0
```

正式 promotion 不允许只看“B 成功多少题”。至少要求：

1. B targeted cross-binding = 0；
2. B overall task pass 不低于 A；
3. 任一 held-out task family 不得 B<A；
4. mechanical error 或 schema reread 至少一项严格优于 A；
5. 如果 A 在这两项已经都是 0，则 B 必须 task parity，且 provider surface schema chars 至少下降 10%，同时 tool failures 不增加；
6. timeout 记 task failure/right-censored，不得看到结果后改称 infra invalid；
7. external page-state oracle 决定 task result，receipt `ok` 不等于 task success。

## 12. 当前停止边界

本轮只允许：

- 远端保存 P3 exact evidence branch；
- 只读 P4 audit；
- 冻结本 MD + machine JSON protocol；
- JSON/hash/diff/security 等机械校验；
- docs-only 本地 commit。

本轮明确不做：

- P4 compiler implementation；
- P4 RED/harness；
- 正式模型 A/B；
- production Semantic Logic consumer；
- Factory/registry production wiring；
- P4 remote push；
- merge main；
- deployment / Web / Feishu / 8901 restart；
- model switch/start。

下一边界是：**protocol-only committed anchor 完成后停下，由 owner 单独授权 P4-D RED/implementation。** P5 仍然是第一个 selective production authority 阶段。
