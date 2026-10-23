# LFL 实时多模态（realtime_multimodal）实施任务清单（tasks）

> **元数据**
> - 特性名：`realtime_multimodal`
> - 文档角色：**实施任务清单（tasks，HOW-to-do）**；SDD 归档 `.codeartsdoer/specs/realtime_multimodal/tasks.md`（两处内容同步）
> - 版本：**v1.1** ｜ 日期：2026-10-23（v1.0 → v1.1：纳入**本地实时语音栈接线**定点修订）
> - 权威需求条款：`docs/SPEC-20261023-realtime-multimodal-requirements-v1.md`（**v1.2，163 条** `RTM-<GROUP>-<NN>`；既有 153 + 新增 10，**冲突以其为准**）
> - SDD 需求索引：`.codeartsdoer/specs/realtime_multimodal/spec.md`（v1.2，**索引非权威**）
> - 权威设计正本：`docs/DESIGN-20261023-realtime-multimodal-architecture.md`（**v1.3，本地实时语音栈接线**；保留 v1.2 的 8 项实现契约与 D1–D22，新增 D23–D28）
> - SDD 设计归档：`.codeartsdoer/specs/realtime_multimodal/design.md`（**v1.3**，与正本同步）
> - 原始设计依据：`docs/LFL-实时多模态-需求实现设计书-20261023.md`
> - M0 产物：`docs/M0-REALTIME-MULTIMODAL-READINESS-20261023.md`（v1.0 记录，**本轮仅设计不改该文件**；其探针 A/B 表述按设计 v1.3 重述为**部分解除**）
> - 事实基线：`main@36a3388e`
> - 任务 ID 约定：`T-<组缩写>-<NN>`（组缩写：DOC / M0 / CONTRACT / M1 / M2 / M3 / M4 / GATE / OPS / REV）
> - **组织原则**：按**用户可运行的闭环**组织（`SPEC §0.7`），**不为 163 条各设一道门槛**；163 条用于追溯与验收映射；首个执行单元仍为 **M0（结算）**，随后进入 **M1 本地语音栈接线**闭环
> - **本文档只做规划，不执行任何编码**；每条任务标注：任务 ID、关联 RTM 需求、依赖前置、涉及文件/模块落点、验收标准、可验证方式

---

## 0. 执行纪律与最高条款（全程最高，优先级高于本清单任何条目）

1. **防退化契约先行**（`AGENTS.md`）：任何改变/修复运行时行为的任务，**动手前**必须读 `docs/DEVELOPMENT_REPAIR_SAFETY.md`；保留精确来源，磁盘文件须有稳定可读 ref 才算闭环恢复路径。
2. **诊断真实输入**：先确认 Provider 可见输入与当前运行时事实，再改模型参数或归因模型能力；跨后端抄来的参数只作实验种子，**不作为对齐事实**。
3. **真实事件→回归测试**：把真实事故固化为回归测试；最终门禁跑**真实 staged/isolated 候选**，不跑陈旧 HEAD。
4. **不靠放宽基线转绿**：禁为让红守卫变绿而扩大架构/测试基线；先判定守卫是否揭示了真实职责错误。
5. **准入不对称**（`AGENTS.md`）：默认准入「放大模型能动性」的改动；「新增控制机械」须说明为何模型+现有工具无法自行判定，并提供**模型可调用的否决/覆盖出口**。
6. **阶段声明纪律**：M0 **不得以 mock 宣布完成**（`RTM-EVD-03`）；M3 完成前**不得**宣称「实时多模态 MVP 已交付」；性能**分开记录「已测」与「达标」**且**「已测」口径必须是浏览器链路端到端**，未达标不得宣布 M3 完成（`RTM-EVD-05`、`RTM-PRF-01`、`RTM-OBS-05/09`、`RTM-EVD-06`）。
7. **本地栈纪律（v1.3 新增，全程）**：首版**唯一链路 = 本地栈**（`mlx-audio` 转写会话 + Ollama `think:false` + 本地流式 TTS）；**不引入 WebRTC**、**不并行远端 Provider**、**不为未选远端 Provider 写空适配器**（`RTM-CAP-05/11/12`、D23）。`WS /v1/realtime` **仅转写**（无 `response.create`、无音频、无工具回环，`RTM-CAP-12`）；音频经**唯一控制通道 WS 二进制帧**承载（上行 16k PCM / 下行 TTS，`RTM-CAP-05`、`RTM-PLY-07`）；工具调用由**桥接基于 `committed` 编排发起**、仍经**唯一服务端入口**（`RTM-TOL-16`）。
8. **服务级 vs 浏览器链路分级（v1.3 新增，全程）**：**服务级已实测 ≠ 浏览器链路验收**（`RTM-EVD-06`）。服务级基线（12.23 s 等，`RTM-OBS-09`）**只作参考**，**不得**作为 M1/M3 浏览器链路验收值，也**不得**与浏览器样本**混算 P50/P95**。浏览器采集/播放/VAD/打断未接通时，依赖浏览器链路的条目（AUD/PLY/PRF/SCN/A11Y 相关）**必须标为未验收**。
9. **交付边界**（设计 v1.3 §4.4）：`Cookies`、浏览器缓存、`data/knowledge_scores/runner_state.json`、`data/runtime/learning_admission.json` 等**运行/用户态文件未被 Git 跟踪且被忽略**，**不清理、不回滚、不纳入提交**；提交**按精确路径逐项选择，不整目录 `git add`**。
10. **越界即停**：本阶段只产出 tasks.md 规划；发现实现问题时登记，**不越批实施**。

---

## 1. 任务总览、依赖关系与建议落位

### 1.1 首批 tasks 输入建议（v1.0 13 条）→ 本文任务落位（保留）

| 输入建议 ID | 建议说明 | 本文任务 ID |
|---|---|---|
| T-DOC-1 | 任务规划文档产出与归档 | `T-DOC-1` |
| T-M0-1 | 冻结候选 + 读防退化契约 + 只读核实存量接口事实 | `T-M0-1` |
| T-M0-2 | 选定 Provider/传输 + 编写能力档案（三态） | `T-M0-2`（v1.1 修订为「确认并冻结**本地栈** + preflight 约束」） |
| T-M0-3 | 执行最小探针 A/B/C（真实、非 mock） | `T-M0-3`（v1.1 修订为 A/B **部分解除**） |
| T-M0-4 | 记录基线 + 列阻断清单 + 门禁证据 | `T-M0-4`（v1.1 增 OBS-09 / CAP-13） |
| T-CONTRACT-1 | 唯一执行链 + 双层调用关联 | `T-CONTRACT-1`（v1.1 增 TOL-16 编排发起） |
| T-CONTRACT-2 | 工具幂等（桥接映射 + 稳定去重键 + 原子认领 + 重启恢复） | `T-CONTRACT-2`（v1.1 增 TOL-16） |
| T-CONTRACT-3 | Provider 适配器补齐接口 | `T-CONTRACT-3`（v1.1 拆 D1 实现）+ `T-CONTRACT-3D`（D2 预留不实现） |
| T-CONTRACT-4 | WS 握手鉴权与拒绝路径 | `T-CONTRACT-4`（v1.1 增音频二进制帧承载 + SEC-08） |
| T-CONTRACT-5 | 输入状态机 AwaitingFinal + 轮次分类 | `T-CONTRACT-5`（v1.1 增 FinalPass/INP-09） |
| T-CONTRACT-6 | 连接状态机全活动态可取消 + ready 定义 | `T-CONTRACT-6`（v1.1 增本地会话重建 REC-05） |
| T-CONTRACT-7 | 关键帧 current_validity / retention_state 分离 | `T-CONTRACT-7` |
| T-CONTRACT-8 | 预算计量适配层 | `T-CONTRACT-8`（v1.1 增本地算力/许可口径） |

### 1.1.1 设计 v1.3「对 tasks 的输入建议」→ 本文任务落位（v1.1 新增，必须纳入）

| 设计 v1.3 建议 | 建议说明 | 本文任务落位 |
|---|---|---|
| M0 修订 1 | `T-M0-2` = 确认并冻结本地栈（`mlx-audio`/Ollama/本地 TTS 的版本/接口/模型/许可）+ preflight 约束（CAP-14） | `T-M0-2`（重写） |
| M0 修订 2 | `T-M0-3` 探针 A/B 改标「**部分解除**：服务级已通、浏览器侧仍阻断，**不得宣布通过**」 | `T-M0-3`（重写 A/B） |
| M0 修订 3 | `T-M0-4` 增「服务级基线登记（OBS-09）」「观察项登记（CAP-13）」 | `T-M0-4`（新增子项） |
| M1 接线 1 | 浏览器 16k 重采样 + 客户端 VAD/打断 | `T-M1-9` |
| M1 接线 2 | `LocalVoiceStackAdapter`（本地转写会话） | `T-M1-10` |
| M1 接线 3 | `DualASRCorrector`（双 ASR 终稿校正） | `T-M1-11` |
| M1 接线 4 | `LocalTTSOrchestrator`（本地 TTS 编排） | `T-M1-12` |
| M1 接线 5 | 控制通道音频二进制帧承载（上行/下行） | `T-M1-10`（含）+ `T-CONTRACT-4`（握手侧） |
| M1 接线 6 | 运行时约束校验（CAP-14） | `T-M1-13` |
| 门禁 1 | `T25` 本地栈能力/观察项/本地服务暴露（SEC-08） | `T-GATE-6` |
| 门禁 2 | `T26` ASR 终稿校正（INP-09） | `T-GATE-7` |
| 门禁 3 | `T27` 服务级 vs 浏览器链路分级（混算为 0） | `T-GATE-8` |
| 契约微调 | `T-CONTRACT-3` 拆「D1 本地转写适配器（首版实现）」/「D2 远端预留（不实现）」 | `T-CONTRACT-3` + `T-CONTRACT-3D` |
| 契约微调 | `T-CONTRACT-1/2` 增「桥接基于 `committed` 编排发起、仍经唯一入口（TOL-16）」 | `T-CONTRACT-1`、`T-CONTRACT-2` |
| 纪律保持 | M0 不得以 mock 完成；M3 前不得宣称 MVP；性能分「已测/达标」且为**浏览器链路口径** | §0 纪律 6/7/8、`T-GATE-5`、`T-GATE-8`、`T-M3-4` |

### 1.2 依赖关系图（阶段 → 闭环，v1.1 更新）

```text
T-DOC-1 ─► T-M0-1 ─► T-M0-2 ─► T-M0-3 ─► T-M0-4        （M0 首批：本地栈服务级已通、浏览器链路探针仍阻断；串行）
                                        │
        ┌───────────────────────────────┴───────────────────────────────┐
        ▼（契约组，可按依赖并行）                                          ▼
 T-CONTRACT-3（D1 本地转写适配器）  T-CONTRACT-4（WS 握手/音频二进制帧）  T-CONTRACT-8（预算计量）
 T-CONTRACT-3D（D2 预留不实现）      │                          │
        │                            ├─► T-CONTRACT-5（输入状态机 + FinalPass/INP-09）
 T-CONTRACT-1（唯一执行链/TOL-16）    ├─► T-CONTRACT-6（连接状态机 + 本地会话重建）
        │                            └─► T-CONTRACT-7（关键帧有效性分离）
        ▼
 T-CONTRACT-2（工具幂等 + TOL-16：依赖 T-CONTRACT-1 + T-CONTRACT-3）
        │
        ▼
 M1 本地语音栈接线闭环（T-M1-1…13）──► M2 任务桥接闭环（T-M2-1…6）──► M3 视觉与联合验收（T-M3-1…5）
                                                                          │
                                                          M4 可写扩展（T-M4-1…2，首版之后）
 全程：T-GATE-*（测试与门禁，含 T25/T26/T27）、T-OPS-*（交付边界）、T-REV-*（评审确认）
```

- **M0 不循环依赖**（设计 §3.2.1）：探针**允许**隔离小脚本 + 现有调用入口 + **本机本地服务**完成真实听说/本地打断/同会话只读工具；**不要求**先完成 `MediaSessionRegistry`/`TurnAggregator`/`TaskBridge`（否则等于提前实施 M1/M2）。
- **契约组可并行**：`T-CONTRACT-3/3D/4/8` 不依赖 M1/M2 组件，可在 M0 结算后按需先启；`T-CONTRACT-5/6/7` 以 `T-CONTRACT-4` 为前置。
- **M1 内部顺序**：`T-M1-9`（采集/重采样/VAD）与 `T-M1-10`（本地转写会话）并行前提，`T-M1-11`（终稿校正）依赖 `T-M1-10`，`T-M1-12`（TTS 编排）依赖 `T-M1-10`，`T-M1-13`（preflight）应早于 `T-M1-10` 接线完成。

### 1.3 任务条目统计（本文 v1.1）

| 组 | 主任务数 | 说明 |
|---|---|---|
| T-DOC（规划文档） | 1 | 本任务本身 |
| T-M0（首批探针与冻结） | 4 | 首个执行单元（v1.1 定点修订） |
| T-CONTRACT（8 项实现契约） | 9 | v1.2 契约逐项落地 + **D2 远端预留拆分**（+1） |
| T-M1（本地语音栈接线） | 13 | 原有 8 + **新增 5 接线主任务**（+5） |
| T-M2（任务桥接闭环） | 6 | 真实只读工具闭环 |
| T-M3（视觉与联合验收） | 5 | 页面共享与完整验收 |
| T-M4（可写扩展） | 2 | 首版之后 |
| T-GATE（验证与门禁） | 8 | 原 5 + **T25/T26/T27 门禁**（+3） |
| T-OPS（交付边界与提交纪律） | 3 | 防回滚/精确提交 |
| T-REV（评审与确认） | 3 | 收尾 |
| **合计** | **54** | 相对 v1.0（45）**新增 9 主任务**；子项动作行共 **194** 项（`- [ ]` 复选框；v1.0 为 144） |

---

## 2. M0 首批：能力、接口与基线冻结（首个执行单元；v1.1 定点修订）

> **M0 目标**：先用**一条真实语音链路**验证设计假设，再进入实现。若探针推翻假设，**先修订裁决与验收，不强行套用接口**。M0 是**探针与核实**，产物为文档/记录，**不是运行态数据**。
> **v1.1 重述**：本地栈**服务级已跑通**（`WS ASR → Ollama → HTTP TTS`，12.23 s 口径，`RTM-OBS-09`），**浏览器链路（采集/16k 重采样/播放/VAD/打断）尚未接入**（`RTM-EVD-06`）。故探针 A/B **部分解除**、**仍不得宣布通过**；能力档案由「各项未知」转为**按本地栈冻结**。

### 2.1 任务规划文档产出与归档（T-DOC-1 ｜ RTM: EVD-01、EVD-05、EVD-06、SPEC §0.7）

- **依赖前置**：无（本任务）
- **落点**：`docs/TASKS-20261023-realtime-multimodal-implementation.md`、`.codeartsdoer/specs/realtime_multimodal/tasks.md`
- **验收标准**：两处文档**内容同步**（归档仅可多归档说明段）；v1.0 13 条建议与设计 v1.3「对 tasks 输入建议」**全覆盖**；每条任务含 ID / RTM 映射 / 依赖 / 落点 / 验收 / 可验证方式
- **可验证方式**：`diff` 两文件正文一致；对照 §1.1、§1.1.1 落位表逐条核对
- [x] 在 `docs/` 生成权威任务清单 v1.1，并归档到 `.codeartsdoer/specs/realtime_multimodal/tasks.md`（内容同步）
- [x] 校对 v1.0 13 条建议（`T-DOC-1`、`T-M0-1…4`、`T-CONTRACT-1…8`）与设计 v1.3 输入建议（本地栈冻结、M1 接线、T25/T26/T27、契约微调）全部落位且无遗漏
- [x] 声明交付边界：任务清单只提交上述两份文档，运行/用户态文件不纳入

### 2.2 冻结候选、读防退化契约、只读核实存量接口事实（T-M0-1 ｜ RTM: CAP-05、CAP-11、EVD-04、CMP-01、REC-02、SEC-08）

- **依赖前置**：`T-DOC-1`
- **落点**：仓库根（`git rev-parse HEAD` + 关键文件 SHA-256）；`docs/DEVELOPMENT_REPAIR_SAFETY.md`；只读核实 `src/llm_loop/web/auth.py`、`src/llm_loop/core/loop/runner.py`、`src/llm_loop/web/routes.py`、`src/llm_loop/core/tool_execution_journal.py`、`src/llm_loop/memory/attachments.py`、`src/llm_loop/workspace/artifacts.py`、`src/llm_loop/tools/registry.py`
- **验收标准**：候选指纹可复现；已读防退化契约；上述存量接口事实**只读核实、零行为修改**并留证；记录「本机服务仅回环/受信、浏览器不直连」的**暴露前提**（`RTM-SEC-08` 前提）
- **可验证方式**：保存 `git rev-parse HEAD` 与 SHA-256 清单；`git status` 证明未改行为；核实结论写入 M0 产物
- [x] 在**隔离 worktree/候选**上冻结指纹：`git rev-parse HEAD` + 关键文件 SHA-256（不把工作树修改当生产事实）
- [x] 读 `docs/DEVELOPMENT_REPAIR_SAFETY.md`，确认可回滚与证据保留边界
- [x] 只读核实：`web/auth.py`（鉴权/Origin 仅覆盖 HTTP）、`core/loop/runner.py`（`cancel` 精确代次、`enqueue_interjection`）、`web/routes.py`（`chat_cancel`、`queue_interject`、`artifact_hydrate`）、`core/tool_execution_journal.py`（认领/恢复保证）、`memory/attachments.py` + `workspace/artifacts.py`（引用与回读）、`tools/registry.py`（`read_file` 读投影预算）
- [x] 记录当前仓库**无任何 WS 端点**（WS 属首次引入）的事实，作为 `T-CONTRACT-4` 的前提
- [x] 核实**本地服务暴露前提**：本机 `mlx-audio`/Ollama 端点仅回环/受信网络可达、浏览器不直连（`RTM-SEC-08`）

### 2.3 确认并冻结本地栈 + preflight 约束（T-M0-2 ｜ RTM: CAP-01、CAP-02、CAP-04、CAP-05、CAP-07、CAP-11、CAP-12、CAP-14、SES-06、SEC-01、SEC-08）

> **v1.1 修订（对齐设计 §3.2.1 步骤 4–5、§3.7.2）**：不再「在候选间实测选定远端 Provider」，改为**确认并冻结本地栈**（`mlx-audio` + Ollama + 本地 TTS），**只确定一条**生产传输实现（本地 WS 转写 + 本地 TTS 编排），**不引入 WebRTC**、**不为远端 Provider 写空适配器**。

- **依赖前置**：`T-M0-1`
- **落点**：能力档案条文（`docs/`，含 `LocalStackProfile`/`RuntimeConstraint`/`ObservationItem`/`ServiceLevelBaseline`）；后续 `src/llm_loop/realtime/local_voice_stack_adapter.py`、`src/llm_loop/realtime/capability_profile.py`（`T-CONTRACT-3`/`T-M1-13` 承接）
- **验收标准**：**只确定一条**生产传输实现（本地 WS 转写 + 本地 TTS 编排）；能力档案逐项记录「官方 / 实测 / 未知」三态；冻结本地栈**版本/接口/模型/许可**与**运行时约束**（CAP-14）；冻结计时口径、用量字段、连接代次与本地停播基线
- **可验证方式**：能力档案逐项可查；**未选远端 Provider 无空适配器**；缺凭据/缺约束须显式列阻断（见 `T-M0-4`）
- [ ] **确认并冻结本地栈**：`mlx-audio`（OpenAI 兼容 REST + WS，ASR/TTS）版本与接口、Ollama（`think:false`）版本、本地流式 TTS；记 **许可**（`apache-2.0`/`openmdw-1.1`/`other`，商用前逐项核实，`RTM-CAP-11`、`RTM-SEC-08`）
- [ ] 冻结**传输实现（唯一）**：本地 `WS /v1/realtime`（**仅转写**，`RTM-CAP-12`）+ 本地 TTS 编排；**不引入 WebRTC**、**不并行第二套传输**（`RTM-CAP-05`）
- [ ] 逐项编写能力档案（三态）：`LocalStackProfile`（版本/端点/模型/**许可**）、传输、输入输出格式、最终转写事件、轮次结束语义、取消与播放截断能力、工具关联、图像支持、恢复方式（`local_rebuild_only`）、连接限制、用量字段、地区/网络实测条件
- [ ] 记录**运行时/环境约束（`RuntimeConstraint`，`RTM-CAP-14`）**：`setuptools<81`、server 依赖（`uvicorn[standard]`/`fastapi`/`python-multipart`/`webrtcvad`）、`think:false`、输入 **16k PCM 单声道**、流式 `flush()` 收尾，各含「期望 / 实检 / 违反后果」
- [ ] 冻结**计时口径**（客户端同一单调时钟）、**用量字段**、**连接代次**与**本地停播**基线（`SPEC §25.2`：M0/M1 建立）
- [ ] 确认**长期 Key / 恢复令牌 / 工具凭据 / `HF_TOKEN` 只在服务端**且本机服务只绑回环/受信网络（`RTM-SEC-01`、`RTM-SEC-08`），浏览器仅经 LFL 受信服务端通信

### 2.4 执行最小探针 A/B/C（真实环境，非 mock；A/B 部分解除）（T-M0-3 ｜ RTM: AUD-01、AUD-03、PLY-02、PLY-07、PRF-02、PRF-03、PRF-04、INP-04、INP-09、TOL-04、TOL-09、TOL-16、CAP-12、EVD-06、OBS-09）

> **v1.1 重述（对齐设计 §3.2.1）**：探针 A/B **部分解除**——**服务级已通、浏览器侧仍阻断**，故 **A/B 仍不得宣布通过**；结论须**分别标注「服务级已实测 / 浏览器链路未验收」**。探针 C **通过**，并**补注**需在 M1 验证桥接编排落点（`RTM-TOL-16`）。

- **依赖前置**：`T-M0-2`
- **落点**：隔离小脚本 + 现有调用入口（浏览器 `getUserMedia`/`WebAudio`、本机本地服务、现有 `read_file` 工具入口 `src/llm_loop/tools/builtin/read_file.py`）；探针脚本作**一次性隔离候选**，**不并入生产路径**
- **验收标准**：A/B 在**服务级**已有原始记录、**浏览器侧显式标阻断**且**不宣布通过**；C 探针**运行时写校验值**且读取值与写入值一致（**防预置答案冒充**）
- **可验证方式**：保存实际命令、退出码、原始观测；`git status` 证明探针脚本未并入生产路径；A/B 分别标注「服务级已实测 / 浏览器链路未验收」
- **执行步骤**：
  1. **探针 A（连续听说）**：**[服务级部分解除]** 已用本地栈脚本观测流式增量与句末终稿；**[浏览器侧仍阻断]** 仍须在浏览器用真实麦克风连续说话，观测 **16k 重采样 → 本地 WS 转写 → 轮次归一化 → 高精度终稿**（含义停顿/长句/中文夹英文/数字/专有名词/回声）。**未接通浏览器前，A 不得宣布通过**（`RTM-AUD-01/03`、`RTM-INP-09`、`RTM-EVD-06`）
  2. **探针 B（本地打断）**：**[服务级部分解除]** 本地链路可本地停止播报；**[浏览器侧仍阻断]** 仍须在浏览器观测「**用户开口（客户端 VAD 起点）→ 扬声器实际停止**」，记录延迟基线（`RTM-PLY-02`、`RTM-PRF-02`）。**未接通浏览器前，B 不得宣布通过**
  3. **探针 C（同会话只读工具）**：**[通过]** 隔离 workspace 内**运行时写入新校验值** → 由真实 `read_file` 经桥接读取回执，核对读取值 == 写入值（`RTM-TOL-09`）；确认**提交前不派发、认领后才派发**（`RTM-INP-04`、`RTM-TOL-04`）；**补注**转写会话下工具**编排落点**（桥接基于 `committed` 发起、仍经唯一入口）为 M1 落地前提（`RTM-TOL-16`）
- [ ] 探针 A：**[服务级部分解除]** 记录本地栈流式增量与句末终稿观测；**[浏览器侧仍阻断]** 列明 16k 重采样/本地 WS 转写/轮次归一化/高精度终稿**未接通**，**不得宣布通过**
- [ ] 探针 B：**[服务级部分解除]** 记录本地链路可本地停播；**[浏览器侧仍阻断]** 列明「客户端 VAD 起点 → 扬声器实际停止」延迟基线**未建立**，**不得宣布通过**
- [ ] 探针 C：隔离 workspace 运行时写校验值 → `read_file` 回执核对一致；确认提交前不派发
- [ ] 探针 C 补注：登记转写会话下工具**编排落点**（桥接基于 `committed`、仍经唯一入口，`RTM-TOL-16`）为 M1 落地前提
- [ ] **约束声明**：本探针**不得以 mock 冒充完成**（`RTM-EVD-03`）；三探针不得先建 `MediaSessionRegistry`/`TurnAggregator`/`TaskBridge`；**A/B 不得因服务级已通而宣布通过**（`RTM-EVD-06`）

### 2.5 记录基线、列阻断清单、门禁证据（含服务级基线登记与观察项登记）（T-M0-4 ｜ RTM: CMP-01、CAP-07、CAP-13、SES-03、EVD-01、EVD-03、EVD-04、EVD-06、OBS-09、PRF-01、PRF-08、SEC-08）

> **v1.1 新增（对齐设计 §3.2.2）**：增**服务级基线登记（`ServiceLevelBaseline`，OBS-09）**与**观察项登记（`ObservationItem`，CAP-13）**；阻断清单由「无实时音频 Provider 凭据」转为「**浏览器链路接线未完成**」「**本地服务暴露/许可待核实**」。

- **依赖前置**：`T-M0-3`
- **落点**：M0 产物更新建议（能力档案、接口映射表、真实网络基线、测试素材与用量范围、M0 探针记录、R01–R20 追溯表、阻断清单、**服务级基线条目**、**观察项条目**）——本轮仅给出**更新建议**，不改 `docs/M0-…` 文件
- **验收标准**：现状基线（文字流/听写/图片识别/取消）有记录；**服务级基线**已登记口径/环境/脚本且**明确不得作浏览器链路验收**；**观察项**含证伪证据/原因待查/退出条件且 `first_release=false`；缺凭据/接口能力/浏览器链路**显式列为阻断**；门禁证据含命令、退出码、候选指纹、失败项，**禁止提前写 PASS**
- **可验证方式**：M0 产物逐项可查；阻断清单非空或明确「无阻断」；`RTM-EVD-04` 独立审查记录；服务级/浏览器链路**分开标注**
- [ ] 记录现状基线：文字流、听写、图片识别、取消的现有行为与延迟（作为后续不回归对照，`RTM-CMP-01`）
- [ ] **服务级基线登记（`ServiceLevelBaseline`，`RTM-OBS-09`）**：登记 `WS ASR → Ollama → HTTP TTS` 场景、环境、脚本、测量（12.23 s 等）与**口径=服务级**，**明确不得作为 M1/M3 浏览器链路验收值、不得混算**
- [ ] **观察项登记（`ObservationItem`，`RTM-CAP-13`）**：登记原生全双工 VoiceChat-11B 的 `falsification_evidence`、`root_cause_candidates`、`exit_conditions`、`first_release=false`；**不得删除证据与复现脚本**
- [ ] 列明阻断：**浏览器链路接线未完成**、**本地服务暴露/许可待核实**为**显式阻断**；不得仅靠 mock 或服务级已通宣布 M0 完成（`RTM-CAP-07`、`RTM-EVD-03`、`RTM-SEC-08`）
- [ ] 保存门禁证据：实际命令、退出码、候选指纹与失败项；完成独立审查，**禁止提前写 PASS**（`RTM-EVD-04`）
- [ ] 确认 M0 退出条件：连续音频/最终转写/取消/工具关联/图像路线可行性有**官方与实测依据**；**浏览器链路未接通即标未验收**（`RTM-PRF-01`、`RTM-PRF-08`、`RTM-EVD-06`）

---

## 3. 实现契约组（v1.2 八项实现契约逐项落地；v1.1 定点微调）

### 3.1 唯一执行链与双层调用关联（T-CONTRACT-1 ｜ RTM: TOL-01、TOL-03、TOL-16、CMP-01）

> **v1.1 增**：本地栈下**桥接是工具调用的编排发起方**（因转写会话无工具回环），**基于 `committed` 编排发起、仍唯一经服务端入口**（`RTM-TOL-16`）。

- **依赖前置**：`T-M0-4`
- **落点**：`src/llm_loop/realtime/task_bridge.py`（新增）；复用 `core/loop/runner.py`（`BackgroundRunner`）、`web/human_turn_queue.py`（`HumanTurnQueue`）
- **验收标准**：桥接**只提交任务**，工具执行**只发生在引擎内**；本地栈下桥接**基于 `committed` 编排发起**工具调用、**仍唯一经服务端入口**（浏览器/桥接无并列执行权）；外层（`tool_call_id`/`turn_id`）与内层（`engine_execution_id`/`round`）**显式绑定**；同一 `read_file` **不被执行两次**
- **可验证方式**：重复派发计数为 0；T10「两通道重复 100 次」下引擎仅派发一次；断言桥接未直连工具管线
- [ ] 固化不变量：桥接只做「确认归属 → 关联代次 → 原子认领 → 提交任务」，**不直连工具管线**
- [ ] 固化**本地栈编排发起语义（`RTM-TOL-16`）**：工具调用由桥接**基于 `committed` 输入编排发起**、**仍唯一经服务端入口**；浏览器/桥接**无并列执行权**
- [ ] 在桥接层显式绑定外层 `tool_call_id`+`turn_id` ↔ 内层 `engine_execution_id`+`round`（防止两条来源被误当同一调用）
- [ ] 固化执行顺序：确认会话及输入归属 → 关联精确任务代次 → 原子认领（唯一键） → 既有授权与预算检查 → 由引擎派发一次 → 记录结果 → 读回真实回执 → 通知实时会话（`RTM-TOL-03`）
- [ ] 确认原 SSE 任务订阅继续使用，**不启动第二份任务消费者**（`RTM-CMP-02`）

### 3.2 工具幂等：桥接映射 + 稳定去重键 + 原子认领 + 重启恢复（T-CONTRACT-2 ｜ RTM: TOL-02、TOL-04、TOL-05、TOL-06、TOL-08、TOL-16、REC-02、REC-06、IDN-01）

> **v1.1 增**：桥接映射须承载**基于 `committed` 编排发起**的来源标识（`RTM-TOL-16`），幂等与认领语义不变。

- **依赖前置**：`T-CONTRACT-1`、`T-CONTRACT-3`
- **落点**：`src/llm_loop/realtime/`（认领记录/映射）；复用 `core/tool_execution_journal.py`（事实底座）
- **验收标准**：`call_key` 为**稳定去重键**（**禁用**参数哈希）；派发前**条件写入唯一认领记录**，写成功才派发；同键重复到达返回**已知状态、不重派**；重启先读认领记录，`claimed` → 返回已知状态**不重派**；崩溃窗口显式 `outcome_unknown`
- **可验证方式**：T10（重复 100 次只派一次）、T13（派发前后崩溃）、T18（执行后修正）回归；合法相同参数**新轮次**不被永久哈希黑名单误拦（`RTM-TOL-06`）
- [ ] 定义调用状态枚举映射：`requested/claimed/running/succeeded/failed/cancel_requested/cancelled/outcome_unknown`（`RTM-TOL-02`）
- [ ] 实现**稳定调用键**（Provider/桥接调用标识，**禁用参数哈希**）与桥接调用映射记录；映射须标注来源为**基于 `committed` 的桥接编排发起**（`RTM-TOL-16`）
- [ ] 实现**原子认领**：派发前以唯一稳定键**条件写入**认领记录（写成功才派发；已认领 → 返回已知状态、不重派）
- [ ] 实现**重启恢复**：先读认领记录，`claimed` → 已知状态且不重派（对齐 `ToolExecutionJournal.recover`「不自动重执行」），`not_claimed` 才进入正常派发
- [ ] 崩溃窗口表达 `outcome_unknown`；**先核远端事实、禁止盲重试**（`RTM-TOL-07/08`、`RTM-REC-02`）

### 3.3 D1 本地转写会话适配器 `LocalVoiceStackAdapter`（首版唯一实现）（T-CONTRACT-3 ｜ RTM: CAP-01、CAP-05、CAP-11、CAP-12、AUD-01、INP-09、REC-05）

> **v1.1 拆分（对齐设计 §2.2.2-D1、D24）**：原 `T-CONTRACT-3`「Provider 适配器补齐接口」拆为 **D1（本地转写适配器，首版实现）** 与 **D2（远端预留，不实现，见 `T-CONTRACT-3D`）**。

- **依赖前置**：`T-M0-4`
- **落点**：`src/llm_loop/realtime/local_voice_stack_adapter.py`（新增，**单实现**）、`src/llm_loop/realtime/provider_adapter.py`（接口定义，不实现远端）
- **验收标准**：D1 契约方法齐备——`open / configure / append / commit / recv / transcribe_final / flush_close / close`；经**回环**连接本机 `WS /v1/realtime`，**仅转写**（无 `response.create`、无音频、无工具回环）；`ready` 以握手 + 转写会话可用为准；无远端恢复令牌时按本地会话重建（`REC-05`）
- **可验证方式**：`append` 受理回执 ≠ 已转写；转写事件仅 `delta`/`completed`；`flush_close` 收尾确认；断言**未调用** `response.create`
- [ ] 实现 `open(profile)`：经**回环**连接本机；**无凭据返回前端**（`SEC-08`）；`ready` = 握手 + 转写会话就绪（`RTM-CAP-12`）
- [ ] 实现 `configure(session_update)`：`input_audio_format=pcm16`、16 kHz 单声道；参数**来自能力档案**，不散落硬编码（`RTM-AUD-01`）
- [ ] 实现 `append(pcm_frame)`：受理回执（**已受理 ≠ 已转写**），帧格式校验（`RTM-CAP-14`）
- [ ] 实现 `commit()` 与 `recv()`：规范化转写事件（`delta`/`completed`）；**仅转写**（无音频/工具事件，`RTM-CAP-12`）
- [ ] 实现 `transcribe_final(pcm_segment)`：调 `/v1/audio/transcriptions` 高精度终稿（`RTM-INP-09`，与 `T-M1-11` 衔接）
- [ ] 实现 `flush_close()`：**必须** flush 收尾（`RTM-CAP-14`）；`close()`：缺最终用量 → `incomplete`；无远端恢复令牌 → 本地会话重建（`RTM-REC-05`）

### 3.4 D2 远端 Provider 适配器预留（不实现）（T-CONTRACT-3D ｜ RTM: CAP-05、CAP-11、CAP-12）

> **v1.1 新增**：远端 Provider **仅预留接口、不实现、不写空适配器**（设计 D23/D24、`RTM-CAP-05/11`）。本条为**边界任务**，验收重点是「确认未实现、无空适配器、无并行传输」。

- **依赖前置**：`T-M0-4`
- **落点**：`src/llm_loop/realtime/provider_adapter.py`（仅接口/文档，不含远端实现）
- **验收标准**：无远端 Provider 空适配器、无并行第二套传输；接口预留不产生运行时分支、不引入 WebRTC；能力档案明确恢复方式 = `local_rebuild_only`
- **可验证方式**：代码检索无远端 Provider 实现/凭证分支；能力档案标注「远端仅预留」；`T25` 验收项之一
- [ ] 声明 D2 **仅接口预留**：远端 Provider **不实现**、**不写空适配器**、**不并行接云端主链路**（`RTM-CAP-05/11`）
- [ ] 断言无运行时分支依赖远端 Provider、无 WebRTC 引入；恢复方式固定为 `local_rebuild_only`（`RTM-CAP-12`）

### 3.5 WS 握手鉴权与拒绝路径（含音频二进制帧承载）（T-CONTRACT-4 ｜ RTM: SES-02、SES-03、SES-07、SEC-01、SEC-06、SEC-08、CAP-05、IDN-02）

> **v1.1 增**：控制通道 WS **同时承载上行 16k PCM 与下行 TTS 音频的二进制帧**（`RTM-CAP-05`）；握手仍须**在 `accept` 之前**显式鉴权；浏览器**不得自由绑定本机服务**（`RTM-SEC-08`）。

- **依赖前置**：`T-M0-4`（可与 `T-CONTRACT-1/3/3D/8` 并行）
- **落点**：`src/llm_loop/web/realtime_ws.py`（新增，含**音频二进制帧转发**）；复用 `src/llm_loop/web/auth.py`
- **验收标准**：**在 `accept` 之前**显式完成身份/Origin/归属校验；拒绝码 4401（未登录/身份失效）/ 4403（跨站 Origin）/ 4404（越权，防枚举）；拒绝后**不建立任何媒体/任务副作用**；控制通道承载文本事件帧 + **音频二进制帧**（上行 16k PCM / 下行 TTS）
- **可验证方式**：新增**未登录连接、跨站 Origin 连接、越权媒体会话连接**三类 WS 握手测试（含 `accept` 前拒绝与关闭码）；断言二进制帧通路仅走**唯一控制通道**
- [ ] 明确 WS **不能**复用 HTTP `Depends`/`Request`；现有 `_OriginGuardMiddleware`/`_CanonicalOriginMiddleware` **只覆盖 HTTP**（`web/__init__.py:98/153`）
- [ ] 握手处从 `websocket.cookies`/`websocket.headers` 取凭据，调用既有 `WebSessionStore.valid`/`_bearer_valid` 完成登录身份校验
- [ ] 握手处从 `websocket.headers` 取 `Origin` 做与 HTTP 同源的精确比较（同源或显式 allowlist），跨站拒绝
- [ ] 校验 `media_session_id` 属当前用户/当前 LFL 会话/workspace；越权按防枚举统一处理（不泄露存在性）；`connection_epoch` 旧代次不得更新当前会话
- [ ] 实现**音频二进制帧承载**：上行 16k PCM / 下行 TTS 音频走**同一控制通道 WS 的二进制帧**；**不引入 WebRTC**、**不并行第二套传输**（`RTM-CAP-05`）
- [ ] 拒绝浏览器提交的**任意本机服务地址/端口**（`RTM-SEC-08`）；实现事件 envelope（`version`/`type`/`event_id`/`seq`/`connection_epoch`/`session_id`/`media_session_id` + 按事件类型必填字段）与 401/403/409/429/503 错误语义

### 3.6 输入状态机：AwaitingFinal + FinalPass 终稿校正 + 轮次分类（T-CONTRACT-5 ｜ RTM: INP-01、INP-02、INP-03、INP-04、INP-05、INP-08、INP-09、AUD-05、AUD-06、STP-03）

> **v1.1 增（对齐设计 §2.1.3-H、D26）**：`AwaitingFinal` 后不再直接进 `Final`，而进入 **`FinalPass`**——句末/轮次结束用**高精度 ASR 重转写整段音频**，以其结果作为 `input.final`；不可用/超时进入 **`ConservativeFinal`**（保守边界 + 精度标注）；**流式错字不得进入 `committed` 或驱动工具**。

- **依赖前置**：`T-CONTRACT-4`、`T-CONTRACT-3`
- **落点**：`src/llm_loop/realtime/event_normalizer.py`、`src/llm_loop/realtime/turn_aggregator.py`、`src/llm_loop/realtime/dual_asr_corrector.py`（新增）
- **验收标准**：`Collecting → AwaitingFinal → FinalPass → Final → Committed` 状态机成立；`delta/final/committed` 三阶段互斥（`delta` 永不驱动任务，仅 `committed` 进队列）；**终稿来自高精度重转写**；`SuspendTool → NotExecuted` **不吞掉该轮有效输入**；提交后按四类意图分类
- **可验证方式**：T01（空音频/长句/delta·final 重复）、T18（先工具事件后转写/迟到/执行后修正）、T26（`delta` 只显示、句末高精度成 `final`、错字不进 `committed`）回归
- [ ] 实现「等待最终识别」阶段：`speech-end`/按住说话松开只结束采集，进入 `AwaitingFinal`（`RTM-AUD-06`）
- [ ] 实现 **`FinalPass`（终稿校正）**：句末/轮次结束触发高精度重转写整段音频，以其结果为 `input.final`；不可用/超时进入 `ConservativeFinal`（保守边界 + `precision_notice`）（`RTM-INP-09`）
- [ ] 实现 `final` 按 `turn_id` + 修订号**归并**，仅一次进队列；临时字幕仅显示（`RTM-INP-02/03`）
- [ ] **硬约束**：**禁止**流式错字进入 `committed` 或驱动工具（`RTM-INP-09`）
- [ ] 实现提前工具事件**暂存并关联轮次**，超时返回**明确未执行状态**且**不丢弃该轮有效输入**（`RTM-INP-04`）
- [ ] 实现提交后**轮次分类**（普通对话 / 任务提交 / 查询 / 纠正），仅任务提交/纠正/查询进入引擎相关路径
- [ ] 实现修正追加（`correction`）：未执行动作可更新，**已执行事实不改写**；迟到识别不反向改写（`RTM-INP-05/08`、`RTM-STP-03`）
- [ ] 长语音按**可回显语义轮次分段提交**，**禁止静默截断为尾部**；超容量暂停/拒绝可见且保留已确认部分（`RTM-AUD-05`）

### 3.7 连接状态机：全活动态可取消 + ready 定义 + 四事实分离（T-CONTRACT-6 ｜ RTM: SES-05、REC-03、REC-05、REC-09、LIF-01、LIF-02、LIF-04、IDN-03、IDN-07、PLY-03、CAP-14）

> **v1.1 增**：本地栈**通常无远端恢复令牌**，恢复由**本地会话重建 + 事实核对**承担，**不假设远端恢复**（`RTM-REC-05`）；**本地服务未起/端口不可达/格式协商失败**为**非可重试错误**，不进 `reconnecting`（`RTM-CAP-14`）；结束顺序含**流式会话 `flush()` 收尾**。

- **依赖前置**：`T-CONTRACT-4`
- **落点**：`src/llm_loop/realtime/media_session.py`（新增）、`src/llm_loop/web/realtime_routes.py`
- **验收标准**：`opening → ready → reconnecting → ready / failed → closing → closed` 状态机成立；**`ready` = 握手完成 + 传输通道就绪（可双向收发）**，`opening` 未就绪前**不得上传媒体**；**任一活动态均可主动结束**并进入 `closing → closed`；非可重试错误不循环
- **可验证方式**：T11（同会话两标签/接管/旧连接恢复）、T12（断网 3/10/30 秒）、T14（本地会话重建）回归；四事实（连接/麦克风/播放/任务）独立可观测
- [ ] 实现连接状态机与 `ready` 定义（不要求先收到首帧）；`opening` 阶段未就绪前禁止上传媒体（`RTM-SES-01`）
- [ ] 实现**全活动态可取消**：任一活动态结束 → `closing → closed`，执行「本地停采集/停播放 → 拒收该代次 → 远端/本地关闭 → 释放资源」（`RTM-LIF-04`、`RTM-IDN-07`）
- [ ] 实现**非可重试错误不循环**：鉴权失效/配额不足/协议不兼容/**本地服务未起/端口不可达/格式协商失败**不进 `reconnecting`（`RTM-REC-09`、`RTM-CAP-14`）；有界重连（3 次，0.5/1/2s 抖动）
- [ ] 实现结束顺序：本地停采集播放 → 拒收该代次后续音频 → **流式会话 `flush()` 收尾** → 请求远端/本地关闭 → 收集可获用量 → 有限收尾窗口 → 释放资源（`RTM-LIF-01/02`、`RTM-CAP-14`）
- [ ] 实现**恢复走本地重建**：无远端恢复令牌时从已提交输入、摘要与证据引用**本地重建**（`RTM-REC-05`）
- [ ] 实现**四事实分离**：`connection_state` / `mic_enabled` / `playback_state` / `task_state` 独立可观测（禁单一 `streaming` 布尔）；旧代次按 `connection_epoch` + `response_id` 隔离（`RTM-PLY-03`、`RTM-IDN-03`）

### 3.8 关键帧：current_validity / retention_state 分离（T-CONTRACT-7 ｜ RTM: VIS-02、VIS-03、VIS-05、VIS-06、VIS-09、RET-01、RET-02、RET-03、CAP-06、IDN-01）

- **依赖前置**：`T-CONTRACT-4`
- **落点**：`src/llm_loop/realtime/keyframe.py`（新增，帧元数据领域对象）；复用 `src/llm_loop/workspace/artifacts.py`（`WorkspaceArtifactStore` 承载原始帧字节）
- **验收标准**：`current_validity`（当前画面有效性）与 `retention_state`（证据保留状态）**分开建模**；`Stale` 只使前者失效、**仍可回答历史问题**；只有删除/到期（`Expired`）才失去回读能力并返回明确失效；派生证据标 `derived`
- **可验证方式**：T08（指代一帧后页面切换/选区变化/历史提问）、T09（限带宽/帧拥塞/连续变化）回归；**不把 `Stale` 实现成一并清理历史证据**
- [ ] 实现帧元数据领域对象：来源标识、`source_epoch`、捕获/接收时刻、宽高、选区、不可变内容引用、`derived` 标记
- [ ] 实现**两个正交维度**：`current_validity` 与 `retention_state` 分离（`Stale ≠ 删除`）
- [ ] 实现绑定后**不可变**（保存精确源，已绑定帧不被新帧替换）与失效更新（来源变化/共享停止/页面代次变化 → 当前有效性失效，证据仍保留）
- [ ] 实现帧龄：客户端**同一单调时钟**计算（`RTM-VIS-06`），服务端另记传输/处理耗时
- [ ] 复用 `WorkspaceArtifactStore` 承载原始帧字节（引用 `artifact://v1/<32hex>`），**不另建第二证据库**（`RTM-RET-05`）；图转文结果标 `derived`，不冒充原图（`RTM-CAP-06`、`RTM-RET-03`）

### 3.9 预算计量适配层与本地栈算力/许可口径（T-CONTRACT-8 ｜ RTM: BUD-01、BUD-02、BUD-03、BUD-04、BUD-05、BUD-07、CMP-01、LIF-05、LIF-07、STP-06）

> **v1.1 增**：本地栈**无远端模态计费**，媒体用量/预算转为**本地算力与模型许可口径**，仍须**分开记录**（`RTM-BUD-01/02`）；首版仍**不改 `BudgetDimension` 合同**。

- **依赖前置**：`T-M0-2`
- **落点**：`src/llm_loop/realtime/media_usage.py`（新增）；复用 `src/llm_loop/resources/task_budget_contracts.py`、`provider_settlement.py`
- **验收标准**：**首版不改 `BudgetDimension` 合同**（以独立媒体计量记录 + 适配层承载）；媒体用量分计（音频输入/输出、图像）并按**本地算力/许可口径**记录；缺账单标 `incomplete`**不标零**；达限停新请求、结算在途
- **可验证方式**：T23（指标/成本/取消残留/网络分层报告）回归；确认 `TaskBudgetLimits.from_dict` 严格校验字段集合**未被破坏**（旧额度/旧记录反序列化不失败）
- [ ] 以**独立媒体计量记录 + 适配层**承载媒体用量，映射到既有维度或旁路统计；**本地栈下按本地算力与许可口径**记录（`RTM-BUD-01/02`）
- [ ] 若必须扩展 `BudgetDimension` 才提供**版本兼容与迁移**（按版本号分支反序列化、旧记录缺省媒体维度按「未知/不适用」补齐、旧额度向前兼容、迁移/双读）
- [ ] 区分**估算/结算**；缺最终用量标 `incomplete`**不标零**；达限行为（停新请求、结算在途，`RTM-BUD-04/05`）
- [ ] 确保**实时路径与任务路径预算独立**，原模型任务预算/上下文策略**不因低延迟语音被调低**（`RTM-BUD-07`）
- [ ] 叠加**残留并发上限**与差异化拥塞（不支持取消时限定在途请求数并计量，`RTM-LIF-05/07`、`RTM-STP-06`）

---

## 4. M1：本地语音栈接线闭环（连续音频、转写、终稿校正与本地播放）

> **M1 重写（v1.1，对齐设计 §3.3）**：闭环 = 开始语音 → **浏览器 16k 重采样**采集 → 本地 `WS /v1/realtime` 增量（`delta` 字幕）→ **句末高精度重转写**（`final`）→ `committed` → 桥接编排 → Ollama（`think:false`）→ **本地 TTS** → 浏览器播放；**开口 → 客户端本地停播（不等服务端）** → 结束释放资源 → **流式会话 `flush()` 收尾**。含 `T-M1-9…13` 五项**接线主任务**。

### 4.1 前端媒体会话客户端与连接代次隔离（T-M1-1 ｜ RTM: SES-05、CAP-05、IDN-02、IDN-07、LIF-04、PLY-03）

- **依赖前置**：`T-CONTRACT-4`、`T-CONTRACT-6`
- **落点**：`webui/src/core/realtime/MediaSessionClient.ts`（新增）；依赖 `webui/src/core/api.ts`、`stores.ts`
- **验收标准**：媒体状态树与 `conv.streaming` **正交**（新语音控制不被 `streaming` 一概禁用）；旧代次输入不更新新连接；**单连接**承载控制事件 + 音频二进制帧（上行/下行），**不引入 WebRTC**
- **可验证方式**：T11 回归；资源清理后台无残留 track/播放节点/计时器/监听器/连接；断言无第二套传输
- [ ] 实现媒体会话客户端：建立/收控/代次隔离/事件归并
- [ ] 实现**单连接媒体承载**：控制文本事件 + 音频二进制帧（上行 16k PCM / 下行 TTS）经**同一控制通道 WS**（`RTM-CAP-05`）
- [ ] 实现四事实媒体状态树（连接/麦克风/播放/任务），与 `streaming` 正交
- [ ] 实现资源清理（`MediaStream` tracks/播放节点/计时器/监听器/连接）

### 4.2 播放队列与本地停播（含本地 TTS 下行）（T-M1-2 ｜ RTM: PLY-01、PLY-02、PLY-03、PLY-05、PLY-06、PLY-07、STP-01、STP-02、PRF-02、PRF-03）

> **v1.1 增**：播放音频来自**本地 TTS 经控制通道下行**（`RTM-PLY-07`），**不依赖 Provider 音频通道**；本地停播仍**不等服务端确认**。

- **依赖前置**：`T-M1-1`、`T-M1-12`
- **落点**：`webui/src/core/realtime/PlaybackQueue.ts`（新增）
- **验收标准**：按 `response_id` 排队/清除；**开口即停播（P95 ≤ 200ms，含语音起点检测）**与**按钮停播（P95 ≤ 100ms，独立于服务端取消确认）**；迟到音频不复活；TTS 首字节可观测
- **可验证方式**：T04（声音输出中开口/按停播/取消 ACK 延迟或缺失）、T07（旧声音迟到/取消迟到/未听完历史截断）回归
- [ ] 实现按 `response_id` 排队增量播放与清除（音频来源为本机本地 TTS 经控制通道下行，`RTM-PLY-07`）
- [ ] 实现**本地停播**（不等服务端确认）并发送该 `response_id` 中断请求
- [ ] 实现迟到音频隔离（按 `connection_epoch` + `response_id`，不复活、不误清新回复）
- [ ] 实现未听边界按客户端实际输出时间线上报；长答案播报策略（`RTM-PLY-04/05`）

### 4.3 客户端单调时钟计时（T-M1-3 ｜ RTM: OBS-05、OBS-09、VIS-06、PRF-02）

- **依赖前置**：`T-M1-1`
- **落点**：`webui/src/core/realtime/MonotonicClock.ts`（新增）
- **验收标准**：帧龄/停播延迟在**客户端同一单调时钟**测量；服务端另记传输/处理耗时（两个未校准 wall clock 不得相减）；**服务级/浏览器链路两套口径分开记录**
- **可验证方式**：延迟主指标以同一单调时钟产出并可复核；服务级基线不混算（`RTM-OBS-05/09`）
- [ ] 实现客户端同一单调时钟，用于帧龄与停播延迟
- [ ] 服务端另记传输/处理耗时（不与客户端 wall clock 相减）
- [ ] 计时口径分清**服务级/浏览器链路**，服务级数值不混入浏览器样本（`RTM-OBS-09`）

### 4.4 连续采集、16k 重采样与轮次检测（服务端骨架）（T-M1-4 ｜ RTM: AUD-01、AUD-02、AUD-03、AUD-04、AUD-05、AUD-06、AUD-07、CAP-14）

> **v1.1 增**：采集须以 **AudioWorklet 采集原生 PCM → 重采样为 16k 单声道 PCM16** 后上行，参数**来自能力档案**（`RTM-AUD-01`、`RTM-CAP-14`）。

- **依赖前置**：`T-CONTRACT-3`、`T-CONTRACT-5`
- **落点**：`src/llm_loop/realtime/media_session.py`、`local_voice_stack_adapter.py`
- **验收标准**：连续采集可用；**上行 16k PCM 单声道**；采样参数来自能力档案**而非硬编码**；回答中可继续输入；按住说话（按下开始采集/松开结束输入/失焦与触摸取消）
- **可验证方式**：T06（外放回声/噪声/停顿/夹英文/按住说话）、T21（真实设备）回归
- [ ] 接入采集与**16k 重采样/格式协商**（参数来自能力档案，不硬编码）；回声处理（`RTM-AUD-01/02`、`RTM-CAP-14`）
- [ ] 轮次归一化与回答中可插话（`RTM-AUD-03/04`）
- [ ] 按住说话行为（按下/松开/失焦/触摸取消）（`RTM-AUD-06`）；受限恢复（`RTM-AUD-07`）

### 4.5 媒体控件、字幕与四事实状态展示（T-M1-5 ｜ RTM: SES-05、INP-03、INP-09、IDN-03、CAP-10、A11Y-04）

- **依赖前置**：`T-M1-1`、`T-M1-2`
- **落点**：`webui/src/components/conversation/realtime/`（新增）
- **验收标准**：字幕区分 `delta` 临时 / `committed` 已提交；**高精度终稿到达后显示 `final`/`committed`**；媒体控制与状态展示与 `streaming` 解耦；字幕节流
- **可验证方式**：手测控件与字幕；`RTM-A11Y-04` 字幕节流可见；`delta` 不驱动任务可见
- [ ] 实现媒体控件（开始/结束语音、麦克风开关、静音播报、按住说话）
- [ ] 实现字幕（`delta` 临时 / `final` 终稿 / `committed` 已提交区分）与节流（`RTM-INP-09`）
- [ ] 实现四事实状态展示；`CAP-10` 媒体控制解耦

### 4.6 会话生命周期 REST（T-M1-6 ｜ RTM: SES-01、SES-04、SES-06、SES-07、LIF-02、LIF-03、RET-04、SEC-05、CAP-14）

- **依赖前置**：`T-CONTRACT-6`
- **落点**：`src/llm_loop/web/realtime_routes.py`（新增，沿用 `routes.py:92` 注册模式）；复用 `web/auth.py`
- **验收标准**：`POST/GET/DELETE /api/v1/realtime/sessions[...]` 可用；`DELETE` **幂等**且**不等同取消 LFL 任务**；缺最终用量标 `incomplete`；**流式会话须 `flush()` 收尾**（`RTM-CAP-14`）；越权不可读取（`RTM-SEC-06`）
- **可验证方式**：T02（拒绝麦克风/无设备/协议缺项）、T17（停共享/停麦克风/退出语音）回归；异常码 401/403/409/429/503
- [ ] 实现 `POST`（建会话，签发 `media_session_id` + `connection_epoch`，登记写入者租约，`connection_state=opening`）
- [ ] 实现 `GET`（四事实 + `task_links` + `cancel_stage` + `last_confirmed_seq`，不创建任务、不改代次）
- [ ] 实现 `DELETE`（幂等；`usage.status=settled|incomplete`；**流式会话 `flush()` 收尾**；不等同取消任务）
- [ ] 媒体入口接入现有鉴权与 Origin 边界；CSRF/Origin 复用既有校验（`RTM-SES-02`、`RTM-SEC-05`）

### 4.7 资源释放与结束顺序（T-M1-7 ｜ RTM: LIF-01、LIF-04、SES-04、RET-04、CAP-14）

- **依赖前置**：`T-M1-1`、`T-M1-6`
- **落点**：前端 `webui/src/core/realtime/`、服务端 `media_session.py`
- **验收标准**：结束语音释放 `MediaStream` tracks/播放节点/计时器/监听器/连接；共享停止释放相应资源；运行缓存有界（字节 + 时间双限）；**流式会话 `flush()` 收尾**
- **可验证方式**：T17、T22（30 分钟会话/反复进出语音）回归；无持续资源增长
- [ ] 实现结束语音的本地资源释放与远端/本地关闭顺序（含 `flush()` 收尾，`RTM-CAP-14`）
- [ ] 实现运行缓存字节 + 时间双限，溢出明确暂停/降级（`RTM-RET-04`）
- [ ] 共享权限不自动重授，显示用户操作入口（`RTM-REC-12`、`RTM-SES-04`）

### 4.8 音频会话闭环门禁（T-M1-8 ｜ RTM: SES-05、AUD-01、PLY-02、PLY-07、LIF-04、OBS-05、OBS-09、BUD-01、CAP-07、INP-09、EVD-06、CMP-01）

- **依赖前置**：`T-M1-1…13`
- **落点**：`tests/realtime/`（新增）；M1 验收记录
- **验收标准**：至少一次**真实麦克风 + 扬声器双向交互（浏览器链路）**；只可称「**音频会话基础完成**」（不得称 MVP）；**服务级数值不得混算**（`RTM-OBS-09`）
- **可验证方式**：T01–T04、T06、T07、T17、T21 本阶段相关项，**并新增 T25/T26/T27 相关项**；保存命令与真实设备证据
- [ ] 跑通「开始语音 → 16k 重采样采集 → 增量字幕 → 句末高精度终稿 → 本地 TTS 播报 → 开口本地停播 → 结束释放资源」
- [ ] 保存至少一次真实麦克风 + 扬声器双向交互（**浏览器链路**）证据；声明范围仅「音频会话基础完成」
- [ ] 登记 **T25/T26/T27** 本阶段相关项（本地栈能力/观察项、终稿校正、服务级 vs 浏览器链路分级）

### 4.9 浏览器 16k 重采样与客户端 VAD/打断（T-M1-9 ｜ RTM: AUD-01、AUD-03、CAP-14、PLY-02、PRF-02、PRF-03）

> **v1.1 新增（设计 §3.8、§2.1.3-J）**：采集与 VAD/打断**在客户端侧**；本地停播优先，**不等服务端确认**；**非固定阈值唯一断句**。

- **依赖前置**：`T-M1-1`
- **落点**：`webui/src/core/realtime/MicCapture.ts`（AudioWorklet + Resampler，新增）、`webui/src/core/realtime/ClientVAD.ts`（新增）
- **验收标准**：`getUserMedia` → AudioWorklet 采集原生 PCM → **重采样 16k 单声道 PCM16** 后上行；参数**来自能力档案**；客户端 VAD 判定语音起点/终点，**开口即触发本地停播**；**禁止固定阈值唯一断句**（服务端 VAD 仅辅助）
- **可验证方式**：T06（回声/噪声/停顿/夹英文）、T04（开口停播）、T21（真实设备）回归；断言上行帧格式为 16k PCM16
- [ ] 实现 AudioWorklet 采集原生 PCM → **重采样为 16k 单声道 PCM16**；采样率/声道/编码**来自能力档案**（`RTM-AUD-01`、`RTM-CAP-14`）
- [ ] 实现**客户端 VAD**：语音起点/终点在客户端判定；**非固定阈值唯一断句**（`RTM-AUD-03`）
- [ ] 实现**客户端打断**：VAD 起点触发**本地停播**（`RTM-PLY-02`、`RTM-PRF-02/03`）；服务端 VAD 仅作辅助信号
- [ ] 上行帧率/格式校验：非 16k PCM16 帧 → **显式错误并拒绝该帧**（不静默丢弃冒充完整，`RTM-CAP-14`）

### 4.10 本地转写会话接线与音频二进制帧承载（T-M1-10 ｜ RTM: CAP-05、CAP-11、CAP-12、AUD-01、AUD-03、REC-05）

> **v1.1 新增（设计 §3.3、§2.1.3-G）**：服务端经**回环**接本地 `WS /v1/realtime`（**仅转写**）；上行 16k PCM 与下行 TTS 音频走**同一控制通道 WS 二进制帧**。

- **依赖前置**：`T-CONTRACT-3`、`T-CONTRACT-4`、`T-M1-9`
- **落点**：`src/llm_loop/realtime/local_voice_stack_adapter.py`、`src/llm_loop/web/realtime_ws.py`
- **验收标准**：服务端经**回环/受信网络**连接本机转写会话；**仅转写**（无 `response.create`/音频/工具回环）；控制通道**同时承载上行 16k PCM 与下行 TTS 音频二进制帧**；浏览器**不直连**本机服务（`RTM-SEC-08`）
- **可验证方式**：链路端到端观测（服务级/浏览器链路分开记录）；断言无第二套传输、无 `response.create`
- [ ] 服务端经**回环**连接本机 `WS /v1/realtime`：`configure`（pcm16/16k）/ `append` / `commit` / `recv`（`RTM-CAP-11/12`）
- [ ] 实现**控制通道音频二进制帧承载**：上行 16k PCM / 下行 TTS 经**同一 WS 二进制帧**；**不引入 WebRTC**、**不并行第二套传输**（`RTM-CAP-05`）
- [ ] 断言**仅转写**：不调 `response.create`、不期待 Provider 音频/工具事件（`RTM-CAP-12`）
- [ ] 浏览器**不直连**本机服务；服务端经回环访问（`RTM-SEC-08`）；无远端恢复令牌时本地会话重建（`RTM-REC-05`）

### 4.11 双 ASR 终稿校正 `DualASRCorrector`（T-M1-11 ｜ RTM: INP-01、INP-02、INP-03、INP-09、AUD-03）

> **v1.1 新增（设计 §2.1.3-H、§2.2.2-D1）**：流式增量→`delta`；句末整段音频→高精度重写→`final`；**流式错字不得进入 `committed` 或驱动工具**。

- **依赖前置**：`T-M1-10`、`T-CONTRACT-5`
- **落点**：`src/llm_loop/realtime/dual_asr_corrector.py`（新增）
- **验收标准**：`delta` 仅显示；`final` 来自**句末高精度重转写**（`/v1/audio/transcriptions`）；不可用/超时 → **保守边界 + 精度标注**；**禁止**流式错字冒充终稿
- **可验证方式**：T26（`delta` 只显示、句末高精度成 `final`、错字不进 `committed`/工具）通过；对照错字样例（如「语音链路→语音路」「克隆→克龙」）
- [ ] 实现「流式增量 → `delta`」：仅字幕显示，**不驱动工具、不进 `committed`**（`RTM-INP-09`）
- [ ] 实现「句末整段 16k PCM（有界运行缓存）→ 高精度重转写 → `final`」；以其结果作为提交来源（`RTM-INP-09`）
- [ ] 实现不可用/超时 → **保守已确认边界提交 + `precision_notice` 精度标注**（`RTM-INP-09`）
- [ ] 断言 **T26** 通过：流式错字不进入 `committed` 或工具派发

### 4.12 本地 TTS 编排 `LocalTTSOrchestrator` 与音频下行（T-M1-12 ｜ RTM: PLY-01、PLY-02、PLY-04、PLY-07、PRF-03、OBS-09）

> **v1.1 新增（设计 §2.1.3-I、§2.2.2-E）**：桥接产出播报文本 → `LocalTTSOrchestrator` 调本地 TTS（`/v1/audio/speech` 或 `stream=True`）→ 经控制通道**下行**交客户端 `PlaybackQueue`；**首字节作可观测项**，服务级/浏览器链路**分开登记**。

- **依赖前置**：`T-M1-10`、`T-CONTRACT-3`
- **落点**：`src/llm_loop/realtime/local_tts_orchestrator.py`（新增）
- **验收标准**：播报文本由桥接产出，本地 TTS 生成音频经**控制通道下行**；按 `response_id` 排队/清除；**TTS 首字节延迟作可观测项**；**不依赖** Provider 音频通道（`RTM-PLY-07`）；被本地停播打断时**及时终止后续音频生成**
- **可验证方式**：T07/T04 回归；首字节延迟在服务级与浏览器链路**分开登记**（`RTM-OBS-09`）
- [ ] 实现桥接 → `LocalTTSOrchestrator` 编排：调用本机 `/v1/audio/speech`（可选 `stream=True`）（`RTM-PLY-07`）
- [ ] 实现音频经**控制通道下行**交客户端；按 `response_id` 排队/清除（`RTM-PLY-01/03`）
- [ ] 实现被**本地停播**打断时**及时终止后续音频生成**（`RTM-PLY-02`、`RTM-PRF-03`）
- [ ] 登记 **TTS 首字节**可观测项（服务级/浏览器链路**分开**，不混算，`RTM-OBS-09`）

### 4.13 本地栈运行时约束 preflight 校验（T-M1-13 ｜ RTM: CAP-03、CAP-04、CAP-14、SEC-08）

> **v1.1 新增（设计 §2.1.3-J、§1.2.8.3）**：建立实时会话**前**探测运行时约束；任一不满足 → **显式错误 + 缺项标识 + 恢复入口**，**不进入 `ready`**；**不得静默空结果**。

- **依赖前置**：`T-M0-2`
- **落点**：`src/llm_loop/realtime/preflight.py`（新增）
- **验收标准**：preflight 探测 `setuptools<81`、server 依赖（`uvicorn[standard]`/`fastapi`/`python-multipart`/`webrtcvad`）、本地服务可达性（回环端口）、Ollama `think:false`、音频格式（16k PCM）；任一不满足 → **显式错误 + 缺项 + 恢复入口**；上行非 16k PCM16 帧 → **显式错误、拒绝该帧**
- **可验证方式**：T25 相关项；构造缺约束场景断言**显式报错而非静默空结果**
- [ ] 实现 preflight：探测 `setuptools<81`、server 依赖、本地服务回环可达性、`think:false`、16k PCM（`RTM-CAP-14`）
- [ ] 任一不满足 → **显式错误 + 缺项标识 + 恢复入口**，**不进入 `ready`**；不静默降级（`RTM-CAP-03/04`）
- [ ] 上行格式校验：非 16k PCM16 → 显式错误并**拒绝该帧**（不静默丢弃冒充完整）
- [ ] 运行时校验 `think:false`：观测到空 `content` 且未配置 → **报错，不静默空回复**

---

## 5. M2：LFL 任务桥接与恢复（任务闭环）

### 5.1 输入提交桥接（`commit_input`）恰一次进队列（T-M2-1 ｜ RTM: INP-01、INP-02、INP-06、INP-07、INP-09、AUD-07、SCN-02）

- **依赖前置**：`T-CONTRACT-1`、`T-CONTRACT-2`、`T-CONTRACT-5`
- **落点**：`src/llm_loop/realtime/task_bridge.py`；复用 `web/human_turn_queue.py`、`core/loop/runner.py`
- **验收标准**：只提交 `committed` 输入（**其 `final` 来自高精度终稿**，`RTM-INP-09`）；已提交输入**恰一次**进队列；降级标识如实
- **可验证方式**：T01、T18 回归；无空任务、无临时字幕执行
- [ ] 将 `committed` 轮次映射为 `queue_enqueue`/`queue_interject`（存在活动 Run 时插话，否则提交任务）
- [ ] 实现两阶段反馈「已接收 / 已生效」分级回执挂点（复用 `_on_received/_on_applied/_on_denied/_on_cbf`）（`RTM-INP-06`）
- [ ] 降级标识与 `DictationButton` 单次听写降级保持可用（`RTM-INP-07`、`RTM-AUD-07`）

### 5.2 查询/纠正/取消三能力与分级回执（T-M2-2 ｜ RTM: INP-06、STP-03、STP-04、STP-05、STP-06、STP-07、TOL-11、TOL-13、SES-07）

- **依赖前置**：`T-M2-1`
- **落点**：`src/llm_loop/realtime/task_bridge.py`；复用 `web/routes.py:1976`（`chat_cancel`）、`routes.py:2137`（`queue_interject`）
- **验收标准**：精确 `run_generation` 校验，代次不符返回 **409**；纠正走「已接收/已采用」；三类停止分离结算，区分「请求 vs 真实完成」；已完成部分**如实报告、不谎称撤销**
- **可验证方式**：T05（停一下/先别说/取消任务/已完成操作）、T19（运行中插话/Run 变化/媒体断开但任务继续）回归
- [ ] 实现 `query_task(session, run_generation?)`（先拉真实状态，不自动重发）
- [ ] 实现 `submit_correction(turn, run_generation)`（精确代次插话，下一安全边界采用）
- [ ] 实现 `request_cancel(run_generation)`（精确取消 + 409 冲突语义 + 如实终态）
- [ ] 实现三类停止分离结算与反馈（本地停播 / 回复取消 / 任务取消）（`RTM-STP-01/02/06`）；歧义不扩大（`RTM-STP-05`）

### 5.3 真实只读工具闭环（`read_file` 隔离 workspace）（T-M2-3 ｜ RTM: TOL-09、TOL-11、TOL-12、TOL-16、EVD-02）

> **v1.1 增**：本地栈下工具调用由**桥接基于 `committed` 编排发起**（`RTM-TOL-16`），仍经**唯一服务端入口**。

- **依赖前置**：`T-M2-1`、`T-CONTRACT-2`、`T-CONTRACT-3`
- **落点**：`src/llm_loop/realtime/task_bridge.py`；复用 `src/llm_loop/tools/builtin/read_file.py`、`tools/registry.py`
- **验收标准**：在隔离 workspace 内**运行时写入新校验值** → 经真实 `read_file` 读取回执核对一致；**禁用假工具回包**；只有收到**真实 LFL 回执**才播报；**桥接基于 `committed` 编排发起**、仍经唯一入口
- **可验证方式**：T19、T24 相关项；读取值 ≠ 写入值即失败（防预置答案冒充）；断言无并列执行权
- [ ] 复用 `read_file` 读取隔离 workspace 内真实诊断文件；运行时写校验值核验（`RTM-TOL-09`）
- [ ] 桥接面收敛为 4 能力（提交任务/查询状态/提交纠正/请求取消），**不把全仓 schema 灌入实时模型**（`RTM-TOL-10`）
- [ ] 工具调用由**桥接基于 `committed` 编排发起**、**仍经唯一服务端入口**（`RTM-TOL-16`）；仅真实回执才播报；旧结果仍写原任务记录（`RTM-TOL-11/12`）

### 5.4 已提交输入/任务链接/工具事实持久化与恢复（T-M2-4 ｜ RTM: REC-01、REC-02、REC-05、REC-06、REC-07、REC-08、REC-10、REC-11、REC-12、REC-13、REC-14、TOL-12）

- **依赖前置**：`T-M2-1`、`T-CONTRACT-2`
- **落点**：`src/llm_loop/realtime/`；复用 `core/tool_execution_journal.py`
- **验收标准**：持久边界仅含已提交需求/任务链接/工具事实/必要恢复状态；**持久失败按位置区分**；恢复**不等于恰好一次**；**本地栈下恢复走本地会话重建**（不强依赖远端恢复令牌）
- **可验证方式**：T13（派发前后崩溃）、T14（本地会话重建/上下文重建）、T15（Journal/附件写入失败/磁盘满）回归
- [ ] 实现持久边界：临时字幕/全部音频分片/未使用预览**不进任务 Journal**（`RTM-REC-01`）
- [ ] 实现持久失败按位置区分处理（`RTM-REC-02`）
- [ ] 实现恢复路径：**本地会话重建** / 恢复失败从已提交输入、摘要与证据引用重建（`RTM-REC-05/06/07/08`）
- [ ] 实现「先拉真实状态」与「离线草稿明确提交」（不自动按当前页面执行过时语音）（`RTM-REC-10/11`）
- [ ] 实现按需补上下文（不灌每块音频）（`RTM-REC-13`）；可恢复交付（`RTM-REC-14`）

### 5.5 有界重连与断线续接（T-M2-5 ｜ RTM: REC-03、REC-04、REC-05、REC-09、REC-11、SCN-04、CMP-02、IDN-07、IDN-08、CAP-14）

- **依赖前置**：`T-CONTRACT-6`、`T-M2-4`
- **落点**：`src/llm_loop/realtime/media_session.py`、前端 `MediaSessionClient.ts`
- **验收标准**：断网 3/10/30 秒行为明确；有界重连（3×0.5/1/2s 抖动）后手动/文字入口；**本地服务未起不得进入 `reconnecting`**（`RTM-CAP-14`）；**不谎称连续理解/完整恢复**；媒体断开**不得**当作任务取消
- **可验证方式**：T12（断网 3/10/30 秒，断在未提交与提交之后）、T19 回归；`RTM-CMP-02` 保持单一路径
- [ ] 实现短暂断连处理（本地停旧播放、显示断线、更换 `connection_epoch`、从已确认 `seq` 核对）（`RTM-REC-03`）
- [ ] 实现有界重连与「不谎称完整恢复」（明确音频间隙）（`RTM-REC-09`、`RTM-REC-04/05/08`）；本地服务未起不循环重连
- [ ] 媒体断连不停外部任务；三类标识分离（`RTM-IDN-07/08`）

### 5.6 任务闭环门禁（T-M2-6 ｜ RTM: TOL-01、TOL-04、TOL-05、TOL-16、REC-02、EVD-02、SCN-03）

- **依赖前置**：`T-M2-1…5`
- **落点**：`tests/realtime/`；M2 验收记录
- **验收标准**：跑通「提出需求 → 真实只读工具执行 → 口头反馈 → 插话纠正 → 断线续接」；**禁用假工具回包**；认领去重、恢复、不明结果可核；**桥接编排发起仍经唯一入口**
- **可验证方式**：T05、T10–T19、T24 本阶段相关项
- [ ] 端到端跑通任务闭环（真实只读工具，无 mock 回包）
- [ ] 核验认领去重（重复 100 次只派一次）、恢复、`outcome_unknown` 可核
- [ ] 核验**转写会话下工具编排落点**：桥接基于 `committed` 发起、仍经唯一入口（`RTM-TOL-16`）

---

## 6. M3：页面视觉与完整 MVP 验收（视觉与联合闭环）

### 6.1 页面共享来源与关键帧采集（T-M3-1 ｜ RTM: VIS-01、VIS-02、VIS-04、VIS-05、VIS-07、VIS-08、SES-04、RET-01）

- **依赖前置**：`T-CONTRACT-7`、`T-M2-6`
- **落点**：前端 `webui/src/core/realtime/` + `webui/src/components/conversation/realtime/`；服务端 `keyframe.py`
- **验收标准**：仅采集**用户选定来源**（不采集未共享来源/任意外部标签页 DOM）；帧元数据齐备；按需采样；拥塞只替换未绑定预览帧
- **可验证方式**：T08（指代一帧后切换/选区变化/历史提问）、T09（限带宽/帧拥塞/连续变化）回归
- [ ] 实现用户手势共享与来源选择（`getDisplayMedia`）；仅采集所选来源（`RTM-VIS-01`）
- [ ] 实现帧元数据（来源标识/`source_epoch`/捕获·接收时刻/宽高/选区/不可变引用）（`RTM-VIS-02`）
- [ ] 实现按需采样（建议初始 0.5–1fps）与拥塞替换（不丢已提交指令/已绑定帧/工具事实）（`RTM-VIS-05/08`）
- [ ] 实现原图授权回读与派生证据 `derived` 标记（`RTM-VIS-07`、`RTM-RET-01`）

### 6.2 指代绑定与历史/当前区分（T-M3-2 ｜ RTM: VIS-03、VIS-04、VIS-09、SCN-01、RET-02、RET-03）

- **依赖前置**：`T-M3-1`
- **落点**：`keyframe.py`、`turn_aggregator.py`（提交点绑定候选帧）
- **验收标准**：含视觉输入的提交点绑定候选帧；候选不唯一/无可用画面 → **提一个澄清问题**；历史 vs 当前区分（历史可用旧帧，当前操作前先刷新核验）
- **可验证方式**：T08、T24（分页与删除）回归；`Stale` 仍答历史问题
- [ ] 实现提交点绑定候选帧与澄清分支（`RTM-VIS-04`）
- [ ] 实现失效更新（来源变化/共享停止/页面代次变化 → 当前有效性失效，证据仍保留）（`RTM-VIS-03`）
- [ ] 实现历史 vs 当前区分（`RTM-VIS-09`）；删除/到期返回明确失效、不用摘要替代原图（`RTM-RET-02/03`）

### 6.3 移动端与可访问性降级（T-M3-3 ｜ RTM: A11Y-01、A11Y-02、A11Y-03、A11Y-04、A11Y-05、A11Y-06、CAP-03、CAP-08、CAP-09、CAP-10）

- **依赖前置**：`T-M1-5`、`T-M3-1`
- **落点**：前端组件与状态
- **验收标准**：桌面与移动端可操作；支持文字/截图降级；键盘与焦点；可访问状态；移动端**实测声明**（未实测不承诺后台连续音频）；**界面标明实际采用的链路与「观察项」**
- **可验证方式**：T20（首次使用/键盘/焦点/字幕/共享不可用）、T21（桌面目标浏览器与手机真实设备）回归
- [ ] 实现文字/截图降级入口与跨端可操作（`RTM-A11Y-01/02`）
- [ ] 实现键盘与焦点、字幕节流、首次价值可见（`RTM-A11Y-03/04/06`）
- [ ] 声明移动端实测能力；链路按**实测能力**判定并界面标明（含「观察项」，`RTM-A11Y-05`、`RTM-CAP-09/13`）

### 6.4 完整性能验收（区分「已测」与「达标」，浏览器链路口径）（T-M3-4 ｜ RTM: PRF-01、PRF-02、PRF-03、PRF-04、PRF-05、PRF-06、PRF-07、PRF-08、OBS-05、OBS-06、OBS-07、OBS-08、OBS-09、EVD-06）

> **v1.1 强化**：性能「已测」**口径必须是浏览器链路端到端**（经麦克风/扬声器）；**服务级数值不得混算**。

- **依赖前置**：`T-M1-8`、`T-M2-6`、`T-M3-1`
- **落点**：性能测试记录；`tests/realtime/`；观测埋点
- **验收标准**：**分开记录「已测」与「达标」**且**「已测」为浏览器链路口径**；未达标可交付测试报告但**不得宣布 M3 完成**；重复派发/跨会话串扰/旧音频复活均 **0 次**；样本量与分层报告、**不删慢样本**；**服务级基线不混算**
- **可验证方式**：T23（指标/成本/取消残留/网络分层报告）、T27 回归；延迟主指标以客户端同一单调时钟测量
- [ ] 度量并记录：首声延迟（P50≤1s/P95≤2s）、本地插话停播（P95≤200ms）、按钮停播（P95≤100ms）、帧新鲜度（≤2s）——**浏览器链路口径**
- [ ] 建立事件/取消/帧龄/工具/用量关联观测（`RTM-OBS-01`）；默认无媒体正文（`RTM-OBS-02`）
- [ ] 分层报告样本量与不删慢样本（`RTM-OBS-06/07`）；工具反馈逐项核对（`RTM-OBS-08`）
- [ ] 分开记录「已测」与「达标」；**服务级基线不混算**（`RTM-OBS-09`、`RTM-EVD-06`）；未达标仅交付报告，**不宣布 M3 完成**

### 6.5 3×30 分钟长会话与兼容回归（T-M3-5 ｜ RTM: PRF-07、CMP-01、CMP-02、LIF-04、LIF-07、LIF-08、SCN-05）

- **依赖前置**：`T-M3-1…4`
- **落点**：长会话测试记录；回归护栏
- **验收标准**：至少 3 场各 30 分钟无持续资源泄漏；原文字流/附件/插话/取消/任务恢复行为保持兼容
- **可验证方式**：T22（30 分钟会话/反复进出语音/切换会话）、T20/T21 回归
- [ ] 执行 3×30 分钟长会话，核验无持续资源泄漏（`RTM-PRF-07`）
- [ ] 核验兼容回归：原文字流、附件、插话、取消、任务恢复、`DictationButton`（`RTM-CMP-01`）
- [ ] 覆盖移动端使用场景（`RTM-SCN-05`）

---

## 7. M4：可写工具扩展（首版之后，标注不进首版验收）

### 7.1 说话期间暂缓副作用派发（T-M4-1 ｜ RTM: TOL-14）

- **依赖前置**：`T-M2-6`
- **落点**：`src/llm_loop/realtime/task_bridge.py`
- **验收标准**：说话期间暂缓副作用派发；精确目标；复用既有授权审查；取消边界明确
- **可验证方式**：M4 专用测试；**不倒算首版能力**
- [ ] 实现说话期间暂缓副作用派发与精确目标
- [ ] 标定取消边界；**不把只读测试结果泛化为「任意工具安全执行」**

### 7.2 外部幂等键与不明结果核对（T-M4-2 ｜ RTM: TOL-15、TOL-07、TOL-08）

- **依赖前置**：`T-M4-1`
- **落点**：`task_bridge.py`、认领记录扩展
- **验收标准**：外部幂等键声明；不明结果核对；写测试先在**隔离可回滚目标**进行
- **可验证方式**：M4 专用测试；`RTM-EVD-05` 阶段声明边界
- [ ] 实现外部幂等键与不明结果核对
- [ ] 写测试在隔离可回滚目标进行（`RTM-EVD-05`）

---

## 8. 验证与门禁（测试与证据分级）

### 8.1 单元/集成测试（T-GATE-1 ｜ RTM: EVD-01、T01–T27 相关）

- **依赖前置**：各阶段实现任务
- **落点**：`tests/realtime/`（新增，沿用 `tests/unit`+`tests/web` 约定）
- **验收标准**：事件时序、桥接幂等、恢复、音画关联、资源清理、**本地栈接线/终稿校正/运行时约束**有测试覆盖
- **可验证方式**：`pytest -k realtime` 全绿；对照 T01–T27 矩阵
- [ ] 建立 `tests/realtime/` 与事件时序/幂等/恢复/资源清理/**本地栈接线**测试骨架
- [ ] 对照 T01–T27 测试矩阵逐项落位

### 8.2 WS 握手三类拒绝测试（T-GATE-2 ｜ RTM: SES-02、SES-03、SES-07、SEC-06、SEC-08、IDN-02）

- **依赖前置**：`T-CONTRACT-4`
- **落点**：`tests/realtime/`（WS）
- **验收标准**：未登录/跨站 Origin/越权媒体会话三类连接均在 `accept` 前拒绝，并断言**拒绝后不建立任何媒体/任务副作用**；断言浏览器**不能**绑定任意本机服务
- **可验证方式**：三类握手测试通过，断言关闭码 4401/4403/4404
- [ ] 未登录连接 → 4401；跨站 Origin → 4403；越权会话 → 4404（防枚举）
- [ ] 断言拒绝后无媒体/任务副作用；拒绝任意本机服务地址（`RTM-SEC-08`）

### 8.3 幂等/恢复/崩溃窗口测试（T-GATE-3 ｜ RTM: TOL-01、TOL-04、TOL-05、TOL-08、TOL-16、REC-02、REC-05、REC-06、PRF-06）

- **依赖前置**：`T-CONTRACT-2`、`T-M2-4`
- **落点**：`tests/realtime/`
- **验收标准**：T10（重复 100 次只派一次/不同用户相同参数）、T13（派发前后崩溃/结果持久化前掉线）、T14（本地会话重建/上下文重建）通过；重复派发 0 次
- **可验证方式**：上述测试全绿；`RTM-PRF-06` 时序正确性 0 次违规
- [ ] T10/T13/T14 回归；重复派发/跨会话/旧音频复活 0 次
- [ ] 崩溃窗口 `outcome_unknown` 表达可核；本地会话重建路径可核（`RTM-REC-05`）

### 8.4 既有能力回归护栏（T-GATE-4 ｜ RTM: CMP-01、CMP-02、CAP-08、CAP-10、BUD-07、RET-05）

- **依赖前置**：各阶段实现任务
- **落点**：`tests/web/`、`tests/unit/`
- **验收标准**：原文字流、附件、插话、取消、任务恢复、SSE 单路径、单次听写、任务预算独立**不回归**
- **可验证方式**：既有测试全绿；`RTM-BUD-07` 原任务预算未被调低
- [ ] 回归文字流/附件/插话/取消/任务恢复
- [ ] 核验 SSE 不新增第二消费者；`DictationButton` 语义不变；任务预算独立

### 8.5 五类证据分开报告与阶段门禁（T-GATE-5 ｜ RTM: EVD-01、EVD-02、EVD-03、EVD-04、EVD-05、EVD-06、OBS-06、OBS-07、OBS-09、PRF-01、PRF-08）

> **v1.1 强化**：在原有「四类证据分开」基础上增**第五类分级：服务级已实测 vs 浏览器链路已验收**（`RTM-EVD-06`）。

- **依赖前置**：`T-GATE-1…4`
- **落点**：门禁记录与回执
- **验收标准**：模拟 / 真实设备 / 真实 Provider / 生产部署**四类证据分开**，且**服务级 vs 浏览器链路分级**清楚；缺任一真实证据列「未验收」；每阶段独立审查保存命令/退出码/指纹/失败项；**禁止提前写 PASS**
- **可验证方式**：四类证据分开 + 服务级/浏览器链路分级可查；阶段门禁记录齐全
- [ ] 四类证据分开报告；缺真实证据列「未验收」（`RTM-EVD-01/02`）
- [ ] **服务级 vs 浏览器链路分级**：浏览器链路未通时相关条目显式未验收（`RTM-EVD-06`、`RTM-OBS-09`）
- [ ] M0 不以 mock 完成；M3 前不宣称 MVP 交付；性能分离「已测/达标」且为**浏览器链路口径**（`RTM-EVD-03/05`、`RTM-PRF-01`）
- [ ] 每阶段独立审查，保存命令/退出码/候选指纹/失败项

### 8.6 门禁 T25：本地栈能力档案、观察项、转写会话边界、运行时约束、本机服务暴露（T-GATE-6 ｜ RTM: CAP-09、CAP-11、CAP-12、CAP-13、CAP-14、SEC-08、AUD-01、TOL-16、PLY-07）

> **v1.1 新增（对齐权威 SPEC §24 T25）**。

- **依赖前置**：`T-M0-2`、`T-M0-4`、`T-M1-10`、`T-M1-13`
- **落点**：`tests/realtime/`；能力档案核对记录
- **验收标准**：能力档案含本地栈**版本/接口/模型/许可**；标注**仅转写、无音频输出、无工具回环**且运行时不依赖 `response.create`/音频回环；观察项证伪证据/退出条件可查且界面不当作已支持；运行时约束违反时**错误可见而非静默空结果**；本机服务仅回环/受信可达、凭据不下发前端、许可核实记录
- **可验证方式**：T25 用例通过；构造缺约束/缺许可场景断言显式报错；断言浏览器不直连本机服务
- [ ] 校验能力档案：`LocalStackProfile` 版本/接口/模型/**许可**齐全（`RTM-CAP-11`）
- [ ] 校验**转写会话边界**：标注「仅转写、无音频、无工具回环」，运行时不依赖 `response.create`（`RTM-CAP-12`、`RTM-TOL-16`、`RTM-PLY-07`）
- [ ] 校验**观察项**：证伪证据/原因待查/退出条件可查、界面不当作已支持能力（`RTM-CAP-13`）
- [ ] 校验**运行时约束**：违反时错误可见、不静默空结果（`RTM-CAP-14`）
- [ ] 校验**本机服务暴露**：仅回环/受信可达、凭据不下发、许可核实（`RTM-SEC-08`）

### 8.7 门禁 T26：ASR 终稿校正（T-GATE-7 ｜ RTM: INP-01、INP-02、INP-09、AUD-03）

> **v1.1 新增（对齐权威 SPEC §24 T26）**。

- **依赖前置**：`T-CONTRACT-5`、`T-M1-11`
- **落点**：`tests/realtime/`；终稿校正核对记录
- **验收标准**：`delta` 仅作显示（进 `committed` 或驱动工具**均为 0**）；句末高精度重转写作 `final`；错字样例（「语音链路→语音路」「克隆→克龙」）不进入 `committed`；终稿不可用时保守边界 + 精度标注
- **可验证方式**：T26 用例通过；对照错字样例与 `final` 来源断言
- [ ] 断言流式增量只作显示：`delta` 进入 `committed` 或驱动工具**为 0**（`RTM-INP-09`）
- [ ] 断言 `final` 来自句末高精度重转写；错字样例不进 `committed`
- [ ] 断言终稿不可用时**保守边界 + 精度标注**（`RTM-INP-09`）

### 8.8 门禁 T27：服务级 vs 浏览器链路证据分级与测量口径（T-GATE-8 ｜ RTM: EVD-06、OBS-05、OBS-09、PRF-01、PRF-02、PRF-03、PRF-04、CAP-07、CAP-03）

> **v1.1 新增（对齐权威 SPEC §24 T27）**。

- **依赖前置**：`T-M1-8`、`T-M3-4`
- **落点**：`tests/realtime/`；性能/证据分级核对记录
- **验收标准**：服务级基线与浏览器链路**分别记录且口径可复现**；服务级数值**不被当作**浏览器验收；服务级与浏览器样本**混算 P50/P95 = 0**；浏览器链路未接通时相关条目显式未验收；M0 探针 A/B 不因服务级已通而宣布通过
- **可验证方式**：T27 用例通过；断言样本分组计算，混算为 0
- [ ] 断言服务级与浏览器链路**分开记录**、口径可复现（`RTM-OBS-05/09`、`RTM-EVD-06`）
- [ ] 断言服务级数值**不充当**浏览器链路验收；**混算 P50/P95 = 0**（`RTM-PRF-01…04`）
- [ ] 断言浏览器链路未通时相关条目显式未验收；M0 探针 A/B **不因服务级已通而宣布通过**

---

## 9. 交付边界与提交纪律

### 9.1 运行文件不清理、不回滚（T-OPS-1 ｜ RTM: 设计 v1.3 §4.4 交付边界）

- **依赖前置**：无
- **落点**：`git check-ignore`、`.git/info/exclude`
- **验收标准**：`Cookies`、浏览器缓存、`data/knowledge_scores/runner_state.json`、`data/runtime/learning_admission.json` 等**未被 Git 跟踪且被忽略**的运行/用户态文件**不清理、不回滚、不提交**
- **可验证方式**：`git ls-files` 无输出；`git check-ignore -v` 命中
- [ ] 核实运行文件未被跟踪（`git ls-files` 无输出；`git check-ignore -v` 命中 `.git/info/exclude`）
- [ ] 断言这些文件不纳入任何提交

### 9.2 回滚边界执行（T-OPS-2 ｜ RTM: LIF-08）

- **依赖前置**：无
- **落点**：Web 相关能力范围
- **验收标准**：出现串会话、重复派发、无法停播、凭据泄漏或资源持续增长时，在 Web 范围关闭新增媒体入口并恢复原文字入口；**不删除任务事实、不中断其他服务**
- **可验证方式**：回滚演练记录
- [ ] 定义回滚触发条件与执行步骤
- [ ] 演练：关闭新增媒体入口并恢复原文字入口，任务事实保留

### 9.3 提交按精确路径选择（T-OPS-3 ｜ RTM: 设计 v1.3 §4.4 交付边界）

- **依赖前置**：无
- **落点**：提交纪律
- **验收标准**：**不整目录 `git add`**；设计交付只提交两份 design 文档；任务规划只提交两份 tasks 文档；实现阶段按源码/测试路径精确提交
- **可验证方式**：每次提交 `git show --stat` 精确可查
- [ ] 声明提交纪律并逐项按精确路径提交
- [ ] 核验每次提交不含被忽略的运行文件与用户态数据

---

## 10. 评审与最终确认

### 10.1 代码审查（T-REV-1 ｜ RTM: EVD-04）

- **依赖前置**：`T-GATE-5`
- **落点**：审查回执
- **验收标准**：关键代码（唯一执行链、原子认领、WS 握手、状态机、**本地栈适配器/终稿校正/TTS 编排**）有独立审查意见并落盘
- **可验证方式**：审查回执存在
- [ ] 对关键实现点完成独立代码审查并落盘回执

### 10.2 设计与实现一致性回顾（T-REV-2 ｜ RTM: EVD-04、CMP-01）

- **依赖前置**：`T-REV-1`
- **落点**：一致性核对记录
- **验收标准**：实现与 design **v1.3** 的 8 项实现契约、D1–D22 与 **D23–D28** 决策逐项核对，无漂移
- **可验证方式**：逐项核对表
- [ ] 逐项核对 8 项实现契约与 **D1–D28** 决策的落地一致性

### 10.3 阶段声明边界确认与变更范围确认（T-REV-3 ｜ RTM: EVD-05、EVD-06、PRF-01）

- **依赖前置**：`T-REV-2`
- **落点**：最终确认记录
- **验收标准**：阶段声明与证据分级一致（M0 不以 mock 完成、M3 前不宣称 MVP、性能分离「已测/达标」且**浏览器链路口径**、**服务级不混算**）；变更范围最终确认
- **可验证方式**：最终确认记录
- [ ] 确认阶段声明边界；确认本次变更范围与提交清单

---

## 附录 A：任务 ↔ RTM 需求映射摘要

| 任务组 | 任务 ID | 关联 RTM 需求（主） |
|---|---|---|
| M0 首批 | `T-DOC-1` | EVD-01/05、EVD-06、SPEC §0.7 |
| M0 首批 | `T-M0-1` | CAP-05/11、EVD-04、CMP-01、REC-02、SEC-08 |
| M0 首批 | `T-M0-2` | CAP-01/02/04/05/07/11/12/14、SES-06、SEC-01/08 |
| M0 首批 | `T-M0-3` | AUD-01/03、PLY-02/07、PRF-02/03/04、INP-04/09、TOL-04/09/16、CAP-12、EVD-06、OBS-09 |
| M0 首批 | `T-M0-4` | CMP-01、CAP-07/13、SES-03、EVD-01/03/04/06、OBS-09、PRF-01/08、SEC-08 |
| 契约组 | `T-CONTRACT-1` | TOL-01/03/16、CMP-01/02 |
| 契约组 | `T-CONTRACT-2` | TOL-02/04/05/06/07/08/16、REC-02/06、IDN-01 |
| 契约组 | `T-CONTRACT-3` | CAP-01/05/11/12、AUD-01、INP-09、REC-05 |
| 契约组 | `T-CONTRACT-3D` | CAP-05/11/12 |
| 契约组 | `T-CONTRACT-4` | SES-02/03/07、SEC-01/06/08、CAP-05、IDN-02 |
| 契约组 | `T-CONTRACT-5` | INP-01/02/03/04/05/08/09、AUD-05/06、STP-03 |
| 契约组 | `T-CONTRACT-6` | SES-05、REC-03/05/09、LIF-01/02/04、IDN-03/07、PLY-03、CAP-14 |
| 契约组 | `T-CONTRACT-7` | VIS-02/03/05/06/09、RET-01/02/03/05、CAP-06、IDN-01 |
| 契约组 | `T-CONTRACT-8` | BUD-01/02/03/04/05/07、CMP-01、LIF-05/07、STP-06 |
| M1 音频 | `T-M1-1…8` | SES-01/04/05/06/07、AUD-01…07、PLY-01…07、IDN-02/03/07、LIF-01…04、OBS-05/09、BUD-01、CAP-05/10/14、SEC-05、RET-04、INP-09、PRF-02/03、EVD-06 |
| M1 接线 | `T-M1-9` | AUD-01/03、CAP-14、PLY-02、PRF-02/03 |
| M1 接线 | `T-M1-10` | CAP-05/11/12、AUD-01/03、REC-05 |
| M1 接线 | `T-M1-11` | INP-01/02/03/09、AUD-03 |
| M1 接线 | `T-M1-12` | PLY-01/02/04/07、PRF-03、OBS-09 |
| M1 接线 | `T-M1-13` | CAP-03/04/14、SEC-08 |
| M2 任务 | `T-M2-1…6` | INP-01…09、STP-03/04/05/06/07、TOL-01/04/05/09/10/11/12/13/16、REC-01…14、CMP-02、IDN-07/08、SCN-02/03/04、EVD-02、CAP-14 |
| M3 视觉 | `T-M3-1…5` | VIS-01…09、RET-01/02/03、SES-04、A11Y-01…06、CAP-03/08/09/10/13、PRF-01…08、OBS-01/02/05/06/07/08/09、EVD-06、CMP-01/02、LIF-04/07/08、SCN-01/05 |
| M4 可写 | `T-M4-1…2` | TOL-14/15、TOL-07/08、EVD-05 |
| 门禁 | `T-GATE-1…5` | EVD-01…06、T01–T27、OBS-06/07/09、PRF-01/06/08、SES-02/03/07、SEC-06/08、REC-02/05/06、CMP-01/02 |
| 门禁（新增） | `T-GATE-6`（T25） | CAP-09/11/12/13/14、SEC-08、AUD-01、TOL-16、PLY-07 |
| 门禁（新增） | `T-GATE-7`（T26） | INP-01/02/09、AUD-03 |
| 门禁（新增） | `T-GATE-8`（T27） | EVD-06、OBS-05/09、PRF-01/02/03/04、CAP-07/03 |
| 交付 | `T-OPS-1…3` | LIF-08、设计 v1.3 §4.4 交付边界 |
| 评审 | `T-REV-1…3` | EVD-04/05/06、CMP-01、PRF-01 |

**覆盖结论**：20 个 RTM 分组（SES/AUD/INP/VIS/PLY/STP/TOL/IDN/REC/LIF/CAP/BUD/OBS/A11Y/SEC/RET/CMP/PRF/EVD/SCN，共 **163 条**）**全部**有任务落位；**新增条款**（CAP-11/12/13/14、INP-09、TOL-16、PLY-07、SEC-08、OBS-09、EVD-06）均有明确落点；M0 为首个执行单元，契约组承接 v1.3 八项实现契约（含 D1/D2 拆分），M1 为**本地语音栈接线闭环**，M2–M4 按可运行闭环推进。

---

## 附录 B：M0 探针执行步骤与「部分解除 / 不得 mock」约束（摘要，详见 §2.1–§2.5）

1. **冻结候选**（`T-M0-1`）：隔离 worktree/候选；`git rev-parse HEAD` + 关键文件 SHA-256。
2. **读防退化契约**（`T-M0-1`）：`docs/DEVELOPMENT_REPAIR_SAFETY.md`。
3. **只读核实存量接口事实**（`T-M0-1`）：auth / runner / routes / journal / attachments+artifacts / registry；含**本机服务暴露前提**（`RTM-SEC-08`）。
4. **确认并冻结本地栈 + 能力档案三态 + 运行时约束**（`T-M0-2`）：只确定一条生产传输（本地 WS 转写 + 本地 TTS 编排）；冻结计时/用量/代次/本地停播基线；记录 `LocalStackProfile`/`RuntimeConstraint`（CAP-14）。
5. **执行最小探针**（`T-M0-3`，**A/B 部分解除**）：
   - **A 连续听说**：**[服务级部分解除]** 本地栈脚本已观测流式增量与句末终稿；**[浏览器侧仍阻断]** 须在浏览器观测 16k 重采样 → 本地 WS 转写 → 轮次归一化 → 高精度终稿；**未接通浏览器前不得宣布通过**（`RTM-EVD-06`）。
   - **B 本地打断**：**[服务级部分解除]** 本地链路可本地停播；**[浏览器侧仍阻断]** 须在浏览器观测「客户端 VAD 起点 → 扬声器实际停止」并记录延迟基线；**不得宣布通过**。
   - **C 同会话只读工具**：**[通过]** 隔离 workspace 运行时写校验值 → 真实 `read_file` 回执核对一致；确认提交前不派发；**补注工具编排落点**（`RTM-TOL-16`）。
6. **记录基线 / 列阻断 / 门禁证据**（`T-M0-4`）：现状基线；**服务级基线登记**（OBS-09）；**观察项登记**（CAP-13）；阻断清单转为「**浏览器链路接线未完成**」「**本地服务暴露/许可待核实**」；保存命令/退出码/指纹/失败项；独立审查，禁提前写 PASS。

> **硬约束**：M0 **不得以 mock 冒充完成**（`RTM-EVD-03`）；**A/B 不得因服务级已通而宣布通过**（`RTM-EVD-06`）；探针脚本为**一次性隔离候选**，**不并入生产路径**；M0 **不依赖** `MediaSessionRegistry`/`TurnAggregator`/`TaskBridge`（消除循环依赖）；缺凭据/浏览器链路/暴露与许可**必须显式列阻断**（`RTM-CAP-07`、`RTM-SEC-08`）。

---

## 附录 C：v1.0 → v1.1 变更清单（定点修订）

| # | 变更位置 | 变更内容 | 依据 |
|---|---|---|---|
| C1 | 元数据 | 需求 153 → **163 条**；设计 v1.2 → **v1.3**；tasks v1.0 → **v1.1** | SPEC v1.2、DESIGN v1.3 |
| C2 | §0 纪律 | 增**执行纪律 7（本地栈唯一链路）**、**8（服务级 vs 浏览器链路分级）**；纪律 6 增「浏览器链路口径」 | CAP-05/11/12、PLY-07、TOL-16、EVD-06、OBS-09 |
| C3 | §1.1 / §1.1.1 | 保留 13 条建议落位表；新增**设计 v1.3 输入建议落位表** | DESIGN v1.3 §3.2.2/§3.3 |
| C4 | §1.2 | 依赖图增 `T-CONTRACT-3D`、M1 接线内部顺序 | DESIGN v1.3 §3.3 |
| C5 | §1.3 | 主任务 45 → **54**（新增 9） | 本文 |
| C6 | `T-M0-2` | **重写**：确认并冻结**本地栈** + preflight（CAP-14）；不选定远端、不写空适配器 | DESIGN v1.3 §3.2.1-4/5 |
| C7 | `T-M0-3` | **重写 A/B 为「部分解除」**：服务级已通、浏览器侧仍阻断，**不得宣布通过**；C 补注 TOL-16 | DESIGN v1.3 §3.2.1-6 |
| C8 | `T-M0-4` | 增**服务级基线登记（OBS-09）**、**观察项登记（CAP-13）**；阻断清单更新 | DESIGN v1.3 §3.2.2 |
| C9 | `T-CONTRACT-1/2` | 增**桥接基于 `committed` 编排发起、仍经唯一入口（TOL-16）** | DESIGN v1.3 §2.1.3-C、D25 |
| C10 | `T-CONTRACT-3` | **拆分**：D1 本地转写适配器（首版实现） | DESIGN v1.3 §2.2.2-D1、D24 |
| C11 | `T-CONTRACT-3D` | **新增**：D2 远端预留（不实现、不写空适配器） | DESIGN v1.3 D23/D24、CAP-05/11 |
| C12 | `T-CONTRACT-4/5/6/8` | 分别增：音频二进制帧承载 + SEC-08；`FinalPass`/INP-09；本地会话重建 REC-05 + CAP-14 不重连；本地算力/许可口径 | DESIGN v1.3 §2.1.3-J/G/H、D26 |
| C13 | `T-M1-9…13` | **新增 5 项接线主任务**（16k 重采样/VAD；本地转写会话/二进制帧；双 ASR 终稿；TTS 编排；preflight） | DESIGN v1.3 §3.3、§3.8 |
| C14 | `T-M1-1…8` | 定点增：单连接二进制帧；本地 TTS 下行；计时分级；16k 重采样；字幕 final；flush 收尾；门禁增 T25/T26/T27 | DESIGN v1.3 §3.3 |
| C15 | `T-GATE-6/7/8` | **新增 T25/T26/T27 门禁任务**；`T-GATE-1` 骨架增本地栈接线；`T-GATE-5` 增证据分级 EVD-06 | SPEC §24 T25–T27 |
| C16 | 附录 A | 映射摘要更新（163 条 + 新增条款落位 + T25–T27） | 本文 |

---

> **文档状态（v1.1）**：本 tasks.md 以 v1.0（45 主任务）为基线**定点修订**，依据权威需求 v1.2（**163 条 RTM**）与设计 **v1.3（本地实时语音栈接线；保留 8 项实现契约与 D1–D22，新增 D23–D28）** 生成，主任务扩为 **54 项**：M0 定点修订（本地栈冻结 + 探针 A/B 部分解除 + 服务级基线/观察项登记）、契约组拆 D1/D2、M1 新增 5 项接线主任务、门禁新增 T25/T26/T27。**本阶段只产出任务规划，不执行任何编码**；首个执行单元仍为 **M0 结算**，随后进入 **M1 本地语音栈接线**闭环。