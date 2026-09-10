# DESIGN-20260910：Resource Governor RG-3D Global Ledger Projection / Shadow Admission Facts

> 状态：**implementation candidate under qualification**
> 基线：`integration/rg3-unified-20260910@12f28f1`
> 分支：`feature/resource-governor-rg3d-ledger-projection-20260910`
> 前置：RG-3C Unified Provider-Call Settlement 已 PASS/CLOSE。
> 本阶段仍然 **不启用 cloud rate/quota/cost enforcement，不改变 provider routing/fallback/retry，不接 TrustDomain/cancel**。

## 0. 裁决

RG-3C 已经解决：

```text
一个 logical provider call
    -> 每一次真实 physical transport send
    -> retry / ERR1210 / fallback lineage
    -> durable EventStore settlement
    -> known usage sum + per-call completeness
```

但这仍不足以做账号级/项目级/模型级的 rate、quota、cost 判断。

原因是：

> **一个 call 的账完整，不等于一个 account/window 的账完整。**

RG-3D 因此只增加一层**可重建的跨 Session 派生投影**，并冻结未来 admission 计算需要的机械事实：

1. exact resource scope binding；
2. exact half-open accounting window；
3. fact validity / freshness / version；
4. cross-session settlement projection；
5. explicit LFL source-set coverage；
6. provider/account global coverage；
7. shadow-only admission facts + fact gaps。

它不产生 `admit / defer / reject`，不消费任务语义，也不拥有 provider 选择权。

---

## 1. 为什么不能直接把 `snapshot_call()` 升级成账号账本

RG-3C `ProviderCallSettlementJournal.snapshot_call()` 的证明范围只有一个 logical call：

```text
call_id
attempts_opened
attempts_settled
attempts_complete
known_usage_sum
usage_complete[field]
```

这个对象不知道：

- 另一个 Session 是否也调用了同一账号；
- SubAgent / Learning / Summarizer / MemoryExtractor 是否在同一资源 scope 消耗；
- 同一 provider 是否绑定多个 account/project/product；
- 一个时间窗口之前是否遗漏历史事件；
- LFL 之外是否存在其他客户端消耗同一 provider account；
- provider control-plane 是否给出更权威的全账号 usage；
- pricing/quota/rate fact 是否仍在有效期内。

因此禁止：

```text
call_complete == true
    => account_window_complete == true       # 禁止
```

也禁止：

```text
sum(all local settled calls)
    => provider billing truth                 # 禁止
```

RG-3D 的核心目标不是“多加一个 sum”，而是把**证明范围**本身显式化。

---

## 2. Source of Truth：EventStore 不变，SQLite 只是 projection

RG-3D 新增：

```text
ProviderSettlementProjectionIndex
```

默认路径：

```text
data/audit/resource_governor/provider_settlement_projection.sqlite3
```

其性质：

- **derived / rebuildable**；
- 可以删除后从 EventStore 重建；
- 不替代 EventStore；
- 不拥有新的 provider truth；
- sink 失败不能影响 provider call、RG-3C EventStore 落盘或用户回答；
- 不在进程启动时扫描全部历史 Session。

生产数据流：

```text
provider call
   |
   v
RG-3C EventStore settlement  <---- durable SoT
   |
   +---- fail-open projection sink
             |
             v
      SQLite cross-session projection
```

如果 SQLite 写失败：

```text
provider call behavior  unchanged
EventStore truth         unchanged
RG-3C snapshot           unchanged
projection               may lag / rebuild later
```

---

## 3. 为什么必须索引四类事件，而不是只索引成功 usage

RG-3D 索引全部四类 RG-3C durable event：

```text
provider.call.opened
provider.call.settled
provider.transport.opened
provider.transport.settled
```

### 3.1 `call.opened`

保留：

- call_id；
- session_id；
- owner_ref；
- ExecutionClass；
- service priority；
- purpose；
- created_at。

用于跨 Session 仍能按 Task / SubAgent / Learning / Summarizer / MemoryExtractor 分账。

### 3.2 `transport.opened`

它证明：

> 一次 physical send 已经开始。

如果只有 opened 没有 settled，不能把它从账中消失；必须保留 unknown exposure。

### 3.3 `transport.settled`

保留：

- actual provider/model；
- physical lineage；
- nullable typed usage；
- safe HTTP/provider code；
- normalized Retry-After/rate-reset facts；
- terminal outcome。

### 3.4 `call.settled`

保留 logical call 最终机械 outcome。

---

## 4. Attempt completeness：opened 与 settled 必须分别证明

SQLite 中出现一个 attempt row，不等于 `transport.opened` 一定存在。

例如重建/损坏/乱序情况下可能先读到：

```text
provider.transport.settled
```

而暂时没有：

```text
provider.transport.opened
```

RG-3D 必须分别计数：

```text
attempts_opened
attempts_settled
```

只有所有 row 都同时有 open fact + settle fact：

```text
attempts_complete = true
```

settled-only orphan 的 token 值仍可以作为：

```text
known lower bound
```

但：

```text
attempts_complete = false
usage_complete[field] = false
```

后续补齐 open event 后才允许变成 complete。

---

## 5. Scope Binding：不得从 URL/provider 名猜账号

新增：

```text
ProviderResourceBinding {
  provider_id
  model_id
  resource_keys[]
  product?
  provenance
  validity
}
```

其中 `resource_keys[]` 继续复用 RG-0/RG-3A：

```text
ResourceKey(provider_id, scope_kind, scope_id)
```

scope_kind 可以是：

```text
provider
account
project
model
runtime
```

关键规则：

- provider/model 与 ResourceKey 的绑定必须是**显式机械事实**；
- 不从 base URL 猜 account/product/project；
- 不从 API key 内容派生账号身份；
- 不从 provider 名猜套餐；
- 不因为两个模型同 provider 就自动判定共享 quota；
- product/account/project/region 仍等待 authoritative adapter 提供。

RG-3D 当前不把这些资源身份塞进 `ProviderSpec/ModelSpec`，避免让 routing registry 同时承担 billing/resource authority。

---

## 6. Exact Accounting Window

新增：

```text
AccountingWindow {
  window_ref
  start_at
  end_at
}
```

语义严格为：

```text
[start_at, end_at)
```

即：

- `started_at == start_at`：属于窗口；
- `started_at == end_at`：不属于窗口。

RG-3D generic projection 不猜：

- “一分钟”是否自然分钟还是 rolling 60s；
- provider 的日额度按 UTC、地区时区还是订阅周期；
- reset header 的裸数字单位；
- billing cycle 的边界。

这些必须由后续 authoritative provider/product adapter 给出明确 window fact。

---

## 7. Fact Validity / Freshness / Version

新增：

```text
FactValidityKind:
  immutable_event
  open_ended
  bounded
  unknown

FactValidity {
  kind
  valid_from?
  valid_until?
  version_ref?
}
```

并机械投影：

```text
current
expired
not_yet_valid
unknown
```

### 7.1 为什么必须有 validity

例如：

- 昨天抓取的 quota snapshot；
- 上个计费周期的 pricing；
- 已经过 reset_at 的 rate remaining；
- operator 后来切换的 account/product mapping；

都不能因为“曾经是真的”就在未来永久有效。

### 7.2 unknown 不是无限有效

```text
validity = unknown
```

只能得到：

```text
freshness = unknown
```

不得解释成：

```text
never expires
```

---

## 8. Coverage 必须分两层

新增：

```text
ProjectionCoverage {
  source_set
  source_scope_ref
  source_watermark_ref
  source_watermarks[]    # session_id / last_seq / event_count / skipped_lines
  source_session_count
  source_event_count
  skipped_event_lines

  provider_global
  provider_global_provenance?
  provider_global_validity?
}
```

### 8.1 Layer A — explicit LFL source-set coverage

例如显式 reconcile：

```text
session A
session B
session C
```

如果这三个 EventStore 文件全部可读且无损坏行：

```text
source_set = complete
source_watermark_ref = exact digest(session_id,last_seq,event_count,skipped_lines)
```

它只证明：

> “我指定的这组三个 LFL Session **截至所捕获的 EventStore high-watermark** 已完整扫描。”

它不证明 watermark 之后不会追加新事件，不证明还有没有 Session D，也不证明 LFL 之外没有调用。
因此未来 admission qualification 若需要“当前覆盖”，必须重新核对/刷新 watermark；不得把一次历史 reconcile 的 complete 当成永久 current。

如果存在损坏行：

```text
source_set = partial
```

### 8.2 Layer B — provider/account global coverage

默认：

```text
provider_global = unknown
```

即使：

```text
source_set = complete
```

也绝不能自动升级。

如果未来 adapter 要声明：

```text
provider_global = complete | partial
```

必须同时带：

```text
provider_global_provenance
provider_global_validity/version
```

缺任何一个都拒绝构造 known global coverage。

若 global coverage 的 authoritative proof 已过期，则 shadow facts 显式产生：

```text
provider_global_coverage_not_current
```

---

## 9. Cross-Session / Cross-Plane 聚合

RG-3D 可以跨 Session 汇总同一 explicit binding：

```text
Task
SubAgent
Learning
Summarizer
MemoryExtractor
```

并保留：

```text
execution_class_counts
purpose_counts
```

这只是机械 attribution，不代表语义价值或优先级判断。

例如：

```text
foreground_task = 7 attempts
subagent        = 3 attempts
background      = 2 attempts
```

程序只记录“发生了什么”，不判断哪类调用“更值得花钱”。

---

## 10. Cross-Provider fallback 必须按 actual transport target 记账

一个 logical call 可以是：

```text
primary  -> provider A / model X
retry    -> provider A / model X
fallback -> provider B / model Y
```

RG-3D 聚合不能把整个 call 全部记到 primary provider。

每个 physical attempt 按 RG-3C 已冻结的：

```text
attempt.provider_id
attempt.model_id
```

进入各自 binding/window。

因此：

```text
provider A aggregate != provider B aggregate
```

但它们仍可通过 call_id / parent_attempt_id 看出属于同一 logical topology。

---

## 11. Usage：known sum 与 complete total 继续分离

RG-3D 继承 RG-3C nullable usage 原则：

```text
None = provider 未报告 / unknown
0    = provider 明确报告 0
```

对每个 token field：

```text
known_usage_sum[field]
usage_complete[field]
```

例如：

```text
attempt 1 total_tokens = 34
attempt 2 total_tokens = unknown
```

则：

```text
known_usage_sum.total_tokens = 34
usage_complete.total_tokens = false
```

34 是 lower bound，不是完整总量。

---

## 12. Generic projection 不发明 provider request quota

一次 physical HTTP send 是 LFL 已观察到的机械事实。

它**不自动等价于**：

```text
provider RPM consumed += 1
quota requests used += 1
billable request += 1
```

不同 provider/product 对：

- 连接失败；
- TLS/HTTP 前断开；
- 429；
- 5xx；
- provider-side retry；
- streaming 中断；

是否计入 request quota/rate/billing，可能不同。

因此 RG-3D generic aggregate 当前只汇总 provider 明确报告或 RG-3C 已保存的 token/provider-unit facts；**不制造 `requests_consumed`**。

request-rate/quota 的 authoritative mapping 留给后续 provider adapter。

---

## 13. Shadow Admission Facts

新增只读对象：

```text
ShadowAdmissionFacts {
  requirement
  binding_freshness
  coverage
  aggregate?
  gaps[]
}
```

可能的 gap：

```text
scope_unbound
binding_not_current
source_set_coverage_partial
source_set_coverage_unknown
provider_global_coverage_partial
provider_global_coverage_unknown
provider_global_coverage_not_current
attempts_incomplete
usage_incomplete
```

关键是：**对象里没有**：

```text
admit
reject
defer
should_run
route_to
fallback_to
```

RG-3D 只把机械事实与缺口摆出来。

---

## 14. Authority Boundary

### RG-3D 程序可以

- 把 RG-3C durable event 投影进可重建 SQLite；
- 基于 exact provider/model + explicit binding 做 scope query；
- 基于 exact `[start,end)` 做时间窗口过滤；
- 累加已知 token/provider-unit lower bound；
- 判断 open/settle event 是否齐全；
- 判断 explicit source-set 是否存在损坏行；
- 校验 binding/provider identity；
- 校验 validity/freshness/version；
- 暴露 fact gaps；
- 发现 projection identity conflict 时拒绝覆盖原事实。

### RG-3D 程序不可以

- 根据任务价值、复杂度、内容决定是否值得调用；
- 选择 provider/model；
- 修改 fallback/retry；
- 从 URL/key/provider 名猜 account/product/project；
- 把 source-set complete 当 provider-global complete；
- 把 unknown usage 当 0；
- 把 physical send 自动解释成 provider request quota 消耗；
- 从 pricing 文档自行推断当前 bill；
- 因 shadow fact 阻断/延迟 provider call；
- 接 TrustDomain 或 cancellation policy。

---

## 15. Startup / Recovery

### 15.1 正常启动

Factory 只构造 index handle：

```text
ProviderSettlementProjectionIndex(path)
```

不做：

```text
scan all sessions
read 100MB+ historical event logs
rebuild every startup
```

因此仅 build_engine 不会创建 SQLite 文件。

### 15.2 Live event

新的 RG-3C settlement event 成功落 EventStore 后，Journal 才 best-effort 投影。

### 15.3 历史回填

必须显式调用：

```text
reconcile_event_store(event_store, explicit_session_ids)
```

调用方必须知道自己扫描的是哪个 source set；返回：

```text
source_scope_ref
source_watermark_ref
source_watermarks (session_id / last_seq / event_count / skipped_lines)
source_session_count
source_event_count
skipped_event_lines
coverage
inserted / duplicate / conflict / ignored
```

### 15.4 Rebuild

SQLite 可以删除后重建；重建不会改变 EventStore。

---

## 16. Idempotency / Conflict

同一个 EventStore event 重投影：

```text
duplicate
```

不得重复计账。

同一个：

```text
call_id / attempt_id
```

若出现不同 provider/model/topology identity：

```text
conflict
```

不得以“最新值”覆盖原事实。

这与 LFL 的 durable fact 原则一致：

> 机械 identity 冲突是完整性问题，不是让程序挑一个看起来更合理的版本。

---

## 17. Privacy / Security

SQLite schema 禁止保存：

```text
prompt
messages
raw response body
raw headers
Authorization
Cookie
API key
tool arguments
task text
hidden reasoning
```

允许保存的都是 RG-3C/RG-3B 已归一化机械字段：

```text
ids / lineage
provider/model
execution class / purpose
timestamps
nullable usage
HTTP status
short provider code
normalized retry/reset facts
```

---

## 18. Performance

实现候选本地 microbenchmark（不触网、不跑模型）：

```text
20 logical calls:
  RG-3C baseline          ~0.554 ms/call
  + RG-3D projection      ~1.397 ms/call
  incremental             ~0.843 ms/call

100 logical calls:
  RG-3C baseline          ~0.471 ms/call
  + RG-3D projection      ~1.391 ms/call
  incremental             ~0.921 ms/call
```

每 logical call 包含四个 durable settlement event。

当前约 1ms/call 的增量不足以证明需要再引入一个后台 queue + durable consumer 状态机；RG-3D 先维持简单同步 fail-open projection。

但这只是 microbenchmark，不等于 production qualification；后续真实 canary 仍需检查 foreground latency 没有物质变化。

---

## 19. Qualification Matrix

RG-3D close 前必须证明：

1. exact half-open window `[start,end)`；
2. validity current/expired/not-yet/unknown 区分；
3. explicit binding provider identity 一致；
4. 无 URL/provider-name/account 猜测；
5. projection sink fail-open；
6. EventStore 仍是唯一 durable SoT；
7. SQLite 可从 EventStore 重建；
8. 重复 reconcile 不重复计账；
9. identity conflict 不覆盖；
10. call open/settle + transport open/settle 四事件均投影；
11. opened/unsettled 保留 unknown exposure；
12. settled-only orphan 不伪装 attempt complete；
13. cross-session Task/SubAgent/... 可统一汇总；
14. cross-provider fallback 按 actual transport target 分账；
15. nullable usage known sum / completeness 分离；
16. explicit source-set complete 不蕴含 provider-global complete；
17. provider-global known state 必须有 provenance + validity；
18. stale provider-global proof 显式报 not-current gap；
19. corrupt EventStore line 令 source coverage 降为 partial；
20. known source-set coverage 必须绑定 exact per-session EventStore high-watermark；
21. generic projection 不制造 request quota/RPM 消耗；
22. ShadowAdmissionFacts 无 decision/admission 字段；
23. Governor/provider_calls/fallback 不 import/消费 projection；
24. SQLite 不保存敏感 payload；
25. Factory 不做 startup historical full scan；
26. prompt/tool surface 与 RG-3C parent exact identity；
27. Ruff/Pyright/py_compile/diff-check/security/arch PASS；
28. full non-real-LLM 100%/exit 0；
29. 如做真实 canary，只验证 projection 与 EventStore 同构；**scope 未绑定时必须如实输出 unbound/unknown，不能从当前凭据或 URL 猜账号**。

---

## 20. 阶段顺序更新

RG-3A 文档里的早期路线曾把“Vendor Fact Adapters”称作 RG-3D。随着 RG-3B/RG-3C 的真实 transport/settlement 实验完成，现在发现中间还缺一层跨 Session ledger projection 与 coverage contract。

因此从当前统一架构 SoT 起，阶段名顺延为：

```text
RG-3A  Cloud Facts Contract                 PASS/CLOSE
RG-3B  Transport Observation / Shadow       PASS/CLOSE
RG-3C  Unified Provider-Call Settlement     PASS/CLOSE
RG-3D  Global Ledger Projection / Shadow    current
RG-3E  Authoritative Vendor/Product Adapters
RG-3F  Shadow Admission Qualification
RG-3G  Limited Enforcement (only after qualification)
```

历史 RG-3A/RG-3B qualification 文档不回写改名，以保留当时的审计语境；总架构与后续新文档以此顺序为准。

TrustDomain 与 provider cancellation/preemption 继续独立阶段处理，不因编号顺延而混入 RG-3E/F/G。

---

## 21. 下一阶段入口：RG-3E

只有 RG-3D 资格化后，RG-3E 才处理 authoritative vendor/product fact adapters，例如：

```text
explicit provider product/account/project identity
rate/quota reset semantics
provider request accounting semantics
control-plane usage snapshots
pricing schedule versions
billing-cycle/window identity
```

adapter 的职责只是：

> authoritative external/provider fact → unified typed contract

它不拥有：

```text
model selection
semantic task value
fallback policy
method applicability
completion judgment
```

即使 RG-3E 完成，下一步仍应先做 **shadow admission qualification**，不能直接开启 cloud enforcement。
