# ASSESS-20261002— 是否引入 OpenSpec：与当前 LFL 工作流的适配性评估

> **类型**: 评估 | **日期**: 2026-10-02 | **提问**: ① 结合当前工作流，是否值得引入 OpenSpec？② 文中工具（OpenSpec + Superpowers）与本仓工具链的适配性对比。
> **结论先行**: **不引入 OpenSpec CLI 本体**；以格式约定方式吸收其 3 项机制（WHEN/THEN 验收场景、验收后归档合并、spec 腐化防护意识）。核心理由：与仓内既有机制重叠度极高，引入会制造第二个规范真相源，且其约束层（提示词文件）弱于本仓已有约束层（工具协议硬门禁）。
> **输入**: 头条文章存档（`docs/local/NOTE-20261002-openspec-superpowers-article.md`）；OpenSpec 官方仓库快照（github.com/Fission-AI/OpenSpec，2026-10-02 抓取，`evidence://v1/fb7ff31b11a56f6330d3447e0b956253e6993b382a5adb9d0447015e4f3b9a18`）；本仓文件系统与工具面实测（2026-10-02）。

## 1. 评估对象当前形态（官网快照，非训练记忆）

- 新版为 **artifact-guided workflow**：`/opsx:explore` → `/opsx:propose`（生成 proposal.md + specs/ + design.md + tasks.md 四件套）→ `/opsx:apply` → `/opsx:archive`（delta 合并进 `openspec/specs/`）。
- 目录约定不变：`openspec/specs/`（系统现状）+ `openspec/changes/`（进行中增量）+ `changes/archive/`。
- 支持 30+ AI 助手（斜杠命令注册）；官方推荐高推理模型 + 干净上下文。
- 进阶：profile 可启用 `/opsx:verify`（对照规范验证实现）、`/opsx:ff`、`/opsx:continue`；stores 模式支持跨仓库共享规范。
- 自我定位："fluid not rigid / built for brownfield"；与 Spec Kit（重型门禁）、Kiro（IDE 锁定）对比强调轻量。MIT；默认匿名遥测（命令名+版本，可 `openspec config set telemetry.enabled false` 关闭）。

## 2. 本仓既有机制实测清单（对比基线）

| 文中概念 | 本仓对应物 | 实测证据 |
|---|---|---|
| 变更四件套目录 | `.codeartsdoer/specs/<change-id>/`：`spec.md`（需求规格，含能力域分节）+ `design.md`（技术方案）+ `tasks.md`（任务清单：垂直切割/验收标准/零回归红线/测试隔离红线） | 仓内数十个变更目录在用；抽样 `d1_event_sourcing` 三件套齐全，tasks.md 含逐任务验收与 `pytest/ruff/pyright` 红线 |
| 系统现状主规范 | `docs/` 下 ARCHITECTURE-*/CONVENTIONS/AX-* 等类型化文档 + `search_docs` 检索；**无按能力域组织的单一现状规范，无机械合并** | `docs/` 树实测；这是真实缺口（见 §4） |
| 归档合并 | 无机械步骤；部分变更有 RESULT/EXECUTION 后续文档 | `docs/analysis/` 内 MAINLINE-RECONCILIATION 系列为多阶段手工文档 |
| TDD 硬门禁 | `tdd_red_green` 工具（red→green 循环）+ 仓级测试门禁契约 | 工具面 + `docs/DEVELOPMENT_REPAIR_SAFETY.md` 契约 |
| systematic-debugging | `fix_loop`（check→定位→子代理修复→重跑，机械编排）+ `code_review` | 工具面 |
| verification-before-completion | `present_files` 产物声明（execute_command 产物必须显式声明）、`update_goal` 终局证据门（任务图收口 + evidence verified）、declaration_check 机制 | 工具协议层强制 |
| 零上下文子代理工单 | durable Goal/Task 图（`task_create` 带 acceptance）+ `spawn_subagent`(acceptance) / `workflow_run`(DAG) / `dsh_task` | 工具面 |
| writing-skills 自定义技能 | `method_manage`（candidate→qualification 生命周期）+ `save_experience` + `skill_list/skill_load`（外部 SKILL.md） | 工具面 |
| 架构变更提案（人审） | `submit_evolution`（人工审阅，可 exec_override 授权执行）+ AGENTS.md 准入不对称原则 | 工具面 + `AGENTS.md` 实测 |
| explore 零风险探讨 | `brainstorm_design` / `design_review` / `grill_me`（只分析不落码） | 工具面 |

## 3. 分层对比

### 3.1 合同层：OpenSpec 四件套 vs `.codeartsdoer/specs/` 三件套 —— 高度同构
形态几乎一一对应（spec↔proposal+specs、design↔design、tasks↔tasks）。差异在两点：OpenSpec 有 CLI **自动创建**与 **archive 机械合并**；本仓靠会话驱动手工维护。功能上"需求落文件、变更可追溯"这一核心价值本仓已具备且在用。

### 3.2 纪律层：Superpowers 技能包 vs LFL 工具协议 —— 本仓更强
Superpowers 的门禁（先测试后实现、完成前验证）是**提示词层**约束——依赖模型遵守技能文本。本仓对应物在**工具协议层**：产物不声明无法交付、Goal 终局要过证据门校验、灾难命令有硬安全边界、测试红线写入 tasks.md 并由 CI 执行。引入 Superpowers 不新增任何强制力，反而引入需要同步的提示词资产。

### 3.3 编排层：tasks.md 工单 vs Goal/Task 图 + 子代理 —— 本仓更强
文中"技巧三"（零上下文工单 + git worktree 并行）在本仓是原生能力：Task 图带 acceptance、子代理隔离派发、DAG 编排。

### 3.4 治理层：OpenSpec 提案 vs 准入不对称 —— 本仓语义更明确
`AGENTS.md`（2026-09-09）：放大模型 agency 的变更默认准入；增加控制机械的变更必须论证"为何模型+现有工具无法自行判断"。OpenSpec CLI 本质是外部控制机械，按本仓治理北极星属于后者，需先通过该论证——而 §2 事实显示主体能力已覆盖。

## 4. 缺口分析：文中机制里本仓确实没有的

1. **WHEN/THEN Scenario 统一验收格式**。本仓 tasks.md 的验收写法多样（"验证：python -c 断言…"等），无统一场景格式，调试时缺一个客观对照基准（文中"技巧二"的全部价值来源）。
2. **验收后机械归档合并**。无"功能验收完 → delta 并回现状文档"的既定步骤；规范更新靠自觉，正是文中"spec 腐化"风险的暴露面——本仓 `docs/` 已有大量一次性分析文档堆积、无腐化守卫，此风险并非假设。
3. **跨仓库 stores**。本仓单仓场景，用不上。

## 5. 裁决：不引入 CLI 本体

1. **双真相源**：`openspec/` 与 `docs/` + `.codeartsdoer/specs/` 并存，"哪边是现状"立即成为问题；文中自警"过期规范比没有规范更糟"。
2. **命令面错配**：`/opsx:*` 面向外部 AI 助手的斜杠命令注册；本仓 harness 本身就是编排者，引入等于在自研 harness 内再嵌一层外部 harness 指令文件，职责重叠。
3. **约束层倒退**：OpenSpec 的强制力止于提示词文件；本仓门禁在工具协议/CI 层，更强。
4. **治理北极星**：控制机械需论证必要性（§3.4），论证不成立。
5. **维护税**：`openspec update` 刷新指令文件、Node 全局依赖、默认遥测需显式关闭——均为纯成本。

## 6. 吸收建议（不引入 CLI，格式约定级落地）

| 吸收项 | 落地方式 | 成本 |
|---|---|---|
| WHEN/THEN 验收场景 | `.codeartsdoer/specs/*/spec.md` 验收段统一用 `#### Scenario:` + `WHEN/THEN`；fix_loop 的 check_command 与测试断言直接引用该场景 | 低（写法约定） |
| 验收即归档 | 变更验收闭合时：spec 目录补 RESULT 文档 + 回写 `docs/` 对应现状文档（ARCHITECTURE-*/CONVENTIONS），把该步骤与"测试过了才合并"同级；手工纪律即刻生效，机械化提案已提交：**EVO-20261002-daa84575**（Goal 终局门新增 spec 归档声明检查轴，pending_review 2026-10-02） | 中（流程约定） |
| 流程分级显式化 | 文中"技巧四"分级（小改直说/边界清晰走 spec 目录/动架构全家桶）与本仓现状一致，可存为 method/experience 供检索 | 低 |

## 7. 文中"三盆冷水"的本仓适用性

- 原型期别上提案 → 本仓已有等价实践（`.tmp-ci/`、worktree 沙箱先例）。
- 一句话能改的别惊动工具 → 同上，小改不强制走 spec 目录。
- 警惕 spec 腐化 → **本仓真实风险面**：`docs/` 历史分析文档无腐化守卫；吸收项 2（验收即归档）是针对性缓解。

## 8. 溯源

- 文章：`docs/local/NOTE-20261002-openspec-superpowers-article.md`（含 evidence ref 与内容 SHA）。
- OpenSpec 官网：`evidence://v1/fb7ff31b11a56f6330d3447e0b956253e6993b382a5adb9d0447015e4f3b9a18`。
- 本仓事实：`AGENTS.md`、`docs/` 树、`.codeartsdoer/specs/` 抽样、当前会话工具面（2026-10-02 实测）。
