# Web 通道剥离：M0 现状调查 + 设计草案

- Goal: GOAL-20261013-a36699bb
- 日期: 2026-10-13　状态: **M1 定稿**（grill_me 评审已过；D1-D6 用户已确认
  「按倾向定」2026-10-14T00:18，§3 决策记录、§4 验收门冻结）
- 动机: 中间件仓库与用户私域（浏览器 CDP / deepseek / chatgpt 账号）解耦；
  真机类验收（Phase6 候选 1 等）归独立项目。

## 1. 影响面全图（2026-10-13T23:35 实测，HEAD=0072fbc0c）

### 1.1 迁出候选（client 核 + 观测面）
| 文件 | 行数 | 角色 |
|---|---|---|
| llm_loop/llm/deepseek_{page,surface,protocol,transport,web}.py | 5 文件 | deepseek 页面自动化 client（相互依赖闭环） |
| llm_loop/llm/chatgpt_{page,surface,protocol,transport,web}.py | 5 文件 | chatgpt 页面自动化 client |
| llm_loop/runtime/chatgpt_binding_health.py | ~? | 观测聚合（prompt-neutral，读磁盘事实） |
| llm_loop/runtime/chatgpt_binding_notifications.py | ~? | 观测通知出口（observational only） |

注：两 client 核共享 `chatgpt_surface.BrowserSurfaceLeaseStore`（deepseek_web.py:402 引用）——
lease 基建随迁，两者本就一体。

### 1.2 中间件侧接缝（改造点，全部已核验）
1. **client 注册**: `factory.py:546-586` — `external_client_factories` 字典，
   enabled 时硬编码 import `build_{chatgpt,deepseek}_web_model_client`（r9-import-exempt: plugin）
   注册 lambda；`pool.py:63,102` 消费（字典已天然支持外部注入）。
2. **provider 目录**: `providers.py load_registry`（chatgpt ~1064-1115 / deepseek ~1119-1170）
   — enabled 时 import `*_MODEL_ID/*_PROVIDER_ID` 常量注册 ProviderSpec
   （browser:// base_url、context tokens、reasoning efforts、cost_tier=subscription）。
3. **观测面挂载**: `web/__init__.py:447-460`（enabled 时建 binding store + notifier）、
   `web/routes.py:103`（_chatgpt_binding_store）、`web/routes.py:3338+`
   （GET /api/v1/chatgpt-web/bindings/health）。
4. **配置**: `config.py:729-750`（chatgpt_web_* 10 字段 + deepseek_web_* 8 字段）、
   `config.py:868-884`（redacted/configured 输出）、`runtime/resolver.py` TomlField 全映射、
   `.env` DEEPSEEK_WEB_* / CHATGPT_WEB_*。

### 1.3 明确不迁（归属已判定）
- `resources/vendor_adapters/deepseek.py` — resources 域 RG-3E 事实归一（无网络 I/O），
  与页面自动化无关，名字撞车而已。
- tests/phase6/ 引擎侧测试（m0/m1/m3/m4/m5，FakeLLM 驱动）— 锁定引擎语义，留在中间件。
- `pool.py external_client_factories` 消费机制 — 剥离后的注册入口，留下。

### 1.4 测试清单（import 级，迁出候选）
unit 14: web_provider_settlement / deepseek_web_model_client / deepseek_page_surface /
transport_settled_facts / transport_prepared_facts / chatgpt_page_reasoning /
chatgpt_binding_health / chatgpt_page_send_collapsed / chatgpt_web_model_client /
chatgpt_page_send_transient / chatgpt_surface / deepseek_web_provider_registration /
chatgpt_web_provider_registration / chatgpt_binding_notifications
phase6 1: test_m2_web_cancel.py（W1-W4，测 web client cancel 语义）
web 2: test_deepseek_web_catalog.py / test_chatgpt_binding_observability.py

**M2 语义级修正（实测各测试被测对象后）**：
- **迁独立项目 14**（M2 已迁移，143 passed 含 3 契约测试）：12 纯 client unit
  （上表去掉 registration ×2）+ web_provider_settlement（client↔resources 集成，
  pip 依赖可跑）+ phase6 m2。
- **留中间件 M3 改写 4**：registration ×2（守卫中间件 load_registry/build_engine
  注册接缝，M3 改为外部注册模块注入断言）；catalog + observability（webui 挂载
  /目录端点，D1 删挂载后改为无挂载/注入暴露断言）。

## 2. 剥离架构

### 2.1 目标形态
独立项目 lfl-web-providers（新 git 仓，本地目录），包含：
- 两 client 核 10 文件 + 观测面 2 文件 + 全部 web 测试
- 自有配置（从中间件 .env 拆出 DEEPSEEK_WEB_* / CHATGPT_WEB_*）
- 自有真机验收脚本与文档（Phase6 候选 1 归属）
- 对中间件的依赖方向: 独立项目 → 中间件（可 import llm_loop 协议契约），反向为零

### 2.2 注册协议（中间件侧改造）
- `pool.py external_client_factories` 消费不变。
- `factory.py` 硬编码 import 段删除，改为可配置外部注册模块：
  settings.web_providers_module（如 "lfl_web_providers"），importlib 动态加载，
  模块暴露 register(registry_hooks, settings) → 返回 factories dict。
- **失败语义分级（grill 盲点修订）**: 未配置 → 静默空字典（合法形态）；
  配置了但 import/注册失败 → warning 日志（含原因）+ 目录不注册 web 条目，
  对齐 providers.py 既有 degraded 风格——不静默吞掉「用户明确想要 web client」的失败。
  模块名仅从 settings（.env/toml，用户自有环境）读取，不接受 web 请求/LLM 输入，
  不新增代码执行面。
- `providers.py load_registry` web 分支删除；web provider 目录条目改由外部注册模块
  经同一注册点供给（registry providers 可注入）或独立项目自带目录快照（D2 决策）。

### 2.3 协议契约面（grill 盲点修订，已核验 2026-10-13T23:40）
- **duck 协议（engine 侧零 import，已核验 engine.py:2011）**:
  `chat(messages, tools, *, timeout_s, model)` + `cancel()`（getattr 探测）+
  异常语义（打断轮丢弃，engine 不 import 任何 web 错误类）。
- **类型 import（M2 迁移实测修正，比 M0 初查的 3 符号宽——契约测试按 7 面覆盖）**:
  `core.message.ToolCall`、`core.run_context.current_reasoning_effort`
  （chatgpt 另有 `current_session_id`）、`llm.client.LLMResponse`、
  `llm.errors.LLMRequestTooLargeError`（两 transport）、`llm.notify.notify`
  （binding_notifications）、`llm_loop.timekeeping.system_local_now`
  （binding_health/notifications 函数内延迟 import）、
  `llm_loop.resources.content_digest.{resolve_content_hmac_key,normalized_response_hmac}`
  （两 web wrapper 函数内延迟 import）。除最后两项外全部为 M2 实测核验；
  timekeeping/content_digest 为 M0 漏记、M2 残留检查发现（合法依赖面，随迁不改）。
- **版本兼容策略**: 独立项目 pin llm-loop 版本 + 契约测试（对已安装 llm_loop 跑
  duck 协议 + 7 符号面冒烟，见上），中间件变更契约面时 bump 独立项目提示。
- test_m2_web_cancel.py 已核验纯 client 侧（无 engine import），可干净迁移；
  engine cancel 探测语义由 phase6 m1 S 系列（FakeLLM）锁定，不受迁移影响。

## 3. 决策记录（D1-D6，用户「按倾向定」2026-10-14T00:18）

| # | 决策 | 选定 | 落地含义 |
|---|---|---|---|
| D1 | 观测面归属 | **A 一并迁出** | binding_health/notifications 随迁；webui 删 `/api/v1/chatgpt-web/bindings/health` 路由与 store/notifier 挂载（`web/__init__.py`/`routes.py`） |
| D2 | provider 目录条目 | **A 外部注册模块运行时注入** | 中间件 `providers.py load_registry` web 分支删除；ProviderSpec（browser:// base_url、context tokens、efforts、cost_tier）由外部注册模块供给，单一事实源在独立项目 |
| D3 | 外部注册形态 | **A 配置模块名 + importlib** | `settings.web_providers_module`，显式配置、零魔法；失败语义分级见 §2.2 |
| D4 | 数据目录 | **移交独立项目** | `data/deepseek-web-provider/`、`data/chatgpt-web-provider/`（lease/sessions）磁盘路径不变、只换归属（独立项目配置指向同路径），既有 lease 连续性保持 |
| D5 | .env 清理 + 发布节奏 | **一次成型一次发布** | 中间件 .env 删 DEEPSEEK_WEB_*/CHATGPT_WEB_*（迁独立项目 .env）；接缝改造+删除+回归合并为一次发布（预期 gen255） |
| D6 | 独立项目环境 | **A 独立 venv + llm-loop pip 依赖** | 版本 pin（本地 path 依赖 + git_head 记录）+ 契约测试（§2.3 duck 协议 + 3 符号冒烟）；不共享中间件环境 |

## 4. 验收门（已冻结 2026-10-14T00:18）
- G1 全量回归绿（中间件，剥离后，预期 tests 计数下降 = 迁出量，0 failed）
- G2 中间件零 web 残留引用（grep deepseek_web/chatgpt_web import 级为 0，
  vendor_adapters/resources 除外）
- G3 独立项目测试绿（迁移后全部 web 测试）
- G4 注册协议往返: 未配置 → 目录无 web 条目、行为=enabled=0；配置 → client 可用
  （桩验证；真机验收留独立项目）
- G5 语义红线不破坏: Phase6 七条红线（chat_stream 零变化/Stop 四态/P1-6/单次结算/
  guard 无死锁/peek fail-open/配置门逃生舱）在中间件全量回归中保持

## 5. 里程碑
- M1 本文档定稿 ✅（grill_me 评审 + D1-D6 用户确认 2026-10-14T00:18）
- M2 独立项目脚手架 + 文件迁移 + 测试迁移（中间件侧不动）→ G3
- M3 中间件接缝改造（factory/providers/config/resolver/.env）+ 原件删除 → G2
- M4 回归 + 发布 + 双侧交付报告 → G1/G4/G5
