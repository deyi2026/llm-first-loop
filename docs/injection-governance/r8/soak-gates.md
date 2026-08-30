# R8.3 Shadow Soak Gates

日期：2026-08-30

R8.3 只验证 **shadow attribution / metadata stability**，不改变 prompt，不把任何 profile 真正应用到 build。`mode=shadow`、`applied=false` 是硬约束。

## 进入条件

- active provider inventory 的 capability metadata 必须 100% complete；
- `unknown=0`；
- registry 不 degraded；
- R8 capability-only 对照仍证明推荐值变化不会改变 provider `messages+tools`。

## Live primary 硬门

在 mirror 的真实 provider 路径上至少同时覆盖一个 strong 和一个 weak 模型，并包含一个长历史 case：

```text
metadata_complete_coverage = 100%
unknown = 0
mode=shadow = 100%
applied=false = 100%
profile recommendation matches ModelSpec = 100%
profile churn = 0
unattributed primary provider attempt = 0
unexpected non-primary live attempt = 0
```

R8.3 的 live prompt 仅用于验证 attribution；模型是否逐字复读诊断 marker **不是 shadow soak gate**。因为 `applied=false`，回答质量在本阶段没有 R8 treatment/control 因果差异；行为质量留到后续 behavior canary。

## Fallback / 1210 路径硬门

不为了制造错误去污染 live provider。复用 production engine 的 deterministic E2E：

- primary + 每个真实 fallback provider call 都必须逐 attempt 产生精确 `injection.profile.shadow`；
- 1210 blind/strip retry 必须产生 `err1210_retry` 独立 attempt；
- resolve failure 不冒充 provider call；
- 上述事件全部 `mode=shadow, applied=false`。

## 结构正交门

R8.3 不得改变 R2/R4/R5/R6 既有结构不变量：

- R2 budget 仍是统一最终注入预算；
- R4 recovery 仍 one-shot、不持久化为 executable conversation history；
- R5 identity summary 仍只改派生摘要、不破坏 raw history；
- R6 exact user truth 仍 provider wire 最后一个 user envelope；
- R0 frozen evidence 必须 0-byte diff。

## 判定

全部硬门 PASS 才允许讨论 behavior canary。R8.3 PASS **不等于** behavior canary 已启用，更不等于 R9 已批准。
