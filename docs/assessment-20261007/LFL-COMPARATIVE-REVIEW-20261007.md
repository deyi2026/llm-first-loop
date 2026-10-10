# LFL 系统性审查与主流 Agent/Harness 横向对比分析

- **审查对象**：LLM-First Core Loop（LFL），仓库 `llm-first-loop-mirror`，版本 `0.6.27`（HEAD `98d1ce90e`）
- **报告日期**：2026-10-07（初版 r1）｜ 2026-10-10（**修订 r2**）｜ 2026-10-10（**修订 r3：评审修正**）
- **对比口径**：分层对比（Agent 框架层 / 执行 Harness 层 / 评测框架层）
- **评分体系**：10 维加权（权重公开于 §4.1）
- **资料声明**：LFL 事实来自本地只读代码审查；对比对象事实优先联网核实（GitHub 页面 / 官方文档，2026-10-07），无法联网核实的条目在文中以 *(知识库，未联网核实)* 标注。
- **修订 r2（2026-10-10）**：LFL 在 10-09~10-10 有大量更新——**插件生态 P1-A~P2-B**（Agent Plugins 标准包 / MCP 全套 / 厂商适配器 / git·archive 安装源 / registry 发现）、**method 生命周期闭环 v2.2**、**方法/经验消费证据链**、**Docker 沙箱后端**。评分与结论已按最新 HEAD 修订。逐项修订与证据见 **§4.5**。
- **修订 r3（2026-10-10，评审修正）**：① §2.4 技术债事实刷新（行数按 2026-10-10 实测；端口文档已修正、该条删除；版本面聚焦 tag 滞后）；② 扩展性 9→8——r2 按「能力存在」给 9，r3 按「能力被外部消费」口径回调：`extension_*` 工具面未接线、无真实插件全链路，9 分门槛 = 工具面接线 + 真实插件跑通；总分 72.9→**71.7**；③ 移除跨层排名表述（生态维度对个人项目近似常数惩罚，跨层分数不可通约）；④ P0-2 出向出口重排：**MCP server 导出优先**于 OpenAI 兼容出口；⑤ 新增 P1-6 消费率闭环、P1-7 对外版本承诺；⑥ P0-1 补 Python 支持策略前置决策。

---

## 0. 执行摘要

LFL 是一个**架构野心与技术纪律都远超「个人项目」的 LLM 优先 Agent 运行时**。它的差异化不在功能清单的堆叠，而在于三件主流框架普遍缺失的东西：**AI 自主演进闭环（自评 → 建议 → 分级执行 → 审计）**、**事件源化单一真相源 + 双轨逐字段对账**、以及**预注册/冻结/对照/Wilson CI 级别的实证研发纪律**。这三项在本次对比的全部对象中，**没有第二个项目同时具备**。

但横评的结论同样清晰：**若以「可被主流社区采纳的通用 Agent 框架」为标准，LFL 初版加权总分 66.7；经 10-09~10-10 的生态补全修订为 72.9（r2），r3 评审按「能力被外部消费」口径将扩展性回调至 8，总分 71.7**。核心矛盾未变——**生态与社区（2→3）、易用性（4→5）** 仍是相对短板，这轮补齐了**扩展性（7→8，能力面已齐、消费面未接线）**与**安全性（7→8）**：MCP 从「固定旧协议 + stdio」升级为「双时代协议 + 三传输 + OAuth + resources/prompts」，并新增标准插件包与主流工具链适配器。剩余硬门槛仍是**未上 PyPI、无对外出口（MCP server 导出 / OpenAI 兼容）、无外部贡献者**。

一句话定位：**LFL 已从「单机高精度研究仪器」补齐为「具备标准生态接入能力的研究级运行时」，但尚未成为「即插即用的工程组件」**——它把「Agent 长期记忆 + 自我改进 + 可审计」这条最难的路走通了并首次对齐了 MCP 生态标准，接下来的瓶颈仍是**把内部资产产品化并对社区开放**。

> **读表口径（r3）**：下表按加权总分排列，仅供维度剖面参照。生态与社区维度实际测量「成立时间 × 组织化投入」，对个人维护的项目近似常数惩罚；框架 / Harness / 评测三层的分数不在同一可通约空间，**排名顺序不构成「谁更好」的结论**。

| 分层 | 代表 | 加权总分（满分 100） |
|:--|:--|:--:|
| 框架层 | Pydantic AI | **85.3** |
| 框架层 | LangGraph | 80.4 |
| Harness 层 | OpenHands | 79.9 |
| Harness 层 | Claude Code | 79.1 |
| 框架层 | OpenAI Agents SDK | 78.1 |
| **LFL（r3 修订）** | **LLM-First Core Loop** | **71.7** ▲ |
| 框架层 | CrewAI | 68.9 |
| Harness 层 | Aider | 68.6 |
| Harness 层 | SWE-agent | 64.6 |
| 框架层 | AutoGen（维护模式） | 62.4 |

---

## 1. 审查对象与口径

### 1.1 LFL 项目档案

| 项 | 内容 | 证据 |
|:--|:--|:--|
| 全称 | **LLM-First Core Loop**（包名 `llm-first-loop`） | `pyproject.toml:2-4`、`README.md:1` |
| 定位 | 「AI 优先」（LLM-first）的 **Agent 运行时 / Harness**；程序最小化 + 文档规则驱动 + AI 自主演进闭环 | `README.md:9` |
| 目标 | 大模型是核心，架构主线 = **消息进 → 理解 → 行动 → 真诚回答 → 记住**；程序是辅助大模型的「感官 + 手脚」，不是约束 | `README.md:5-25` |
| 技术栈 | Python ≥3.13、FastAPI、httpx、uv 锁定；前端 React 18 + TS + Vite | `pyproject.toml:5-15`、`webui/package.json` |
| 规模 | `src` 399 个 py / **146,959 行**；测试 **801 文件**（r2 复核 10-10，r1 为 738）/ 7,215 用例（r1 计数）；`docs` 732 文件 | 本地 `find/wc`、探索代理 |
| 核心功能 | 五阶段状态机、严格 function calling（C1-C6）、事件源化、记忆/检索/证据、方法学习闭环、自评/演进、SubAgent、浏览器、工作区、多 provider | `src/llm_loop/` 各子系统 |
| 三端接入 | CLI、Web（FastAPI，实际默认端口 **8903**）、飞书桥；共享同一 `build_engine` 装配路径 | `README.md:104`、`web/__init__.py:385`、`feishu/__init__.py:50-61` |
| 许可 / 发布 | Apache-2.0；**未发布 PyPI**（`release.yml` 仅 GitHub Release 草稿） | `LICENSE:2`、`.github/workflows/release.yml` |
| 发展阶段 | **开源框架化「B 路线」进行中**；P1/P2/P3 基本完成，唯一明确缺口是 PyPI 发布 | `README.md:3`、`docs/ROADMAP-B-20260814.md` |
| 资料范围 | 公开面仅 10 份文档（`docs/INDEX.md`）；`evals/`、`data_ab/`、`papers/`、根目录 26 个 `*.swe-*.json` 为本地实验存档（多未纳入 git） | `docs/INDEX.md`、探索代理 |

**阶段判定**：功能层面处于**「准成熟（functional-mature）」**——核心闭环、多端、多模型、评测、事件溯源均已可用；产品/社区层面处于**「早期（early）」**——无包发布、无外部用户、文档内面为主。

### 1.2 对比对象清单与选择依据

按用户指定的**三层结构**选取每层最具代表性、且与 LFL「Agent 运行时/Harness」定位可比的样本：

| 层 | 对象 | 选择依据 | 已核实公开事实（2026-10-07） |
|:--|:--|:--|:--|
| **框架层** | **LangGraph** | 最主流的低层有状态编排框架，LFL 的直接同类 | 42.8k★/7.3k fork/7,140 commits，MIT；durable execution + HITL + memory + LangSmith |
| 框架层 | **OpenAI Agents SDK** | 官方轻量原语派代表，生产级 | 原语少（Agent/Handoff/Guardrail）；Sandbox agents、Realtime/Voice、Sessions（SQLAlchemy/Redis/MongoDB/Dapr/Encrypted）、MCP、内置 tracing |
| 框架层 | **Pydantic AI** | 类型化 + capability 组合派，含官方 Harness | 100% 覆盖率；capabilities 抽象；Harness（Coder/Researcher）；8 种持久化执行引擎；OTel/Logfire；Gateway 成本控制；独立 Evals |
| 框架层 | **CrewAI** | 多智能体「crew + flow」高抽象派 | 多智能体协作、guardrails/memory/knowledge/observability、企业平台与触发器 |
| 框架层 | **AutoGen** | 多智能体先驱，**但已进入维护模式** | 61.3k★/9.3k fork/3,782 commits；**maintenance mode，官方推荐迁移至 Microsoft Agent Framework (MAF)** |
| **Harness 层** | **OpenHands** | 开源编码 Agent 全栈（SDK+Server+Canvas+Cloud） | 组件化 SDK + Agent Server + Agent Canvas + Cloud/Enterprise + Sandbox Server + benchmarks |
| Harness 层 | **SWE-agent** | SWE-bench 参考实现，学术标准 Harness | Princeton 出品；面向 GitHub issue 修复；沙箱执行 *(知识库，未联网核实)* |
| Harness 层 | **Aider** | 终端结对编程标杆 | **44K★、6.8M 安装、15B tokens/周**；repo map、git 集成、110+ 语言、lint/test 自动修复、语音 |
| Harness 层 | **Claude Code** | 商业闭源 Harness 事实标准 | 编码为主；subagents/skills/MCP/hooks；高采纳度 *(知识库，未联网核实)* |
| **评测层** | **Inspect AI** | 前沿评测框架（UK AISI + Meridian） | 200+ 预置评测；dataset/solver/scorer 组合；agent 评测；沙箱（Docker/K8s/Modal/Proxmox/Vagrant）；20+ provider；VS Code 扩展 |
| 评测层 | **promptfoo** | 提示/模型评测与红队主流工具 | 声明式配置、CI 集成 *(知识库，未联网核实)* |
| 评测层 | **LangSmith** | 可观测 + 评测平台 | 与 LangGraph/LangChain 深度集成，trace/eval *(知识库，未联网核实)* |
| 评测层 | **SWE-bench** | 软件工程 Agent 基准事实标准 | F2P∧P2P 判定、Docker 化 *(知识库，未联网核实)* |

> 说明：AutoGen 保留在清单内是因为它是被广泛引用的「多智能体框架」基线，但**其维护模式状态本身就是一个对比结论**（见 §3.1）。

### 1.3 评分维度、权重与评分标准

采用 10 维加权（满分 100），**权重按「Agent 运行时/Harness」定位设定**，偏向可复用性、可扩展性与工程质量：

| # | 维度 | 权重 | 1-3 分 | 4-6 分 | 7-8 分 | 9-10 分 |
|:--:|:--|:--:|:--|:--|:--|:--|
| 1 | 功能完整性 | 15 | 单一场景 | 覆盖主要场景 | 覆盖广且深入 | 全场景 + 独特能力 |
| 2 | 架构设计 | 12 | 紧耦合 | 分层一般 | 清晰可演进 | 有理论依据 + 可验证 |
| 3 | 易用性 | 10 | 难以上手 | 需较多配置 | 文档好、分钟级上手 | 零门槛 + 生态工具 |
| 4 | 扩展性 | 12 | 无扩展点 | 有限扩展 | 稳定 API + 插件 | 多轨扩展 + 标准协议 |
| 5 | 性能与效率 | 8 | 慢/耗资源 | 一般 | 有优化机制 | 自适应 + 可观测调优 |
| 6 | 生态与社区 | 12 | 无社区 | 小圈层 | 活跃社区 | 头部生态 + 大量使用者 |
| 7 | 安全性 | 8 | 无防护 | 基础防护 | 多层防护 + 审批 | 沙箱隔离 + 完备审计 |
| 8 | 工程化 | 10 | 无 CI/测试 | 有基础测试 | CI + 门禁 | 多层门禁 + 方法论 |
| 9 | 成本控制 | 5 | 无 | 可换模型 | 成本路由 | 预算/网关治理 |
| 10 | 适用场景广度 | 8 | 单点 | 少数场景 | 多场景 | 通用 + 多模态 |

**加权总分 = Σ(维度得分 × 权重) ÷ 10**（每维 1-10 分，加权和除以 10 归一到 100）。评分理由逐项列于 §4.3。

### 1.4 资料可信度声明

- **已联网核实**：LangGraph、AutoGen、CrewAI、Pydantic AI、OpenAI Agents SDK、OpenHands、Inspect AI、Aider（GitHub/官方文档，2026-10-07）。GitHub API 因限流（403）不可用，星标数取自仓库页面。
- **未联网核实（知识库）**：SWE-agent、Claude Code、promptfoo、LangSmith、SWE-bench。相关结论用于定性对比，不用于关键分差。
- **时效性**：生态数据（星标、版本）随时间变化，本报告为 2026-10-07 快照。

---

## 2. LFL 现状与成熟度评估

### 2.1 架构与功能盘点

- **核心循环**：`LoopEngine` 五阶段状态机（`core/loop/engine.py:619` 起），Mixin（Build/Events/Kpi/Lifecycle）+ 20 个组合服务（Router/Fallback/ToolCycle/RunFinalizer/…）的混合形态。提示构建被显式拆为 `prompt_build/stages/`，每阶段产出 `BuildDecision` schema，判定显式化。
- **严格 function calling（C1-C6）**：声明先落盘 → tool_call_id 程序统一管理 → 孤儿声明合成「已取消」回执 → 「声明数 == 结果数」对账不变量（`engine_services/tool_cycle.py:344-503`）。**这是本次对比对象中做得最系统的 provider 协议硬化。**
- **事件源化**：`data/event_logs/<sid>.jsonl` append-only 事实轨，`replay` 纯函数重建、`reconcile` 与 session JSON 逐字段对账（`event_log/`）。**双轨（人读 JSON + 机读事件）设计为对比对象中所独有。**
- **记忆与学习**：`memory/`（条目/档案/检索/证据/摘要）、`experiences/`（工程经验库）、`methods/`（方法卡 + LearningPlane 后台离线自蒸馏，前台优先 + 跨进程锁）。
- **自省与演进**：`introspection/`（八维状态、12 个 registry_*、self_evaluate、submit_evolution 七态状态机 + `EVOLVE_LOCAL_EXEC` 分级权限 + 全链路审计）。
- **多模型**：OpenAI 兼容 / Anthropic Messages / Google Gemini / LM Studio 四协议；provider 注册表 + fallback 链 + 模型窗口自适应预算 + `ProjectionDensityTracker` 在线校准 chars/token。
- **扩展与接入**：工具注册（4 项协议）、无代码 Skill（`skills/<name>/SKILL.md`，24 个现成技能）、MCP 客户端、SubAgent、fleet 租约、浏览器感知/受控操作、工作区隔离、CodeArts 调度。
- **工程化**：738 测试文件 / 7,215 用例、三件套门禁（ruff/pyright/pytest 全量）、`r9_commit.sh` 机检 + 跨 worktree 提交队列锁、三层 CI、事件溯源、审计日志族。

### 2.2 成熟度雷达（文字）

| 维度 | LFL 表现 | 判断 |
|:--|:--|:--|
| 功能完整性 | 覆盖极广，且含独特能力（演进/事件溯源/学习） | 高 |
| 架构设计 | 理念清晰、可验证拆分；但超大文件与残留兼容层 | 中高 |
| 易用性 | Python≥3.13、巨量配置、内部术语、无 PyPI | 低 |
| 扩展性 | 工具 + Skill 双轨 + 公共 API | 中高 |
| 性能 | 预算自适应、密度校准、资源治理；单进程仍重 | 中高 |
| 生态社区 | 个人仓库、无包发布、无外部使用者 | **极低** |
| 安全性 | 灾难性安全硬阻断 + SSRF + symlink + 审批流；非完备沙箱 | 中高 |
| 工程化 | 门禁 + 方法论（预注册/冻结/Wilson CI） | 高 |
| 成本控制 | cost_tier 路由、模型切换；无硬预算/网关 | 中 |
| 场景广度 | 编码/浏览器/飞书/headless；无 voice/realtime | 中高 |

### 2.3 核心亮点（相对对比对象的差异化）

1. **AI 自主演进闭环**：`self_evaluate → submit_evolution → 人工审阅 → 分级执行 → 审计`。对比对象中，Pydantic AI/LangGraph 等提供的是「人类开发者的可观测与调优」，**没有一个把「模型自我评估并提交架构演进建议」做成一等运行时能力**。
2. **事件源化 + 逐字段对账**：以 append-only 事件轨为机读真相，session JSON 为人读真相，`reconcile` 提供一致性证明。OpenHands/LangGraph 有 checkpoint/state，但**缺少「双真相源 + 可证明一致」的审计姿态**。
3. **严格 FC 协议硬化**：孤儿声明兜底与「声明数==结果数」不变量，系统封死 provider 400 风险。
4. **实证研发纪律**：预注册（pre-registration）+ 冻结协议（27 个 FROZEN）+ 配对对照 + Wilson 95% CI + 负结果同呈现 + 反事后调参条款。**这在同类项目中极为罕见**，更接近学术/安全评测机构（如 Inspect AI）的规范，而非普通框架。
5. **程序最小化的可验证落地**：机械判定收窄为非语义（`nonconvergence_guard`、`token_budget`、`fleet`），决策类判断交 AI + 规则（`docs/ai_rules.md` 477 行 / RULE-AI-00~26 为维护规则 SoT）。

### 2.4 技术债与风险

| 风险 | 证据 | 影响 |
|:--|:--|:--|
| 超大文件 + 高耦合宿主 | `factory.py` 2837 行、`engine.py` 2641 行、`registry.py` 1956 行（2026-10-10 实测，仍在增长）、`session.py`/`history.py` ~100KB | 新人理解成本、回归面 |
| Mixin 与组合服务并存 | `engine_services/` 大量 `self._host` 回边 + 文件级 pyright 豁免 | 静态类型安全削弱 |
| 残留兼容路径 | `err1210`、`LEGACY_PROGRAM_FINAL_MARKER`、`legacy_truncated_tail` | 认知负担、潜在死代码 |
| 配置面极宽 + 三态开关 | `config.py` 66KB；`LFL_TOOL_GUIDANCE`/`LFL_EVIDENCE_CAPSULE`/`CACHE_GUARD_PERF_BLOCK` | 回归矩阵成本高 |
| 外部红豁免登记 | `tests/guards/external_red_registry.json` ~90 项（带销号期限） | 显性技术债 |
| 版本面不一致 | `pyproject.toml`=0.6.27 = `CHANGELOG` v0.6.27，但 **git tag 停在 v0.6.26**（2026-10-10 复核） | 发布可信度：对外无锚定 tag |
| 文档滞后 | CONTRIBUTING 仍提 Release Drafter（`.github/release-drafter.yml` 不存在，2026-10-10 复核）；原「README/api 写端口 8902」一条已失效删除——README:104 现为 8903，与实际一致 | 上手误导 |
| 仓库卫生 | 顶层 26 个 `*.swe-*.json`、`.env.bak-*`、`data/` 33 万文件、`evals/` 25 万文件 | 克隆/检索成本 |
| **无 PyPI / 无 OpenAI 兼容出口 / MCP server 未接线** | `release.yml` 无 publish；`web/routes.py` 仅自有 REST；`cache_guard/mcp_server.py` 无调用者 | **生态采纳的最大阻塞** |

---

## 3. 逐项对比

### 3.1 框架层

| 维度 | LFL | LangGraph | OpenAI Agents SDK | Pydantic AI | CrewAI | AutoGen |
|:--|:--|:--|:--|:--|:--|:--|
| 抽象层级 | 全栈运行时（高内聚） | 低层编排 | 轻量原语 | 类型化 SDK + capability | 高层 crew/flow | 分层（Core/AgentChat/Ext） |
| 多智能体 | SubAgent + fleet 租约 | 子图/多节点 | Handoffs / agents-as-tools | SubAgents capability | Crew 原生 | 原生（先驱） |
| 持久化/恢复 | 事件源 + session + 中断恢复 | Checkpointer/durable | Sessions（多后端） | 8 种持久化引擎 | Flow 持久化 | 有限 |
| 记忆 | 条目/档案/语义/证据/经验/方法 | 短期+长期 memory | Sessions | Memory capability | memory/knowledge | 有限 |
| 工具 | 严格 FC + 孤儿回执 + MCP 客户端 | 生态工具海量 | 函数工具 + MCP | tools + MCP | 工具/集成 | MCP/扩展 |
| 可观测 | 事件溯源/审计/KPI | LangSmith | 内置 tracing | OTel/Logfire | observability | AutoGen Bench |
| 上手门槛 | 高 | 中 | 低 | 低-中 | 低 | 中 |
| 状态 | 活跃（个人） | 活跃（公司） | 活跃（OpenAI） | 活跃（Pydantic） | 活跃（公司） | **维护模式** |
| 独特点 | **自主演进闭环 + 事件溯源对账** | durable 执行 | 原语极简 + 实时语音 | 类型 + 组合 + 评测 | 多智能体易用 | 多智能体历史地位 |

**要点**：
- LangGraph 与 LFL 定位最接近（都是低层运行时），但 LangGraph 走「图/状态机 + 生态集成」，LFL 走「AI 优先 + 文档规则 + 事件溯源」。LangGraph 胜在生态与文档，LFL 胜在自主演进与审计深度。
- OpenAI Agents SDK / Pydantic AI 代表**「轻量、类型化、可组合」**方向，上手成本远低于 LFL，且都有成熟的持久化与评测配套。LFL 的「大而全」在此维度是劣势——**功能多不等于可采纳**。
- AutoGen 进入维护模式提醒：**多智能体编排层的竞争已收敛到少数生态（LangGraph/Pydantic AI/MAF）**，LFL 若走通用框架路线，须回答「为什么不用 LangGraph」。

### 3.2 执行 Harness 层

| 维度 | LFL | OpenHands | SWE-agent | Aider | Claude Code |
|:--|:--|:--|:--|:--|:--|
| 目标场景 | 通用 Agent 运行时（编码+浏览器+IM） | 编码 Agent 全栈 | SWE-bench/issue 修复 | 终端结对编程 | 编码 Harness |
| 沙箱隔离 | 非完备（EXEC_MODE 分级 + 灾难性硬阻断） | **容器/Sandbox Server** | 沙箱执行 | 无（本地执行） | 权限模型 *(知识库)* |
| 执行接口 | CLI/Web/飞书/headless | SDK/Server/Canvas/Cloud | CLI/Python | CLI | CLI/IDE |
| 商业配套 | 无 | Cloud/Enterprise | 无 | 无 | 订阅/API |
| 社区规模 | 无 | 大（组织化） | 中（学术） | **44K★/6.8M 安装** | 头部 |
| 独特点 | 事件溯源 + 自主演进 + 飞书桥 | 组件化 + 云服务 | 基准参考实现 | 极简 + git 工作流 | 产品化打磨 |

**要点**：
- **隔离能力是 Harness 的核心分水岭**。OpenHands 有独立 Sandbox Server 与容器隔离，Inspect AI 有多后端沙箱；LFL 明确自述「非完备沙箱」，依赖 `EXEC_MODE` 分级 + 灾难性安全硬阻断 + 人工审批。**在不可信代码/多租户场景下，LFL 的隔离等级低于主流 Harness。**
- Aider 的 44K★ / 6.8M 安装说明：**终端专用工具的单一场景极致打磨，其采纳度可以碾压通用框架**。LFL 的「通用」定位反而稀释了单点体验。

### 3.3 评测框架层

| 维度 | LFL（内置评测） | Inspect AI | promptfoo | LangSmith | SWE-bench |
|:--|:--|:--|:--|:--|:--|
| 定位 | 运行时内置评测体系 | 通用前沿评测框架 | 提示/模型评测 + 红队 | 可观测 + 评测平台 | 软件工程基准 |
| 评测集 | `tests/eval_sets/scenarios_v1.json`（6 场景） | **200+ 预置评测** | 声明式用例 | 与 trace 集成 | 标准数据集 |
| 统计严谨 | **预注册/冻结/配对/Wilson CI** | 支持 metric/多 scorer | CI 集成 | 支持 | F2P∧P2P 严格判定 |
| Agent 评测 | 内置 + 真实 LLM nightly | **支持内置/外部 agent（Claude Code/Codex/Gemini CLI）** | 有限 | 支持 | 编码 agent |
| 沙箱 | 复用自身执行边界 | **Docker/K8s/Modal/Proxmox/Vagrant** | 无 | 无 | Docker |
| 可复用性 | 与 LFL 强耦合 | 独立 PyPI 包 | 独立工具 | SaaS | 独立 |

**要点**：
- LFL 的**评测方法论（预注册/冻结/Wilson CI）在严谨度上不输甚至超过多数框架内置评测**，但**可复用性极差**——它绑死在 LFL 运行时内，外部无法拿来评别的 Agent。Inspect AI 的价值恰在于「独立、可组合、跨 framework」。
- 差距的本质是**范式差异**：LFL 是「自证式评测」（证明自己的改动有效），Inspect 是「他证式评测框架」（评任何模型/Agent）。两者互补。

### 3.4 关键能力矩阵（LFL 视角）

| 能力 | LFL | 主流代表 | 差距性质 |
|:--|:--:|:--|:--|
| 严格 function calling 协议硬化 | ✅ 领先 | OpenAI/Anthropic SDK | **领先** |
| 事件源化 + 逐字段对账 | ✅ 独有 | LangGraph checkpoint / OpenHands state | **领先** |
| AI 自主演进闭环 | ✅ 独有 | 无同类一等能力 | **领先** |
| 实证评测纪律 | ✅ 领先 | Inspect AI 相当 | **持平/领先** |
| 沙箱隔离 | ⚠️ 弱 | OpenHands/Inspect/SWE-agent | 落后 |
| 标准协议出口（OpenAI 兼容 / MCP server） | ❌ 缺 | 多数框架 | 落后 |
| 包分发（PyPI/pip） | ❌ 缺 | 全部 | 落后 |
| 社区与外部使用者 | ❌ 缺 | 全部 | 落后 |
| 类型安全 / IDE 体验 | ⚠️ 弱 | Pydantic AI | 落后 |
| 语音/实时/多模态 | ❌ 缺 | OpenAI SDK/Pydantic AI | 落后 |
| 上手时间（首次跑通） | ⚠️ 长 | OpenAI SDK/Pydantic AI/Aider | 落后 |

---

## 4. 分项评分、总分与理由

### 4.1 权重表（公开计算）

| # | 维度 | 权重 | 权重理由 |
|:--:|:--|:--:|:--|
| 1 | 功能完整性 | 15 | Harness 的首要价值是「能做成什么」 |
| 2 | 架构设计 | 12 | 决定长期可演进性 |
| 3 | 扩展性 | 12 | 框架的分发价值取决于扩展点 |
| 4 | 生态与社区 | 12 | 决定被采纳与被维护 |
| 5 | 工程化 | 10 | 生产可用性的底座 |
| 6 | 易用性 | 10 | 直接决定获客 |
| 7 | 安全性 | 8 | 执行真实副作用的前提 |
| 8 | 适用场景广度 | 8 | 通用性 |
| 9 | 性能与效率 | 8 | 长任务/多轮成本 |
| 10 | 成本控制 | 5 | 运行经济性 |
| | **合计** | **100** | |

### 4.2 评分矩阵

| 项目 | 功能15 | 架构12 | 易用10 | 扩展12 | 性能8 | 生态12 | 安全8 | 工程10 | 成本5 | 场景8 | **加权总分** |
|:--|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Pydantic AI | 9 | 9 | 8 | 9 | 7 | 9 | 7 | 9 | 8 | 9 | **85.3** |
| LangGraph | 8 | 9 | 7 | 9 | 7 | 10 | 6 | 8 | 6 | 8 | **80.4** |
| OpenHands | 9 | 8 | 7 | 8 | 7 | 9 | 8 | 8 | 6 | 8 | **79.9** |
| Claude Code | 8 | 8 | 9 | 7 | 8 | 10 | 8 | 8 | 5 | 6 | **79.1** |
| OpenAI Agents SDK | 7 | 8 | 9 | 8 | 7 | 9 | 7 | 8 | 6 | 8 | **78.1** |
| **LFL（r3 修订）** | **9** | **8** | **5** | **8** | **7** | **3** | **8** | **9** | **6** | **8** | **71.7** ▲ |
| CrewAI | 7 | 6 | 8 | 7 | 6 | 8 | 6 | 7 | 6 | 7 | **68.9** |
| Aider | 7 | 6 | 8 | 6 | 7 | 9 | 6 | 7 | 7 | 5 | **68.6** |
| SWE-agent | 6 | 7 | 6 | 6 | 7 | 8 | 7 | 7 | 6 | 4 | **64.6** |
| AutoGen | 7 | 7 | 6 | 7 | 6 | 5 | 5 | 7 | 5 | 6 | **62.4** |

### 4.3 分项评分理由（重点说明 LFL 与高分项/低分项）

**LFL**（r3 修订后的分值；★ 为 r2 变动项，☆ 为 r3 评审回调项）
- 功能完整性 9：五阶段循环 + 记忆/检索/经验/方法 + 自评/演进 + SubAgent/fleet + 浏览器 + 工作区 + 多 provider + 三端 + 事件溯源，广度与深度兼具；扣 1 分因缺 voice/realtime/多模态。
- 架构设计 8：事件溯源、严格 FC、程序最小化理念清晰且可验证；r2 新增 `extensions/` 独立包管理模块与 MCP 五层分层（protocol/transport/client/auth/assembly）；扣分因核心超大文件、Mixin/服务并存、pyright 局部豁免。
- 易用性 ★5（4→5）：新增 Agent Plugins 标准包与 Claude/Codex/Gemini/Cursor/VS Code 适配器，**插件作者接入门槛下降**；但仍 Python≥3.13、18KB `.env`、内部术语、**无 PyPI**。
- 扩展性 ☆8（r2 曾按能力面给 9，r3 回调 7→8）：**能力面补齐是真实的**——工具注册 + 无代码 Skill 双轨之上，新增 **MCP 双时代协议 + 三传输（stdio/Streamable HTTP/legacy SSE）+ OAuth(PKCE) + resources/prompts + registry 发现 + git/archive 安装源 + 标准插件包**。但 r3 按「能力被外部消费」口径回调：**能力存在 ≠ 能力被消费**——`extension_*` 模型工具接口未实现、`sources.py`/`directory.py` 多为库函数未接入运行时工具面，外部使用者尚无一条「安装插件 → 模型调用」的完整路径。**9 分门槛**：`extension_*` 工具面接线 + 至少一个真实插件全链路跑通。
- 性能 7：模型窗口自适应预算 + 密度在线校准 + 资源治理 + 多查询融合影子观测；扣分因单进程重、长会话成本可观测但未优化到极致。
- 生态与社区 ★3（2→3）：生态**兼容位**显著增强（对齐主流工具链与 MCP 标准）；但包发布/外部使用者/第三方贡献者**仍未出现**，社区规模未变。
- 安全 ★8（7→8）：灾难性安全硬阻断 + SSRF/DNS rebinding/symlink 防护 + 审批流之外，新增 **Docker 沙箱后端（`--network=none --read-only --cap-drop ALL`，fail-closed）**、MCP OAuth 身份隔离、archive 安全解压（越界/炸弹/链接防护）、装配身份冲突报告。
- 工程化 9：测试 738→**801** 文件、三件套门禁、提交队列锁、三层 CI、预注册/冻结/Wilson CI；扣 1 分因外部红豁免登记与版本面历史遗留。
- 成本控制 6：cost_tier 路由 + 模型自主切换 + fallback + knowledge 消费预算；无硬预算/网关级成本治理。
- 场景广度 ★8（7→8）：编码、浏览器、IM、headless 多场景，r2 经 MCP/插件生态接入进一步拓宽；仍无语音/实时/图像生成。

**高分对照**
- Pydantic AI 85.3：在「类型化 + 可组合 + 持久化 + 评测 + 可观测 + 成本网关 + 多场景」上几乎无短板，且 100% 覆盖率；唯一略弱是性能与安全（相对沙箱方案）。
- LangGraph 80.4：生态 10 分、扩展 9 分、架构 9 分；安全 6 分（无内置沙箱）与成本 6 分拉低。
- OpenHands 79.9：功能 9 + 安全 8（独立 Sandbox Server）；易用性 7（自托管较重）。
- Claude Code 79.1：易用 9 + 生态 10；成本 5（闭源商业）与场景 6（编码为主）拉低。
- AutoGen 62.4：功能/架构尚可，但**生态 5（维护模式）** 与安全 5 拖累；象征「不进化即衰退」。

### 4.4 雷达图（文字描述）

以 LFL 为基准的五边形雷达（功能/架构/易用/扩展/生态/安全/工程/成本/场景）：
- **LFL 的雷达形状是「哑铃形」**：功能完整性与工程化凸出（9/9），架构、扩展、安全居中偏上（8/8/8），易用性与生态两个方向凹陷（5/3）。
- **Pydantic AI 是「近似正多边形」**：各维 7–9，无明显短板。
- **LangGraph 与 Claude Code 是「生态单极形」**：生态 10 分突出。
- **AutoGen 是「整体收缩形」**：维护模式导致全维平庸。
- 可交互雷达图见同目录 `LFL-COMPARATIVE-REVIEW-20261007.html`。

### 4.5 增量复核（2026-10-09 ~ 10-10 更新对评分的影响）

**触发**：用户指出 LFL 近期在**生态补全**与**方法/经验使用**上有大量更新。经对最新 HEAD（`98d1ce90e` / v0.6.27）复核，确认以下实质变化（证据均为本地只读代码/文档）：

| # | 更新（提交/模块） | 事实证据 | 影响维度 | 分值变动 |
|:--:|:--|:--|:--|:--:|
| 1 | **Agent Plugins 1.0.0 标准包**（P1-A） | `extensions/formats.py`（固定位置 `plugin.json`/`skills/`/`mcp.json` 解析 + 组件级 CompatibilityReport）、`extensions/store.py`（CAS 原子写 + 不可变副本）、`extensions/catalog.py`（预算投影） | 扩展性 | 7→9（r3 回调至 8，见 §4.3） |
| 2 | **MCP 全套**（P1-B/P1-C/P2-B） | `tools/mcp_protocol.py`（双时代：现代 `2026-07-28` + legacy）、`mcp_transport.py`（stdio / Streamable HTTP / legacy SSE 三传输）、`mcp_auth.py`（RFC 9728/8414/7591 + PKCE + client_credentials）、`mcp_client.py`（分页/能力保真/typed 错误/连接代际）、`mcp_assembly.py`（三层装配 + 身份冲突报告）、resources/prompts 路由工具 | 扩展性、场景广度 | ↑ |
| 3 | **厂商生态适配器**（P2-A） | `extensions/vendor_formats.py`：Claude Code / Codex / Gemini / Cursor / VS Code / mcp-servers-json 格式嗅探与转换 | 易用性、生态兼容位 | 4→5 |
| 4 | **git/archive 安装源 + registry 发现**（P2-B） | `extensions/sources.py`（commit/digest 固定、安全解压 64MB/4096 条上限）、`extensions/directory.py`（只读发现候选） | 扩展性 | ↑ |
| 5 | **method 生命周期闭环 v2.2** | `methods/store.py`（`record_use`/`record_qualification`/`annotate_freshness`/`update_status`；独立证据门控；`update_status` 禁止 candidate→active 直跳；usage ledger append-only + 单调水位防 git revert 抹除） | 功能完整性、工程化 | 维持高位 |
| 6 | **方法/经验消费证据链 + 语义检索** | `introspection/search.py`（method/experience 词法+RRF）、`methods/reflection.py`（reflect 期语义检索）、`subagent/runner.py:1873`（委派前有界 method 检索）、`engine_services/knowledge_runtime.py`（canary advisor 注入，默认 off） | 功能完整性 | 维持高位 |
| 7 | **Docker 沙箱后端** | `tools/sandbox.py`：bwrap / docker 双后端，docker `--network=none --read-only --cap-drop ALL`，后端缺失 fail-closed | 安全性 | 7→8 |
| 8 | **测试规模增长** | 738 → **801** 个 `test_*.py`，新增 `test_extensions_*` / `test_mcp_*` / `test_resource_vendor_*` 一批 | 工程化 | 维持 9 |

**修订后 LFL 得分**：r2 为 `9/8/5/9/7/3/8/9/6/8` → 72.9；**r3 评审将扩展性回调至 8**：`9/8/5/8/7/3/8/9/6/8` → **加权总分 71.7**（原 r1 66.7，+5.0）。分数用于维度剖面参照，不构成跨层排名结论。

**仍然存在的缺口（不因本轮更新改变）**：
1. **无 PyPI 发布**（`release.yml` 仅 GitHub Release 草稿，无 publish job）——生态与社区维度无法再提升的根本原因。
2. **无对外 OpenAI 兼容出口**（`/v1/chat/completions`）；Web 仅自有 REST。设计文档 FR-14「LFL 能力对外导出」标注为 **P3 未实现**。
3. **`extension_*` 模型工具接口未实现**（`DESIGN §10.1` 拟议 `extension_list/inspect/manage/status/read/call`，代码中不存在）——插件管理仍为代码 API，模型无法自主管理插件。
4. **安装授权/配额/源域白名单工具接口未实现**；`sources.py`/`directory.py` 多为库函数，未全面接入运行时工具面。
5. **方法/经验消费率仍低**（仓库自带审计 `docs/AUDIT-20261007-p0-architecture-gap.md` 自述约 6/677 ≈ 0.9%）；开场 ACTIVE 卡注入已被实验否决，当前为 model-driven 检索 + 每 run 一次回记提醒 + canary，尚未形成闭环收益证明。

**方法论评价**：本轮更新延续了 LFL 的一贯姿态——**先补正确性、再补能力、并保留诚实边界**（如 MCP 不广播未实现能力、沙箱 fail-closed、消费证据 append-only + 水位防丢失）。这使「扩展性/安全性」的跃升是**结构性的而非功能堆叠**，因此本次给分提升是可信的。值得注意：仓库自身已产出 `AUDIT-20261007-p0-architecture-gap.md`，其结论（"能力增速超过收敛速度"、kernel 无显式边界契约、durability 基座分散、method 消费闭环缺 T0）与本报告独立观察**高度一致**，可互为佐证。

---

## 5. LFL 可执行改进建议

按优先级 P0（阻塞采纳）→ P3（增强）排序，每条含动作、预期收益与验证方式。

### P0 — 阻塞生态采纳（建议 1-2 个月内完成）

| 建议 | 动作 | 预期收益 | 验证 |
|:--|:--|:--|:--|
| **P0-1 发布 PyPI 包** | 前置决策：**包元数据明确 Python 支持策略**（兼容 3.12 或明确 ≥3.13 并在 README 首屏声明——直接决定受众面）。随后 `release.yml` 增加 `build` + trusted publishing，打出 `llm-first-loop`；提供 `pip install llm-first-loop` | 易用性 +3、生态 +2；消除「只能源码安装」门槛 | 干净环境 `pip install` 跑通 examples/01 |
| **P0-2 对外出口（r2 部分完成；r3 重排出向优先级）** | ✅ *入向* 已补齐：MCP 客户端全套 / 标准插件包 / 厂商适配器（Claude·Codex·Gemini·Cursor·VS Code）。**出向按序**：① **MCP server 导出**——把记忆/证据/方法学习/工具面导出为 MCP server，让其他 Agent 宿主直接复用 LFL 差异化能力（价值密度在工具面而非对话面，优先做）；② `extension_*` 模型工具接口；③ OpenAI 兼容出口 `POST /v1/chat/completions`（无状态会话接口与 LFL 有状态运行时阻抗失配，降为次要） | 生态 +1、扩展性 +1；第三方宿主直接消费 LFL 能力 | 第三方 MCP 客户端连通 LFL 导出 server 并成功调用 ≥1 个核心工具 |
| **P0-3 降低首跑成本** | 提供 `lfl init` 向导 + 极小默认配置；`RUN_MODE=minimal` 作为默认示例；README 首屏给「3 行跑通」 | 易用性 +2 | 新用户在无 `docs/` 阅读下 5 分钟跑通 |
| **P0-4 剥离仓库噪声** | 将 `evals/`、`data_ab/`、26 个 `*.swe-*.json`、`.env.bak-*` 移出主仓（独立 repo/Release 资产） | 克隆体积与检索成本大幅下降；专业度提升 | 克隆时间/体积对比 |

### P1 — 架构与工程质量（3-6 个月）

| 建议 | 动作 | 预期收益 | 验证 |
|:--|:--|:--|:--|
| **P1-1 拆分超大文件** | 对 `factory.py`/`engine.py`/`registry.py`/`session.py` 继续 R9 式逐字平移拆分，恢复 pyright 严格 | 架构 +1、可维护性 | 无行为变更 + 函数体量守卫下降 |
| **P1-2 容器化沙箱（r2 已实现，待默认化）** | ✅ 已有 `tools/sandbox.py`（bwrap / docker 双后端，`--network=none --read-only --cap-drop ALL`，缺失 fail-closed）；下一步：作为默认推荐执行档、完善 `docs/operations/EXECUTION-ISOLATION.md`、扩大适用边界 | 安全维持 8 | 不可信代码默认容器内执行 |
| **P1-3 清收外部红豁免与兼容层** | 按期销号 ~90 项外部红；移除 `err1210`/legacy 分支 | 工程化 +1 | 豁免登记归零、守卫绿 |
| **P1-4 版本面统一** | 以单一 SoT 派生 `pyproject`/`CHANGELOG`/tag；修正 README 端口与 CONTRIBUTING 滞后 | 工程化 +1 | 版本一致性检查入 CI |
| **P1-5 评测资产外化** | 把 `run_eval.py` + scenarios 抽成可独立复用包/规范，输出与 Inspect 兼容的日志格式 | 生态 +1、扩大影响力 | 第三方可用其评测自己的 Agent |
| **P1-6 方法/经验消费率闭环（r3 新增）** | 当前消费率 ~0.9%（6/677）——三个独有能力之一有「有器官、无循环」的空转风险。定义消费收益 T0（消费 → 行为改变 → 可度量收益的证据链），为消费率与闭环收益设可验证目标 | 自主演进闭环从「存在」变「有效」，差异化不空转 | 预注册的消费率/收益度量报告 |
| **P1-7 对外版本承诺（r3 新增）** | PyPI 发布前建立外部可依赖锚点：tag 与 `pyproject` 同步的机械门禁（当前滞后：代码 0.6.27 vs tag v0.6.26）+ 弃用周期声明（0.x 内不破坏行为写入对外文档）。与 P1-4 互补：P1-4 对内一致性，本条对外承诺 | 生态/易用；采纳者可锚定版本 | CI 版本一致性门禁绿 + 文档含弃用政策 |

### P2 — 差异化放大（6-12 个月）

| 建议 | 动作 | 预期收益 |
|:--|:--|:--|
| **P2-1 把「自主演进闭环」做成标杆** | 撰写设计论文/技术报告 + 可复现 demo，对齐 §2.3 亮点 1；开放 `submit_evolution` 协议 | 确立不可替代的学术/工程影响力 |
| **P2-2 事件溯源协议标准化** | 将事件模型/对账工具抽为独立规范，供其他 Harness 采用 | 从「自用能力」升级为「行业协议」 |
| **P2-3 多模态/语音补齐** | 按需接入 voice/realtime（可选，非核心） | 场景广度 +1 |

### P3 — 长期（12 个月+）

- 建立外部贡献者门槛友好的 good-first-issue、RFC 流程与治理模型（对齐 OpenHands 组织化）。
- 探索商业化配套（云托管/企业版），对齐 OpenHands/CrewAI 路径。

### 预期收益汇总

以 r3 修订基线（**71.7**）起算：若完成剩余 P0 + P1（PyPI 发布、MCP server 导出、清收外部红、版本统一、评测资产外化、消费率闭环），预计 LFL 加权总分从 **71.7 → ~78**（易用性 5→7、生态 3→5、工程 9→10），进入本轮对比的上游（与 OpenHands / Claude Code 同档），且**唯一不可替代性（自主演进 + 事件溯源 + 实证评测纪律）保持不变**。

---

## 6. 结论

1. **LFL 的能力是真实的、非营销的**：事件源化对账、严格 FC 硬化、自主演进闭环、实证评测纪律，四项均经代码与文档证据证实，且多数为对比对象所无。
2. **LFL 的短板是结构性的、非能力性的**：初版生态 2/10 与易用性 4/10 不是「做不出来」，而是「未对外开放」。r2 的生态补全（MCP 全套、标准插件包、厂商适配器、Docker 沙箱）把**扩展性 7→8（r3 回调：能力面已补齐、消费面未接线）、安全 7→8** 补上，总分 66.7→**71.7**；但生态维度受限于**仍未上 PyPI、仍无外部贡献者**，只从 2→3。
3. **战略已部分收敛：从「追功能」转向「转开放」且初见成效**：r2 证明 LFL 具备按标准（Agent Plugins / MCP）补齐生态的能力；剩余杠杆集中在**对外出口与分发**（PyPI、**MCP server 导出优先**、`extension_*` 工具面；OpenAI 兼容出口次之），投入小、杠杆大。
4. **差异化应被放大而非稀释**：LFL 不应以「通用框架」与 LangGraph/Pydantic AI 正面竞争功能，而应以「**可审计、可自我演进的 Agent 运行时**」占据差异化生态位，并把事件溯源/评测方法论产品化对外输出。
5. **对标基线选择建议**：日常工程对标 **OpenHands**（隔离与产品化）与 **Pydantic AI**（类型化与组合）；生态接入对标 **MCP 生态**（本轮已对齐）；方法论对标 **Inspect AI**（独立评测）；社区建设对标 **LangGraph**。

---

## 7. 附录：来源与不确定性

### 7.1 联网核实来源（2026-10-07）

- LangGraph 仓库页：https://github.com/langchain-ai/langgraph （42.8k★、MIT、durable/HITL/memory/LangSmith）
- AutoGen 仓库页与文档：https://github.com/microsoft/autogen 、https://microsoft.github.io/autogen/stable/ （61.3k★、**维护模式**、Microsoft Agent Framework 继任）
- CrewAI 文档：https://docs.crewai.com/ （多智能体 crews/flows、企业平台）
- Pydantic AI 文档：https://ai.pydantic.dev/ （100% 覆盖率、capabilities、Harness、8 种持久化引擎、OTel/Gateway/Evals）
- OpenAI Agents SDK 文档：https://openai.github.io/openai-agents-python/ （原语、Sandbox agents、Realtime/Voice、Sessions、MCP、tracing）
- OpenHands 文档：https://docs.all-hands.dev/ （SDK/Agent Server/Canvas/Cloud/Enterprise/Sandbox Server/benchmarks）
- Inspect AI 文档：https://inspect.aisi.org.uk/ （200+ evals、dataset/solver/scorer、多后端沙箱、20+ provider）
- Aider 官网：https://aider.chat/ （44K★、6.8M 安装、15B tokens/周、repo map、git 集成）

### 7.2 未联网核实（知识库，用于定性）

SWE-agent、Claude Code、promptfoo、LangSmith、SWE-bench 的部分能力描述为知识库信息，未在本次会话逐条联网核实；相关分值不构成关键分差。

### 7.3 不确定性

- 星标/安装量/版本为 2026-10-07 快照，随生态变化。
- 评分为主观加权，权重方案已在 §4.1 完全公开，可替换权重复算。
- 对比对象的功能边界以其公开文档为准，未做逐项实测。

---

*报告生成：2026-10-07 ｜ 修订 r2：2026-10-10 ｜ 修订 r3（评审修正）：2026-10-10 ｜ 交付物：本 Markdown + 同目录交互式 HTML 看板*