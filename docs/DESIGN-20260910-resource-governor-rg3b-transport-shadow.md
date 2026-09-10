# Resource Governor RG-3B — Transport Observation / Shadow

> 状态：implementation candidate
> 基线：`feature/resource-governor-rg3b-transport-shadow-20260910`，父提交 `8c88218`
> 前置：RG-3A Cloud Fact Contract 已资格化；本阶段仍不启用 cloud admission/enforcement。

## 1. 目标

RG-3B 只解决一个问题：让 LFL 在**真实 provider transport 边界**看见可验证的机械资源事实，同时保持现有 Task / SubAgent / Learning / fallback 行为不变。

当前重点 provider 为 GLM、MiniMax、DeepSeek。仓库当前三者均走 OpenAI-compatible transport，因此本阶段首先在该 wire path 捕获：

- HTTP status；
- provider 报告的 nullable input/output/total/cache/reasoning token usage；
- 标准 `Retry-After`；
- 语义明确、可安全归一化的 rate-limit limit / remaining / reset facts；
- HTTP error 与 HTTP 200 + SSE error 中的**结构化 provider code**。

这些 observation 只用于 shadow 资格与后续 RG-3C settlement 输入准备，**绝不参与本阶段的 admission、routing、fallback、retry、cost 或 quota 决策**。

## 2. LLM-First 权力边界

RG-3B 可以：

1. 读取 provider 已返回的 transport/usage 事实；
2. 做机械类型归一化；
3. 把 raw response 中的安全子集转成 closed typed facts；
4. 在进程内 bounded recorder 中暂存最近 observation；
5. 对无法证明含义的字段保持 unknown。

RG-3B 不可以：

- 判断任务重要性、质量、复杂度、完成度；
- 决定选哪个模型/provider；
- 因观察到 rate/quota/cost fact 而阻断、延迟或降级请求；
- 修改 fallback 顺序或 retry 语义；
- 估算 provider 没有报告的 token/额度；
- 根据 provider 名称、URL 或错误文本猜 product/account/rate-limit 语义；
- 接入 TrustDomain 或 cancellation/preemption。

## 3. 数据流

```text
already-selected provider call
        |
        v
LLMClient transport
        |
        +--> existing response/error behavior --------> caller
        |
        +--> fail-open shadow observer
                 |
                 +--> ProviderResponseFacts
                 +--> ProviderUsageFacts
                 +--> ProviderErrorFacts
                           |
                           v
                 bounded process-local recorder
```

Shadow observer 是旁路。observer 抛出任何异常时，原 provider 调用的成功/失败结果必须保持不变。

## 4. 共享观察面

Factory 创建一个 `ShadowTransportRecorder`，同时传给：

- default `LLMClient`；
- `ModelClientPool`；
- Pool 后续构造的所有 routed `LLMClient`。

因此使用这些客户端的 Task、SubAgent、Learning Reflection、MemoryExtractor、Summarizer 等执行面可以共享同一个 transport observation 面，而不需要各自实现第二套 usage/error 采集逻辑。

RG-3B **不要求**这些业务平面改代码消费 observation。

## 5. nullable usage：`None` 与 `0` 必须分开

旧 `LLMResponse` 为兼容历史调用方，仍以 `0` 作为“未提供/零值”的混合表示。本阶段不改该公开兼容合同。

RG-3B 必须在 raw provider usage mapping 进入旧 accumulator **之前**捕获：

```text
字段不存在 / 非法 -> None
provider 明确报告 0 -> 0
provider 明确报告正数 -> exact value
```

只有至少一个有效 typed usage value 时才产生 `ProviderUsageFacts`；全 unknown mapping 不制造空事实。

当前 OpenAI-compatible 映射：

- `prompt_tokens` -> `input_tokens`
- `completion_tokens` -> `output_tokens`
- `total_tokens` -> `total_tokens`
- `prompt_cache_hit_tokens` / `cached_tokens` / `prompt_tokens_details.cached_tokens` -> `cached_input_tokens`
- `completion_tokens_details.reasoning_tokens` -> `reasoning_tokens`

多 usage chunk 在 RG-3B 中仍是**多条 observation**，不是 provider-call settlement。去重、最终值选择、跨 retry/fallback call identity 归并属于 RG-3C。

## 6. Header 安全与 reset 真实性

Raw headers 从不进入 typed fact 或 recorder。RG-3B 只即时读取白名单机械字段。

### 6.1 `Retry-After`

标准 HTTP `Retry-After` 支持：

- delta-seconds；
- HTTP-date，经 observation clock 转为 non-negative seconds。

只保存归一化后的 `retry_after_seconds`。

### 6.2 rate-limit reset

RG-3B 只通用解析名称中资源指标明确的 header family：

- `x-ratelimit-*-requests` -> `REQUESTS`
- `x-ratelimit-*-tokens` -> `TOTAL_TOKENS`

对 reset 值：

- `250ms` / `1s` / `2m` / `1h` 等带明确单位的 duration 可归一化；
- **裸数字不解释**。不同 provider 的裸数字可能代表 seconds-from-now、epoch 或私有单位；RG-3B 保持 unknown，等待 RG-3D vendor adapter 基于已验证 provider contract 解释。

通用 `RateLimit-*`、未知 vendor-private header 也不在 RG-3B 猜语义。

## 7. Error 安全

`ProviderErrorFacts` 只能保存：

- provider/model identity；
- HTTP status（若存在）；
- 结构化 provider code（若存在）；
- typed retry/rate reset facts；
- provenance。

禁止保存：

- raw response body；
- raw headers；
- error message/diagnostic 文本；
- prompt/messages；
- API key/Authorization/Cookie；
- tool arguments 或 task text。

Provider code 仅接受结构化 `error.code` 或 top-level `code`，且必须是短、code-like scalar。`{"error":"private diagnostic"}` 不能被重新解释为 code。

HTTP 200 + SSE error 要保留两个事实层：

```text
http_status = 200
provider_code = provider SSE code (if explicitly present)
```

不能用 provider code 覆盖 HTTP status。旧 `LLMHTTPError` 的历史兼容行为本阶段不改。

## 8. Recorder 生命周期

`ShadowTransportRecorder`：

- process-local；
- thread-safe；
- 默认最多 2048 条；
- FIFO bounded eviction；
- monotonic sequence 仅用于本进程 observation 顺序；
- 不落盘；
- 不作为 quota/cost ledger；
- 不参与 restart recovery。

这样 RG-3B 不会在尚未定义 durable settlement/idempotency 前制造第二套账本。

## 9. 与 RG-2 / RG-3A 的关系

RG-2：
- ProviderCallCoordinator / ResourceGovernor 已负责 qualified local runtime concurrency lease。

RG-3A：
- 定义 cloud product/rate/quota/cost/usage/error typed contracts。

RG-3B：
- 只把真实 transport 事实投影进 RG-3A typed vocabulary；
- `ResourceGovernor` 和 `provider_calls.py` **不得读取这些 shadow observations**。

因此：

```text
RG-2 admission path     unchanged
RG-3B observation path  side-channel only
```

## 10. 本阶段明确不做

1. 不做 RPM/TPM enforcement；
2. 不做 quota enforcement；
3. 不做 cost calculation/budget enforcement；
4. 不把 observation 写入 durable ledger；
5. 不把 Task 的 `request.usage` 当统一 provider ledger；
6. 不做 product/account alias 自动推断；
7. 不故意制造 429；
8. 不修改 fallback/retry；
9. 不接 TrustDomain；
10. 不接 provider cancellation/priority API。

## 11. Qualification Matrix

### Deterministic

必须证明：

- reported zero 与 unreported usage 区分；
- invalid/empty usage 不制造 fact；
- HTTP 429 -> typed error/retry/reset；
- HTTP-date Retry-After 正确归一；
- HTTP 200 + SSE error 保留 HTTP/provider 两层 identity；
- arbitrary error diagnostic 不会进入 provider_code；
- secret/raw headers/body 不进入 fact；
- observer failure 对原请求 fail-open；
- recorder bounded/thread-safe；
- default/routed clients 共享 recorder；
- Governor/provider-call admission 不 import/消费 shadow facts。

### Real provider canary

对当前凭据可用的 GLM / MiniMax / DeepSeek，各做最多一次 tiny request：

- 不打印 prompt、response body、API key、raw headers；
- 只打印 typed fact 摘要；
- 不主动制造 429；
- provider 自然错误时记录 typed error；
- 没有 rate-limit header 时如实报告“未观察到”，不补官网静态值。

### Regression

- Universal Prompt 与 provider tool surface 不变；
- Ruff / Pyright / py_compile / diff-check / security PASS；
- focused + adjacent tests PASS；
- full non-real-LLM PASS。

## 12. RG-3C 入口

只有 RG-3B 完成真实 transport qualification 后，RG-3C 才处理：

- provider-call identity；
- one call / retry / fallback attempt 的 settlement 边界；
- usage observation 归并；
- Task/SubAgent/Learning/Extractor/Summarizer 统一 accounting；
- durable/idempotent usage ledger。

即使到 RG-3C，也先做 shadow settlement；enforcement 继续后置。
