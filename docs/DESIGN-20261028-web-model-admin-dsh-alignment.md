# Web 端模型添加与管理对齐 DSH：需求与实现设计书

> **状态**：Draft v1（待评审）
> **日期**：2026-10-28
> **范围**：`webui/` + `src/llm_loop/web/provider_*` + `src/llm_loop/llm/{providers,pool}.py` + 默认模型路由（`core/loop/engine_services/routing.py`、`core/session.py`）
> **对齐基线**：本机安装的 DSH 0.2.1-rc.x 中 `@deepseek-ai/dsh-client-ui-settings-models`、`@deepseek-ai/dsh-llm-pi-ai`、`@deepseek-ai/dsh-agent-default-model`、`@deepseek-ai/dsh-client-ui-model-selection` 的公开契约
> **变更类型**：Web 控制面契约修复 + 默认模型运行语义变更（行为变更，需独立提交与 qualification）

---

## 0. 结论摘要（TL;DR）

**当前 Web 端“模型添加和管理”不是模型能力问题，而是 Web 控制面的输入/输出契约断裂。**

1. **P0：编辑 Provider、启停 Provider、在编辑器里加/删模型、通过编辑器修改已有 Provider 的 API Key，全部返回 HTTP 422。**（“清除 Key”走独立 credential 端点，不受影响。）
   前端把快照中的运行时事实（`effective`，以及 DeepSeek 模型上的 `note`）原样回写给 `PUT /api/v1/providers/{id}`；后端 `ProviderModelAdminInput` / `ProviderAdminProviderInput` 使用 `extra="forbid"`，于是直接拒绝。该问题已在 live 8903 上复现（见附录 A）。
2. **P0：默认模型只写配置，不更新运行默认。**
   `POST /api/v1/providers/default-model` 只写 `.env` 的 `LLM_MODEL`（外部 env 拥有时直接拒绝），startup default client 仍是启动快照，因此返回 `restart_required=true`。用户看到“配置默认”已变、“运行默认”未变，必须重启 Web Runtime 才生效，和“通过 Web 配置并生效”的目标相反。
3. **P1：模型没有独立的“添加”入口。**
   后端已有 `POST/PUT/DELETE /api/v1/providers/{id}/models...`，但 Web API client 没有封装，UI 也没有调用；用户只能在 Provider 编辑器里整包保存，而整包保存正好命中 422。
4. **P1：错误不可诊断。**
   422 的 `detail` 是数组，`providerResult()` 用 `String(body.detail)` 转成 `"[object Object]"`，用户看不到哪个字段不合法。
5. **P1：目录刷新只覆盖当前标签页。**
   `notifyModelCatalogChanged()` 是 `window` 事件，跨标签/跨端没有服务端事件；DSH 用 `llm/adapters-updated` 等推送。
6. **P2：管理界面与 DSH 的模型管理模型仍有结构差异**：没有模型显示名、输入模态、模型发现（discover models）、默认模型与会话选择的清晰分层，模型选择器也未按 Provider 分组。

**建议分阶段落地，而不是一次性重写：**

| 阶段 | 目标 | 风险 |
|---|---|---|
| Phase 0（hotfix） | 修复 422、恢复编辑/启停/加删模型/改 Key；422 可读错误 | 低，独立提交 |
| Phase 1（热生效） | 默认模型 live 切换；默认 vs 会话选择语义；模型级 API 接入 UI；跨标签目录刷新 | 中，涉及默认路由与会话语义 |
| Phase 2（DSH 对齐） | 模型发现、显示名/输入模态 | 中 |
| Phase 3（体验） | Provider 模板、分组选择器、添加 Provider 双模式、移动端布局 | 低 |

---

## 1. 审查范围与证据

### 1.1 代码路径

| 层 | 文件 | 职责 |
|---|---|---|
| Web UI | `webui/src/components/layout/ProviderManager.tsx` | Provider/模型编辑、启停、删除、测试、默认模型 |
| Web UI | `webui/src/core/api.ts` | Provider 管理 API client、错误归一 |
| Web UI | `webui/src/components/conversation/ModelControls.tsx` | Composer 模型选择器 |
| Web UI | `webui/src/core/chat.ts` | `/api/v1/models` 目录读取、同标签变更事件 |
| Web 路由 | `src/llm_loop/web/provider_routes.py` | Provider/模型 HTTP 端点 |
| Web 控制面 | `src/llm_loop/web/provider_admin.py` | 快照、CAS、锁、原子写、Registry 重载、默认模型 |
| 输入 schema | `src/llm_loop/web/schemas.py` | `extra="forbid"` 的严格输入 |
| Registry | `src/llm_loop/llm/providers.py` | `ProviderSpec`/`ModelSpec`、加载优先级 |
| 运行路由 | `src/llm_loop/llm/pool.py` | Registry 热替换、per-model client 缓存、默认 client |
| 主循环 | `src/llm_loop/core/loop/engine_services/routing.py` | 默认/会话 override 路由 |
| 会话 | `src/llm_loop/core/session.py` | `model_override` |

### 1.2 live 复现（8903）

UI 实际发出的 body 形状（节选，来自当前快照的 `providerToInput()`）：

```json
{
  "expected_version": "<sha256>",
  "provider": {
    "id": "cognilocal",
    "enabled": true,
    "base_url": "http://localhost:8901/v1",
    "models": [
      { "id": "ornith-ai/Ornith-1.5-35B-A3B-MLX", "context": 65536, "effective": true },
      { "id": "qwen3.8-flash-next", "context": 65536, "effective": true }
    ]
  }
}
```

服务端响应：

```text
HTTP 422
{"detail":[
  {"type":"extra_forbidden","loc":["body","provider","models",0,"effective"],
   "msg":"Extra inputs are not permitted","input":true},
  {"type":"extra_forbidden","loc":["body","provider","models",1,"effective"],
   "msg":"Extra inputs are not permitted","input":true}
]}
```

DeepSeek Provider 还会额外命中 `note`：

```text
loc: ["body","provider","models",0,"note"]  → extra_forbidden
loc: ["body","provider","models",0,"effective"] → extra_forbidden
```

这说明 422 不是偶发环境问题，而是**前端快照回写**与**后端严格输入**之间的确定性契约错误。

### 1.3 为什么现有测试没抓住

- `tests/web/test_provider_admin.py` 的 `_provider()` 夹具只构造干净的可写字段，从不包含 `effective`、`note`，所以后端测试全绿。
- `webui/src/provider-admin.test.tsx` 的“模型可在设置页声明自己的推理档位”测试把 `PUT` mock 成无条件返回 200，只断言 `reasoning_efforts`，不断言请求 body 不包含运行时字段，所以前端测试也绿。
- 两边的“假绿”正好覆盖了真实用户路径。**这本身应成为一个回归测试设计缺陷，按 `docs/DEVELOPMENT_REPAIR_SAFETY.md` Q6 修正。**

### 1.4 影响面

| 用户动作 | 当前结果 | 根因 |
|---|---|---|
| 新建 Provider | 可用（新模型没有 `effective`） | — |
| 新建后再编辑 Provider | **422** | 模型快照含 `effective` |
| 停用/启用 Provider | **422** | `toggleProvider()` 走 `replaceProvider()`，body 含 `effective` |
| 在编辑器里添加模型 | **422** | 整包保存，同上 |
| 在编辑器里删除模型 | **422** | 整包保存，同上 |
| 修改已有 Provider 的 API Key | **422** | 先 `PUT provider`，再写 credential；第一步就失败 |
| 删除 Provider | 可用（除非它是默认来源） | 走 DELETE 端点，不经过严格 provider body |
| 测试连接 | 可用 | 只发 provider/model id |
| 修改全局默认模型 | 写 `.env`（可写时）成功，但运行默认不变 | startup default client 冻结 |
| 新增 Provider 后立即在 Composer 使用 | 同标签可用（有本地事件）；跨标签需刷新 | 目录刷新无服务端事件 |
| `MODEL_PROVIDERS` 只读模式 | 编辑按钮仍可打开，保存时才 409；清除 Key 按钮也未禁用 | 只读态未覆盖所有写入口 |

---

## 2. 当前实现盘点

### 2.1 配置面与运行面被混在同一个扁平对象里

`provider_admin.snapshot()` 返回的 Provider/模型对象同时包含：

- **可写配置事实**：`enabled`、`base_url`、`api_key_env`、`default_model`、`models[].context`、`reasoning_*` 等；
- **运行时事实**：`effective`、`credential_configured`、`credential_source`、`effective_provider_count` 等。

UI 的 `providerToInput()` 只对 Provider 顶层字段做了白名单，对模型对象使用了对象展开：

```ts
models: provider.models.map((model) => ({
  ...blankModel(),
  ...model,          // ← 把 effective / note 原样带回来了
  enabled: model.enabled !== false,
  ...
}))
```

后端输入 schema 又是严格模式：

```python
class ProviderModelAdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

两者组合就是确定性 422。

### 2.2 数据流

```text
ProviderManager
  └─ providerToInput(snapshot)  ← 含运行时 effective / note
       └─ PUT /api/v1/providers/{id}
            └─ ProviderReplaceRequest
                 └─ ProviderAdminProviderInput(extra="forbid")
                      └─ 422 extra_forbidden
```

### 2.3 生效链路

```text
providers.local.json
  └─ load_registry()
       └─ ModelClientPool.replace_registry()
            └─ /api/v1/models、Composer 选择、下一次请求的 per-model client

LLM_MODEL(.env)
  └─ build_engine() 构造 startup LLMClient
       └─ ModelClientPool.default_client（冻结）
            └─ 只有重启 Web Runtime 才会换
```

因此：

- **新增/编辑/删除模型、Provider 热替换**：设计上已经可以“下一次请求生效”（`replace_registry` 会退休旧 client）；
- **默认模型**：只做到“下一次启动生效”，没有做到“下一次请求生效”。

### 2.4 端点与 UI 使用情况

| 端点 | 后端 | Web API client | UI 使用 |
|---|---|---|---|
| `GET /api/v1/providers` | 有 | `fetchProviderAdmin` | 有 |
| `POST /api/v1/providers` | 有 | `createProvider` | 有 |
| `PUT /api/v1/providers/{id}` | 有 | `replaceProvider` | 有（422 主路径） |
| `DELETE /api/v1/providers/{id}` | 有 | `deleteProviderConfig` | 有 |
| `PUT /api/v1/providers/{id}/credential` | 有 | `updateProviderCredential` | 仅“清除 Key”/新建时 |
| `POST /api/v1/providers/{id}/models` | 有 | **无** | **无** |
| `PUT /api/v1/providers/{id}/models/{mid}` | 有 | **无** | **无** |
| `DELETE /api/v1/providers/{id}/models/{mid}` | 有 | **无** | **无** |
| `POST /api/v1/providers/default-model` | 有 | `setConfiguredDefaultModel` | 有（只改配置） |
| `POST /api/v1/providers/reload` | 有 | `reloadProviderRegistry` | 有（手动兜底） |
| `POST /api/v1/providers/{id}/test` | 有 | `testProviderConnection` | 有 |

**模型级 API 已经存在，只是没有接到 UI。** 这是 Phase 0/1 最低成本的修复点。

### 2.5 问题登记

| ID | 级别 | 问题 | 证据 | 修复阶段 |
|---|---|---|---|---|
| P0-1 | P0 | 编辑/启停 Provider、加删模型、通过编辑器改 Key 全部 422 | 附录 A；`ProviderManager.tsx:62` + `schemas.py:287` | Phase 0 |
| P0-2 | P0 | 默认模型只改配置，运行默认冻结 | `provider_admin.py:540`；`tests/web/test_provider_admin.py:148` | Phase 1 |
| P1-1 | P1 | 模型级 API 未接 UI | `api.ts` 无 `addProviderModel`；UI 只在编辑器整包保存 | Phase 1 |
| P1-2 | P1 | 422 错误显示 `[object Object]` | `api.ts:1259` | Phase 0 |
| P1-3 | P1 | 目录刷新仅当前标签页 | `chat.ts` window event；无 SSE | Phase 1 |
| P1-4 | P1 | 编辑 DeepSeek 会因 `note` 422 | live 422；schema 无 `note` | Phase 0 |
| P1-5 | P1 | 新会话无条件继承旧 override，默认切换被遮蔽 | `routes.py:1441` | Phase 1/2 |
| P2-1 | P2 | 无模型显示名/输入模态 | `ModelSpec` 无字段 | Phase 2 |
| P2-2 | P2 | 无模型发现 | 无端点 | Phase 2 |
| P2-3 | P2 | 模型选择器未按 Provider 分组 | `ModelControls.tsx` 扁平 `<select>` | Phase 3 |
| P2-4 | P2 | 无跨运行时 DSH 同步 | 现有 `apply-dsh-config.sh` 人工桥 | 非目标（另立设计） |

---

## 3. DSH 的模型添加/管理方式（对照基线）

> 以下只描述 DSH 的公开契约，不复述其内部实现；用于确定 LFL 要对齐的“语义”，不是要求把 TypeScript 代码搬过来。

### 3.1 DSH 的模型管理模型

| 维度 | DSH 的做法 |
|---|---|
| **配置载体** | 活动 profile 的 settings document / Cordis patch；每个 section 有 revision，写入用 `settings.mutate` 路径操作 + revision CAS；客户端只拿到 redacted descriptor |
| **凭据** | `credentials.set/unset/describe`；只写不读；模型设置页只要求输入一个 **API key**，由页面派生 `<ROUTE>_API_KEY` 引用，`cordis.patch.yml` 不出现明文 |
| **Provider 目录** | 适配器声明 “configurable provider directory”；`llm-pi-ai` 提供已安装厂商目录 + 手写自定义路由；`llm-deepseek` 是固定组合路由。Provider ID 一旦创建就是 settings key，不可在页面里改 |
| **添加 Provider** | 两种模式：① 从已安装目录选择一个 dormant provider；② **Custom model API**：Provider ID、endpoint、协议、至少一个模型；支持 `llm/discoverModels` 在保存前拉取候选模型 |
| **模型行** | 每个模型可编辑：`id`、显示 `name`、`contextWindow`、`maxTokens`、输入类型（Text/Image）、（自定义路由）reasoning levels；未展示的字段保存时保留 |
| **保存语义** | 保存的是“配置事实”；运行时状态（adapter 是否加载、凭据是否配置）单独展示，不回写 |
| **生效语义** | 适配器每次请求解析当前配置；新配置对**下一次请求**生效，**不需要重启**；运行中的 step 保持它开始时选定的模型 |
| **默认模型** | `agent-default-model` 的 `currentSelection()` / `saveSelection()`；保存后对**后续新建 agent** 生效；已有 session 的选择不被覆盖 |
| **会话选择** | `session.selectModel`；选择决定下一次请求；运行中的 step 不变 |
| **目录刷新** | `llm/adapters-updated`、`settings/document-updated`、`credentials/reference-updated` 事件；客户端订阅后收敛，不靠轮询 |
| **GUI 目录成员资格** | GUI 只允许选择和提交 `listModels` 目录中的模型；适配器必须 advertise 模型；“目录中不存在”是明确状态，不伪造可用性 |
| **错误** | `settings-conflict`、`settings-rejected`、`credential-rejected`、`bad-request` 等稳定错误；字段级拒绝，编辑器保持打开 |

### 3.2 DSH 的关键设计原则

1. **配置面 / 运行面分离**：可写字段与只读事实不混在一个可回写的对象里。
2. **保存即生效**：没有“保存后请重启”的主流程；重启只用于代码/部署级变化。
3. **默认模型与会话选择分离**：默认只影响“没有选择的新 agent”；已有会话的显式选择优先。
4. **目录是权威**：模型必须被 adapter advertise，才能出现在 GUI；目录之外的选择显示为不可用，而不是悄悄替换。
5. **凭据只写**：页面永远不读回密钥；只展示“已配置/缺失/来源”。
6. **失败可恢复**：revision 冲突、字段非法、凭据拒绝都有明确错误和重试入口；不静默覆盖。

### 3.3 DSH 与 LFL 的概念映射

| DSH | LFL 当前对应物 | 目标对齐方式 |
|---|---|---|
| settings document + revision | `data/providers.local.json` + `config_version`（SHA256） | 保留文件与 CAS；增加配置/运行分离 |
| `settings.mutate` | `provider_admin.mutate()` | 保留；补 PATCH 行级操作 |
| `credentials.set` | `.env` + `api_key_env` | 保留；派生变量名、隐藏 env 名、只写 |
| configurable provider directory | `ProviderRegistry` + `web_provider_registration` | 保留；增加模板与发现 |
| `llm-pi-ai` custom route | provider + `wire_protocol` | 保留 LFL 协议集；补自定义端点流程 |
| model rows | `models` dict + `ModelSpec` | 补 `name`、`input_modalities`、`note` |
| `listModels` | `GET /api/v1/models` | 保留；补显示名/默认/来源 |
| `llm/discoverModels` | 无 | 新增 `POST /api/v1/providers/discover-models` |
| `llm/adapters-updated` | 同标签 `notifyModelCatalogChanged` | 新增 SSE `providers_updated` |
| `agent-default-model` | `.env` `LLM_MODEL` + startup client | 改为 live default ref + 持久化 |
| `session.selectModel` | `session.model_override` | 保留；补“默认”清除与来源 |
| `settings-conflict` | `provider_config_conflict` | 保留；错误体补 `current_version` |

### 3.4 不能直接照搬的部分

| DSH 能力 | 为什么 LFL 本阶段不做 | 处理 |
|---|---|---|
| OAuth / 账号登录 Provider | LFL 没有 DSH 的 account/authorization seam | 非目标；继续 API key |
| `openai-responses` 协议 | LFL `LLMClient` 只支持 `openai`/`anthropic`/`google`/`lms-chat` | 不在本设计扩展协议；文档标注差异 |
| 任意 reasoning level 词汇 + wire value | LFL 运行时的 effort 词表与 `reasoning_effort_map` 是既有合同，扩展需独立 qualification | 本阶段只暴露 LFL 已支持词表；词表扩展另立设计 |
| 插件式 settings 框架 | LFL 是 Python 单体 + 文件控制面，不值得为模型管理引入通用 settings 框架 | 复用现有 CAS/锁/原子写 |
| 直接改写 `~/.dsh/settings.yaml` | DSH 是独立运行时，有自己的 profile/credential；跨运行时同步是另一个问题 | 明确非目标；保留现有 `scripts/apply-dsh-config.sh` 的人工桥 |

---

## 4. 需求

### 4.1 用户故事

| ID | 用户故事 |
|---|---|
| US-1 | 作为本机操作者，我可以从 Web 添加一个 OpenAI-compatible / Anthropic / 本地端点 Provider，填写 Base URL、API Key 和至少一个模型，保存后立即在 Composer 里看到并选择它，不需要重启。 |
| US-2 | 作为操作者，我可以在已有 Provider 下单独添加一个模型、修改它的 context/output/协议/推理声明、删除它，而不影响同 Provider 的其他模型。 |
| US-3 | 作为操作者，我可以编辑 Provider 的 Base URL、超时、默认模型、凭据；保存后下一次请求生效，不需要重启。 |
| US-4 | 作为操作者，我可以启用/停用 Provider 或单个模型；停用后它从可选目录消失，正在使用它的会话显示“当前不可用”，而不是被程序悄悄改写。 |
| US-5 | 作为操作者，我可以把任意已启用模型设为全局默认；新建会话使用新默认，已有会话的显式选择保持不变；界面明确显示“已生效”而不是“请重启”。 |
| US-6 | 作为操作者，我可以只输入 API Key，系统自动派生环境变量名；密钥不出现在 JSON、页面、日志、错误里。 |
| US-7 | 作为操作者，我可以在保存前“获取可用模型”，从端点返回的候选里勾选，而不是手抄模型 ID。 |
| US-8 | 作为操作者，当另一个标签页或外部编辑改了配置时，我的页面会提示冲突并提供“重新加载”，不会静默覆盖。 |
| US-9 | 作为操作者，当 Provider 由 `MODEL_PROVIDERS` 环境变量拥有时，页面明确只读，并说明为什么 Web 写入不会生效。 |
| US-10 | 作为模型/后续 Agent，我通过 `/api/v1/models` 看到的是“当前真实可路由的目录”，包括模型显示名、Provider、输入模态、默认标记和不可用状态。 |

### 4.2 功能需求

| ID | 需求 | 验收要点 |
|---|---|---|
| FR-1 | **配置投影**：前端构造写入 body 时只允许配置字段；运行时事实永不回写 | 单测断言 body 不含 `effective`/`credential_*`；后端对运行时字段仍返回 422 |
| FR-2 | **Provider 行级操作**：启用/停用、改默认模型、改显示名走轻量 PATCH，不要求整包 body | PATCH 成功；不再因模型快照字段 422 |
| FR-3 | **模型级增删改**：UI 直接调用已有 `/models` 端点；每个模型行可独立保存/删除 | 新增模型后 `GET /models` 立即出现；删除后消失 |
| FR-4 | **保存即生效**：Provider/模型变更后下一次 LLM 请求使用新配置；无需重启 | 集成测试：变更后 `pool.get_client` 看到新配置；`restart_required=false` |
| FR-5 | **默认模型 live**：设置默认后，pool 的默认选择立即切换并持久化；新会话使用新默认 | `runtime_default_model` 等于新值；新会话无 override 时使用新默认；旧会话 override 不变 |
| FR-6 | **默认 vs 会话选择**：新增“默认模型”选项；清除会话 override；新建会话只有在用户显式选择过模型时才继承 | 选择默认后 session override 为空；新建会话回落到默认 |
| FR-7 | **目录一致性**：所有变更后 `/api/v1/models`、Composer、设置页目录一致；跨标签通过服务端事件刷新 | SSE `providers_updated` 触发刷新；3 秒内收敛 |
| FR-8 | **错误可诊断**：422/409/502 显示字段路径、原因、当前 revision；不出现 `[object Object]` | 单测覆盖 422 数组格式化；冲突可重新加载 |
| FR-9 | **密钥只写**：API Key 输入为空时保留原 key；只写 `.env`；自动派生变量名；不回显 | 响应/页面/日志无明文；清除 Key 需确认 |
| FR-10 | **模型发现**：保存前可请求端点模型列表，候选可勾选；不自动写入 | 成功/失败/超时/非支持协议都有明确诊断 |
| FR-11 | **模型元数据**：模型行支持显示名、输入模态、context、max output、协议、推理声明、备注 | 保存后 `/models` 目录反映这些字段 |
| FR-12 | **配置来源权威**：`MODEL_PROVIDERS` 环境变量仍最高优先级；Web 只读并解释原因 | 写入返回 409；UI 隐藏/禁用**所有**写入口（编辑、启停、删除、改 Key、加模型、默认切换） |
| FR-13 | **未知字段保留**：编辑时不丢失 `note` 等未展示配置字段 | round-trip 测试：保存后原字段仍在 |
| FR-14 | **并发安全**：所有写操作走现有锁 + CAS；冲突不覆盖 | 两写一成功一 409；文件只写一次 |
| FR-15 | **回滚**：Registry 加载失败时恢复修改前文件与运行 Registry | 注入非法配置；接口 4xx/5xx；文件与 registry 仍为旧值 |

### 4.3 非功能需求

| ID | 需求 |
|---|---|
| NFR-1 | 现有 WebAuth、Origin/CSRF、HostGuard 边界不变；新增端点自动继承 |
| NFR-2 | 密钥/URL userinfo/响应体不得进入日志、错误、DOM、API 响应 |
| NFR-3 | 单进程控制面假设明确；多进程部署需要重启或额外 watcher（本设计不承诺） |
| NFR-4 | 配置写入原子、0600、失败不留下半写文件 |
| NFR-5 | 不引入新的模型质量推断、自动路由、自动摘要或语义裁决 |
| NFR-6 | 现有 `MODEL_PROVIDERS`、`LLM_MODEL`、`data/providers.json` 兼容 |
| NFR-7 | 变更可独立回滚；Phase 0 与 Phase 1 分开提交 |

### 4.4 非目标

- 不做模型能力评分、自动选模型、自动 fallback 策略变更。
- 不做 Provider OAuth/账号登录。
- 不做 DSH profile 的自动改写 / 跨运行时模型同步。
- 不做模型下载、量化、部署。
- 不在本阶段扩展 reasoning 词表或 `openai-responses` 协议。
- 不做多租户 RBAC；沿用现有 Web 鉴权。

---

## 5. 目标设计

### 5.1 分层

```text
┌─────────────────────────────────────────────────────────────┐
│ Web UI                                                       │
│  ModelSettingsPanel (Provider rows / editor / model rows)    │
│  ModelControls (Composer picker)                             │
│  modelCatalog store  ← SSE providers_updated                │
└───────────────┬─────────────────────────────────────────────┘
                │ config-only JSON + expected_version
┌───────────────▼─────────────────────────────────────────────┐
│ Web control plane (provider_routes.py)                       │
│  snapshot / mutate / PATCH / model CRUD / discover           │
│  error normalization (field path, revision, safe details)    │
└───────────────┬─────────────────────────────────────────────┘
                │ atomic write + CAS + flock
┌───────────────▼─────────────────────────────────────────────┐
│ provider_admin.py                                            │
│  config projection  |  runtime facts  |  rollback            │
│  default-model manager (live)                                │
└───────────────┬─────────────────────────────────────────────┘
                │ load_registry / replace_registry
┌───────────────▼─────────────────────────────────────────────┐
│ ProviderRegistry + ModelClientPool                           │
│  per-model clients  |  live default ref  |  in-flight holds  │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 配置事实与运行事实分离

**可写配置事实**（Web 输入/持久化）：

Provider：
`id`、`display_name`、`enabled`、`base_url`、`api_key_env`、`default_model`、`timeout_s`、`history_budget_chars`、`max_input_tokens`、`max_tokens`、`chars_per_token`。

Model：
`id`、`name`、`enabled`、`context`、`max_input_tokens`、`max_tokens`、`cost_tier`、`capability_tier`、`input_modalities`、`multimodal`（兼容）、`wire_protocol`、`thinking`、`reasoning_capable`、`reasoning_control`、`reasoning_efforts`、`reasoning_effort_map`、`reasoning_default_effort`、`reasoning_replay`、`send_tool_choice`、`reasoning_split`、`runtime_identity`、`temperature`、`top_p`、`top_k`、`min_p`、`note`。

**只读运行事实**（响应中单独命名空间，永不作为输入）：

`effective`、`credential_configured`、`credential_source`、`effective_provider_count`、`effective_model_count`、`default.runtime_model`、`default.applied`、`default.persistence`、`catalog_version`、`loaded_at`、`degraded`。

响应形状（增量兼容）：

```json
{
  "source": "local",
  "mutable": true,
  "config_version": "sha256...",
  "default": {
    "model": "glm/glm-5.3",
    "runtime_model": "glm/glm-5.3",
    "configured_source": "dotenv",
    "persistence": "dotenv",
    "applied": true,
    "restart_required": false
  },
  "providers": [
    {
      "id": "glm",
      "enabled": true,
      "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
      "api_key_env": "GLM_API_KEY",
      "default_model": "glm-5.3",
      "models": [
        {
          "id": "glm-5.3",
          "name": "GLM-5.3",
          "enabled": true,
          "context": 1000000,
          "input_modalities": ["text"],
          "runtime": { "effective": true }
        }
      ],
      "runtime": {
        "effective": true,
        "credential_configured": true,
        "credential_source": "dotenv"
      }
    }
  ]
}
```

> 为兼容现有测试/前端，v1 的扁平 `effective`/`credential_*` 字段可保留一个版本，但 UI 只读 `runtime`；下一个版本移除扁平运行时字段。**关键是 UI 的写入投影必须从类型上排除运行时字段。**

### 5.3 数据模型

```ts
// 只用于写入的配置投影（不含 effective/credential_*）
export interface ProviderConfigInput {
  id: string;
  display_name?: string;
  enabled: boolean;
  base_url: string;
  api_key_env?: string;
  default_model?: string;
  timeout_s?: number | null;
  history_budget_chars?: number | null;
  max_input_tokens?: number | null;
  max_tokens?: number | null;
  chars_per_token?: number | null;
  models: ModelConfigInput[];
}

export interface ModelConfigInput {
  id: string;
  name?: string;
  enabled: boolean;
  context: number;
  max_input_tokens?: number | null;
  max_tokens?: number | null;
  cost_tier?: string;
  capability_tier?: "strong" | "weak" | "unknown";
  input_modalities?: Array<"text" | "image">; // 本阶段对齐 DSH 的 Text/Image；audio/video 属未来扩展
  multimodal?: boolean; // 兼容；与 input_modalities 同步
  wire_protocol?: "openai" | "anthropic" | "google" | "lms-chat";
  thinking?: boolean;
  reasoning_capable?: boolean;
  reasoning_control?: "unknown" | "none" | "thinking_type" | "chat_template" | "always_on_effort" | "legacy";
  reasoning_efforts?: string[];
  reasoning_effort_map?: Record<string, string>;
  reasoning_default_effort?: string | null;
  reasoning_replay?: "configured" | "none" | "tool_calls" | "full";
  send_tool_choice?: boolean;
  reasoning_split?: boolean;
  runtime_identity?: string;
  temperature?: number | null;
  top_p?: number | null;
  top_k?: number | null;
  min_p?: number | null;
  note?: string;
}
```

约束：

- `id`：Provider 仍为 `^[a-z][a-z0-9_-]{0,31}$`；Model ID 禁止空白/控制字符，并新增 **env-safe** 约束 `^[^\s#='"]+$`（用于 `LLM_MODEL` 写入 `.env`）。
- `context >= 1024`；`max_tokens >= 1`；`input_modalities` 至少一个。
- `reasoning_default_effort` 必须属于 `reasoning_efforts`。
- `base_url` 仅 `http/https`，必须有 hostname，禁止 userinfo。
- `api_key_env` 必须匹配 `^[A-Za-z_][A-Za-z0-9_]{0,127}$`；写 credential 时仍要求 `_API_KEY`/`_TOKEN`/`_SECRET` 后缀。
- `note` 最大 4096 字符；不参与路由。

### 5.4 默认模型与会话选择

这是“配置并生效”的核心语义，必须与 DSH 对齐：

| 状态 | 行为 |
|---|---|
| 新会话，用户未显式选模型 | 使用**当前 live 默认** |
| 已有会话，有显式 override | 保持 override；默认变更不影响它 |
| 已有会话，override 指向已删除/停用模型 | `/models` 返回 `current_available=false`；UI 显示“当前不可用”；不自动改写 |
| 用户选择“默认模型” | 清除 session override；下一次请求使用 live 默认 |
| 运行中的 step | 保持该 step 开始时捕获的 client/model；默认变更只影响下一个 step/请求 |
| 默认切换 | 立即更新 `ModelClientPool` 的 live 默认；持久化到 `.env`（或明确 runtime-only） |

**当前 LFL 的偏差**：`_new_session_model_override()` 会无条件继承上一个 shared session 的 `model_override`，即使该 override 只是之前继承来的。这样用户切换默认后，新会话仍沿用旧模型，默认“看起来没生效”。修复方式：

- `Session` 增加 `model_override_source: "user" | "inherit" | None`。
- 兼容旧 session：读取时若没有该字段且 `model_override` 非空，按 `"user"` 处理（历史上能留下 override 的都是显式选择或旧继承语义，不能因为升级把已有选择判成无效）；不强制回写文件。
- `_apply_session_model_override()` 在显式 `model_change` 时写 `source="user"`。
- `_new_session_model_override()` 只继承 `source="user"` 的 override；否则返回 `None`，让默认生效。
- 新增 `POST /api/v1/sessions/{id}/model`，body `{ "model": "provider/model" | null }`；`null` 清除 override。
- Composer 增加“默认模型”选项。

### 5.5 生效语义矩阵

| 变更 | 生效点 | 是否需要重启 |
|---|---|---|
| 新增/删除/替换 Provider | `replace_registry` 后下一次请求 | 否 |
| 新增/删除/修改模型 | 同上 | 否 |
| 修改 Base URL/超时/预算 | 新 client 在下一次请求构造 | 否 |
| 修改 API Key | `client_params` 每次按 env 解析；清缓存 | 否 |
| 启用/停用 Provider | registry 替换；目录变化 | 否 |
| 设置全局默认 | pool live default 切换；新会话/无 override 请求 | 否 |
| 修改会话选择 | 下一次请求 | 否 |
| `MODEL_PROVIDERS` env 变化 | 需要进程重启（部署级） | 是 |
| 代码/插件变化 | 需要重启 | 是 |

### 5.6 服务端事件

复用现有 `GET /api/v1/events` SSE，新增命名事件：

```text
event: providers_updated
data: {"type":"providers_updated","config_version":"sha256...","catalog_version":"sha256...","default_model":"glm/glm-5.3"}
```

实现方式（低成本）：

- 把 Provider 文件 hash + live 默认 ref + registry 代数纳入现有 SSE 的指纹计算；
- 指纹变化时推送 `providers_updated`；
- 现有 3s 轮询足够；不需要新建长连接。
- 前端 `events.ts` 监听后：刷新 `modelCatalog`、若设置页打开则刷新 Provider 快照；不覆盖用户正在编辑的 draft（若 draft 存在，只提示冲突）。

### 5.7 安全

- 继续使用 WebAuth + `_OriginGuardMiddleware` + HostGuard；新端点自动继承。
- API Key 只写 `.env`，0600；响应/日志/错误/DOM 不回显。
- 测试连接/发现的错误只返回异常类型、HTTP status、timeout 类别；不反射 provider body/URL userinfo。
- `base_url` 允许 localhost/私网（本地模型是明确能力），但禁止 `file:`/`gopher:`/userinfo；发现请求限制超时、响应大小、候选数量、重定向。
- 严格区分配置/运行字段；后端继续 `extra="forbid"`，前端投影修复根因。
- `MODEL_PROVIDERS` 环境变量保持最高优先级；Web 只读并解释。

---

## 6. 详细实现

### 6.1 Phase 0：恢复基本可用（hotfix，独立提交）

#### 6.1.1 前端配置投影

在 `webui/src/core/api.ts` 把“事实”和“输入”拆成两个类型：

```ts
export interface ProviderModelConfig {
  id: string;
  name?: string;
  note?: string;
  // ...仅配置字段
}

export interface ProviderModelFact extends ProviderModelConfig {
  effective?: boolean;                 // 兼容 v1 扁平运行时事实；只读，不参与写入
  runtime?: { effective?: boolean };   // v2 运行时事实；只读
}

export interface ProviderConfigInput { /* 仅配置字段 */ }

export function toModelConfig(model: ProviderModelFact): ProviderModelConfig {
  return {
    id: model.id,
    name: model.name,
    enabled: model.enabled,
    context: model.context ?? 131072,
    max_input_tokens: model.max_input_tokens ?? null,
    max_tokens: model.max_tokens ?? null,
    cost_tier: model.cost_tier ?? "mid",
    capability_tier: model.capability_tier ?? "unknown",
    input_modalities: model.input_modalities,
    multimodal: model.multimodal,
    wire_protocol: model.wire_protocol ?? "openai",
    thinking: Boolean(model.thinking),
    reasoning_capable: Boolean(model.reasoning_capable),
    reasoning_control: model.reasoning_control ?? "unknown",
    reasoning_efforts: model.reasoning_efforts ?? [],
    reasoning_effort_map: model.reasoning_effort_map ?? {},
    reasoning_default_effort: model.reasoning_default_effort ?? null,
    reasoning_replay: model.reasoning_replay ?? "configured",
    send_tool_choice: model.send_tool_choice !== false,
    reasoning_split: Boolean(model.reasoning_split),
    runtime_identity: model.runtime_identity ?? "",
    temperature: model.temperature ?? null,
    top_p: model.top_p ?? null,
    top_k: model.top_k ?? null,
    min_p: model.min_p ?? null,
    note: model.note,
  };
}

export function toProviderConfig(provider: ProviderAdminFact): ProviderConfigInput {
  return {
    id: provider.id,
    display_name: provider.display_name,
    enabled: provider.enabled !== false,
    base_url: provider.base_url,
    api_key_env: provider.api_key_env ?? "",
    default_model: provider.default_model ?? "",
    timeout_s: provider.timeout_s ?? null,
    // ...
    models: provider.models.map(toModelConfig),
  };
}
```

`ProviderManager` 的 `providerToInput` 改为 `toProviderConfig`；禁止再用 `...model`。

**回归测试**：

```ts
it("写入 body 不包含运行时事实", async () => {
  // render + click 保存
  expect(JSON.stringify(putBody)).not.toContain('"effective"');
  expect(JSON.stringify(putBody)).not.toContain('"credential_configured"');
  expect(JSON.stringify(putBody)).not.toContain('"runtime"');
});
```

#### 6.1.2 后端接收 `note`

`ProviderModelAdminInput` 增加：

```python
note: str = Field(default="", max_length=4096)
```

这样 DeepSeek 的 `note` 不会被 422，也不会在保存时被静默删除。其他未知字段在 Phase 1 用 `extra` 兜底。

#### 6.1.3 行级 PATCH

新增：

```text
PATCH /api/v1/providers/{provider_id}
body: { "expected_version": "...", "enabled": false }
body: { "expected_version": "...", "default_model": "glm-5.3" }
body: { "expected_version": "...", "display_name": "GLM" }
```

实现：`mutate()` 读取当前 raw，只改指定字段，校验最终配置后写回。这样“停用/启用”不再需要整包 body，从结构上消除 422 复发。

前端 `toggleProvider()` 改为 `setProviderEnabled(id, enabled, version)`；`changeProviderDefault()` 改为 PATCH。

#### 6.1.4 错误归一

`providerResult()`：

```ts
function formatProviderError(body: any): string {
  const detail = body?.detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const path = Array.isArray(item?.loc) ? item.loc.slice(1).join(".") : "";
        return path ? `${path}: ${item.msg}` : String(item?.msg ?? item);
      })
      .join("；");
  }
  return String(detail ?? body?.error ?? "操作失败");
}
```

同时保留 `error` code、`current_version`、`status`，供 UI 显示冲突/字段错误。

#### 6.1.5 失败时恢复真实快照

`fail()` 后调用 `load()`：

- 422/409：保留 draft，重新拉取 snapshot，显示“配置已被其他操作更新/字段非法”；
- 不要只显示错误而让界面停留在旧版本；
- 若 `load()` 失败，显示“配置读取失败；当前显示上次已知状态”。

**Phase 0 验收**：在 live/隔离实例上，编辑任一 Provider、启停、加模型、删模型、改 Key 均返回 2xx；`GET /api/v1/models` 立即反映变化；无需重启。

### 6.2 Phase 1：默认模型 live + 模型级 UI

#### 6.2.1 `ModelClientPool` 的 live 默认

```python
@dataclass
class ModelClientPool:
    registry: ProviderRegistry
    default_client: LLMClient
    _default_model_ref: str | None = None   # None = 仍用启动 default_client（兼容）
    _default_guard: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def get_default_ref(self) -> str:
        """展示/报告用：live override 优先，否则启动默认的 canonical ref。"""
        with self._default_guard:
            if self._default_model_ref:
                return self._default_model_ref
        return self._startup_default_ref()

    def get_client(self, model_override: str | None) -> LLMClient:
        if model_override is None:
            with self._default_guard:
                live_ref = self._default_model_ref
            if live_ref:
                client, _, _ = self.get_resolved_client(live_ref)
                return client
            with self._guard:
                return self.default_client
        client, _, _ = self.get_resolved_client(model_override)
        return client

    def set_default_model(self, model_ref: str) -> str:
        registry = self.registry_snapshot()
        pid, mid = registry.resolve(model_ref)
        canonical = f"{pid}/{mid}"
        # 先通过正常路径 resolve + 构造/取缓存，失败则不提交
        self.get_resolved_client(canonical)
        with self._default_guard:
            self._default_model_ref = canonical
            self._default_registry = registry
        # 可选：兼容 engine.llm 的 callback；见 6.2.2
        return canonical
```

要点：

- **启动兼容**：`_default_model_ref` 初始为 `None`，`get_client(None)` 仍返回启动 `default_client`，避免 startup env（`LLM_BASE_URL`/`LLM_MAX_TOKENS`）与 registry 参数的隐式差异。
- **先 resolve/构造，再提交 ref**；构造失败不改变默认。
- 默认 ref 变化不修改已有 client；在途请求持有旧 client，下一请求走新 ref。
- `registry` 替换后，若默认 ref 仍可 resolve，继续使用；若不可 resolve，标记 `default_unavailable`，不静默替换。
- `get_default_ref()` 是“展示默认”，不等于 `get_client(None)` 的内部选择；前者在未设置 live override 时返回启动默认的 canonical，后者返回启动 client 本身。

#### 6.2.2 `engine.llm` 兼容

`engine.llm` 在多个地方被直接使用（`routing.py` 的错误回退、辅助 summarizer 等）。Phase 1 只要求**主循环和 Web 请求**使用 live 默认：

- `routing.py` 默认路径改为 `self._host.llm_pool.get_client(None)`，`model_used` 用 `pool.get_default_ref()`；
- `routing.py` 的 `except ValueError` 回退不再用 `self._host.llm`（旧默认），而是返回明确的 model-unavailable 结果或使用 live 默认；
- `engine.llm` 保持启动 client，供未迁移的辅助路径使用；在 factory 中注册 `on_default_changed` 回调，把新 client 写回 `engine.llm`（可选，Phase 1 后半）。
- 辅助路径（summary/learning）仍可使用启动 client；文档标注“主对话 live，辅助路径下一次启动生效”，或后续统一到 pool。

#### 6.2.3 持久化

`provider_admin.set_default_model()`：

1. `registry.resolve(model_ref)` → canonical；
2. 判断 `LLM_MODEL` 来源：
   - `external_env`：只设置 runtime default，返回 `persistence="process"`、`durable=false`、提示“本次进程生效；重启后由外部环境决定”；
   - `dotenv`/`missing`：先写 `.env`（原子、0600），成功后再 `pool.set_default_model()`；失败则回滚 `.env`；
3. 返回 snapshot：`configured_default_model`、`runtime_default_model`、`default.applied=true`、`restart_required=false`（除非持久化失败）；
4. 删除/停用默认 Provider/模型时，同时检查 `configured` 与 `runtime` 两个 ref，任一命中都拒绝，避免 runtime-only 默认被误删。

#### 6.2.4 模型级 UI

新增 API client：

```ts
addProviderModel(providerId, version, model)
replaceProviderModel(providerId, modelId, version, model)
deleteProviderModel(providerId, modelId, version)
setProviderEnabled(providerId, enabled, version)
```

Provider 卡片增加：

- `+ 添加模型` → 打开模型行编辑器 → `POST .../models`；
- 每个模型行：编辑/启停（`PUT` 完整 model）、删除（`DELETE`）、测试（`POST /test` with model）；
- 删除/重命名默认模型时显示服务端 409 的可操作提示。

Provider 编辑器保留批量编辑，但保存时使用 `toProviderConfig()`；模型行增删只改 draft，保存时整包 PUT。两条路径都可用，互不替代。

#### 6.2.5 目录事件

`events.ts` 增加：

```ts
es.addEventListener("providers_updated", () => {
  notifyModelCatalogChanged();
  providerAdminStore.refreshIfOpen();
});
```

`/api/v1/events` 的指纹加入：

- `providers.local.json`/`providers.json`/`MODEL_PROVIDERS` 的 effective hash（现有 `config_version` 可复用）；
- `pool.get_default_ref()`；
- registry 代数（每次 `replace_registry` 递增）。

#### 6.2.6 默认 vs 会话选择

按 5.4 落地：

1. `Session` 增加 `model_override_source`；旧 session 无字段且 override 非空 → 按 `"user"` 读取。
2. `_apply_session_model_override()` 显式 `model_change` 写 `"user"`；继承写 `"inherit"`。
3. `_new_session_model_override()` 只继承 `"user"`；否则 `None`（使用 live 默认）。
4. 新增 `POST /sessions/{id}/model`：`model=null` 清除 override；设置时校验 registry 可用性。
5. Composer 增加“默认模型”选项；`/api/v1/models` 的 `current` 用 session override 优先，否则 `pool.get_default_ref()`；同时返回 `current_source`（`session`/`default`）。
6. 删除/停用某个模型后，已有 override 保持并显示 `current_available=false`；不自动改写。

### 6.3 Phase 2：模型发现与元数据

#### 6.3.1 `POST /api/v1/providers/discover-models`

请求：

```json
{
  "base_url": "https://api.example.com/v1",
  "wire_protocol": "openai",
  "api_key": "sk-...",          // 可选；只写内存，不落盘
  "provider_id": "glm"          // 可选；使用已保存凭据
}
```

响应：

```json
{
  "candidates": [
    { "id": "glm-5.3", "name": "GLM-5.3", "context_window": 1000000,
      "max_output_tokens": 65536, "input_modalities": ["text"] }
  ],
  "diagnostics": null
}
```

实现：

- `openai`：`GET {base_url}/models`，Bearer key；解析 `data[]` 或 `models{}`；
- `anthropic`：API root 已以 `/v1` 结尾时用 `GET {base_url}/models?limit=1000`，否则 `GET {base_url}/v1/models?limit=1000`；`x-api-key` + `anthropic-version`；
- `google`/`lms-chat`：本阶段返回 `unsupported_protocol`，不猜测；
- 仅候选，不写入；用户勾选后由 `POST /providers`/`POST /models` 显式添加；
- 超时 10s、响应上限 2MB、候选上限 2000、禁止跨 host 重定向；
- 错误只返回 `type`/`status`/`timeout`/`unsupported_protocol`。

#### 6.3.2 模型元数据

`ModelSpec` 增加：

```python
name: str = ""
input_modalities: tuple[str, ...] = ()
```

解析规则：

- `input_modalities` 存在则使用；否则 `multimodal=True` → `("text","image")`，否则 `("text",)`；
- `multimodal` 保留为兼容字段，保存时与 input modalities 同步；
- `name` 用于 `/api/v1/models` 的 `display_name`，为空回退 `id`。

`/api/v1/models` 增加：

```json
{
  "default": "glm/glm-5.3",
  "current": "glm/glm-5.3",
  "current_source": "default",
  "current_available": true,
  "catalog": [
    {
      "id": "glm/glm-5.3",
      "provider": "glm",
      "provider_name": "GLM Coding Plan",
      "model": "glm-5.3",
      "display_name": "GLM-5.3",
      "context": 1000000,
      "max_input_tokens": 1000000,
      "max_output_tokens": 65536,
      "input_modalities": ["text"],
      "reasoning_capable": true,
      "reasoning_control": "always_on_effort",
      "reasoning_efforts": ["low", "high", "max"],
      "reasoning_default_effort": "max",
      "available": true
    }
  ]
}
```

保留 `models`、`current_available` 兼容字段。

#### 6.3.3 Provider 模板（Phase 3）

Phase 2 只做“从现有 Provider 复制”+“自定义端点”；Phase 3 再补内置模板：

- DeepSeek、OpenAI-compatible、Anthropic、LM Studio、Ollama、llama.cpp。
- 模板只填 base URL/protocol/默认模型，不自动拉取密钥、不自动保存。
- 不把模板当成“已验证可用”；仍由用户测试连接。

### 6.4 Phase 3：界面与 DSH 对齐

- `ModelControls` 用 `<optgroup>` 按 Provider 分组（最小改动），显示 `display_name`；后续可替换为可搜索的自定义菜单。
- 增加“默认模型”选项；选择后调用 `POST /sessions/{id}/model` 清除 override。
- 设置页拆成：
  - 顶部：全局默认模型 + 目录状态 + 刷新；
  - Provider 卡片列表；
  - “添加模型提供方”双模式：从模板/从自定义端点；
  - 每个 Provider 的模型表格（行内编辑/删除/测试）；
  - 高级折叠：原始 JSON 只读、Provider 默认模型、超时/预算。
- 移动端：卡片纵向堆叠，按钮保持可点；设置页不依赖横向表格。
- 可访问性：字段 label、错误 `aria-describedby`、冲突 banner 可聚焦、删除确认。

---

## 7. API 契约

### 7.1 快照

```text
GET /api/v1/providers
```

返回见 5.2。新增/保留：

| 字段 | 说明 |
|---|---|
| `default.model` | 配置默认（`.env`/`LLM_MODEL`） |
| `default.runtime_model` | 当前 live 默认 |
| `default.persistence` | `dotenv` / `external-env` / `process` |
| `default.applied` | 是否已对运行时生效 |
| `default.restart_required` | 仅部署级变化为 true |
| `providers[].runtime` | `effective`/credential 状态 |
| `providers[].models[].runtime` | `effective` |
| `providers[].models[].input_modalities` | 配置事实 |
| `providers[].models[].name` | 显示名 |

### 7.2 行级 PATCH

```text
PATCH /api/v1/providers/{provider_id}
```

```json
{ "expected_version": "sha256...", "enabled": false }
```

允许字段：`enabled`、`default_model`、`display_name`、`timeout_s`、`history_budget_chars`、`max_input_tokens`、`max_tokens`、`chars_per_token`。不允许改 `id`、`models`（用模型级端点）。

响应：完整快照（同 GET）。冲突：

```json
{ "error": "provider_config_conflict", "detail": "配置已变化，请刷新后重试。", "current_version": "sha256..." }
```

### 7.3 模型级 CRUD

```text
POST   /api/v1/providers/{provider_id}/models
PUT    /api/v1/providers/{provider_id}/models/{model_id}
DELETE /api/v1/providers/{provider_id}/models/{model_id}?expected_version=...&confirm=true
```

Body 使用 `ModelConfigInput`；`POST` 的 `model.id` 必须在 Provider 内唯一；`PUT` 支持改名（path 旧 id，body 新 id）。路由沿用现有 `{model_id:path}`，客户端必须对含 `/` 的模型 ID 做 URL 编码（如 `ornith-ai/Ornith-...`）。

删除/停用保护：

- 如果目标是全局配置默认或 live 默认 → 409 `default_model_cannot_delete` / `default_model_cannot_disable`；
- 如果目标是 Provider `default_model` → 409 `provider_default_model_cannot_delete` / `provider_default_model_cannot_disable`；
- 如果删除/停用后启用 Provider 没有任何启用模型 → 409 `provider_requires_model`。

### 7.4 默认模型

```text
POST /api/v1/providers/default-model
{ "model": "glm/glm-5.3" }
```

响应：

```json
{
  "default": {
    "model": "glm/glm-5.3",
    "runtime_model": "glm/glm-5.3",
    "configured_source": "dotenv",
    "persistence": "dotenv",
    "applied": true,
    "restart_required": false
  }
}
```

`model` 必须是全限定 `provider/model`，且能 `registry.resolve()`；否则 404 `model_not_found`。

### 7.5 模型发现

```text
POST /api/v1/providers/discover-models
```

见 6.3.1。返回候选，不持久化。

### 7.6 会话模型

```text
POST /api/v1/sessions/{session_id}/model
{ "model": "glm/glm-5.3" }
{ "model": null }   // 清除 override，回到默认
```

响应：

```json
{ "session_id": "...", "model": "glm/glm-5.3", "source": "user", "available": true }
```

### 7.7 错误码

| code | HTTP | 场景 | UI 行为 |
|---|---|---|---|
| `provider_config_conflict` | 409 | revision 过期 | 刷新快照；保留 draft |
| `provider_config_managed_by_env` | 409 | `MODEL_PROVIDERS` 拥有 | 只读提示 |
| `provider_not_found` | 404 | id 不存在 | 刷新列表 |
| `provider_exists` | 409 | 重复 id | 字段错误 |
| `model_not_found` | 404 | 模型不存在 | 刷新目录 |
| `model_exists` | 409 | 重复模型 | 字段错误 |
| `default_model_cannot_delete` | 409 | 删默认模型 | 先切换默认 |
| `default_model_cannot_disable` | 409 | 停用默认模型/Provider | 先切换默认 |
| `default_provider_cannot_disable` | 409 | 停用承载默认模型的 Provider | 先切换默认 |
| `provider_default_model_cannot_delete` | 409 | 删 Provider 默认模型 | 先改 Provider 默认 |
| `provider_default_model_cannot_disable` | 409 | 停用 Provider 默认模型 | 先改 Provider 默认 |
| `default_model_cannot_rename` | 409 | 改默认模型 id | 先切换默认 |
| `provider_test_failed` | 502 | 连接测试失败 | 显示类型/status/timeout |
| `discovery_failed` | 502 | 发现失败 | 显示类型/status |
| `unsupported_protocol` | 400 | 该协议不支持发现 | 手填模型 |
| `runtime_apply_failed` | 500 | Registry 应用失败 | 已回滚；重试 |
| `invalid_field` | 422 | 字段非法 | 字段级提示 |

422 保留 FastAPI 结构，但 UI 必须格式化 `detail[]`，不能 `String()`。

---

## 8. 兼容、迁移与回滚

### 8.1 配置兼容

- `providers.local.json` 继续作为完整本机快照；不改名、不改目录。
- `providers.json` tracked seed 仍只作为种子，不被 Web 修改。
- `MODEL_PROVIDERS` env 仍最高优先级；Web 只读。
- 新字段（`name`、`display_name`、`input_modalities`、`note`、`runtime`）全部可选；旧文件直接可读。
- 未知字段保留：Phase 1 给 Provider/Model 输入增加 `extra`/merge 机制，保存时保留未展示字段；Phase 0 先支持 `note`。
- `multimodal` 与 `input_modalities` 双向兼容：新写用后者，旧读用前者推导。

### 8.2 默认模型兼容

- 启动时仍读 `LLM_MODEL`；`_default_model_ref` 初始保持 `None`（继续使用启动 `default_client`），`get_default_ref()` 返回启动默认的 canonical 供展示。这样不会在启动时重建 client，也不会改变既有 env 参数语义。
- 旧 API 的 `restart_required` 字段保留，但在 live 默认下为 false；旧 UI 仍能渲染。
- 外部 env 拥有 `LLM_MODEL` 时，Web 默认写不持久化；返回 `persistence="process"`，不假装 durable。
- 多进程/多 worker：本设计只保证单进程控制面；`MODEL_PROVIDERS` 或外部 env 变化仍需重启。文档明确。

### 8.3 回滚

- Phase 0/1/2 各自独立 commit；回滚单个 commit 即可。
- 文件写入仍是原子替换；失败恢复旧 bytes；Registry 加载失败不提交。
- 默认模型切换先构造后提交；失败不改 live ref。
- 迁移不删除旧字段；不做不可逆重写。
- 回滚后旧版仍能读新文件（新字段被旧解析器忽略）。

---

## 9. 测试计划

### 9.1 先写 RED（按 DEVELOPMENT_REPAIR_SAFETY Step 3）

| RED | 断言 | 当前结果 |
|---|---|---|
| R1 前端投影 | `providerToInput(snapshot)` 不含 `effective`/`note` | 失败（含 `effective`） |
| R2 UI 形状 PUT | 后端接受 UI 投影 body，2xx | 失败（422） |
| R3 运行时字段拒绝 | 含 `effective` 的 body 返回 422 且 loc 含字段名 | 通过（契约保留） |
| R4 默认 live | `set_default_model` 后 `pool.get_client(None)` 使用新模型 | 失败（仍旧 client） |
| R5 模型级 UI | UI 调 `POST /models` 后目录出现新模型 | 失败（无 API 封装） |
| R6 422 可读 | UI 错误文本包含 `models.0.effective`，不是 `[object Object]` | 失败 |
| R7 跨标签 | 另一客户端写入后 SSE 推送 `providers_updated` | 失败（无事件） |

### 9.2 后端测试

`tests/web/test_provider_admin.py` 新增：

1. `test_replace_provider_accepts_ui_projection_without_runtime_facts`：用 `to_provider_config` 形状的 body，2xx；文件内容无 `effective`。
2. `test_replace_provider_rejects_runtime_facts_with_field_path`：body 含 `effective`，422，`detail[0].loc` 含 `effective`。
3. `test_patch_provider_enabled_keeps_models_and_reloads`：PATCH 停用；`/models` 消失；再启用恢复。
4. `test_add_model_endpoint_appears_in_catalog`：POST model；无重启；`/models` 含新 id。
5. `test_replace_model_rename_preserves_unknown_fields`：含 `note`，改名后 `note` 保留。
6. `test_delete_model_default_guards`：配置默认/live 默认/Provider 默认三种保护。
7. `test_set_default_applies_live_and_persists_dotenv`：`runtime_default_model` 新值；`restart_required=false`；`.env` 写入。
8. `test_set_default_external_env_is_runtime_only`：`LLM_MODEL` 来自外部 env；不写 `.env`；`persistence="process"`。
9. `test_default_change_does_not_override_existing_session`：旧 session override 不变；新 session 用新默认。
10. `test_new_session_inherits_only_explicit_override`：inherit source 语义。
11. `test_providers_updated_fingerprint_changes`：SSE 指纹变化。
12. `test_discover_models_openai_and_anthropic`：mock HTTP；候选解析；无持久化。
13. `test_discover_models_redacts_secret_and_bounds_response`：错误不含 key；超大/超时拒绝。
14. `test_unknown_model_fields_preserved`：`note`/`extra` round-trip。
15. `test_env_owned_readonly`（已有，保留）。
16. `test_conflict_returns_current_version`。

> **必须同步修改的旧测试**：`test_provider_admin_default_is_persisted_but_runtime_default_stays_startup_snapshot` 锁定的是旧语义（`restart_required=true`），Phase 1 要把它改成 live 断言，不能保留“旧测试绿 + 新行为未测”。`docs/api.md` 中“默认仍需重启”的说明也要同步更新。

### 9.3 前端测试

`webui/src/provider-admin.test.tsx` 新增/修改：

1. 编辑保存 body 不含 `effective`、`credential_*`、`runtime`。
2. 停用走 `PATCH`，body 只有 `enabled` + `expected_version`。
3. 添加模型走 `POST /models`，成功后目录事件触发。
4. 422 数组显示为可读字段错误。
5. 默认模型切换显示“已生效”，不出现“重启后生效”。
6. `providers_updated` 事件触发 `fetchModels` + provider snapshot 刷新。
7. “默认模型”选项清除 override。
8. 保存冲突保留 draft 并提供重新加载。
9. 编辑 DeepSeek 模型保留 `note`。

### 9.4 集成/隔离 live

不触碰用户 8903/live `.env`。使用：

- 临时数据目录 `LFL_DATA_DIR=/tmp/lfl-model-admin-<ts>`；
- 临时 `LFL_ENV_FILE`；
- 本地 fake OpenAI 端点（`/v1/models` + `/v1/chat/completions`），验证：
  1. 添加 Provider + 模型；
  2. `/api/v1/models` 出现；
  3. 发一条 chat，fake provider 收到请求；
  4. 修改模型 context/max_tokens，下一次请求生效；
  5. 设置默认，新会话使用；旧会话 override 不变；
  6. 停用 Provider，目录消失，当前选择显示不可用；
  7. 重启进程，配置与默认持久化；
  8. 全程无 422、无重启（除第 7 步验证持久化）。

### 9.5 门禁

按 `docs/DEVELOPMENT_REPAIR_SAFETY.md`：

- focused pytest（provider admin + LLM pool + routing + web routes）；
- 相邻 suite（provider/model/auth/queue/runtime manifest）；
- Ruff / Pyright / compile；
- WebUI Vitest + TypeScript + Vite build；
- 架构守卫（ratchet）；
- `git diff --check`；
- secret/绝对路径扫描；
- 最终在 staged candidate 或 isolated worktree 上执行，避免旧 HEAD 假绿。

---

## 10. 验收标准

- [ ] 1. 在 Web 添加一个自定义 Provider（Base URL + 协议 + 至少一个模型），保存成功，Composer 立即出现，无需重启。
- [ ] 2. 在已有 Provider 下单独添加模型，保存成功，目录立即出现。
- [ ] 3. 编辑 Provider 的 Base URL/超时/默认模型，保存成功；下一次请求使用新配置。
- [ ] 4. 停用/启用 Provider 与单个模型，保存成功；目录与 `current_available` 正确。
- [ ] 5. 删除模型/Provider 时，默认来源保护返回可操作 409；切换默认后可删除。
- [ ] 6. 设置全局默认后，`runtime_default_model` 立即等于新值；新会话使用，旧会话 override 不变；`restart_required=false`。
- [ ] 7. 选择“默认模型”清除会话 override；新建会话不再无条件继承旧 override。
- [ ] 8. 修改 API Key 后下一次请求使用新 key；响应/页面/日志无明文。
- [ ] 9. 422/409/502 显示字段路径与原因，不出现 `[object Object]`。
- [ ] 10. 跨标签页写入后 3 秒内目录收敛；不覆盖正在编辑的 draft。
- [ ] 11. `MODEL_PROVIDERS` env 存在时 Web 只读，写操作返回可解释 409。
- [ ] 12. 非法配置导致 Registry 加载失败时，文件与运行 Registry 回滚到修改前。
- [ ] 13. 现有 `providers.local.json`/`providers.json`/`LLM_MODEL` 兼容；DeepSeek `note` 不丢失。
- [ ] 14. focused/adjacent/full gates 在最终 candidate 上通过。

---

## 11. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 默认切换与在途请求竞争 | 在途 step 换模型/不一致 | 先构造后提交；在途持有旧 client；测试并发 |
| `engine.llm` 与 pool 默认分叉 | 辅助路径仍用旧模型 | Phase 1 主循环走 pool；回调/文档标注辅助路径；后续统一 |
| Registry 回滚后文件/运行不一致 | 用户看到旧/新混合 | `_apply_local_config` 先写后 reload；失败恢复 bytes；测试注入失败 |
| 未知字段被保存删除 | 手写配置丢失 | `note` + `extra`/merge；round-trip 测试 |
| 外部 env 拥有 `LLM_MODEL` | Web 默认无法持久化 | 明确 `persistence="process"`；不假装 durable |
| 多进程/多 worker | 其他进程默认不更新 | 文档标注单进程假设；部署级重启；后续 watcher |
| 发现端点 SSRF/大响应 | 资源/安全 | 仅认证用户；http/https；超时/大小/候选上限；禁止跨 host 重定向 |
| UI 仍回写运行时字段 | 422 复发 | 类型拆分 + body 断言 + 后端 422 字段测试 |
| 测试假绿 | 提交后才发现 | UI mock 断言 body；后端用 UI 投影；staged gate |

**回滚**：Phase 0/1/2 独立 commit；每阶段可单独 revert。配置格式只增不减；旧代码可读新文件。不做不可逆迁移。

---

## 12. 实施顺序与文件清单

### 12.1 提交边界

| 提交 | 内容 | 关键文件 | 门禁 |
|---|---|---|---|
| C0 | 修复 422 + 可读错误 + PATCH 启停 + `note` | `ProviderManager.tsx`、`api.ts`、`schemas.py`、`provider_routes.py`、`provider_admin.py`、测试 | focused + webui |
| C1 | 模型级 API 接入 UI + 目录事件 | `api.ts`、`ProviderManager.tsx`、`provider_routes.py`、`events.ts` | focused + webui + SSE |
| C2 | 默认模型 live + 会话默认语义 | `pool.py`、`routing.py`、`provider_admin.py`、`routes.py`、`session.py`、`ModelControls.tsx` | focused + adjacent + live |
| C3 | 模型发现 + 元数据 | `providers.py`、`provider_admin.py`、`routes.py`、`ProviderManager.tsx` | focused + webui |
| C4 | Provider 模板 + 分组选择器/移动端/文档 | `ModelControls.tsx`、`ProviderManager.tsx`、`docs/api.md` | webui + build |

### 12.2 文件清单

**后端**

- `src/llm_loop/web/schemas.py`：`note`、`display_name`、`input_modalities`、PATCH/session/discover 请求模型；字段校验。
- `src/llm_loop/web/provider_routes.py`：PATCH、模型级路由复用、discover、错误体。
- `src/llm_loop/web/provider_admin.py`：配置投影、`extra`/merge、live default、默认保护、错误体。
- `src/llm_loop/llm/providers.py`：`ModelSpec.name/input_modalities`、解析、未知字段保留。
- `src/llm_loop/llm/pool.py`：`_default_model_ref`、`get_default_ref`、`set_default_model`、`get_client(None)`。
- `src/llm_loop/core/loop/engine_services/routing.py`：默认路径走 pool；错误回退。
- `src/llm_loop/factory.py`：初始化 default ref；可选 `on_default_changed`。
- `src/llm_loop/web/routes.py`：`/models` 新字段；SSE `providers_updated` 指纹。
- `src/llm_loop/core/session.py`：`model_override_source`。
- `src/llm_loop/web/schemas.py`：`SessionModelRequest`。
- `docs/api.md`：API 语义更新。

**前端**

- `webui/src/core/api.ts`：类型拆分、PATCH、模型 CRUD、discover、错误归一。
- `webui/src/core/chat.ts`：`display_name`/`input_modalities`/`default`/`current_source`。
- `webui/src/components/layout/ProviderManager.tsx`：投影、PATCH、模型行、默认模型、错误。
- `webui/src/components/conversation/ModelControls.tsx`：默认选项、分组、不可用状态。
- `webui/src/core/events.ts`：`providers_updated`。
- `webui/src/core/stores.ts`：catalog/provider snapshot store（可选）。
- `webui/src/i18n/zh.ts`：新文案。

**测试**

- `tests/web/test_provider_admin.py`
- `tests/unit/test_model_pool_per_model.py` / 新 `test_model_default_live.py`
- `tests/unit/test_providers.py`
- `webui/src/provider-admin.test.tsx`
- `webui/src/provider-retry.test.tsx`（如涉及）
- `webui/src/model-controls` 相关测试

---

## 13. 开放问题（评审时确认）

1. **默认模型持久化位置**：继续用 `.env` 的 `LLM_MODEL`，还是新增 `data/model_defaults.json`？
   推荐 Phase 1 继续 `.env`（改动最小、启动兼容）；如果外部 env 托管 `LLM_MODEL` 的场景常见，再引入独立 JSON 并把 `.env` 仅作为启动 fallback。
2. **默认模型是否允许“仅本次运行”**：外部 env 拥有 `LLM_MODEL` 时，是拒绝设置（更严格）还是允许 runtime-only（更可用）？
   推荐允许 runtime-only，但 UI 明确标注，不写 `.env`。
3. **未知字段保留策略**：`extra` 字段 vs 服务端 merge。
   推荐服务端 merge（保留客户端未展示字段），`extra` 仅用于显式扩展；两者都要有大小/深度限制。
4. **是否在本期加入 `openai-responses`**：不建议；LFL client 未支持，属于独立协议扩展。
5. **是否同步 DSH settings**：不建议混入本设计；DSH 是独立运行时，跨运行时同步应另立设计（现有 `scripts/apply-dsh-config.sh` 仅人工桥）。
6. **模型发现是否允许私网**：允许（与 base_url 现有能力一致），但必须认证、限时、限量、禁跨 host 重定向。

---

## 附录 A：live 422 复现记录

环境：本机 LFL Web `127.0.0.1:8903`，当前 `providers.local.json` 配置。

请求（UI 投影形状，节选）：

```json
{
  "expected_version": "<config_version>",
  "provider": {
    "id": "cognilocal",
    "enabled": true,
    "base_url": "http://localhost:8901/v1",
    "api_key_env": "",
    "default_model": "qwen3.8-flash-next",
    "models": [
      { "id": "ornith-ai/Ornith-1.5-35B-A3B-MLX", "context": 65536, "effective": true },
      { "id": "qwen3.8-flash-next", "context": 65536, "effective": true }
    ]
  }
}
```

响应：

```text
HTTP/1.1 422 Unprocessable Entity
{"detail":[
  {"type":"extra_forbidden","loc":["body","provider","models",0,"effective"],
   "msg":"Extra inputs are not permitted","input":true},
  {"type":"extra_forbidden","loc":["body","provider","models",1,"effective"],
   "msg":"Extra inputs are not permitted","input":true}
]}
```

DeepSeek Provider 的模型还包含 `note`，同样命中 `extra_forbidden`。

结论：**UI 的 `...model` 展开 + 后端 `extra="forbid"` 是确定性冲突，不是环境偶发。**

## 附录 B：DSH 参考契约（本机安装包实测）

- `@deepseek-ai/dsh-client-ui-settings-models`：
  - Models 设置页 join provider directory / settings document / credentials；
  - 只持有 redacted descriptor，编辑通过 `settings.mutate` 路径操作 + revision；
  - API key 只写，派生 `<ROUTE>_API_KEY`；
  - 添加 Provider 双模式 + `llm/discoverModels`；
  - 模型行字段：id/name/contextWindow/maxTokens/input types/reasoning levels；
  - 保存后下一次请求生效，运行中 step 保持原选择。
- `@deepseek-ai/dsh-llm-pi-ai`：
  - `providers` 配置字典；`apiKeyEnv` 为凭据引用；
  - 配置按请求解析，settings 变化无需重启；
  - 自定义路由需要 `api`/`baseURL`/非空 `models`；
  - 发现模型只返回候选，不写入配置。
- `@deepseek-ai/dsh-agent-default-model`：
  - `currentSelection()` / `saveSelection()`；
  - 保存写入 active profile patch，对后续新建 agent 生效；
  - 已有 session 的选择优先。
- `@deepseek-ai/dsh-client-ui-model-selection`：
  - `/model` 与 Composer 共用 per-session directory；
  - `session.selectModel` 提交选择；
  - 运行中 step 保持启动时的选择；
  - 目录缺失的已选模型保持显示但不伪造可用。

## 附录 C：关键代码位置

| 位置 | 说明 |
|---|---|
| `webui/src/components/layout/ProviderManager.tsx:62` | `providerToInput` 展开模型对象（422 根因） |
| `webui/src/components/layout/ProviderManager.tsx:171` | `toggleProvider` 走整包 `replaceProvider` |
| `webui/src/components/layout/ProviderManager.tsx:395` | “+ 添加模型”只改本地 draft，保存走整包 |
| `webui/src/components/layout/ProviderManager.tsx:431` | “保存并热重载”按钮 |
| `webui/src/core/api.ts:1259` | `providerResult` 用 `String(detail)`（`[object Object]`） |
| `src/llm_loop/web/schemas.py:287` | `ProviderModelAdminInput(extra="forbid")` |
| `src/llm_loop/web/schemas.py:358` | `ProviderAdminProviderInput(extra="forbid")` |
| `src/llm_loop/web/provider_routes.py:60` | `_provider_input_to_raw` |
| `src/llm_loop/web/provider_admin.py:399` | `snapshot()` 生成运行时事实 |
| `src/llm_loop/web/provider_admin.py:540` | `_set_default_model_locked` 只写 `.env` |
| `tests/web/test_provider_admin.py:148` | 现有测试明确接受 `restart_required=true` |
| `docs/api.md:118` | 现存文档明确“默认仍需重启” |

## 附录 D：术语

| 术语 | 含义 |
|---|---|
| 配置事实 | 操作者声明、可持久化、可回写的字段 |
| 运行事实 | 进程当前状态（effective/credential/loaded），只读 |
| live default | 当前进程实际用于“无 session override”请求的默认模型 |
| 配置默认 | 持久化的启动默认（`.env` `LLM_MODEL`） |
| 目录 | `/api/v1/models` 返回的当前有效 Registry 模型集合 |
| Catalog membership | 模型必须出现在目录中，GUI 才允许选择/提交 |
| CAS | `expected_version` 与文件 hash 比较后再写 |
| 退休 client | `replace_registry` 后旧 client 保留给在途请求，最后引用释放后关闭 |
