# LFL 鸿蒙原生智能体化评估 v2 —— "原生鸿蒙 Agent 应用 + 语言框架重构"可行性

- 日期：2026-10-11（Asia/Shanghai）
- 状态：分析建议（ANALYSIS_ONLY）；本文不表示任何方案已实现、已授权或已部署。
- 前置文档：`docs/ANALYSIS-20261011-harmonyos-lfl-assessment.md`（v1，结论为"接入优先、拒绝运行时移植"）。
- 本文修订前提：用户明确"看好鸿蒙生态，能原生成为鸿蒙 Agent 应用很有意义；必要时可重新考虑适合鸿蒙的语言框架重构"。评估目标由"是否接入"升级为"**是否值得做原生鸿蒙智能体应用，以及用什么语言/框架重构、重构到什么程度**"。
- 平台事实来源（华为开发者官方文档，2026-10 抓取）：HMAF 白皮书、鸿蒙智能体框架高阶方案、Agent Framework Kit、Intents Kit、鸿蒙编程语言白皮书（详见 §1 与文末来源）。
- 证据口径：**S**=读码/读官方文档确证；**H**=待验证（外部平台或本环境未复现）；**X**=结论性不推荐/不适用。

---

## 0. 结论摘要

**结论：原生鸿蒙智能体化"技术成立、平台有官方路径"，但"全量重构 LFL 内核"不划算；正确姿势是"平台接入 + 智能体外壳 + 内核渐进原生化"三层演进，语言上 ArkTS 与仓颉分工、C/C++ 仅用于热路径，Python 内核不作为被消灭对象而是收敛为 A2A/MCP 服务端。**

| 判断项 | v1 结论 | v2 修订结论 |
|---|---|---|
| A 运行时移植（Python harness 原样上鸿蒙） | 否决 | **仍不推荐（X）**；但"鸿蒙 PC 上跑 Python 服务"存在社区路径，可作过渡（§3.4） |
| B 能力接入（MCP/Skills 接入 DevEco CLI） | 主线 | **保留**，作为 L0 即时可做层 |
| C 原生客户端 | 以需求为门槛 | **升级为 L1"鸿蒙智能体外壳"**：应用 + Agent Framework Kit + Intents Kit + A2A，是"原生成为鸿蒙 Agent 应用"的官方落点 |
| D 能力反向供给 | 建议并行 | 保留（`export-serve-mcp`） |
| **E 语言/框架重构内核** | 未评估 | **新增：成立但须分层**。首选**仓颉 Agent DSL**承载 Agent 内核（官方"面向 LLM 智能体编程"+兼容 MCP+一码三端），**ArkTS** 承载 App/UI 与系统 Kit 集成，**C/C++** 仅热路径；**不做 1:1 全量重写** |

**一句话定位**：不是"把 LFL 编译成鸿蒙应用"，而是"**用鸿蒙官方智能体框架把 LFL 的差异化能力封装成一个可上架、可被小艺调度的原生鸿蒙智能体，并用仓颉/ArkTS 渐进重建其内核，Python 侧退化为 A2A/MCP 服务端**"。

---

## 1. 平台侧新事实（这是 v1→v2 判断改变的依据）

> v1 时我尚不掌握以下事实，故对"原生 Agent 应用"给了过低评价。以下均为官方文档确证（S）。

### 1.1 鸿蒙有第一方智能体框架 HMAF

- **鸿蒙智能体框架（HMAF）** 有独立白皮书；智能体定义 = "一种能够自主执行任务、提供智能服务的应用组件"，具备 Agent Card（身份/能力/技能元数据）、A2A 协议（智能体间通信：任务管理/消息传递/产物生成）、Artifact（可标识产物）等一等概念。（HMAF 白皮书 / Agent Framework Kit 术语）
- 能力分层开放：系统级 AI 能力跨"端、云、MCP、意图框架工具"。
- **小艺开放平台**是 Agent 与 Skill 的统一开放平台，提供四大开发模式：**LLM 模式 / 工作流模式 / A2A 模式（直连三方智能体）/ 多 Agent 模式**；覆盖开发→调试→评测→分发→运营→商业化全生命周期，多端调试（手机/平板/车机/PC/手表），成品上架智能体市场并接入系统入口（导航条/小艺搜索/小艺建议）。（高阶方案 §鸿蒙智能）

### 1.2 "原生成为鸿蒙 Agent 应用"有明确官方路径

- **Agent Framework Kit**：Function 组件 + A2A 协议模块。
  - Function 组件：应用内"拉起指定智能体"，把 App 与智能体组合成服务；
  - A2A 模块：应用内智能体可作为 **Client 或 Server** 与其它应用智能体（含小艺）交互——即**LFL 可作为 A2A Server 直连小艺**。
  - 约束：当前支持 Phone/Tablet；中国境内；不支持模拟器。（Agent Framework Kit 简介）
- **Intents Kit（意图框架）**：HarmonyOS 级意图标准体系，把应用/元服务功能分发到小艺对话/搜索/建议；支持 Phone/Tablet/PC/2in1；API 20+ 可用装饰器定义意图。
  - **关键约束：意图注册仅面向企业开发者**（个人开发者不可申请注册）。（Intents Kit 简介）
- **Skill** 是"AI Agent 可调用的标准化能力单元"，小艺开放平台提供 Skill 全生命周期（Vibe Coding / 本地导入 / 真机测试 / 一键发布 / 审核上架）。

### 1.3 鸿蒙是多语言生态，"适合鸿蒙的语言框架"有多个候选

| 语言 | 定位与关键能力 | 对 LFL 的意义 |
|---|---|---|
| **ArkTS** | 官方首选、TS 基础、声明式 UI（ArkUI）、并发（TaskPool/Worker/**Sendable** 共享对象）、标准库丰富 | App/UI、系统 Kit 集成、轻量编排层 |
| **仓颉 Cangjie** | 官方静态语言、高性能/强安全/跨平台；**原生 Agent DSL（面向 LLM 智能体编程：Agent 声明式配置、提示词模式、多 Agent 协同、多轮对话）**；**兼容 MCP 生态**；**一码三端（鸿蒙/Android/iOS/Windows/Linux/macOS）**；鸿蒙 7.0 商用、8.0 完备 | **Agent 内核重构的首选语言**：语言级支持正是 LFL 的领域 |
| **C/C++（NDK）** | 仅对性能密集/底层/生态兼容场景开放 | 可选热路径（如向量检索、压缩），非编排层 |

- ArkTS/仓颉/C/C++ 可互操作：ArkTS↔C++（Node-API）、仓颉↔C（`@C`/`foreign`/`@FastNative`）、仓颉↔ArkTS（`ohos.ark_interop` + `@Interop` 宏）。（编程语言整体框架）
- **Python/Go/Rust/Java/Julia** 由 **OpenHarmonyPCDeveloper 开源社区**支持在鸿蒙上开发——这改变了 v1"A 完全不可行"的边界（见 §3.4），但不改变"App 内无官方 Python 运行时"的结论。

### 1.4 端侧与执行能力

- 端侧推理：Kernel Enhance Kit 的"格物服务"提供 QoS 感知的端侧推理加速；系统提供 AI 能力分层开放。
- LFL 依赖的**网络流式调用**（HTTPS/SSE）在鸿蒙由 Network Kit 支持（HTTP/HTTPS/WebSocket）——鸿蒙端直接调模型 API 可行。
- **执行类能力不可移植**：LFL 的 shell/subprocess/文件锁/真实 Chromium-CDP（§2.2）在鸿蒙 App 沙箱内没有对应物，须改用鸿蒙原生 Kit 或保留服务端。

---

## 2. LFL 资产盘点与"重构画像"

> 规模事实：`src/llm_loop` **434 文件 / 162,528 行**；`tests/` **815 文件 / 186,213 行**。核心资产分布见下。

### 2.1 核心能力与模块归属（S）

| 能力 | 主要模块 | 重构属性 |
|---|---|---|
| LoopEngine 五阶段循环 | `core/loop/engine.py`(2641)、`lifecycle.py`、`runner.py`、`engine_services/`(23 服务) | **纯逻辑，可跨语言重写**（重写成本最高项） |
| strict function calling（C1-C6） | `core/message.py`、`llm/schemas.py`、`tools/registry.py` | 纯逻辑，可重写；契约须精确复刻 |
| 记忆/检索 | `memory/`(8071)、`introspection/search.py`(1232) | 算法可重写；**落盘层含 `fcntl` 锁** |
| 事件溯源 | `event_log/`(3976) | 格式清晰（JSONL），可跨语言重实现 |
| Method/Experience 学习平面 | `methods/`、`experiences/`、`core/loop/method_learning.py` | 纯逻辑为主 |
| self_eval / evolution | `introspection/evaluator.py`、`evolution*.py` | 纯逻辑为主 |
| Skills 加载 | `skills/loader.py`（`SKILL.md`） | 纯逻辑，可重写 |
| MCP 客户端 | `tools/mcp_client.py`(1500)、`mcp_transport.py` | 可重写；或用平台 MCP |
| LLM 调用层 | `llm/client.py`(3204)、`providers.py`(1232)、`errors.py`、`pool.py` | 协议逻辑可重写（SSE 解析/错误分类/fallback） |
| **OS 强耦合** | `browser/`(CDP)、`feishu/`、`web/`(FastAPI)、`runtime/service_control.py`(4446)、`tools/safety.py`、`tools/sandbox.py`、`tools/mcp_transport.py`(stdio) | **不可/极难移植**（见 2.2） |

### 2.2 平台耦合度分级（S）

- **可跨语言重写**：`semantic_logic/`、`eval/`、`task_quality/`、`methods/reflection.py`、`llm/errors.py`、`core/message.py`、`llm/schemas.py`。
- **依赖 Python 生态**：`httpx`(LLM/网页抓取)、`fastapi/uvicorn`(web)、`websockets`(CDP)、`lark-oapi`(飞书)、`trafilatura`(正文提取)、`pypdf`、`pycryptodome`、`zstandard`、`pyyaml`。
- **依赖 OS 特性（鸿蒙 App 内无对应）**：
  - `fcntl`/`flock` 文件锁：**36 个源码文件**（session/scheduler/event_log/memory/methods/experiences/runtime…）。
  - `subprocess`：MCP stdio、web_fetch、service_control、播放器等。
  - POSIX 信号/进程：`service_control.py`、`learning_runtime.py`、`web`、`feishu`。
  - **真实 Chromium + CDP**：`browser/*`、`llm/chatgpt_web.py`/`deepseek_web.py`（网页版 provider）。
  - 沙箱：`tools/sandbox.py`（bwrap/docker）；`tools/safety.py`（shell/python `-c` 载荷检查）。
- **数据契约**：会话 JSON（`version=5`，`messages[]` 结构化）、事件日志 JSONL（`event_id/session_id/seq/type/ts/payload`，48 类事件）、方法 `METHOD.md`（YAML frontmatter）、经验 `EXPERIENCE-*.md`、证据 ledger（blob+index）。
  - **注意：除 cache attribution 外，仓库没有覆盖 session/event/memory/method 的正式语言无关 JSON Schema**——重构前须先补"可迁移契约"（schema 化），否则跨语言重写无对齐基准。

### 2.3 重构画像小结

- **可带走**（跨语言重写）：循环状态机、FC 协议、记忆/检索算法、事件模型、学习/自省/演进逻辑、Skill/MCP 协议。
- **必须替换**（换鸿蒙原生 Kit）：网络（`httpx`→Network Kit / `@ohos.net.http`）、存储（→ArkData / 文件沙箱）、密钥（→Asset Store Kit）、并发（→TaskPool/Worker/仓颉并发）。
- **不能带走**（须服务端保留或重构语义）：真实 Chromium/CDP 浏览器操作、shell 执行、飞书长连接、POSIX 服务生命周期。
- **最大隐性成本**：**186,213 行测试**与大量行为契约。这些是 LFL 的"防退化资产"，重构若不带测试基线，等于放弃其工程信誉。

---

## 3. 语言与框架选型

### 3.1 三种候选的适配度（对照 LFL 能力需求）

| 维度 | ArkTS | 仓颉 Cangjie | Rust | C/C++ NDK |
|---|---|---|---|---|
| Agent/编排表达力 | 中（自己搭） | **高（原生 Agent DSL + MCP）** | 中（自建，生态成熟） | 低 |
| UI/系统入口集成 | **高（ArkUI/Kit）** | 中（经 ArkTS 互操作） | 低（须经 C ABI/Node-API 桥接） | 低 |
| 并发模型 | TaskPool/Worker/Sendable | 轻量线程+无锁并发 | 成熟（async/tokio/rayon） | 手写 |
| 跨平台复用 | 低（鸿蒙向） | **高（一码三端）** | **高（生态广，含 ohos target）** | 高（需自管） |
| 生态成熟度 | **高（TS/JS 兼容）** | 中（7.0 商用/8.0 完备，演进中） | **高（但非鸿蒙一等）** | 高但门槛高 |
| 鸿蒙官方地位 | **一等（首选）** | **一等（静态语言首选）** | 社区（OpenHarmonyPCDeveloper） | 一等（NDK） |
| 适合承载 | App/UI + 薄编排 | **Agent 内核** | native 内核/跨平台引擎 | 热路径/算法库 |

### 3.2 推荐分工

- **Agent 内核（循环/记忆/工具编排/学习闭环）→ 仓颉**：官方 Agent DSL 正是"面向 LLM 智能体编程"，且兼容 MCP、一码三端——既贴合 LFL 领域，又不把内核永久锁死在鸿蒙。**这是 v2 相对 v1 最重要的新增判断。**
- **App/UI 与系统能力集成（会话界面、意图、卡片、拉起智能体、密钥/存储/网络）→ ArkTS**。
- **热路径（向量检索、压缩、复杂解码）→ C/C++ 可选**，非必需。
- **Python 侧不删除**：浏览器自动化、shell 执行、飞书桥、本地大规模文件/进程编排等"OS 强耦合能力"保留为 **A2A/MCP 服务端**，由鸿蒙端调用。

### 3.3 为什么不建议"直接用 ArkTS 全量重写"

ArkTS 生态友好、UI 强，但 LFL 内核是"无 UI 的并发编排 + 大量结构化数据契约"，用 ArkTS 自建 Agent 编排会重复造 HMAF/仓颉 DSL 已经提供的东西，且跨平台复用差。

### 3.4 "在鸿蒙 PC 上跑 Python 服务"（过渡路径）

官方白皮书列明 Python 由 **OpenHarmonyPCDeveloper 开源社区**支持在鸿蒙上开发（H，非官方 App 运行时）。这使"A 方案"从"完全不可行"变为"PC 场景下可作过渡"：短期可用鸿蒙 PC 承载现有 Python LFL 服务 + 与其上的 L1 智能体外壳通信。但 LFL 的原生依赖（`lark-oapi` 等）是否可在该社区运行时可用仍是 **H**，不可当作既定事实。

### 3.5 Rust 作为重构语言的适配性（追问）

**结论：Rust 不适合做"鸿蒙 App 的主语言"，但适合做"跨平台、无 UI 的内核/引擎"实现语言；对 LFL，它与仓颉定位重叠，需按"是否需要跨平台复用 + 团队语言能力"二选一。**

官方事实依据（S）：

- **鸿蒙官方主语言只有 ArkTS / 仓颉 / C/C++**；**Rust 被列入"其他编程语言"，官方支持方式是 OpenHarmonyPCDeveloper 开源社区**（与 Python/Go/Java/Julia 并列）——即**非一等公民、社区支持**。
- **NDK 官方只覆盖 C/C++**（libc/libc++/Node-API/FFRT/zlib/Drawing 等），没有 Rust 的一等构建链或绑定。Rust 要进 App，须自行编为 `cdylib`/`staticlib`，经 **C ABI + Node-API** 封装成 ArkTS/仓颉可调用的 native 模块——**可行，但非开箱即用，胶水自建**。
- 官方"跨平台开发解决方案"清单（Flutter、RN、KMP/CMP、Cordova、Ionic、Chromium、CEF、Electron、Qt、Taro、uni-app、Lynx、Hippy、ArkUI-X）**不含 Rust**——Rust 不在官方 App 跨平台生态重点内。
- Rust 在鸿蒙更多落在**系统/设备/native 层**（官方博客有"鸿蒙 OS 之 Rust 开发""以 Rust 调用 HiLog"）。Rust 有 `*-unknown-linux-ohos` target，可编到 OpenHarmony/HarmonyOS native 层（**H**，商用设备与 DevEco 构建/签名/上架链路的成熟度待验证）。

对 LFL 分层判断：

- **L2 App/UI/系统入口**：Rust **不适合**（用 ArkTS）。
- **L1 智能体封装（Agent Card/Skill/意图/A2A 上架）**：由鸿蒙平台侧承担，Rust 无从直接受益。
- **L0/L2 内核（循环/记忆/检索/事件/协议）**：Rust 与仓颉都"可"，差异见下表。
- **热路径（向量检索/压缩）**：Rust 与 C/C++ 都合适。

Rust vs 仓颉（内核二选一）：

| 维度 | Rust | 仓颉 Cangjie |
|---|---|---|
| 鸿蒙官方地位 | 社区（非一等） | **官方一等（静态语言首选）** |
| Agent 语言设施 | 无（需自建编排） | **原生 Agent DSL + MCP 兼容** |
| 与 ArkTS/系统集成 | 自建 C ABI/Node-API 胶水 | 官方 `@Interop` 宏 + DevEco 自动生成胶水 |
| 上架/工具链红利 | 无 | **DevEco / 小艺生态原生** |
| 生态/人才/库成熟度 | **成熟、广** | 新兴 |
| 跨平台 | **最广（含 ohos target）** | 一码三端（鸿蒙/Android/iOS/Win/Linux/macOS） |
| 对 LFL 团队的迁移成本 | 取决于团队 Rust 能力 | 新语言 |

**建议**：

- 若目标是"**原生鸿蒙智能体应用**"、接受鸿蒙优先 → **内核用仓颉**，Rust 仅在热路径可选。
- 若首要诉求是"**一套内核跨多平台复用**"、且团队 Rust 能力更强 → 可用 **Rust 写引擎，ArkTS（可选仓颉）做壳**；但须接受不享受鸿蒙官方 Agent DSL/上架红利，并自建 Node-API 桥接与构建链。
- **无论哪种，都不建议用 Rust 做 App 层**。

**待验证（H）**：Rust `ohos` target 在 HarmonyOS NEXT 商用设备 + DevEco 构建/签名/上架链路中的实际可行性。

---

## 4. 目标架构（混合三层）

```
┌──────────────────────────────────────────────────────────┐
│ L2 鸿蒙原生 App（ArkTS/ArkUI）                              │
│  · 会话 UI、卡片、意图(Intents Kit)、拉起智能体(AFK Function)│
│  · 系统入口（小艺对话/搜索/建议）                            │
├──────────────────────────────────────────────────────────┤
│ L1 鸿蒙智能体（HMAF）—— 上架小艺开放平台/智能体市场           │
│  · Agent Card / Skill 集 / 意图Schema                      │
│  · 与其他智能体经 A2A 协作；可作 A2A Client 或 Server        │
├──────────────────────────────────────────────────────────┤
│ L0 能力后端（可 Python / 可仓颉，先服务后原生）             │
│  · 现有 LFL：循环/记忆/经验/方法/证据/自省 经 MCP/A2A 暴露   │
│  · 浏览器自动化/CDP、shell 执行、飞书桥（OS 强耦合，留服务端）│
└──────────────────────────────────────────────────────────┘
演进：L2 先做（薄）→ L1 封装（中）→ L0 内核按能力链渐迁仓颉（重、长期）
```

**职责边界一句话**：**平台能力（意图/入口/A2A/Skill）交给鸿蒙；Agent 智能（记忆/经验/方法/证据/自省）是 LFL 的护城河，逐步原生化；OS 强耦合能力留在服务端，绝不硬塞进 App 沙箱。**

---

## 5. 重构范围分级（先做 / 缓做 / 不做）

| 级别 | 内容 | 理由 |
|---|---|---|
| **P0 立即可做（不改内核）** | L0 接入（MCP 装 DevEco CLI/小艺工具）；L1 智能体外壳 + Agent Card + Skill 化；补"语言无关契约 schema" | 低成本、可回滚、先验证平台资质与收益 |
| **P1 值得做（新增原生层）** | L2 ArkTS App：会话/记忆浏览/事件时间线/A2A 客户端；仓颉 Agent DSL 承载"会话内编排"试点 | 发挥平台优势，不触碰全部 43 万行 |
| **P2 长期择机** | 将记忆/方法/学习闭环内核用仓颉逐能力链重写（带测试基线） | 价值高但成本高，须以能力链为单位、可独立验收 |
| **不做（X）** | 1:1 全量重写 43 万行；把浏览器 CDP/shell 执行搬进 App；为鸿蒙单点新增硬门禁或私有执行器 | 收益递减、违背"程序最小化"与 admission asymmetry |

**验收原则（沿用 `docs/DEV*` 与仓库纪律）**：以能力链为单位、逐条独立验收；重构必须携带对等测试基线；"接入成功/连通"≠"模型会用/有收益"（分连通/检索/采用/收益四验收面）。

---

## 6. 关键待验证闸门（决定路线成立与否，均标 H）

| 闸门 | 问题 | 影响 |
|---|---|---|
| **G1 开发者资质** | 意图注册、智能体上架是否要求**企业开发者**（Intents Kit 已明确"仅限企业"）？ | 决定 L1 能否落地；个人开发者可能被挡在意图/上架之外 |
| **G2 A2A 接入约束** | 小艺开放平台"直连三方智能体(A2A 模式)"是否允许外部自建 LLM 循环的 Agent 接入？协议与准入条件？ | 决定"LFL 作 A2A Server 挂小艺"的可行性 |
| **G3 仓颉成熟度** | Agent DSL / MCP 兼容 / 一码三端在 7.0 商用的实际完备度；生态与文档成熟度 | 决定 L2 内核重构的可行性 |
| **G4 DevEco CLI 平台** | DevEco CLI 是否仅鸿蒙 PC 运行（v1 遗留闸门） | 决定 L0 是异机接入还是需在鸿蒙 PC 部署 |
| **G5 端侧模型策略** | 是否必须端侧推理（格物服务），还是允许纯云端 LLM API？ | 决定隐私/成本架构 |
| **G6 合规与许可** | 上架审核、数据合规（中国境内）、DevEco/小艺工具链的使用与分发许可 | 决定能否商业化 |

**纪律**：以上均为外部平台事实，不得按本仓库既有代码或本文推断当作既定事实（对齐 `AGENTS.md`）。

---

## 7. 分阶段路线（每阶段可独立验收、可回滚）

1. **阶段一（P0，异机/本仓即可）**：L0 接入 + 契约 schema 化
   - MCP 接入 DevEco CLI；梳理 session/event/memory/method 的语言无关 schema（当前缺失，是重构前提）。
   - 产出：接入回执 + 工具清单 + schema 草案。
2. **阶段二（P1，鸿蒙侧）**：L1 智能体外壳
   - 定义 Agent Card/Skill/意图 Schema；在 App 内用 AFK Function 拉起；打通 A2A（LFL 先作 Server）。
   - 产出：可在真机拉起、被小艺调度、与其他 Agent 协作的最小闭环。
3. **阶段三（P1/P2）**：L2 ArkTS App
   - 会话/记忆/事件时间线 UI；与 L0 后端经 MCP/A2A。
4. **阶段四（P2，长期）**：内核仓颉原生化（逐能力链）
   - 先在仓颉 Agent DSL 中试"会话编排"链，再按记忆→方法→学习闭环分批迁移，每批带对等测试。
5. **并行**：D（`export-serve-mcp`）向鸿蒙生态供能。

**明确不做**：1:1 全量重写；把 OS 强耦合能力搬进 App；为鸿蒙单点新增硬门禁。

---

## 8. 风险清单

- **资质风险（最高）**：企业开发者门槛可能直接决定"原生智能体应用"是否可达（G1）。
- **重构风险**：43 万行 src + 18.6 万行 tests，若无契约 schema 与测试基线，重构会丢失 LFL 的工程信誉（这正是其护城河）。
- **平台锁定风险**：仅用 ArkTS 全量重写会锁死鸿蒙；用仓颉（一码三端）可显著缓解。
- **能力错配风险**：浏览器 CDP/shell 执行是 LFL 关键能力，App 沙箱内无法承载，须明确"服务端保留"。
- **验证陷阱**：把"上架/连通"当成"智能体有价值"。

---

## 9. 结论

1. **"原生成为鸿蒙 Agent 应用"值得做且平台有官方路径**（HMAF + 小艺开放平台 + Agent Framework Kit + Intents Kit），这是 v2 相对 v1 的实质升级。
2. **但"适合鸿蒙的语言框架重构"不等于"全量重写"**：正确策略是 **ArkTS（App/系统集成）+ 仓颉 Agent DSL（Agent 内核，长期）+ C/C++（热路径）**，Python 内核收敛为 **A2A/MCP 服务端**。
3. **LFL 的护城河（记忆/经验/方法/证据/自省）应作为"原生化的核心资产"**，而 OS 强耦合能力（浏览器/shell/飞书）留在服务端。
4. **第一步不是写代码，而是解 G1-G3**：开发者资质、A2A 三方接入准入、仓颉 Agent DSL 成熟度。在此之前，投入应保持在"可验证、可回滚的接入与外壳"范围。
5. **重构前置动作**：先补齐 session/event/memory/method 的**语言无关 schema**（当前缺失），否则跨语言重写无对齐基准。

---

## 附：来源

- 鸿蒙智能体框架白皮书（HMAF）：https://developer.huawei.com/consumer/cn/doc/guidebook/ai-agent-0000002355199797
- 高阶解决方案 · 鸿蒙智能（小艺开放平台/Agent Framework Kit）：https://developer.huawei.com/consumer/cn/doc/guidebook/solution-0000002784570841
- Agent Framework Kit 简介：https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/hmaf-introduction
- Agent Framework Kit 术语（Agent/A2A/Agent Card/Artifact）：https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/hmaf-glossary
- Intents Kit 简介（意图框架，仅企业开发者）：https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/intents-introduction
- 意图框架概述（配置/装饰器开发方式）：https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/insight-intent-overview
- 鸿蒙编程语言整体框架（ArkTS/仓颉/C++/互操作/社区语言）：https://developer.huawei.com/consumer/cn/doc/guidebook/programming-language1-0000002593254720
- 鸿蒙编程语言演进策略（仓颉 AgentDSL、一码三端）：https://developer.huawei.com/consumer/cn/doc/guidebook/programming-language3-0000002593094802
- 代码事实：本仓库 `pyproject.toml`、`src/llm_loop/**`、`README.md`、`docs/DESIGN-20261009-plugin-ecosystem-integration.md`