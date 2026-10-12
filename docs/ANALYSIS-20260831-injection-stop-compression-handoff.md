# ANALYSIS-20260831 — 程序注入干扰 & 压缩衔接：两轮讨论落地总结（讨论发生于 2026-08-30 UTC）

> 来源会话: 004976ea-5a23-4ae9-9f16-83b18767720a（飞书镜像，2026-08-30）
> 依据: episode :158（注入干扰/飞书 stop）、episode :184（压缩衔接）完整问答 + 镜像区代码取证
> 性质: 落地总结文档；所有实施项须按镜像协议写入 mirror → submit_evolution → Web 端「演进审批面板」审批后执行
> 附录 A 补全同期被打断的 HF 模型评估（原提问因两次 LLM 调用失败未获回答）

## 0. 一页结论

| # | 议题 | 结论 | 动作 |
|---|---|---|---|
| 1 | 推理中程序注入是否干扰 | 成立，三重实证（98605ad7 / 68fed5f5 / 本会话停滞样本） | 分层开关，不一刀切 |
| 2 | 注入是否交用户控制 | 赞成，但 recovery/压缩通知两层不可关 | /inject minimal\|standard\|full（P2） |
| 3 | 飞书 /stop 不生效 | 实锤：handlers.py 无该指令处理器 | P1 补 ~20 行处理器 |
| 4 | 压缩是否要先停推理 | 不需要：压缩只发生在轮间 build 时 | 改"衔接原子性"，非停推理 |
| 5 | 压缩衔接真病根 | 恢复工作被逐轮推给模型，非程序一次交接完 | EVO 三改动（边界门/单次恢复包/防死循环） |

## 1. 讨论一：程序注入干扰与用户控制（episode :158）

### 1.1 命题（用户原话）
"我发现大模型在推理过程中，程序注入消息是不对的，很容易造成干扰，你评估下。应该赋予用户自己决定是否插入信息（在输入端）和停止推理（web端已实现，飞书端的/stop不生效）。"

### 1.2 事实核查
**注入干扰成立——三个证据**
1. focus.py 头部注释（实证 98605ad7，episode 内引用）：本地模型把注入消息（切换感知/记忆/经验/提醒）误读为"独立消息/新任务"而绕路——48 次工具调用一半是重复探测，68 分钟未完成任务。
2. 规则 v7 第 10 条（实证 68fed5f5）：元状态语料占据生成位尾部会把弱模型带偏、答非所问。
3. 本会话活样本：每轮工具调用后注入 digest，压缩前后对同一 query 重复调 search_archive 3-5 次（典型停滞），最终 LLM 报错、用户 /stop。

**治理框架已存在，缺的是"用户控制"这一环**
- injection_labels.py：四层语义标签；injection_budget.py：统一硬预算 8000 字符（MIN 512），BudgetPriority = RECEIPT(0) < PROGRAM_RECOVERY(10) < CRITICAL_STATUS(20) < STATUS(30) < REFERENCE(40)，整块保留或丢弃、从不截半；_CRITICAL_STATUS_SLOTS 白名单（decision_header/semantic_header/task_anchor/task_frontier/interop/gate_note/budget_receipt）。
- 现有控制仅 env 级 INJECTION_BUDGET_CHARS，无输入端开关。

**Web 端停止链路（已实现，完整）**：webui/src/core/conversation.ts:303 stopStreaming() → src/llm_loop/web/routes.py:605 POST /api/v1/chat/cancel → runner.cancel() → 引擎主循环每轮检查 _background_cancelled（engine.py:775/866）提前终止。

**飞书 /stop 缺口（实锤）**：feishu/handlers.py 仅拦截 /model（M50）、/new·/clear（M55）、审批指令（EVO-20260817），无 /stop 处理器；目录内所有 "stop" 均为进程生命周期（SIGTERM/SIGINT/bridge.stop）。/stop 落入普通消息路径进 engine.run，被当成一条用户消息——故"不生效"。

### 1.3 提议评估
**提议 A（输入端注入开关）：赞成，但必须分层，不能单开关**

| 层 | 建议 | 理由 |
|---|---|---|
| program_recovery（恢复） | 不可关 | 规则 19 中断恢复的唯一可执行例外，关掉破坏会话韧性 |
| 上下文压缩通知、缓存守卫 | 不可关 | "信息零丢失"诚实性契约 + 成本保护 |
| reference（记忆/经验） | 可关/可调 | 有用但非必需，弱模型下主要干扰源之一 |
| status 环境部分（任务锚点/frontier/digest） | 可关/可调 | 高频注入噪音主体；强模型留有益，弱模型直接带偏 |

实现：/inject minimal|standard|full 指令（照抄 M55 拦截模式），底层复用现成 BudgetPriority 分层 + critical slots 白名单——顺势增量，不是重构。默认 standard，弱模型场景切 minimal。
风险提示：完全关闭注入 = 压缩后模型不自知、中断后无法恢复、缓存成本失控；分层开关是必要的。

**提议 B（飞书 /stop）：赞成，路径明确、成本低**
1. handlers.py 加 _try_handle_stop_command（模式照抄 M50/M55，约 20 行）；
2. 取消语义复用引擎 _background_cancelled 每轮检查；~~唯一核实点：飞书 bridge 的 runner 实例与 web 是否共享取消通路~~（核实点已关闭，2026-08-31 评审修正：飞书 handlers 直接持有 `engine: LoopEngine`（`self._engine`，handlers.py:69-83），runner 为 web 侧包装——P1 对 engine 复用取消语义即可，同进程闭环，无跨进程需求）；
3. 复用 bridge.py 已有 _persist_interrupted 中断补偿落盘，stop 后回复"已停止，可用 /continue 或重发恢复"；
4. 一个坑（本会话两次实况演示）：取消瞬间 LLM 会报 Operation canceled / Model unloaded——错误分类必须识别"用户主动取消"，不得当真实故障重试。

## 2. 讨论二：压缩与推理的衔接（episode :184）

### 2.1 命题（用户原话）
"上下文压缩通知、缓存守卫，不应该在变压缩变推理注入，如果进行压缩，是否需要先停止推理，转而配合压缩好，做好衔接再接着任务？"

### 2.2 事实核查
**"边压缩边推理"物理上不存在——压缩只发生在两次 LLM 调用之间（build 时）：**
- build.py:688-720 预算分级：80% 只发"准备态"提示（不压缩不打断推理）；90%（COMPACT_RATIO 默认 0.9）才平滑压缩，裁到目标水位留缓冲；增长率双轨 nudge（EVO-20260824-54d46549：准备态后增长 ≥ 预算 5% 或 20K 字符才预警）。
- history.py:718-726 渐进折叠（每次只折最老 K 组，不一次大裁）+ freeze_compression 熔断（连续压缩仍超线 → 冻结一切程序压缩、锚点不动）。
- injection_budget.py：恢复类注入走 PROGRAM_RECOVERY 优先级（仅次于回执），整块不截半。

**但"衔接不是原子的"是真病根**：压缩通知 + Evidence Manifest 多次插在工具轮之间（每次 ledger_version 不同），恢复工作被逐轮推给模型 → 压缩后同 query 重复检索 4-5 次（停滞），随后 LLM 报错、用户 /stop（本会话实况）；与规则 10 记载的"元状态语料占生成位尾部带偏弱模型"同源。

### 2.3 建议（EVO 三改动点）
1. **任务边界压缩门**：工具链未收敛（还有 pending 工具调用）时延迟折叠，到自然边界（用户轮/无 pending 工具）才折；撞硬顶由 engine 前置 context_pressure + freeze 熔断兜底。
2. **单次恢复包**：压缩事件只发一个 PROGRAM_RECOVERY 块（归档了什么 + 任务锚点 + top-K 关键 ref）；manifest 按事件去重，不再逐轮重发。
3. **程序级防恢复死循环**：压缩后同 query 检索 ≥2 次即注入硬提示"已恢复过，基于现有证据继续"，≥3 次强制收束轮次——把规则 11.1"核对一次即止"从软约束变成程序强制。

## 3. 合并落地路线图

| 优先级 | 项 | 规模 | 依赖/核实点 |
|---|---|---|---|
| P1 | 飞书 /stop 处理器 | ~20 行 + 取消错误分类 | ~~核实 runner 实例归属~~（已关闭：飞书侧直接持有 engine，同进程取消）；**验收须含 /stop 后 /continue 恢复实测**；取消原因经标记位分类，不靠错误文本匹配 |
| P2 | /inject 分层开关 | 指令拦截 + 档位→BudgetPriority 映射 | 先 shadow 验证 minimal 档对弱模型漂移的改善，再定默认值 |
| P2 | 任务边界压缩门 | build/history 折叠时机调整 | 与 /inject 同属注入路径，可合并一个 EVO 分项审批 |
| P3 | 单次恢复包 + 防死循环 | manifest 事件去重 + 检索计数器 | 依赖 P2 档位语义定稿 |

共同路径：改动全部写入 mirror 区 → submit_evolution → Web 端左侧「演进审批面板」审批 → 登记完成。

## 4. 附录 A：HF 模型评估补全（被打断话题）

Q: "你觉得这个怎么样？Lord-H4D3ZS/Qwen3.8-Distill-35B-A3B-Coder-Abliterated"（因两次 LLM 调用失败未答，此处基于已取证模型卡补全）

**模型卡事实（web_fetch 2026-08-30）**
- 基座 Qwen/Qwen3.6-35B-A3B（MoE，总 35B/激活约 3B）；性质 = 社区蒸馏 + coder 导向 + abliterated（移除拒绝对齐）。命名说明：标题"Qwen3.8-Distill"系教师进名蒸馏命名法（类比 DeepSeek-R1-Distill-Qwen-32B：Qwen3.8 教师 → Qwen3.6 基座学生），非笔误（2026-08-31 评审修正）。
- 交付物：*-Q2_ROCMFPX.gguf（约 16GB 显卡可装）+ BUILD.md/build_rocmfpx.sh（需按 pinned commit b2f5829 自建 ROCmFPX runtime）；Apache-2.0；月下载 30,031。
- 模型卡自认：tool-calling/agentic 弱（thin PoC corpus，"the first thing the next run must fix"）；MTP nextn 张量在但投机解码依赖 runtime 支持；纯文本无视觉；HF 无法识别其量化变体。
- web_search 未见第三方评测（仅 Qwen 官方系列结果）。

**评估**
1. agent 主力不合格：模型卡自己承认 tool-calling 是第一弱点；本会话刚实证弱模型在注入环境下漂移/停滞——与 LFL agent loop 的主力需求直接冲突。
2. 部署摩擦高：ROCmFPX 为私有量化格式，标准 llama.cpp/LM Studio 路径不直接识别，需自建 runtime（pinned commit）；Q2 极低比特通常精度损失明显。
3. abliterated：对本地编码实验无关键增益，拒绝剥离带来的用途/合规边界由使用者自担。
4. 相对本机 LM Studio 已在列的 qwen3.6-27b（同家族标准版）增量有限：仅多 coder 蒸馏 + 去拒绝 + Q2 私有量化。
5. **结论：不建议接入 LFL 工作流**。若要实验：隔离环境对照 qwen3.6-27b 跑编码/agent 基准后再定，且优先找标准量化（GGUF Q4+）版本而非 ROCmFPX Q2。

## 5. 附录 B：证据索引

> **行号基线注记（2026-08-31 评审复核）**：下表 evidence 快照与现行代码存在 12-50 行漂移——复核时点镜像区 commit `97711c0`：build.py 80%/90% 分级实际位于 :726-732、engine 取消检查点 :440/720/776、BudgetPriority 枚举位于 `core/injection_budget.py:36-40`。实施时以现行代码为准，勿按快照行号索骥。

| 内容 | 引用 |
|---|---|
| 讨论一完整问答 | episode:004976ea-5a23-4ae9-9f16-83b18767720a:158:79da5e37f81e0a2bb3f5 |
| 讨论二完整问答 | episode:004976ea-5a23-4ae9-9f16-83b18767720a:184:1bec214b47368cef7e06 |
| HF 模型卡正文 | evidence://v1/c18c430a11903480a733c42e7fe1fb27590d27b8eeceae540c7bccc1c40cda49 |
| 第三方评测缺失（搜索结果） | evidence://v1/7395d6f8122413b1b5abcce76cc7b4880c78185eaa3721e15e8dee6c4ff3fe5c |
| injection_budget.py L1-70 | evidence://v1/73b7e14ee463632fc993c61d8b207ed457227eaa887bdc659af3fe479415ec9d |
| build.py L661-720（预算分级/nudge） | evidence://v1/ea4e6ec1b413b08da4010a289513d98489ab5efef0ec1d106fbc28368b3543ee |
| history.py L1360-1405（压缩注入/折叠标注） | evidence://v1/65e2c821d00b6125fbb6d18033c8e9093575b5852ce61e40ef338aa4decdee3a |
| 取消链路 grep（engine/routes/conversation.ts） | evidence://v1/c7ecf8bb61da41416e03186763329027877efc3f40339ed541ed77256cec99e |

（完）
