# Qualification — Unified Resource Governor RG-1

> Status: RG-1 resource qualification PASS
> Branch: `feature/resource-governor-rg1-learning-20260910`
> Parent: `5e6ca45` (`feat(resources): define Resource Governor RG-0 contracts`)
> Implementation commit: `70ce23e` (`feat(resources): add RG-1 lease governor`)
> Scope: process-local lease/concurrency/service-order + Learning foreground-gate migration

## 1. 结论口径

本报告只验证 RG-1 的**机械资源生命周期**，不把 Method 产出质量、后台 Reflection reasoning policy、RPM/TPM、费用、TrustDomain 或 request cancellation 混入结论。

当前阶段可声明：

- `ResourceGovernor` 可以维护显式 concurrency limit 与原子 lease；
- Learning 旧 foreground facts 已迁到 `ForegroundActivityProbe`，held foreground run lease 时不进入 provider；
- foreground release 后 Learning 只发出一次已准入 provider call；
- provider 正常返回或失败，lease 都会 finally 归零；
- 不支持 cancel 的 runtime 不发生假抢占；
- Task/SubAgent/ModelClientPool 仍未进入 Governor lease。

不能声明：

- RG-1 已限制真实 MLX/cloud provider 的总并发；当前 Learning key 是 process-local coordination fact，不是 provider capacity；
- server-default Thinking 下 Reflection 已稳定；
- Reflection 一定生成合法 Method candidate；
- RG-1 已处理 cloud rate/cost/trust/cancel。

## 2. Deterministic / unit qualification

已覆盖：

1. `max_concurrency=1` 时第二请求 `DEFERRED/CONCURRENCY_FULL`；
2. release 后后续请求可 admission；
3. unknown limit -> `REQUIRED_FACT_UNKNOWN`，不等价 unlimited；
4. multi-key 请求任一 key full 时零 partial increment；
5. overlapping blocking waiters 按 `(ServicePriority, arrival sequence)` 服务；
6. external foreground barrier 阻止 P2/P3+ background，不阻断 P0/P1 active-task class；
7. foreground 到达不删除/伪取消已开始 background lease；
8. ToolRegistry truthiness 不被当 workload activity；
9. runner / `_sync_active` / nested `*.run.lock` foreground facts 保持；
10. foreground 在 admitted/start gap 到达 -> Learning `requeued(foreground_arrived)`；
11. Learning lane full -> job 仍 queued / attempt=0；
12. unresolved resource target -> yield / attempt=0 / no guessed provider；
13. Reflection exception -> active lease/in-flight 最终归零；
14. Learning OFF -> shared Governor 存在，但无 Learning thread/lease；
15. Learning ON -> 使用 `engine.resource_governor` 同一实例；
16. SSE done + genuine next turn 不等待 post-task Reflection。

Targeted Learning/Resource/Web suite：59/59 PASS。
Broader runner/session/factory/provider adjacency suite：PASS（208 cases）。
Arch/factory/resource focused gate：57/57 PASS。
Ruff `src tests`：PASS。
Pyright：0 errors / 0 warnings / 0 informations。
`git diff --check`：PASS。
Pre-commit full `pytest tests -q -m 'not real_llm'`：100% / exit 0（153s）。

## 3. Live existing-runtime canary

### 3.1 运行环境

复用已经运行的：

```text
http://127.0.0.1:8901/v1
ornith-ai/Ornith-1.5-35B-A3B-MLX
```

没有：

- 启动第二个大模型；
- 重启 8901；
- 修改 8901 launcher/concurrency/cache 参数；
- 重启 8903；
- 写入生产 Session/Method data。

Live 数据全部在 `/private/tmp` 隔离目录，完成后可删除。

### 3.2 Arm A — server-default Thinking

先在：

```text
sessions/workspace-a/foreground.run.lock
```

持有真实 exclusive flock，再调用 Learning：

```text
_try_execute -> False
provider_calls = 0
job_state = queued
active_leases = 0
```

释放 foreground flock 后：

```text
provider_calls_total = 1
journal = admitted -> started -> failed(reflection_call_failed)
elapsed ~= 124.5s
active_leases_after = 0
in_flight_after = 0
```

此臂证明：provider failure 不泄漏 lease；不能证明 Reflection 业务成功。

### 3.3 Arm B — same runtime/model, canary request `reasoning_mode=off`

只改变该隔离 canary 请求上下文的 reasoning control，不改 server/model/config。

held flock 阶段：

```text
_try_execute -> False
provider_calls = 0
job_state = queued
active_leases = 0
```

释放后：

```text
provider_calls_total = 1
journal = admitted -> started -> none(reflection_model_not_json)
elapsed ~= 46.8s
active_leases_after = 0
in_flight_after = 0
```

此臂中的 provider transport 正常返回，Learning 取得终态；模型返回内容未满足 Reflection JSON contract，因此终态为 `none(reflection_model_not_json)`。**这不应被描述为 Method candidate/schema PASS。**

### 3.4 Live 裁决

RG-1 资源面 PASS：

- foreground held -> zero provider call；
- release -> exactly one admitted provider call；
- provider error 与 provider normal-return 两类出口都 release lease；
- 无 fake preemption；
- 8901 / 8903 未重启。

独立遗留风险：server-default Thinking 的后台 Reflection 有明显 latency / output-contract 稳定性问题。它发生在 Resource Governor 已完成 admission 之后，且两臂 lease 行为一致，因此不归因于 RG-1；应在后续 Learning execution-policy 专项处理，而不是把 reasoning policy 偷塞进 Resource Governor。

## 4. Provider-visible invariant

相对 RG-0 parent `5e6ca45` 的实际 parent/candidate 对照：

```text
Universal Prompt source
  SHA256 = 30c6e3667ca8d4f10aeb0ab0e26667b1988f19a6879379137517070e2316e3d6
  byte-identical = true

registered lazy tool surface
  tools = 62
  canonical bytes = 21730
  SHA256 = 023d23dd974f311ab67e770471767fae4aa019cf978cedb2ba171cc17ec61484
  byte-identical = true

runtime-health projected provider surface
  tools = 60
  canonical bytes = 21118
  SHA256 = 59a1e3d313e3cc51df2bce78ca0ea838238e54747fe0d1ecdbff0ddd2745df1c
  byte-identical = true
```

因此 RG-1 没有通过 prompt/tool schema 改变模型输入或工具可见性。

## 5. Foreground-first 的准确边界

RG-1 当前能证明的是：

```text
foreground active before Learning provider admission
    -> Learning does not enter provider
```

以及 generic Governor 中：

```text
P0 waiter > overlapping P3 waiter
```

但 Task provider call 尚未迁入 lease；generic LLMClient 也没有可验证 request cancel。因此如果 Background Learning 已经进入一个 `prompt-concurrency=1` 的 provider 请求，新到达的 foreground 不能被 RG-1 伪装成“已抢占”。RG-1 不做这种虚假保证。

这不是 bug concealment，而是阶段边界：Task/SubAgent provider-call lease 属于 RG-2；真正已开始请求的抢占只能在未来 adapter 明确支持 cancel/priority 后进入 RG-5。

## 6. Committed-state verification

Implementation commit `70ce23e` 基于 RG-0 parent `5e6ca45`，精确 13 files。提交前与提交后均没有把 qualification 报告混入实现树；因此下面结果来自真实 clean committed implementation state，而不是带未提交文档的 working tree。

Committed-state 结果：

```text
git status                         clean
implementation files               13
focused/adjacent + arch             PASS
Ruff src tests                      PASS
Pyright                             0 errors / 0 warnings / 0 informations
py_compile                          PASS
git show --check                    PASS
tracked-tree security               PASS (1483 files)
Universal Prompt vs 5e6ca45         byte-identical
registered provider surface         62 / 21730 bytes / identical SHA
projected provider surface          60 / 21118 bytes / identical SHA
full pytest -m not real_llm         100% / exit 0 / 151s
```

## 7. Final RG-1 ruling

RG-1 resource scope **PASS / CLOSE**：

- shared ResourceGovernor 已从 contract 进入最小 runtime；
- lease / explicit concurrency / atomic multi-key / service ordering 已可执行；
- Learning foreground gate 已行为等价迁入；
- Learning failure/terminal paths 不泄漏 lease；
- unknown resource facts 不猜；
- Task/SubAgent/provider pool 没有提前进入 RG-2；
- prompt/tool provider surface 零变化；
- 本地 live 证明 held foreground lock 时零 provider call，release 后只产生一次已准入调用且终态释放资源；
- 没有伪造 request preemption。

独立未关闭项：

1. server-default Thinking 的 background Reflection 可出现高延迟并最终 `reflection_call_failed`；
2. reasoning-off live arm transport 正常完成，但返回内容不是合法 Reflection JSON，终态为 `none(reflection_model_not_json)`；
3. 以上属于 Learning execution/output-contract 质量问题，不属于 RG-1 resource lifecycle；
4. 真实 provider concurrency、Task/SubAgent lease 属 RG-2；RPM/TPM/cost 属 RG-3；TrustDomain 属 RG-4；可验证 cancel/priority 属 RG-5。

因此后续不得引用本报告为“Method Learning 质量 PASS”或“后台 Learning 已可抢占”。
