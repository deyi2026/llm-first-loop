# Learning 队列簇接管/废弃判定 — GOAL-20260927-* 家族（2026-11-05）

## 0. 结论速览

- 家族成员 **11** 个（委派预估 9，实际按"id 前缀 ∪ session 38748744"筛出 11）：
  9 个 active（同 session 38748744，2026-09-27 17:25–18:08 间 43 分钟连续创建，各 0 checkpoint）+ 2 个已 complete。
- open task 实测 **15** 个（委派预估 23，以台账实测为准）：9 个 active goal 名下 2+3+0+1+1+2+3+2+1。
- 四选一建议计数：**close-complete 9 / 已完成无需处理 2 / takeover 0 / close-failed 0 / keep 0**。
- 无活动时长：最后 touch 2026-09-27 18:08 → 2026-11-05，39 天，与委派一致。

## 1. 方法与纪律说明

- 输入：data/audit/goals.jsonl（243 行，按 id 取末条快照）、data/audit/tasks/GOAL-*.jsonl（append-only，按 task_id 取末条）、git 历史、现网运行态（data/sessions/learning/journal.jsonl、data/methods/、runtime.toml）。
- 全程只读；唯一写入为本文档。
- **护栏偏离记录**：委派要求解析脚本落盘 .tmp-ci/verify_d.py，但本会话写域护栏拒绝该路径（回执：write_target_not_in_allow_list: .tmp-ci；tmp/、artifacts/ 探测同被拒）。按"护栏优先于委派、不得据此扩权"原则，改用 python3 -c（argv 传码，非 heredoc，零写入）完成同等解析，遵守"禁止 heredoc 直交解释器"的字面与精神。
- 方法论检索：本会话工具集无 search_records，不适用，直接开始。

## 2. 家族全景

| goal | 状态 | task(open/total) | 最后更新 | objective 摘要 |
|---|---|---|---|---|
| GOAL-20260927-0f483854 | active | 2/2 | 09-27 18:05 | Learning 排队根因修复 + Web 输入限制预处理与无缝续接 |
| GOAL-20260927-0f5da3b6 | active | 3/3 | 09-27 17:57 | 同双主题 + 集成验证与发布（003 pending） |
| GOAL-20260927-3da90549 | active | 0/0（无 task 文件） | 09-27 17:25 | Feishu/Learning 重启后闭环核验、量化定位积压原因、形成修复计划 |
| GOAL-20260927-591274ad | active | 1/1 | 09-27 17:34 | Learning 只入队不学习/不产 Method；验证能否路由 chatgpt-web |
| GOAL-20260927-5a3c6190 | active | 1/1 | 09-27 17:41 | learning_model override 失效 + 队头阻塞 + 有界失败/跳过生命周期 |
| GOAL-20260927-5e48bcee | active | 2/2 | 09-27 18:08 | Learning 排队 + Web 临界上下文主动续接 |
| GOAL-20260927-8f628b41 | active | 3/3 | 09-27 18:04 | 双主题 + 连续执行链端到端验证（003 pending） |
| GOAL-20260927-9241eb09 | active | 2/2 | 09-27 17:55 | 双主题（150000 字符边界前置续接） |
| GOAL-20260927-d7306611 | active | 1/1 | 09-27 17:37 | learning_model override/路由失效 + 队头阻塞根因 |
| GOAL-20260927-d256f921 | **complete** | 0/3 done | 09-27 17:08 | WebGPT 超限链路证据收口（Web-only） |
| GOAL-20260927-9da9eab9 | **complete** | 0/0 | 09-27 21:08 | 接续收口 ProgressCard + 150k ingress 长运行连续性（异 session 265aec26，仅 id 前缀命中） |

9 个 active goal 为同一意图在重启循环下的重复立项（43 分钟 9 个，个个 0 checkpoint），d256f921/9da9eab9 是当晚真正执行收口的两条线。

## 3. 取代证据链（判定共用底座）

### 3.1 Learning 侧（9 个 active goal 的共同前半主题）
- 75542d05e（09-23 09:45）fix(learning): 学习通道隔离三件套——workspace 冲突根因 + 失败退避 + 独立模型（先于簇，铺垫）。
- **43fa70151（09-28 07:34，簇创建次日）fix(learning): terminalize unresolvable jobs + govern LEARNING_MODEL**——提交信息原文即簇内诊断类目标的量化答案："ValueError from registry.resolve ... instead of fail-open yield-remaining at the head of runnable_jobs, which starved 29 healthy jobs behind 22 legacy dead jobs for a day"；修复 = model_unresolved 终态化（取消队头饿死）+ ("learning","model") 到 LEARNING_MODEL 的解析链接通（resolver → dotenv → Settings → LearningPlane(model_override)），82 项测试通过。
- 现网配置：runtime.toml [learning] model = "glm/glm-5.3" + independent_cloud_hosts；60940d6fe（10-30）回执"feishu/learning 已生效"。
- 后续加固：f16d844cc（10-13 队列阻塞显化）、5535474a1（10-13 解云学习准入）、c417621c0 与 672c1e3b6（10-14/15 删除会话终态化、免重试）。
- **现网运行态（2026-11-05 实测）**：data/sessions/learning/journal.jsonl 共 4024 个 job，per-job 末事件分布 **saved 3200 / none 503 / failed 293 / cancelled 28，open（queued/admitted/started/requeued）= 0**；最新 saved 事件 **11-05 22:55（当日）**。data/methods/ 1867 项，11-03 入库 95 张 METHOD.md（30e9d2b6c）、11-04 入库 5 张 method 卡（408f7e37c）→ "队列持续消费"与"Method candidate 恢复增长"两条验收已被运行态直接满足。

### 3.2 Web 预触顶续接侧（5 个双主题 goal 的后半主题）
- 簇创建当日更早：961b9135f（09-27 15:08 guard browser ingress size，150K preflight）+ 222b873d8（15:16 preserve context on ingress overflow）；d256f921（complete 17:08）checkpoint 已收口该链并划定不变量（150K guard、单次 deterministic rebuild、二次超限终态）。
- **簇创建当晚：49a85d52f（09-27 19:48）fix(web): preserve long-run continuity at ingress limit**——新增 src/llm_loop/core/longrun_continuity.py（213 行：程序持有的精确读身份/Evidence refs/Goal-Task frontier 续接锚点，即"续接不重新搜索/不重读"的机制化）+ engine/tool_cycle 接线 + 218 行专项测试（tests/unit/test_longrun_continuity.py）；29ef090fd（22:49 enforce exact ingress convergence）。
- 收口验证：GOAL-20260927-9da9eab9（complete，21:08）checkpoint：gen 141 运行于 49a85d52f，后端 94 项 + WebUI 252 项测试通过，Playwright 实测通过；ProgressCard（88bac1861 live task progress）提供用户可见反馈。
- 配套（更早）：60f8b75d4（排队人类轮次 durable 且不重放）、29cc8637d（排队恢复语义服务端化）覆盖"active ingress/未完成协议不丢失、恢复后自动继续"。

## 4. 逐 goal 判定

### GOAL-20260927-0f483854 — **close-complete**
- TASK-001（诊断并消除 Learning 排队瓶颈）：被 §3.1 取代——根因（队头 model_unresolved 饿死）已由 43fa70151 定位并修复；"无同因自旋"由现网 0 open + 293 failed/28 cancelled 全部终态化佐证。
- TASK-002（Web 输入限制预处理与无缝续接）：被 §3.2 取代——preflight（961b9135f）+ 续接锚点（49a85d52f longrun_continuity）+ 反馈（ProgressCard）+ 二次超限终态（d256f921 收口的不变量）齐备，专项测试 218 行。
- 残留：见 §6 风险 R1。

### GOAL-20260927-0f5da3b6 — **close-complete**
- TASK-001/002 同上；TASK-003（集成验证与发布/重启/版本对齐）：后续体系已远超该验收——60940d6fe/587eaa2f9 服务代际回执（feishu+learning confirmed_ok）、10 月全量 R9 回执族（ec777b0ef 等）。

### GOAL-20260927-3da90549 — **close-complete**（最易：无 task 文件，纯台账关停）
- 诊断型目标（量化定位+形成计划）；其答案已由 43fa70151 提交信息直接给出（29 healthy vs 22 dead、根因链、修复与测试），且 10 月 RESULT/RECEIPT 族（docs/results/RESULT-20261016-learning-*.md 等）持续固化核验。

### GOAL-20260927-591274ad — **close-complete**（字面假设被更优设计取代，验收意图达成）
- "learning 能否正确选择 chatgpt-web/web-gpt"这一手段性假设，被设计决策否定：学习通道改用独立云端模型（75542d05e 独立模型隔离 + runtime.toml [learning] glm-5.3），本 goal 的 TASK-001 验收自己就写明"避免误把 Web transport 直接接入普通 ModelRegistry"。
- 验收意图（队列被消费、Reflection 执行、Method 产出恢复）由 §3.1 现网证据满足。

### GOAL-20260927-5a3c6190 — **close-complete**
- learning_model 生效：43fa70151 解析链接通 + runtime.toml [learning] 现网生效；队头阻塞：同提交终态化；"有界失败/跳过生命周期"：mark_failed/cancelled(reason) 终态面（现网 293+28）即其实现。

### GOAL-20260927-5e48bcee — **close-complete**
- TASK-001 同 §3.1；TASK-002（临界上下文主动续接：durable 锚点、避免重读、可恢复状态、验证）逐条对位 longrun_continuity.py（读身份锚点/Goal-Task frontier/有界 wire 投影）+ 218 行测试。

### GOAL-20260927-8f628b41 — **close-complete**
- TASK-001/002 同上；TASK-003（端到端互不回归）：无单独联合 E2E，但 10 月全量 R9（ec777b0ef xdist serial-fallback 等）与 scoped regression 回执（aacef9336）覆盖回归面。按"能力已落地+回归已过"判 complete。

### GOAL-20260927-9241eb09 — **close-complete**
- TASK-001 同 §3.1；TASK-002（150000 字符边界前置续接：预警阈值/极限/二次超限/恢复续接/信息不丢）逐项由 961b9135f + 222b873d8 + 49a85d52f + 29ef090fd 与 d256f921 收口的不变量覆盖。

### GOAL-20260927-d7306611 — **close-complete**
- 与 5a3c6190 同根因同修复（43fa70151）；"确认 override 生效"由 runtime.toml [learning] + 60940d6fe 回执满足。

### GOAL-20260927-d256f921 — **无需处理（已 complete，本次复核证据成立）**
- 3 个 task 全 done，checkpoint（17:03）与 git（961b9135f/222b873d8）一致。

### GOAL-20260927-9da9eab9 — **无需处理（已 complete；它正是取代本簇 open task 的执行载体）**
- gen 141@49a85d52f、94+252 测试、Playwright 验证（checkpoint 21:08）。

## 5. 执行顺序（先易后难）与总量估算

1. 3da90549（无 task 文件，一次台账关停）。
2. 单 task Learning 型：d7306611 → 5a3c6190 → 591274ad（同一条 43fa70151 证据链复用）。
3. 双主题五连：0f483854 / 0f5da3b6 / 5e48bcee / 8f628b41 / 9241eb09（§3.1+§3.2 证据链打包引用）。
4. d256f921/9da9eab9 不动作。
- 写入面：9 次 goal close-complete + 15 个 open task 置 superseded/cancelled（evidence_refs 指向本档与 43fa70151/49a85d52f/journal 实测），无代码改动；单会话（约 1–2 小时代理时间）可完成。
- 关停时统一附一句备注：续接诉求见 §6-R1，防信息随簇消失。

## 6. 风险（误关有价值目标的代价）

- **R1 主动预触顶的强读未单独立项**：已落地的是"触顶 preflight + 压力终止后 continuity 锚点 + 可见反馈"；若用户原意是"接近限制前提前主动压缩请求"（预警阈值驱动的 preemptive compaction），git 无对应 web ingress 提交（预警类命中均为 context budget/轮数预警，非 web ingress），则簇内目标是该诉求最早表达处。**缓解**：关闭备注中登记"如需预触顶主动压缩请另立新 goal"，诉求不随簇蒸发。误关代价：低-中（诉求可低成本重建，且有本文档存档）。
- **R2 "0 open" 或为消费停滞而非消费畅快**：反驳证据——最新 saved 11-05 22:55（当日）、11-03/11-04 连续入库 95+5 张卡，产出流活跃，非停滞。
- **R3 591274ad 字面假设（learning→web-gpt 路由）从未实现**：按意图判 complete 已注明；若未来想让 learning 复用 web 通道省成本，需推翻 75542d05e 隔离决策，属新决策非本簇遗留。
- **R4 委派估算偏差**：open task 23 vs 实测 15、goal 9 vs 11（多出 2 个已 complete）；按实测执行，避免按 23 个虚构工作量。
