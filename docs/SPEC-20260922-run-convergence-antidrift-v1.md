# SPEC：run 收敛与防漂移优化包 v1（fc0ed66c 事故驱动）

| 项 | 值 |
|---|---|
| 状态 | draft-for-review（事实已核验，方案待人工评审；本文档不含已执行代码改动） |
| 定稿时间 | 2026-09-22 16:35 本地（08:35 UTC），dsh 会话 |
| 事实核验窗口 | 2026-09-22 15:43–16:32 本地（事件日志 3/4.jsonl、action_trace、队列、进程、env） |
| 事故对象 | 会话 fc0ed66c-e669-41c4-94d7-7e05031bbac6（wake 驱动的验证类 run） |
| 部署基线 | gen68 = 4c76cb2e2（main，含 S1–S4）；live 三服务 verify=ok |
| 关联文档 | SPEC-20260922-service-control-restart-fixpack-v1.md（§8.2 S4 由本事故同日前置触发） |

---

## 1. 背景与事故时间线

用户观察："LFL 一直思考和探索，不收敛"。四个候选解释：漂移重复 / 污染干扰 / 注入干扰 / 折叠失去原任务。核验时间线（本地时）：

| 时刻 | 事件 | 证据 |
|---|---|---|
| 上午–15:08 | 会话完成 webui 时区修复（gen66 两提交的作者） | git log bb8e81ac4/79360a2d7 |
| 15:09–15:12 | 自行调查 `service_control publish --help`（被 shell 围栏挡）→ **自行发起 `service_control restart`**（execute_command 后台 job-7fe39572a80245658ee1，经自身工具管道）→ 自排 60s 唤醒"检查该 job 终态并完成验证" | action_trace 07:09–07:12 |
| 15:12 | gen66 重启被 SIGPIPE 杀死（rc=-13）：**调用方正是本会话的工具管道**。事故由 S4a 修复（durable stdio），本包不再处理 | svc-8011bb79 + S4 事故记录 |
| 15:36–15:37 | 操作员发布 gen67 + **绕过 service_control 直连启动 web(64587)** | managed_service_deployment.json；ps |
| 15:43 | 唤醒触发（原 wake_owner_pid=31365 已死，迟至直连进程出现才被认领）；run 启动 | schedule.json；action_trace 07:43:12 |
| 15:45–16:02 | 模型基于刚合并的 S4 做自主迭代（改 expected_generation 为可选 + 2 个测试） | 主仓 git diff（后 stash） |
| 16:07–16:08 | 操作员清直连进程，run 腰斩 → post-crash reconcile 复活，在 gen68 新 web 上继续 | 事件日志 4.jsonl 起点 07:55:45 |
| 15:51→16:16 | 任务语义已漂移为"审计我今天做过的所有 restart"；convergence_decide 三连 continue | action_trace 07:51/08:02/08:16 |
| 16:15 | run.compact：161,401→62,995 chars（drop 61.0%，archived=70）——原唤醒 prompt 被淘汰出工作面 | run.compact 事件 |
| 16:10–16:26+ | round 1→11，每轮 2–8 分钟（110K 上下文 + 深推理），run 持续在途 | request.usage rounds |
| 全程 | 用户两条插话 14:58:48 / 15:02:53 处于 `interject_received`，等 run 让出 turn 边界——**从未送达** | human_turn_queue.json |

**净结论**：任务对象（gen66 重启验证）在 15:12–15:20 已被后续事件取代（gen67/68 上线、job 被杀、自身 edit 被 stash），但 run 无从知晓；此后每轮都发现"新的未解事实"（S4 被称为"未知提交"、PID 全死），收敛判定永远有理由 continue；压缩进一步淘汰了原始任务锚点，使再锚定不可能。

## 2. 已核验事实（F 系）

### 2.1 四假设裁决

- **F1 漂移重复：成立，但为"变体探索"而非精确重复。** 5 次 convergence_decide 的 args_sha256 全不同（2b538c…/014aa7…/3df4bb…/8e1b7e…/b61106…）；工具调用每次换参数（16:24 仍在 `ps -p 64587,51785,52066` 追已死 PID；16:12 仍 poll 3 小时前的 job）。
- **F2 环境污染：已排除。** 当前 web(63083) env 干净（LFL_*/PYTHONPATH 全指主仓根，无 compaction-merge 残留）；restart 链路 P2 防御生效。DSH 会话内的残留未传染 LFL。
- **F2' 语义污染：成立（外生事实变迁）。** merge/S4/stash/换进程均发生在 run 之外，观察窗口内成为"无法解释的新事实"，持续供给 continue 理由。
- **F3 注入干扰：未发现证据。** provider-view 组成、事件流、队列来源均无 alien 内容；模型读到的是真实文件/回执。
- **F4 折叠失去原任务：成立，为放大器而非初始因。** 漂移始于 15:51（早于 16:15 的压缩）；压缩把原 prompt 淘汰出工作面（archive 有稳定 ref，工作面只剩摘要），使再锚定不可能。前缀守卫如实报告复用崩塌（final_lcp=20/47，cached 3,561/110K chars）但无止血语义。

### 2.2 既有防漂移措施盘点（全部在运行，均未命中本次形态）

- **F5** `LFL_EXACT_DUPLICATE_TOOL_FOLD=1`：生效；raw_tool_chars 449,602 → projected 449,602，folded_results=0——只折叠精确重复，变体探索零命中。
- **F6** `LFL_DUPLICATE_GUARD_MODE=shadow`：生效但只观察不阻断（审计记录 SE-20260903-002 含 `duplicate-guard 阻断帧 blocked=True` 先例，说明 enforce 能力存在）。同记录 `stagnation_rate=0.0`（连续重复口径）——**现有口径测不到变体探索**。
- **F7** 工具工作集批处理（BATCH_CHARS=65536/RECEIPTS=1/GRACE_GROUPS=1）：生效，只分组不减量。
- **F8** `convergence_decide` 收敛判定：生效，但 unresolved 清单由模型自写、无机械事实输入，"审计型任务"可无限续命。
- **F9** 本地小模型采样抗漂移（repetition_penalty 族）：**不适用**——当前 provider=glm/glm-5.3 远端 sampling={}，且按开发契约 Q4 跨 runtime 参数本不应照搬。
- **F10** `max_iterations` 硬边界已存在（动态优先、静态兜底，engine terminate.max_iterations 路径）——轮数上限不是缺失项，缺的是让模型**知道该停**的事实。
- **F11** `history_anchors` 语义核实：是**前缀缓存锚**（历史起点固定供缓存命中），与任务锚无关——任务源保真属于新缺口，非重复建设。
- **F12** `fixed_summary/summary_chain` 追加式压缩存在：原文在 archive 有稳定 ref（符合 exact capture 契约），缺口仅在"任务进行中不再回注工作面"。
- **F13** schedule 条目已带结构化字段（session_id/goal_id/goal_generation）：subject 引用是自然扩展，不需新存储形态。
- **F14** 会话当日事件日志 1–4.jsonl 合计 ≈26MB、多次 resume——长寿命会话的 context rot 是结构性诱因（branch 机制存在但 wake 子任务未使用）。

## 3. 问题清单（P 系）

| # | 问题 | 严重度 | 证据 |
|---|---|---|---|
| P1 | 任务对象消亡不可见：wake 任务无结构化 subject，run 无法机械感知"对象已被取代" | P0 | F1/F2'/时间线 |
| P2 | convergence_decide 输入无机械事实：无 run 寿数/轮数/token、无自身历史 unresolved 对照、无队列插话压力 | P0 | F8 |
| P3 | 任务源消息被压缩淘汰：任务进行中，起源 prompt 不在工作面，再锚定不可能 | P0 | F4/F11/F12 |
| P4 | 插话饥饿：interject 只能等 turn 边界，run 不收敛则用户永久失联（"不收敛"体感的直接来源） | P0 | 队列 14:58/15:02 |
| P5 | post-crash reconcile 无差别复活：被操作员清掉的 run 照常复活并继承已死任务 | P1 | 16:08 复活 |
| P6 | wake 所有权/时延：owner 进程死亡后唤醒迟至 30 分钟（且由直连进程认领） | P2 | schedule.json wake_owner_pid=31365 |
| P7 | 长寿命会话 context rot：wake 子任务不分会话，26MB 事件/日 | P2 | F14 |
| P8 | 变体探索无观测口径：stagnation/duplicate 口径均为精确/连续重复 | P2 | F6 |

## 4. 修复项（R 系）

> 设计总纲（对齐治理北极星）：**程序供事实、保边界、保可恢复；模型做语义、取舍与完成判断。** 以下所有 R 项均以"附加机械事实/保真回注/通道修复"形态实现，无一新增启发式裁决门。

### R0｜P0 运维处置（即时，人工）
终止 fc0ed66c 当前 run（不 resume）：其审计对象不存在，结论不会到来；其今日有效产出已全数保全（时区修复=gen66 提交；S4 迭代=stash@{0}/stash@{1}）。终止后插话自然以下一轮进入。**待用户批准执行。**

### R1｜wake 结构化 subject_refs + 唤醒事实注入（←P1）
- schedule 条目增加可选 `subject_refs`（job_id / expected_generation / action_id / ref 类型枚举），模型排程时自填（它知道自己在排什么）；缺省空、行为不变（向后兼容）。
- 唤醒投递与 reconcile 复活时，程序解析 subject 现状并**以事实段附于唤醒消息**：`job-xxx 终态=killed(16:07)；desired_generation 66→68；本唤醒排队 30min、owner 曾死亡`。模型读到即可判"任务已过时，报告并关闭"。
- 拒绝方向：程序不得输出"任务已失效"的**结论**，只附状态差量。

### R2｜convergence_decide 回执附机械事实三件套（←P2/P8）
工具**回执**（非输入，避免模型代写）固定附加：
1. **run vitals**：本次任务起算的轮数/墙钟/累计 tokens（source：request.usage 既有数据）；
2. **自身历史镜像**：前 K=3 次 convergence_decide 的 unresolved 节选（各 ≤200 chars，逐字，不做相似度计算）——模型看见"我在写同一件事的第 4 遍"即自识别循环，语义判断留给模型；
3. **队列压力**：`interject_received` 计数与最早一条时间。

### R3｜任务源消息压缩豁免（←P3）
- 任务进行中（run 活跃且未终态），其**起源消息**（wake prompt / 最近一条 human 指令）作为压缩豁免位固定在工作面（cap=1 条，仅当前任务；前序任务源照常 archive）。
- 与既有机制的关系：不动 `history_anchors`（缓存锚）；不动 recent-pairs 窗口；是对"exact source 已存档但不再可见"缺口的保真回注，符合 Q2 可恢复性契约。

### R4｜插话轮边界强制可见（←P4）
- 每轮工具循环边界检查 `interject_received`：非空即以用户消息进入下一轮上下文（现机制已保证 turn 边界投递，缺的是 run 长轮下的可见时点）。程序只搬运用户消息，不裁决打断时机；模型收到后自行决定收尾或转向。
- R2 的队列压力事实与本项互补：一个让模型"知道有人在等"，一个保证"下一轮必然听见"。

### R5｜wake 子任务会话分叉协议（←P7）
- 不改代码先立协议：wake 驱动的独立验证/巡检类子任务，排程时指向**分叉会话**（branch 机制既有），父会话只留结论摘要。降低单会话 context rot 与压缩频次。
- 可选后续：schedule 工具在 `wake=true` 且目标为同会话时提示分叉选项（提示非强制）。

### R6｜reconcile 复活携带中断事实（←P5）
- post-crash reconcile 复活 run 时，若死亡窗口内发生过 service-control restart（barrier/动作记录可查），在复活上下文附"`run 因共享服务重启中断于 16:07`"事实行。模型可据此决定放弃或续跑，而非默认续跑。

### 明确不做（本轮否决项）

- **变体重复阻断 enforce**：见拷问 E——对本事故类无效且属语义机械。
- **新增 run 硬轮次/时长上限**：见拷问 F——`max_iterations` 边界既有，收紧会误杀合法长任务。
- **近似重复的语义相似度计算**：程序不做语义（守则 Q5）。

## 5. 设计裁决记录（拷问 A–H）

| 疑点 | 拷问 | 裁决 |
|---|---|---|
| A | R2 让程序评价 unresolved"相似"了吗？ | 否。只逐字镜像前 K 次，相似性识别由模型完成；程序零语义。附带收益：F8 的"自写自批"结构被打破——判定输入有了独立事实源 |
| B | R4 会不会打断即将收尾的工作？ | 打断者是用户消息本身，程序只保证下一轮可见；是否转向由模型判断。用户指令优先是仓库既有原则 |
| C | R1 的"对象消亡"由谁定义？ | 不定义。subject_refs 由模型排程时结构化自报；程序只报状态差量（job 终态/generation delta）。不自报 refs 的任务退化为现状行为，非破坏性 |
| D | R3 锚会不会撑爆上下文/永久滞留？ | cap=1 条、仅活跃任务、典型 ≤300 chars；任务终态即失去豁免。与 fixed_summary 分工：摘要管长期，豁免位管"正在做的这件事的原文" |
| E | 变体重复 enforce 能否止血？ | **否决**。本事故每次调用参数皆异（F1），近似重复检测需要语义相似度=程序越权；且对"每次都新的探索"根本无重复可拦。保留 shadow 观测，仅当未来口径（P8）证明高误伤率低再议 |
| F | 加轮次/时长硬上限？ | **否决**。terminate.max_iterations 既有（F10）；收紧上限会杀死合法小时级任务（本仓库常态）。改供 run vitals 事实（R2），让模型自限 |
| G | reconcile 该不该自动复活？ | 不改复活策略（真崩溃恢复价值更高），但复活必须携带中断事实（R6）；结合 R1 的 subject 现状，模型复活首轮即可自行了断 |
| H | 是否与 CR-R1 cognitive/Decision Packet 重复建设？ | 否。cognitive 管决策包编译/遥测（shadow）；本包管**任务生命周期事实的可供性**。R2 的 vitals 若未来进 Decision Packet，则作为其输入源合并，实现时对齐 telemetry 归因字段即可 |

## 6. 治理对照（准入不对称审计）

| 项 | 性质 | 依据 |
|---|---|---|
| R1/R2/R6 | 事实可供性（agency 放大） | 默认准入；无新增门 |
| R3 | 保真回注（可恢复性） | Q2 契约的直接延伸 |
| R4 | 用户通道修复 | 只搬运用户消息，无程序裁决 |
| R5 | 使用协议 + 可选提示 | 零强制 |
| 否决项 | control machinery | 均已在 §5 说明"为何模型+现有工具不能自判"不成立 |

## 7. 验收清单（实现时逐项落测）

- [ ] R1：排程带 subject_refs → 对象终态/generation 前移后，唤醒消息含事实段；无 refs 行为不变（回归）
- [ ] R2：回执含 vitals/前 K 次镜像/插话计数；镜像逐字无相似度计算（代码审查项）；K 与截断上限生效
- [ ] R3：压缩后工作面仍含活跃任务起源消息逐字原文；任务终态后豁免解除；cap=1
- [ ] R4：长 run 中入队插话 ≤1 轮内进入上下文；无插话零变化（回归）
- [ ] R5：协议文档化；schedule 提示为非强制
- [ ] R6：restart 窗口内死亡 → 复活上下文含中断事实行；正常崩溃路径无变化（回归）
- [ ] 端到端重演：模拟"任务对象被取代 + 变体探索"场景，convergence_decide 在事实注入后 ≤2 轮给出终止/转向决策（对照：现状无限 continue）
- [ ] 全量单测 + 既有 stagnation/duplicate 口径测试零回归

## 8. 实施顺序与回滚

**顺序**：R0（运维，即时）→ R2（纯回执附加，最小侵入）→ R4（通道）→ R1+R6（subject 事实族，同批）→ R3（压缩豁免，动 history 管线需独立资格验证）→ R5（协议）。每项独立 commit + focused gate，红绿先行（先写失败不变量）。

**回滚**：R1/R2/R6 为纯附加事实，删除即回退；R3 豁免位关闭即回退；R4 关闭检查点即回退。无状态迁移，单向安全。

## 9. 残余边界（有意接受）

1. 不自报 subject_refs 的任务，对象消亡仍不可见（R1 依赖排程时自报；协议教育 + schedule 提示逐步覆盖）。
2. 变体探索本身不设机械阻断——接受"事实供给后仍由模型判断"的残余风险，换取不越语义红线。
3. 长寿命操作员会话的彻底治理（分叉协议的强制化）超出本包，先以 R5 协议收敛习惯。
4. wake 所有权时延（P6）未单列修复项：直连启动被 S3/S4 收敛为受控通道后，owner 死亡窗口已大幅缩小；留观。
