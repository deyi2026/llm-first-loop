# DeepSeek Super-agent 原型解剖与「为具身智能做准备」假设的证据检验

**—— 一份技术发展分析报告**

| 项 | 值 |
| --- | --- |
| 报告类型 | 技术发展分析报告（分析 + 证据检验 + 可执行建议） |
| 观测时点 | 2026-11-02 10:11–10:30 CST（本报告所有"实测"结论均在该窗口内取得） |
| 分析主体 | LFL 主代理（llm-first-loop），对 deepseek-ai/dsh-superagent-prototype 与 DeepSeek 官方长文的一手取证 + 同领域论文交叉验证 |
| 与既有文档的关系 | 本仓库 2026-11-02 日报（`docs/promotion/20261102-lfl-daily-52.md`）已完成**事实核验层**工作；本报告不重复其核验，只在其上做**技术发展分析**与**假设检验**，并补充本轮新增的一手仓库取证与论文证据 |
| 证据分级 | E1 = 一手（官方仓库代码/文档、arXiv 论文原文）；E2 = 权威二手（媒体报道、官方博客转述）；E3 = 社区解读/评论；U = 未核实/未取得原文 |

---

## 0. 摘要：四条结论

**结论 1 —— 发布物是真实的，但它是"研究原型"而非产品。**
DeepSeek Harness 团队于 2026-10-31（北京时间晚间）发布技术长文《Super-agent 设计探索：迈向更自主的 Agent 系统》，并同步开源研究原型 `deepseek-ai/dsh-superagent-prototype`。该仓实测：MIT 许可、**仅 1 次提交**（commit date `2026-10-31T12:05:39Z`）、created `2026-10-31T09:32:46Z`、2026-11-02 10:26 CST 时 star 8,187 / fork 830。README 自述 *"Research prototype for reference only, not an official DeepSeek product"*，并明确声明"公开版本与内部版本、以及文章所描述的实现三者不同；文章中的部分设计属于未来方向，本原型并未实现"。**这三条限定语是理解这次发布的第一把钥匙：文章讲的是"设计意图"，仓库给的是"意图的一个可读子集"。** [E1]

**结论 2 —— "为具身智能做准备"这个判断，目前没有一手证据支撑。**
本轮对仓库 README、SETUP 与全部 9 篇 docs（共 2,091 行）做全量关键词扫描，结果是**全部为 0**：`embodied` 0、`robot` 0、`具身` 0、`physical world` 0、`manipulat*` 0、`real-time` 0、`control loop` 0、`sim2real` 0、`watchdog` 0。DeepSeek 公开仓库版图中也没有机器人 / VLA 项目（最接近物理世界的是 2024 年的 DreamCraft3D，属 3D **资产生成**，不是控制策略）。官方长文自述的待解难题清单里同样没有具身。因此：**"为具身做准备"目前只能是推断，不能写成事实。** [E1]

**结论 3 —— 但存在一条比"姿态"硬得多的证据链：coding agent 的自主性正在成为具身智能的**上游供给**。**
2026-10-29 的论文《Gym-Anything for Robotics: Scaling physical simulations with digital agents》（arXiv:2610.40565）明确写道：*"simulation creation is a coding agent task, so improvements in coding agents translate directly into richer and more faithful simulations"*；并在 RoboWorld 基准上给出残酷数据——**所有被测前沿模型在 25 个仿真任务上全部失败，平均 reward 仅 0.06**，其解法正是用"代码策略"生成仿真任务与演示数据。同时，具身侧的前沿架构正在收敛到"云端强推理 + 本地快控制 + critic 触发升级"的分层结构（arXiv:2610.30587，报告 time-between-action latency 下降 28.8%–82.6%），这与 Super-agent 的 **Router / Worker 双层**在结构上高度同构。
**于是更准确的命题是：可迁移的是"自主性基础设施层"（触发 → 授权 → 异步长时程执行 → 结构化上下文 → 人只在必要时介入），不可迁移的是"闭环控制与世界模型层"。Super-agent 更像是给具身栈准备"操作系统与治理层"，而不是"手"。** [E1]

**结论 4 —— 对本项目（LFL）的可执行结论有 5 条（见 §6）。**
其中最该立刻做的是把 LFL 现有的"每次调用即过闸"升级为"**事件驱动常驻源 + 授权判定独立成层 + 外部看门狗巡检**"三件套；而具身方向**现在不入场**，先走"**仿真/数据生成即 coding 任务**"这条已被论文验证的最短路径。

---

## 1. 研究方法与证据边界

### 1.1 本轮实际做了什么

| 类别 | 动作 | 产物/结果 |
| --- | --- | --- |
| 一手抓取 | GitHub API 取仓库元数据、文件树、提交历史；raw 抓取 README、SETUP、docs/000–008 共 11 个文件 | 快照存 `/tmp/dsh/`（本会话临时目录，未写入仓库） |
| 关键词扫描 | 对上述 11 个文件拼接文本（2,091 行）逐词计数 | 9 个关键词全部 0 命中 |
| 文档精读 | 000-philosophy / 001-domain / 002-authorization / 003-execution / 004-prompts / 005-panel / 006-deployment / 007-architecture / 008-cookbook | 抽出领域模型、授权模型、执行模型、面板取舍、原型自述的待解问题 |
| 官方文章 | 尝试直接抓取官方公众号正文（mp.weixin） | **失败**：抓取被拒；检索命中的 mp.weixin 链接经核对为无关文章 |
| 二手交叉 | IT之家转述、aicodewith.ai 综述、eneralabs、explainx.ai、本仓库留存的媒体抓取件 `docs/promotion/receipts/d52research/*.txt` | 用于还原官方文章的模块划分与实验数字（标 E2） |
| 论文取证 | arXiv API 按提交时间倒序检索 VLA / embodied / long-horizon / cs.SE 四组关键词 | 8 篇 2026-10 一手论文（标 E1） |
| 委派调研 | 2 个子代理并行调研"具身智能现状"与"自主 agent 演进" | 其中 1 个因上下文预检超限结算失败，经压缩后续跑成功；具身侧子代理仍在运行（见 §7） |

### 1.2 证据边界（必须写明）

1. **官方长文原文未取得。** 公众号正文无法直接抓取，报告涉及官方文章的模块划分、机制名与实验数字，均标注 E2 并注明来源为媒体转述/综述。**这些数字应视为"官方口径的二手转述"，未经原文逐字核对。**
2. 论文与仓库部分为 E1，可直接核验（含 arXiv 编号与文件路径）。
3. 本报告对"动机"的任何判断都严格区分：仓库写了什么 / 官方说了什么 / 我推断什么。**推断不升级为事实。**

### 1.3 一个方法论提醒

这次讨论最容易犯的错，是把"官方发布的自主 agent 基础设施"与"官方的具身意图"绑在一起叙述。**基础设施的通用性 ≠ 意图的具身性。** 报告第 3、4 节专门处理这个分离。

---

## 2. 事实层：Super-agent 到底发布了什么

### 2.1 发布物与时间线

| 时间（UTC / CST） | 事件 | 级别 |
| --- | --- | --- |
| 2026-10-31 09:32:46Z / 17:32 CST | GitHub 仓 `deepseek-ai/dsh-superagent-prototype` 创建 | E1 |
| 2026-10-31（晚间） | 官方公众号发布长文《Super-agent 设计探索：迈向更自主的 Agent 系统》（英文转写标题 *Exploring Super-agent Design: Towards a More Autonomous Agent System*） | E2 |
| 2026-10-31 12:05:39Z / 20:05 CST | 唯一一次提交 `feat: add the dsh-superagent research prototype` | E1 |
| 2026-11-02 08:00 CST | 本仓库日报完成发布物核验（star ~7.2k） | E1（本仓库内） |
| 2026-11-02 10:26 CST | 本轮复测 star 8,187 / fork 830 / open issues 0 | E1 |

仓库自述定位（README 原文要点）：dsh-superagent 是**面向单个 GitHub 仓库的主动性 coding agent**，以插件包形式供 DeepSeek Harness 使用；它监听 GitHub 与（可选的）飞书；当被允许的人提出工作请求时，它建立工作项，在**自己的 agent 会话与目录**中完成工作，并在原对话中回复（例如交付一个 PR）；**一个 web 面板只展示"需要人处理"的部分**。官方给出的设计原则是：**尽可能少占用人的注意力，尽可能多地产出价值**；只在被请求时、或当团队写下的规则允许时才行动；只在需要人行动、或人能用上结果时才说话。[E1]

### 2.2 官方文章主张的结构（E2，多源交叉）

**问题定义**：单个会话内 agent 可以承接的问题有限，人只能同时盯 3–5 个活跃会话；即便通过 CLI / MCP 扩展，仍存在**阻塞、上下文混乱、本地离线即中断**三类问题。[E2]

**目标**：Super-agent 应是**连续、高产、主动、持久**的。

**五个模块**（多篇二手转述一致）：

1. **双层架构**：Router（判断"要不要做、交给谁"）/ Worker（具体执行）；
2. **事件驱动**：以 GitHub issue、飞书消息等事件作为触发源，而非人盯着会话；
3. **异步交互**：面向人的异步 ReAct 循环，人不必等待会话结束；
4. **存算分离**（BYOM：Bring Your Own Model）：模型可插拔，状态与计算分离；
5. **看门狗（Watchdog）**：外部进程监视 agent 运行与交付。**注意：这一模块在原型仓中不存在任何实现或文档痕迹（关键词 0 命中）。** [E1 否定证据]

**三个关键机制**：[E2]
- **Inline & Spill**：上下文内联快速路径，超限则外溢为可持久化状态；
- **Chain of Recall**：跨会话的召回链，把"记得发生过什么"变成一等公民；
- **投机执行**：对高概率分支先执行后校验，降低等待。

**官方给出的实验数据**（E2 口径，**未经原文核对**）：
- 单次运行约 300 条消息、约 20 个工作请求、重复 5 次；Super-agent p50 **12.4 min** vs 对照 p50 20.4 min，p95 **15.7 min** vs **29.5 min**；
- Router 压测：触发到达率 1/min → 40/min 时，批处理 1.0 → 2.8、单请求延迟 2.5s → 3.9s、**单次决策推理 6.4s → 1.6s**；
- token 成本：23.2M cache-read vs 对照 6.1–10.8M（约 3.8×）。

**官方自述的四个待解难题**：[E2]
① Router 的规模化扩展；② 跨月尺度的长期记忆；③ 人与 agent 无会话式协作；④ agent 实例间 A2A；以及**安全与隐私**——提示注入、凭据泄漏、跨设备权限、云端 agent 触达本地设备。

### 2.3 原型代码事实（E1，本轮逐份读过）

仓库结构（文件树实测，共 216 个文件）：`docs/` 9 篇、`src/` 111 个、`tests/` 65 个、`prompts/` 15 个、`skills/` 2 个、`locale/` 2 个（en/zh）、`examples/` 1 个、`cordis.patch.yml`。核心领域模型（`001-domain.md`）：

| 领域概念 | 定义要点 |
| --- | --- |
| Source | 事件来源（GitHub issue / 飞书），**提供真实数据** |
| Trigger | 事件落到某个具体 Thread 上（一个仓库 = 一个 Thread） |
| Eval | 准入检查 + 研判，产出 Decision |
| Decision | 四选一：**接单 / 停止 / 忽略 / 未完成** |
| Mandate | 对某个 Thread 的**授权**（带版本，可撤销）；**准入的兜底判据** |
| Ticket | 一个可追踪的工作项（对标 issue） |
| Assignment | 一次派工（可多工单并行） |
| Subscription | 订阅规则，扇出为 Assignment；**注意：扇出不带准入检查，Mandate 才是授权** |
| Report | worker 交付回执（正文 + diff / PR 引用） |

授权模型（`002-authorization.md`）：Policy 版本化；`accept` 模式三档 `off` / `observe` / `auto`；每个 Source 可单独允许或禁止。**关键口径**：准入失败**不等于**拒绝执行——当存在 Mandate 时准入仅降级为"自动执行"。[E1]

执行模型（`003-execution.md`）：Executor 以**宿主 operator 的操作系统用户身份**运行，`danger-full-access`，"我们不声称这是安全边界"。派工创建**独立工作目录**，每个 Ticket 一个**独立 agent 会话**。[E1]

面板（`005-panel.md`）：只展示需要人处理的部分；不健康的工作项折叠；产物本身不进面板，只进交付。[E1]

### 2.4 官方实验的解释边界（防止过度解读）

官方自己说明：该实验是**合成负载**，测的是**调度与协作**，**不测单任务的执行质量**。[E2]
→ 因此"p95 从 29.5 降到 15.7"只能支持"**调度与并发编排更快**"，**不能**推出"任务做得更好"。任何把这两个数字当成"自主性能力提升"来引用的说法，都是越界。

### 2.5 一手与宣传之间的三处落差

1. **看门狗缺席**：官方文章列为五大模块之一，原型仓 2,091 行文档 + 全部代码中无任何对应实现（0 命中）[E1]。
2. **公开版 ≠ 内部版 ≠ 文章**：README 明说三者不同，文章中部分设计"属于未来方向" [E1]。
3. **非官方产品**：README 明写 "not an official DeepSeek product"，且原型以"整个仓一次性提交"的形式给出——这更像**设计公开**，而非**可运行产品的发布**。[E1]

**小结：** 这次发布的信息价值，主要在**架构思想与授权模型**，不在可运行能力，也不在具身意图。

---

## 3. 假设检验：「Super-agent 是为具身智能做准备」成立吗

### 3.1 先把假设写成可证伪的判据

"为具身智能做准备"这句话如果只是"技术上有用处的直觉"，无法检验。要变成可检验命题，必须能指出**应当出现的可观察痕迹**。我设定四类判据 + 一个反证条件：

| 判据 | 若"为具身准备"成立，应当看到 | 实际观察（2026-11-02 10:15 CST 实测） | 判定 |
| --- | --- | --- | --- |
| J1 物理世界表述 | 文档/代码中出现 embodied / robot / 物理世界 / 实时控制的显式建模 | README + SETUP + 9 篇 docs（2,091 行）关键词计数**全为 0** | ❌ 不成立 |
| J2 感知—动作闭环抽象 | 存在"观测 → 状态 → 动作 → 反馈"的一等抽象（Source/Ticket 之外的闭环对象） | 领域模型止于 Source→Trigger→Eval→Decision→Ticket→Assignment→Executor→Report→Delivery，**无观测/动作/反馈对象** | ❌ 不成立 |
| J3 不可逆动作与安全包络 | 存在动作危险度分级、力/速度/碰撞边界、许可式授权（safety envelope） | 授权模型只有"接不接单"与"谁批准"，**无物理动作语义**；权限单位是"能不能改这个仓库" | ❌ 不成立 |
| J4 具身相关的验证/仿真依赖 | 依赖仿真器、机器人数据集、具身 benchmark | `sim2real` 0 命中；依赖为 GitHub API / 飞书 / 本地文件 / git | ❌ 不成立 |
| J5（反证）官方声明 | 官方文本明确提及面向物理世界/机器人 | 官方长文（E2 口径）与仓库自述均无；待解难题清单为规模化、长期记忆、无会话协作、A2A、安全与隐私 | ❌ 未见 |

### 3.2 反向证据：DeepSeek 的公开技术版图离具身有多远

实测 DeepSeek 公开仓库组合（`GET /orgs/deepseek-ai/repos`）：模型侧为 DeepSeek-V3.2 / V3.1 / R1 / Coder / VL / VL2 / Janus 多模态 / OCR，工具侧为 deepseek-harness、dsh-superagent、Engram（记忆）、DeepSelect（自检索）、profile-data、awesome-deepseek-agent。
**其中没有任何机器人策略、VLA、控制或仿真项目。** 独立复核：另一路委派调研对 deepseek-ai 组织的 **46 个公开仓库**做了独立清点，同样没有 robot / embodied / VLA 命名项目，也未发现官方任何具身方向表态——与本轮关键词扫描结论一致。[E1] 与"物理世界"最接近的是 **DreamCraft3D**（2024，3D 资产生成）——它生成的是**内容资产**，不是**动作策略**，更不是闭环控制。[E1]

> 这里要说清一个容易混淆的点：多模态理解（VL/VL2）≠ 具身动作。缺的是从"看懂"到"动起来"之间的全部环节：动作空间表示、时序控制、动力学、接触与力、安全约束。

### 3.3 支持性解读（弱证据，但成立）

即便动机未证实，下面三条**结构性事实**让"Super-agent 与具身自主同构"成为有价值的分析对象：

1. **它被定位为通用 agent 运行时，而非某个应用的脚本**：`cordis.patch.yml` + Harness 的"everything is a plugin"架构意味着，**新的 Source/Executor 是一等扩展点**——这正是"接物理世界"在工程上的入口形态（只是目前没人接）。[E1]
2. **官方自己把"云端 agent 触达本地设备"列为安全风险**：这说明作者团队在思考的是**泛在设备**（电脑、手机、家电、机器人都在其中），而不是纯软件。[E2]
3. **Router/Worker 分层在具身侧有直接同构物**：《Know When to Escalate: Critic-Guided Adaptive Execution for Cloud-Local Embodied Agents》（arXiv:2610.30587，2026-10-22）把机器人任务拆为**云端长程推理**与**本地快控制**两层，由 critic 在中间触发升级/降级，报告 **time-between-action latency 降低 28.8%–82.6%**、任务成功率相对最强协作基线提升 **6.3–18.3 个百分点**；其 **shared handoff memory** 在执行体之间保持上下文与任务进度，与 Super-agent 的 Chain of Recall / Inline & Spill 同构。Super-agent 的 Router（快、只做判单）与 Worker（慢、可长跑）在结构上一一对应。[E1]

### 3.4 最硬的一条：coding agent 正在变成具身智能的上游供给

《Gym-Anything for Robotics: Scaling physical simulations with digital agents》（arXiv:2610.40565，2026-10-29）的核心论点与数据：[E1]

- 论点：*"simulation creation is a coding agent task, so improvements in coding agents translate directly into richer and more faithful simulations."*
- 现状：RoboWorld 基准（25 个仿真任务）上，**所有被测前沿模型全部失败，平均 reward 仅 0.06**；甚至最优模型的成功任务数也远低于人类。
- 做法：用 agent 写**代码策略**生成仿真任务与演示数据，用"特权经验"自辅助学习，再蒸馏到 π0.5 之类的策略上。
- 推论：**具身智能当前最稀缺的资源之一是"可验证的物理经验数据"，而生产这类数据的一个可行路径，恰恰是让自主 coding agent 造仿真、造任务、造策略。** 这就是"Super-agent 式的自主性"对具身最直接、也最可验证的贡献路径。

**更直接的桥接证据（E1）**：2026-10-27 的《RoboAuto: Autonomous Robot Program Search through Multi-Level Physical Understanding》（arXiv:2610.36533）开篇即指出——LLM agent 已能"迭代生成、评估并改进可执行解"，并在机器人操作中以 **Code-as-Policy** 的形式工作；2026-10-29 的《CaPtain: A Pipeline for Post-Training Code-as-Policy Robot Agents》（arXiv:2610.40799）进一步把"代码即策略"的机器人 agent 做成了可后训练的流水线。**这意味着"coding agent"与"具身策略"在 2026 年已是同一套方法论的两副面孔：一边产出代码，一边产出动作程序。** 这是对用户直觉最有力的一手支撑——但它支撑的是"**方法论共用**"，而不是"DeepSeek 在为具身布局"。

> 换句话说：即使 DeepSeek 的动机**完全是 coding**，Super-agent 的自主性基础设施也**客观上**会被具身栈消费——只是路径是"供给数据与仿真"，而不是"接管身体"。

### 3.5 结论（分层给出）

| 命题 | 判定 | 依据 |
| --- | --- | --- |
| "DeepSeek 官方宣布为具身智能做准备" | ❌ **无证据，且现有证据反向** | J1–J5 全部不成立；仓库与文章零提及 |
| "Super-agent 的架构能迁移到具身自主" | ⚠️ **部分成立，有明确边界** | 上层（触发/授权/异步执行/上下文/人在环）可迁移；下层（闭环控制/世界模型/安全包络）不可迁移，见 §4.6 |
| "Super-agent 会间接服务具身（作为数据与仿真的上游）" | ✅ **成立，且有论文级证据** | arXiv:2610.40565 的论点与 RoboWorld 数据 |
| "这是官方意图" | ❓ **不可判定**（动机属公司内部信息，公开材料不可知） | —— |

**一句话回答用户的问题**：*如果把"为具身准备"理解成"官方宣布要造机器人"，那证据不支持；如果理解成"这套自主性基础设施会先在 coding 侧成熟、并在数据与仿真层实际喂给具身"，那么这个判断**方向上成立、证据上已有独立论文支撑**，但它是一个**关于未来的推断**，不是关于 DeepSeek 意图的事实。*

### 3.6 可证伪预测（未来 6–12 个月的观察清单）

**若假设升级为"可信"，应观察到以下任一（按信号强度排序）：**
1. DeepSeek 公开 VLA / 机器人策略 / 机器人仿真框架，或发布具身 benchmark；
2. `dsh-superagent` 出现 **telemetry / control / device / sensor** 类 Source 或 Executor（可在仓库关键词与提交历史中直接观测，成本极低）；
3. 官方长文或 Harness 文档出现 physical / embodied / real-time / control loop 字样；
4. DeepSeek 招聘中出现具身智能 / 机器人 / 强化学习控制岗（公开招聘页可核）。

**若假设应被降级为"纯 coding 叙事"，应观察到：**
- Super-agent 后续迭代只增加协作类 Source（Issue、飞书、Slack、文档）与评测；
- 看门狗、长期记忆、A2A 仍停留在文章层面，不进代码；
- DeepSeek 的公开仓库继续零具身资产。

> 这张清单的价值在于：**它把一次不可核验的动机猜测，转成了每周可复核一次的公开可观测指标。**（复核方式：仓库关键词计数 + 提交历史 + 招聘页 + 官方文档 diff。）

---

## 4. 技术发展分析：coding agent 与具身自主到底差在哪

用户直觉"具身智能跟 coding 是不一样的，需要自主性安排"是对的，但**"不一样"具体在哪一层**，需要拆开讲。下面用一个可复用的分析框架：**自主性栈（Autonomy Stack）**。

### 4.1 分析框架：自主性栈六层

| 层 | 职责 | coding agent 的成熟度 | 具身自主的成熟度 |
| --- | --- | --- | --- |
| **L1 感知与状态估计** | 从环境获取观测，形成对当前状态的估计 | 近乎完美：仓库状态是**精确、完整、无噪声**的；编译/测试给出确定性反馈 | **最弱层**：部分可观测、传感器噪声、多视角融合、状态估计本身是研究问题 |
| **L2 任务分解与调度** | 把目标拆成可执行步骤，并行/串行编排 | 高：SWE 基准上已可跑长链条；结构化上下文（Spine、依赖图）成熟 | 中：长时程分解仍脆弱（AtomTree 指出单次 LLM 规划的弱点，arXiv:2610.38744） |
| **L3 技能执行** | 在环境里施加动作 | 高：改文件、跑命令，可无限重放、可回滚（revert PR） | **次弱层**：动作不可重放、不可回滚，且受动力学与接触约束 |
| **L4 反馈与验证** | 判断"做对没有" | 中高：测试/CI 是廉价 oracle，但存在 reward hacking 与"测试绿≠需求满足" | 低：成功信号来自物理后果，昂贵、稀疏、延迟；arXiv:2610.39543 主张用 **consequence-grounded** 信号替代表面一致性 |
| **L5 记忆与上下文** | 跨会话/跨任务保持状态 | 中：上下文窗口 + 结构化压缩 + 外置记忆（Chain of Recall / Spine 式结构化子任务树） | 低：需要**场景持久化**（物体在哪、被人动过没有），与 L1 耦合 |
| **L6 授权与治理** | 决定谁能触发、什么算越权、如何审计与回滚 | 中：Super-agent 的 Trigger/Eval/Decision/Mandate 就是这一层 | 低：授权要落到**动作安全包络**（速度/力/碰撞/区域/人类共处规则），且不可逆 |

**关键判断**：coding agent 与具身自主**共享 L2、L5、L6 的架构需求**（这也是 Super-agent 真正可迁移的部分），而**分歧集中在 L1、L3、L4**（这恰恰是具身研究的主要战场）。这个切分解释了为什么"自主 agent 运行时"可以成为具身栈的上层，而不能替代具身栈本身。

### 4.1.1 参照系：具身一侧这两年的公开节奏（2024-10 → 2026-08）

要判断 Super-agent 与具身的关系，先得知道具身这一侧这两年的公开节奏（下表 arXiv 条目已逐条回查标题与日期）：

| 层级 | 公开节奏 |
| --- | --- |
| VLA 端到端主线 | π0（2024-10-31）→ π0.5（2025-04-22）→ Gemini Robotics（2025-03-25，arXiv:2503.20020）→ Gemini Robotics 1.5（2025-10，arXiv:2510.03342）→ GR00T N1（2025-03-18，arXiv:2503.14734）→ GR00T N1.5 / N1.6 / N1.7（具体日期仅见于 release 列表，[U]） |
| 架构范式 | GR00T N1 自论文起就是**双系统**（System 2 视觉语言模块 + System 1 diffusion transformer 动作头），Figure Helix 同走"通用脑 + 专用策略"（发布日未逐页核实，[E2]）——**"双层"在模型内部已是标准件**，与 Super-agent 的 Router/Worker 属同一种分层直觉的不同实现层 |
| 世界模型 | Genie 系列、V-JEPA 2（2025-06）、NVIDIA Cosmos（2025-01）、1X World Model Challenge 技术报告（2025-10，arXiv:2510.07092） |
| 评测 | LIBERO（2023-06）、BEHAVIOR-1K（2024-03）、RoboCasa（2024-06）、EmbodiedBench（2025-02）、AgiBot World（2025-03）、RoboArena 真机分布式评测（2025-06）、Behavior-Skill 长时程评测（2026-08，arXiv:2608.30536） |
| 数据 | AgiBot World 大规模真机采集平台（2025-03，arXiv:2503.06669）、银河通用 GraspVLA 千亿级合成动作预训练（2025-05，arXiv:2505.03233） |

两个常见误读需要先纠正：

- **SA-1 / SA-2 是分割与世界模型预训练的**数据来源**，不是"自主性分级"基准**；学界并没有统一的 autonomy level 标准，常见的四级表述（脚本/遥操作 → 端到端 VLA → 长时程多阶段 → 长时程自主）只是口头约定。[U]
- **主流 VLA 至今仍以短视野动作序列为主**，长时程专项评测（Behavior-Skill，2026-08）才刚出现；"LLM agent + 机器人"的公开代表作仍有限。[E2]


### 4.2 九条具体差异（附证据）

1. **时间尺度差 3–4 个数量级**：coding 是"分钟级调度 / 秒级动作"；具身是"毫秒级控制"。实测 NVIDIA GR00T N1.7（README 声明 Apache 2.0 且可商用，基座权重在 HF 上为 gated 访问）：在 RTX PRO 6000 Blackwell Server Edition 上约 **40 Hz**、Jetson AGX Thor 上经 TensorRT 约 **28 Hz**（batch-1 LIBERO，Thor MAXN + `jetson_clocks`）；VLM 骨干为 Cosmos-Reason2-2B（Qwen3-VL 架构），预训练含 20K 小时 EgoScale 人类视频。[E1]
2. **反馈的可得性与成本**：coding 的 oracle 是编译/测试（秒级、免费、可重放）；具身的 oracle 是物理后果（昂贵、稀疏、带噪声，且**不可重放**）。这直接决定了具身必须比 coding **更依赖先验（world model / VLA）而非在线试错**。
3. **不可逆性与安全包络**：PR 可 revert；机器人"抓错杯子""撞到人"不可 undo。授权模型必须从"要不要做"升级为"**在什么物理边界内做**"（force / speed / workspace / human-presence），且需要独立于执行体的**安全仲裁**。
4. **失败的可学习性不对称**：coding 失败几乎总能复现（环境可重建）；具身失败往往**不可复现**（接触、热、电池、磨损、他人干扰），因此"从失败学习"必须靠**数据化的事故记录**而不是"再跑一遍"。
5. **数据获取路线不同**：coding 数据是**副产品**（人类本来就在写代码）；具身演示数据是**人工成本中心**（遥操作）。arXiv:2610.40828《From Teleoperation to Long-Horizon Dexterity》（2026-10-29，CoRL 2026 Workshop）以 **281 条模仿学习策略、约 1,700 次真机试验**（五指手抓取并插入 RJ45 连接器）给出量化警示：点云策略上，仅 ROI 裁剪、机器人基座坐标系表示、点编码器内归一化三项各自就带来 **70–100 个百分点**的成功率提升；VLA 上改用绝对动作预测亦使插入成功率提升最多 70 个百分点。同时，**验证集 loss 与真机成功无一致关系**；67 项离线指标中仅 5 项（预测运动的平滑性与直接性，且仅在单一策略族内）与插入成功相关（r = −0.70 ~ −0.80）。结论是：离线指标只能用于初筛，不能替代真机评估。[E1]
6. **上下文结构与"物理记忆"不同**：coding 的上下文是文本/符号；具身的上下文是**几何 + 时序 + 场景状态**，纯 token 化的上下文工程无法直接承载。
7. **多智能体协作的语义不同**：Super-agent 的多 agent 是"任务并行、共享同一文件系统"；具身的多机器人是**共享物理空间**（相互阻塞、抢占同一目标、互相造成不可逆后果）。
8. **能耗与算力预算**：机器人是电池受限的嵌入式系统；一个"云端大模型 + 本地小模型"的分层必须在**能量**而非仅**延迟**上做预算（这解释了为何行业普遍走向 on-device 小模型 + 云端升级路径）。
9. **责任归属**：coding 领域的公开质疑已经出现（本地留存的媒体抓取件中就有读者指出："主动行动的 AI 出错时，谁来背锅？"）。在物理世界，同样的质疑会从"情绪"变成"法律与伦理问题"——**自主性越高，治理层越不能缺**。

### 4.3 自主性的经济学：coding 换"注意力"，具身换"风险敞口"

这是本报告最想强调的一条**结构性区别**，也直接决定了授权模型的设计差异：

- **coding agent 的自主性收益**：把人从"盯会话"中解放出来。官方口径就是"人只能同时盯 3–5 个会话"（E2）；机制是**注意力预算**问题，因此 Super-agent 的核心策略是"**尽量少打扰人，只在必须打扰时打扰**"，面板只显示需要人处理的事。[E1]
- **具身自主的自主性收益**：换的是**风险敞口**——每多一步自主，就多一份不可逆代价。因此具身领域的默认立场是**保守自主**（conservative autonomy）：速度/力/空间受限、人类共处规则优先、异常立即停机、升级路径必须显式。

**推论**：Super-agent 的授权模型（accept: off/observe/auto + Mandate 版本化 + 逐 Source 允许名单）在 coding 侧是**成熟解**；直接搬到具身侧会**系统性低估风险**。具身侧必须在同一套框架上再加两层：**动作危险度分级**与**独立于执行体的安全仲裁**。LFL 现有的"审查闸"（RULE-AI-28 / `review_admission`）本质上就是后一层的雏形——但它现在只作用于"发布/推送/全测"这类可回滚动作，尚未覆盖不可逆物理动作。

### 4.4 2026 年正在发生的架构收敛（这是"super agent"叙事最扎实的部分）

| 收敛点 | coding 侧 | 具身侧 | 共同抽象 |
| --- | --- | --- | --- |
| 分层决策（快判 + 慢执行） | Router / Worker（Super-agent） | 云端推理 + 本地快控制 + critic 升级（arXiv:2610.30587） | **两级自主体**：上层决定"要不要/交给谁"，下层决定"怎么做" |
| 结构化上下文 | Inline & Spill、Chain of Recall（Super-agent）；Spine 子任务树（arXiv:2610.37224）、CodeSpecWeave 规格编织（arXiv:2610.40256） | AtomTree 层级状态感知规划（arXiv:2610.38744） | **把上下文当作可管理状态，而非一串 token** |
| 依赖与验收的结构化 | WEAVE 把真实 PR 历史转成依赖结构化的可执行任务 + Graph Credit 度量（arXiv:2610.22039）；CodeSpecWeave 用相互依赖的规格与可执行测试合成任务（arXiv:2610.40256） | CoRAct 把推理与动作对齐到**可验证的后果信号**（movement 等物理可验证成分，arXiv:2610.39543） | **可验证的中间产物**替代"感觉对了" |
| 数据/环境的供给瓶颈 | 前沿模型在 SWE-bench Pro 上已到 51.78%（Nemotron 3.5 Super，arXiv:2610.38095）；**harness 本身**成为可递归自改进的优化对象（HarnessPro，arXiv:2610.26770） | RoboWorld：所有被测前沿模型在 25 个测试任务上**全部失败**，平均 reward 仅 **0.06**（arXiv:2610.40565） | **基准与环境成为主战场**，不再是"模型再大一点" |
| 现实差距 | 离线指标只能初筛策略，不能替代真机评估（arXiv:2610.40828：67 项离线指标仅 5 项相关，且仅限单一策略族内） | 同左：验证 loss 与真机成功无一致关系，表示选择造成 70–100pp 差距 | **"离线指标好"≠"现实表现好"** |

**2026-10 新增的两个信号（E1）**：

1. **harness 本身成了可自改进的优化对象**：《HarnessPro: Recursive Harness Self-Improvement with Pareto Optimization》（arXiv:2610.26770，2026-10-20）在 Terminal-Bench 2 / SWE-Bench Pro / ProgramBench 上，以 GPT-5.5+Codex、GLM-5.2+Claude Code 为被试，让 agent 诊断执行轨迹并改写自己的 harness；heavy 模式相对 RHO 取得平均 **+2.0 个百分点**通过率、**每任务成本 −26.1%**。**这意味着"agent 运行时"正从脚手架变成竞争性资产**——Super-agent 公开的正是这一层的参考实现，而本项目自己的 RSI 议题也落在这里。
2. **测试时扩展成为主流手段**：《Nemotron 3.5 Super and Lightning》（arXiv:2610.38095，2026-10-28）报告 Nemotron 3.5 Super 在 **SWE-bench Pro 上 51.78%**，并把"并行 agent 执行 + 自验证"作为测试时扩展手段。**"投机执行""自验证""并行编排"在模型侧与系统侧是同一件事**，只是 DeepSeek 把它写进了运行时。


**读法**：这五条收敛说明，"super agent"不是营销词，而是一个**正在发生的架构收敛**：把 agent 从"一次性会话里的问答模型"变成"**有结构化状态、有分层决策、有外部监督、能长期运行的系统**"。而**具身智能是这套架构最难的应用场景**，因为它同时压满了 L1/L3/L4 三层的短板。

### 4.5 迁移边界表：哪些部件能搬，哪些必须重做

| Super-agent 部件 | 具身对应物 | 可迁移？ | 失效模式 / 必须重做的部分 |
| --- | --- | --- | --- |
| Source（事件源） | 传感器流、任务队列、人类语音/手势指令 | ⚠️ 部分 | 传感器是**连续流**而非离散事件；Source 需支持采样率与时间戳对齐 |
| Trigger / Event → Thread | 一台机器人 / 一个场景 / 一个任务序列 | ✅ | 需要绑定**物理实例 ID** 而非仓库 ID |
| Eval（准入 + 研判） | 任务可行性/安全前置检查 | ⚠️ 部分 | 必须接入**动作可执行性**与**安全包络**，而非"要不要接单" |
| Decision（接单/停止/忽略/未完成） | 执行/暂停/拒绝/重规划 | ✅ | 需要新增"**紧急停止**"这一等公民状态（当前模型无此状态） |
| Mandate（授权） | 作业许可（谁能让它动、动多大范围、多久） | ⚠️ 部分 | 授权要绑定**时空域 + 动作类型 + 有效期**，且需可即时撤销（物理上撤销有延迟） |
| Ticket / Assignment（工单/派工） | 任务/子任务分配 | ✅ | 需支持**抢占与中断**（另一任务更高优先） |
| Executor（独立目录 + 独立会话） | 独立技能/策略实例 | ⚠️ 部分 | 物理世界**无法并行复制身体**；需资源锁与物理互斥 |
| Report / Delivery（回执 + PR） | 任务结果 + 状态回传 + 异常事故记录 | ✅ | 需结构化"事故/失败"记录（供后续学习） |
| 上下文工程（Spill/Recall） | 场景持久化记忆 | ❌ 不直接迁移 | 需 **3D/时序状态**表示，token 化不够（对应 L1/L5 的根本差异）；可参考 CARE 的 **shared handoff memory**（跨执行体保持上下文与任务进度，arXiv:2610.30587），但它保留的是**符号进度**而非物理状态 |
| Watchdog（官方文章有、原型无） | 独立于主体的安全监控/急停 | ✅ **概念可迁移，且最该优先搬** | 需要硬实时性与失效安全（fail-safe），不是普通看门狗 |
| Watchdog + BYOM | 端侧小模型 + 云端大模型 | ✅ | 需按**能量/热**而非仅延迟调度 |

### 4.6 三条趋势判断（附证伪条件）

| # | 判断 | 置信度 | 依据 | 证伪信号 |
| --- | --- | --- | --- | --- |
| **T1** | **coding agent 运行时会成为具身栈的"上层编排与治理层"**（负责触发、授权、审计、人机界面），但不替代 VLA/控制栈 | 中高 | arXiv:2610.40565 把仿真构建定义为 coding 任务并给出实证路径；2610.30587 的分层架构显示"上层慢推理 + 下层快控制"是行业共同收敛方向 | 具身侧自建端到端全栈且与 coding 栈完全隔离；或 Super-agent 长期停留在 demo |
| **T2** | **竞争主战场从"模型能力"转向"可验证的物理经验数据与环境"** | 高 | RoboWorld 前沿模型全败、平均 reward 0.06；真机试验表明离线指标无法预测实机表现（差 70–100pp） | 出现无需数据的通用真机策略（显著突破）；或合成数据完全不再需要 |
| **T3** | **自主性推进的主战场是"授权、可回滚、可归因"，而不是"更大的模型"** | 中高 | 官方自述难题即落在治理面（长期记忆、A2A、跨设备权限、提示注入）；本次发布的最大工程增量恰恰是授权模型（Eval/Decision/Mandate/accept-mode） | 出现"端到端自治 + 可归因"的新范式，使显式授权层成为冗余 |

> **对 T3 的补充（重要且可操作）**：Super-agent 的授权模型（accept 三档 + Mandate 版本化 + 逐 Source 允许名单 + 面板只露需要人处理的部分）**不是 DeepSeek 独有的**，而是与 Anthropic《Building effective agents》的 workflow/agent 分工、Claude Code 的权限模式、以及 OpenAI Codex 的 sandbox/approval 档位同属一个行业共识家族。[E2/E3] 这意味着：**这部分能力已经商品化，LFL 缺的也不是它，而是它与自身事件流的耦合。**

---

## 5. 竞争格局与舆论（2026-11 视角）

### 5.1 三条路线，边界正在移动

| 路线 | 代表 | 强项 | 短板 |
| --- | --- | --- | --- |
| **A. coding-runtime 通用化** | DeepSeek Harness + dsh-superagent；Anthropic/OpenAI 的 coding agent 家族 | 事件驱动、授权模型、协作与人机界面成熟；数据自产 | 不含物理世界能力；作者自述"部分模块未实现" |
| **B. VLA / 专用策略** | GR00T N1→N1.7（arXiv:2503.14734，2025-03；README 实测 ~40 / ~28 Hz，[E1]）；Gemini Robotics / 1.5（arXiv:2503.20020 / 2510.03342）；π0 / π0.5（2024-10 / 2025-04）；Gemini Robotics 2（2026-07-30，[E2 检索摘要，未逐页核实]） | 端侧实时性与双系统范式成熟；动作先验强 | 数据依赖重、验证信号稀缺、跨本体迁移难；**主流仍是短视野动作序列** |
| **C. 混合分层（cloud-local + critic）** | arXiv:2610.30587 类方法；行业普遍架构选择 | 同时拿到快控制与强推理；可按能量/延迟预算调度 | 升级判据与安全仲裁难做对 |

**判断**：2026 年的真实进展在 **A 与 B 的接合处**——A 侧提供"上层编排与治理"，B 侧提供"下层控制与先验"。Super-agent 的意义在于 **A 侧第一次把"授权模型"写成了可读的一等公民**（Trigger/Eval/Decision/Mandate），这恰好是 B 侧最缺、也最难外包的部分。

### 5.2 舆论与工程之间的错位（值得记录）

- 本仓库当日留存的榜单抓取显示，中文舆论已把"超级智能体/Super-agent"当作独立话题热议（热榜 rank 6、热度 5618310；[E1 本地留存]）。
- 但公开讨论中同时出现两条质疑：**①"自主性越强，人的角色越像签批机器，责任却仍在人"；②"Super-agent 是面向 coding 的 IDE 形态还是面向通用 Agent 形态"**（[E3 本地留存的媒体抓取件与评论]）。
- 这两条质疑，恰好对应本报告 §4.2 的第 9 条（责任归属）与 §3.5 的动机分层。**它们不是噪音，而是"授权模型必须成为一等公民"这一结论的独立佐证。**

### 5.3 中国团队的位置（一句话）

在 coding 侧，中国团队已有平台化产品与蒸馏小模型（如腾讯智能体平台、阿里云多智能体编排、阿里 "Quick" 0.3B 本地蒸馏，[E2 检索摘要，**未逐页核实**]）；在具身侧，公开可见的主力仍是 VLA 与机器人本体的产业玩家（智元、银河通用、宇树、千寻智能等，[E3 未逐页核实]）。**DeepSeek 在具身侧目前基本缺席——这正是"为具身准备"假设最大的空缺处，也是最容易被外部叙事填补的地方。**

---

## 6. 对本项目（LFL）的对照与可执行建议

### 6.1 LFL ↔ Super-agent 对照表

| Super-agent 概念 | LFL 中的对应物（现状） | 差距判断 |
| --- | --- | --- |
| Source（事件源） | 飞书/Web 通道、会话入口、网关事件 | ⚠️ 事件仍以"会话调用"为主，缺**常驻事件源**与订阅扇出 |
| Trigger / Event→Thread | `schedule`（含 wake / 常驻授权）、`event_predicate` | ✅ 有触发与常驻授权原语，**缺与业务事件流的直接绑定** |
| Eval（准入 + 研判） | RULE-AI-28 + `review_admission`（start/status，签发一次性资格） | ⚠️ 闸门只覆盖"发布/推送/全测"等**可回滚**动作；缺"入口身份 / 动作强度 / 影响范围"三要素 |
| Decision（接单/停止/忽略/未完成） | `task_update` 状态机（pending→in_progress→done/blocked/…） | ⚠️ 缺**紧急停止**类状态（具身必需） |
| Mandate（授权，版本化） | 规则集 `docs/ai_rules.md`、escalation_token、force_credential | ⚠️ 授权**绑定在规则文本**，不是绑定在"某动作 × 某范围 × 某有效期"的**可撤销授权对象** |
| Ticket / Assignment | durable Goal + Task 图（`create_goal`/`task_create`） | ✅ 已有可追踪工单与依赖 |
| Executor（独立目录 + 独立会话） | `spawn_subagent`（隔离 worktree + 独立上下文）、`dsh_task`（隔离进程/会话） | ✅ 相当完整；⚠️ worktree 孤儿清理机制（本次调研实际触发过 WORKTREE_LIMIT）需常态化 |
| Report / Delivery | `evidence_refs`、`settlement_*`、`present_files` | ✅ 证据链与结算完整，是 LFL 相对 Super-agent 的**强项** |
| Panel（只露需要人处理的事） | Web UI + `service_control` 视图 | ⚠️ 面板视角目前是"服务生命周期"，不是"**待人决策的工作项**" |
| Watchdog（官方文章有、原型无） | `service_control` 的 desired-state CAS + reaper 分档回收（30s/120s/2100s）+ `event_predicate` 唤醒 | ✅ **已有等价机制**，但未以"看门狗"显式组织与审计 |

**一句话**：LFL 在**证据链、结算、任务图**上强于 Super-agent 原型；在**事件驱动常驻、授权对象化、面板视角**上弱于它。这三条是本次发布对 LFL 最直接的可借鉴点。

### 6.2 五条可执行建议

**A1 —— 把"每次调用即过闸"升级为"事件驱动常驻源"（优先级：高）**
- 为什么：Super-agent 的增量主要不在模型，而在"**事件先于会话**"。LFL 目前的许多能力仍以"被调用"为入口。
- 怎么做：定义最小 Source 协议（事件 → 结构化 Trigger → 落点标识），把现有 `schedule` 的周期任务与业务事件统一成 Trigger 源；先接一个真实来源（网关/飞书/仓库事件）。
- 验收：任一 Trigger 能被独立回放并产生可追溯的 Decision 记录；触发不依赖人发起会话。
- 风险：常驻源会带来"无人值守时的错误放大"，必须与 A2/A3 同时上，不得单独启用。

**A2 —— 把授权从"规则文本"提升为"可撤销的授权对象"（优先级：高）**
- 为什么：Super-agent 的 Mandate（绑定 Thread、版本化、可撤销）与 accept 三档（off/observe/auto）是**可移植的最小授权单元**；LFL 现有规则集更接近"策略文档"，难做单动作撤销。
- 怎么做：引入 `Mandate{id, scope, strength∈{off,observe,auto}, expires_at, version, revocation_log}`；把 `review_admission` 的"资格"从一次性令牌扩展为可续期/可撤销的授权；强度分档与 DeepSeek 的 accept 模式对齐。
- 验收：任何一次自动执行都能回答"依据哪条 Mandate、哪个版本、是否仍在有效期内"。
- 风险：授权对象化会让规则与实际授权**双源不一致**，必须规定"运行时以 Mandate 为准，规则只作生成器"。

**A3 —— 把现有的 reaper/CAS 显式升级为"看门狗巡检回路"（优先级：中高）**
- 为什么：官方文章把看门狗列为五大模块之一却**未实现**（0 命中），而这恰恰是 LFL **已经具备**的能力：desired-state CAS、reaper 分档回收、`event_predicate` 唤醒。**这是 LFL 可以立刻补上 DeepSeek 缺的一块，且值得对外表达。**
- 怎么做：定义巡检项（服务活性、任务停滞、证据缺口、授权过期、上下文超限），统一为"检测 → 判定 → 动作（续期/降级/回收/升级）"的闭环，并记录审计。
- 验收：任意"卡死"的 Task/服务能在约定时限内被检出并处置，且处置过程有审计记录。
- 风险：巡检项过多会产生噪声与误处置；需分级（阻断级 vs 建议级）。

**A4 —— 上下文从"窗口预算"走向"结构化状态"（优先级：中）**
- 为什么：Super-agent 的 Inline & Spill、Chain of Recall，与学界的 Spine（子任务树结构化上下文，arXiv:2610.37224）、CodeSpecWeave（规格编织，arXiv:2610.40256）指向同一件事：**长时程任务的胜负手是上下文结构，不是窗口大小。**
- 怎么做：对长任务引入"结构化子任务树 + 外置记忆（Engram 经验库、synopsis 长源摘要）"，在 `adjust_strategy.history_budget` 之外定义"什么进上下文、什么进记忆、什么只留指针"。
- 验收：长任务的失败归因中，"上下文丢失/错配"占比可量化并下降。
- 风险：结构化本身增加编排成本；需用小样本先验证收益再推广。

**A5 —— 具身方向：不入场控制栈**，先做"仿真与数据生成即 coding 任务"（优先级：中）
- 为什么：这是**唯一有论文级证据支持、且与 LFL 现有能力（coding、证据链、结算）完全对齐**的具身切入点（arXiv:2610.40565）。同时它避开了 T3 风险（不可逆动作）与 §3 的动机不确定性。
- 怎么做：做一条小闭环——**用 LFL 的 coding 能力生成仿真任务/环境脚本/演示数据 → 用 LFL 的 evidence/settlement 机制记录每个物理实验的可追溯过程（参数、随机种子、失败模式）**。产出物是"数据与环境的可复现记录"，不是机器人。
- 验收：生成的环境/演示能被第三方按记录复现；失败样本进入经验库并可被检索复用。
- 风险：容易滑向"做一个半成品机器人栈"；**明确拒绝**接入真实执行体（不可逆动作）。

### 6.3 明确不建议做的三件事

1. **不要把"自主"等同于"放权"。** Super-agent 的自主性收益是"注意力预算"问题（coding），迁移到具身会变成"风险敞口"问题；照搬 accept=auto 到物理动作是**系统性低估风险**。
2. **不要在报告/结论中把"为具身准备"写成事实。** 依据见 §3.5；正确写法是"无公开证据 + 架构可迁移 + 存在间接供给路径"。
3. **不要把厂商叙事当结论。** 官方实验是合成负载、只测调度不测质量；"p95 更快"≠"能力更强"。引用时必须带这两句限定。

---

## 7. 风险、不确定性与未核实清单

| # | 项 | 状态 | 影响 | 处置建议 |
| --- | --- | --- | --- | --- |
| U1 | 官方公众号长文**原文全文**未取得（抓取被拒、检索命中链接经核对无关） | 未核实 | §2.2 的模块名/机制名/实验数字均为二手转述 | 引用时标 E2；后续人工登录微信复核原文即可闭合 |
| U2 | 具身侧委派调研 | **已完成并并入**（§4.1.1、§5.1、附录 C） | —— | 其 arXiv 引用已由本轮 `id_list` 方式逐条回查标题与日期 |
| U3 | Gemini Robotics 2（2026-07-30）、GR00T Reference Humanoid Robot、中国厂商 2026 年动态、Figure Helix 官方原文 | E2/E3，未逐页核实 | §5 格局判断的时效性与细节 | 引用时保留"未逐页核实"标注 |
| U8 | GR00T N1.5 / N1.6 / N1.7 的确切发布日；学界是否存在统一的 autonomy level 标准 | U（只见 release 列表 / 口头约定） | §4.1.1 时间线的精度 | 引用时按"约 2025-12 / 2026-04"表述，不作精确断言 |
| U4 | 官方实验数字的统计口径（样本量、任务构成、对照基线） | 未核实 | 不能据此比较不同系统的优劣 | 只在"同口径内部比较"意义下引用 |
| U5 | Super-agent 内部版与公开版的差异 | 不可知 | 无法评估其真实成熟度 | 只能以公开版为界 |
| U6 | "看门狗"在原型中缺失，究竟是"未实现"还是"改名" | 未核实（0 命中） | 影响对"官方进度"的判断 | 记为待观察项，随 §3.6 清单复核 |
| U7 | 本报告的 LFL 对照部分基于本仓库当前实现与工具契约 | 局部 | 运行时行为可能与文档口径有偏差 | 以工具回执为准；§6 建议均标注为待落地项 |

---

## 附录 A：Super-agent 领域模型速查（据 `docs/001-domain.md`、`002-authorization.md`、`003-execution.md`）

| 概念 | 一句话释义 | 关键规则 |
| --- | --- | --- |
| Source | 事件来源（GitHub issue / 飞书），提供真实数据 | 可逐个允许或禁止 |
| Trigger | 事件落到某个 Thread（一个仓库 = 一个 Thread） | 事件驱动，非会话驱动 |
| Eval | 准入检查 + 研判 | 失败 ≠ 拒绝（有 Mandate 时降级为自动执行） |
| Decision | 接单 / 停止 / 忽略 / 未完成 | 四选一 |
| Mandate | 对 Thread 的授权，版本化、可撤销 | **准入的兜底判据** |
| Ticket | 可追踪工作项（对标 issue） | 每个 Ticket 独立 agent 会话与目录 |
| Assignment | 一次派工 | 可多工单并行 |
| Subscription | 订阅规则，扇出为 Assignment | **扇出不带准入检查，Mandate 才是授权** |
| Executor | 执行者 | 以 operator OS 用户 + `danger-full-access` 运行；官方不声称是安全边界 |
| Report / Delivery | 交付回执 | 产物是文件与 PR；面板只显示"需要人处理"的项 |
| accept mode | off / observe / auto | 全局或逐 Source 的执行强度分档 |

## 附录 B：本轮一手取证方法（可复现）

```bash
# 仓库元数据（MIT / 单次提交 / star 数）
curl -s https://api.github.com/repos/deepseek-ai/dsh-superagent-prototype
curl -s "https://api.github.com/repos/deepseek-ai/dsh-superagent-prototype/commits?per_page=10"
# 文件树
curl -s "https://api.github.com/repos/deepseek-ai/dsh-superagent-prototype/git/trees/main?recursive=1"
# 文档快照（README / SETUP / docs/000-008），本地拼接后做关键词计数
for f in 000-philosophy 001-domain 002-authorization 003-execution 004-prompts \
         005-panel 006-deployment 007-architecture 008-cookbook; do
  curl -s -o docs/$f.md "https://raw.githubusercontent.com/deepseek-ai/dsh-superagent-prototype/main/docs/$f.md"
done
cat docs/*.md README.md SETUP.md > all_docs.txt   # 2,091 行
for k in embod robot 具身 "physical world" manipul watchdog "real-time" "control loop" sim2real; do
  printf "%-16s %s\n" "$k" "$(grep -ic "$k" all_docs.txt)"; done   # 全部 0
```

## 附录 C：来源清单

| # | 来源 | URL / 路径 | 日期 | 级别 | 支撑论断 |
| --- | --- | --- | --- | --- | --- |
| S1 | DeepSeek Super-agent 原型仓库（README/SETUP/docs） | `github.com/deepseek-ai/dsh-superagent-prototype` | 2026-10-31 起 | E1 | 发布物性质、领域模型、授权模型、执行模型、面板、关键词 0 命中 |
| S2 | 仓库 GitHub API 元数据 | `api.github.com/repos/deepseek-ai/dsh-superagent-prototype` | 2026-11-02 取 | E1 | MIT、单次提交、created/pushed 时间、star 8,187 / fork 830 |
| S3 | 本仓库日报（发布物核验） | `docs/promotion/20261102-lfl-daily-52.md` | 2026-11-02 | E1（内部） | 官方文章口径、看门狗未实现、star ~7.2k、结论口径 |
| S4 | 本地留存的官方文章转述抓取件 | `docs/promotion/receipts/d52research/article-7703116079979102762.txt`、`trending_text.txt` | 2026-11-02 | E2/E3 | 官方模块划分、媒体转述、舆论质疑（人工盯防 / IDE vs 通用 Agent） |
| S5 | IT之家《DeepSeek Harness 团队发布 Super-agent 研究原型》 | `ithome.com/1/020/615.htm` | 2026-10-31/11-01 | E2 | 发布内容与官方实验数字转述 |
| S6 | aicodewith.ai Super-agent 综述 | `aicodewith.ai/zh/blog/deepseek-super-agent-review-dsh-superagent` | 2026-11 | E2 | 五个模块、Router 压测数字、token 成本口径 |
| S7 | eneralabs / explainx.ai 解读 | `eneralabs.com/blog/...`、`explainx.ai/blog/...` | 2026-11 | E2/E3 | Router/Worker/Trigger/Watchdog 架构概述 |
| S8 | Gym-Anything for Robotics | `arxiv.org/abs/2610.40565` | 2026-10-29 | E1 | 仿真构建是 coding agent 任务；RoboWorld 前沿模型全败、平均 reward 0.06 |
| S9 | Know When to Escalate: Critic-Guided Adaptive Execution for Cloud-Local Embodied Agents（CARE） | `arxiv.org/abs/2610.30587` | 2026-10-22 | E1 | 分层自主体；成功率 +6.3–18.3pp；time-between-action latency ↓28.8–82.6%；shared handoff memory |
| S10 | From Teleoperation to Long-Horizon Dexterity（281 条策略 / 约 1,700 次真机试验，CoRL 2026 Workshop） | `arxiv.org/abs/2610.40828` | 2026-10-29 | E1 | 表示选择带来 70–100pp 差距；验证 loss 与真机成功无一致关系；67 项离线指标仅 5 项相关且仅限单一策略族 |
| S11 | AtomTree（层级状态感知规划） | `arxiv.org/abs/2610.38744` | 2026-10 | E1 | 单次 LLM 规划的弱点与层级化改造 |
| S12 | CoRAct（后果对齐的推理-动作一致性） | `arxiv.org/abs/2610.39543` | 2026-10 | E1 | 需要可验证后果信号而非表面一致性 |
| S13 | Spine: Compiling Subtask Trees into Structured Context for Long-Horizon Coding Agents | `arxiv.org/abs/2610.37224` | 2026-10-27 | E1 | 结构化上下文优于平铺上下文；压缩历史会丢失未完成子任务信息 |
| S14 | CodeSpecWeave（相互依赖的规格）/ WEAVE（依赖结构化任务 + Graph Credit） | `arxiv.org/abs/2610.40256`、`arxiv.org/abs/2610.22039` | 2026-10-29 / 2026-10-20 | E1 | 规格与依赖的可验证化；可验证的中间产物替代"感觉对了" |
| S15 | HarnessPro: Recursive Harness Self-Improvement with Pareto Optimization | `arxiv.org/abs/2610.26770` | 2026-10-20 | E1 | harness 成为可自改进优化对象；heavy 模式 +2.0pp 通过率、每任务成本 −26.1%（对比 RHO） |
| S16 | NVIDIA Isaac-GR00T README（N1.7） | `github.com/NVIDIA/Isaac-GR00T` | 2026 | E1 | ~40 Hz / ~28 Hz 端侧推理、Cosmos-Reason2-2B / Qwen3-VL 骨干、20K 小时 EgoScale、许可 |
| S17 | Gemini Robotics 2（2026-07-30） | 检索摘要（未逐页核实） | 2026-07-30 | E2/U | 三模型、整体控制、多机器人协同、端侧适配 |
| S18 | Anthropic《Building effective agents》（workflow vs agent）、Claude Code 权限档位 | `anthropic.com/engineering/building-effective-agents` 等 | 2024–2026 | E2 | 授权/审批分档是行业共识家族，非 DeepSeek 独有 |
| S19 | METR 长时程时间跨度研究（子代理转述） | `metr.org`（E2/E3） | 2025–2026 | E2 | 长时程可靠性的度量与现状；具体数值**未逐页核实** |
| S21 | Nemotron 3.5 Super and Lightning | `arxiv.org/abs/2610.38095` | 2026-10-28 | E1 | SWE-bench Pro 达 51.78%；并行 agent 执行 + 自验证的测试时扩展 |
| S22 | RoboAuto: Autonomous Robot Program Search through Multi-Level Physical Understanding | `arxiv.org/abs/2610.36533` | 2026-10-27 | E1 | LLM agent 迭代生成/评估/改进可执行解；Code-as-Policy 用于机器人操作 |
| S23 | CaPtain: A Pipeline for Post-Training Code-as-Policy Robot Agents | `arxiv.org/abs/2610.40799` | 2026-10-29 | E1 | "代码即策略"的机器人 agent 后训练流水线 |
| S24 | AtomTree（IROS 2026） | `arxiv.org/abs/2610.38744` | 2026-10-28 | E1 | 层级子目标树 + 轻量记忆 + 回溯重规划；ALFRED 上优于既有 LLM 规划器 |
| S25 | Gemini Robotics: Bringing AI into the Physical World | `arxiv.org/abs/2503.20020` | 2025-03-25 | E1 | VLA 家族 + Gemini Robotics-ER 具身推理模型；含安全讨论 |
| S26 | Gemini Robotics 1.5 | `arxiv.org/abs/2510.03342` | 2025-10 | E1 | VLA + Gemini 分层 |
| S27 | GR00T N1（双系统架构） | `arxiv.org/abs/2503.14734` | 2025-03-18 | E1 | System 2 视觉语言 + System 1 扩散动作头，与 Super-agent 分层同构 |
| S28 | RoboArena（真机分布式评测） | `arxiv.org/abs/2506.18123` | 2025-06 | E1 | 真机评测的跨策略不可比问题 |
| S29 | Behavior-Skill（长时程 VLA 评测） | `arxiv.org/abs/2608.30536` | 2026-08 | E1 | 长时程专项评测出现，说明主流 VLA 仍以短视野为主 |
| S30 | AgiBot World Colosseo（智元大规模真机采集） | `arxiv.org/abs/2503.06669` | 2025-03 | E1 | 具身数据成本是产业级瓶颈 |
| S31 | GraspVLA（银河通用合成动作预训练） | `arxiv.org/abs/2505.03233` | 2025-05 | E1 | 千亿级合成动作预训练路线 |
| S32 | 1X World Model Challenge 技术报告 | `arxiv.org/abs/2510.07092` | 2025-10 | E1 | world model 与自采数据路线 |
| S33 | π0 / π0.5 官方博客 | `physicalintelligence.company/blog/pi0`、`/pi05` | 2024-10-31 / 2025-04-22 | E1 | 端到端 VLA 路线与开源权重 |
| S34 | deepseek-ai 组织仓库清单（46 个公开仓） | `api.github.com/orgs/deepseek-ai/repos` | 2026-11-02 取 | E1 | 独立复核：无 robot / embodied / VLA 命名项目 |
| S20 | LFL 本仓库规则与设计 | `docs/ai_rules.md`、`docs/DESIGN-20261028-web-model-admin-dsh-alignment.md` | 2026-10/11 | E1（内部） | LFL 侧对照与 §6 建议的落点 |

---

## 尾注

1. 本报告所有"实测"结论（仓库元数据、关键词计数、文档释义）均取自 2026-11-02 10:11–10:30 CST 的直接抓取；一手快照存于会话临时目录 `/tmp/dsh/`。
2. 官方公众号长文原文未取得，涉及官方文章的表述一律标 E2 并注明"二手转述"；**未核实项已在 §7 单列，结论不依赖任何未核实项**。
3. arXiv 编号与论文主张为 E1（通过 arXiv API 直接读取题名/日期/摘要），本报告未逐篇通读全文，故只引用其摘要级论断。
4. §6 的建议均为**待落地项**，本报告不声称已实现任何一条。
6. 附录 C 中所有 arXiv 编号均以 `id_list` 方式逐条回查标题与摘要确认；成稿过程中一条误配编号（曾把 SWE-bench Pro 相关论述挂到无关编号）已在交付前更正。
7. §4.1.1 与 §5.1 的具身产业节奏由独立委派调研产出，其 arXiv 引用已由本轮再次回查；标注为 E2/U 的条目保持原状不升格。
5. 本报告的结论与本仓库 2026-11-02 日报**不冲突**：日报负责"发布物是什么、有没有坑"，本报告负责"这说明什么趋势、对我们意味着什么"。
