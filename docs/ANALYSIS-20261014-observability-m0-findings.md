# 可观测性 M0 现状调查（候选 3，GOAL-20261014-bafe28d5）

- 日期：2026-10-14　任务：五桶 t_effect（interruptible / natural_boundary / llm_stream /
  llm_stream_interrupt / sync_window_poll）从测试期度量升级为运行时可观测面板
- 方法：M0 现状调查（本文件）→ grill_me 设计评审 → 定验收门 → 再实施
- 本文档所有行号均为 2026-10-14 上午当前树实测（git HEAD 0072fbc0c 之后，web-carveout 会话有新提交）

## 1. 数据链路五环（写入 → 持久化 → 聚合 → HTTP → 前端）

### 1.1 写入侧（engine 消费点 → hq 终态戳记）

| 桶 | 写入机制 | 证据 |
|---|---|---|
| interruptible | `mark_interject_received(interrupt_receipt=True)`（本轮回执含打断） | hq L392-393 参数、L411-412 条件置位 |
| natural_boundary | `consumed_via=round_start` 或老数据无戳记（缺省兜底） | hq L397-398 注释、L629-630 else 分支 |
| llm_stream | `consumed_via=final_gate` | hq L625-626 |
| llm_stream_interrupt | `consumed_via=llm_stream_interrupt`（Phase5 M2 流内打断收割） | engine L2419 注释判序说明；hq L621-622 |
| sync_window_poll | `_interrupt_via="sync_window_poll"`（同步窗口轮询两处命中点） | engine L2080、L2094（含 L2089 命中优先无节流终检） |
| （idle，现状第 6 口径） | `consumed_via=gap_harvest` | hq L627-628 |

标记入口为 CAS 形态（hq L387-417 `mark_interject_received`），由 routes.py L2033
`_on_received` 回调装配传入 engine；`applied_at` 为终态上幂等追加（L445+）。

### 1.2 持久化（数据源即面板历史）

- 文件：`{data_dir}/human_turn_queue.json`（hq L31 `QUEUE_FILENAME`）
- 原子写：tempfile + os.replace（`_save` L106+，D2 二分：写失败=definitely_not_committed）
- items 即滚动历史：`compact(keep_n=500)` 保最近 500 条终态（L557-569）；
  时间戳全集 created_at / interject_requested_at / received_at / applied_at /
  consumed_via / interrupt_receipt 均落盘——**趋势数据已天然存在，无需新增采集**。
- 单进程契约：8903 单进程（多实例不跨进程互斥，docstring L58-60）。

### 1.3 聚合（已有雏形，比交接预期更完整）

- `interject_pressure(session_id)` → {count, oldest_enqueued_at}（L514-535，
  DC-1 术语映射口径）；运行时消费：`engine.interjection_pressure_probe`（web/__init__.py
  L435-439 fail-open 注入，CLI/feishu 装配不经此处=不注入）。
- `aggregate_interject_metrics(session_id)`（L581-668）：三口径 t_ack/t_persist/
  t_effect/t_applied + 最近邻序法 P50/P95（n=0→null 不造数）+ 分桶汇总每桶
  n/p50_t_effect/p95_t_effect/insufficient_sample(<5 诚实标注)。
  只统计 interject_received 终态；denied/requeued 不混入。

### 1.4 HTTP 暴露

- `GET /api/v1/chat/queue/metrics?session_id=`（routes.py L2101-2113，Phase3 G2，
  只读零写副作用）。
- 队列项级查询端点（L2086 附近，item 快照含全部时间戳）。

### 1.5 前端消费

- **零**：`grep -rn "queue/metrics" webui/src` 0 命中（2026-10-14 实测）。
  ChatQueue.tsx 有队列 UI，但无任何 metrics 消费。

## 2. 测试期度量现状（对照物，非运行时）

- tests/phase6/test_m3_metrics.py：fake 窗口 1.2s、t+0.3s 注入、n=10；
  T1 门 P50≤100ms / P95≤200ms（实收 29.6/59.5），T2 门 P50≤100ms（实收 30.1）；
  产出 reports/phase6/m3/。**测试直接读 item 时间戳自算（L80），不经 aggregate 分桶**。
- 真机工件（一次性抽查，非持续看板）：reports/phase6/m5/REALPAGE_TEFFECT_v5.json
  （真页面 cancel→错误返回 0.714s、stop 图标 1→0、发送按钮恢复）、
  reports/web-carveout/g4/ROUNDTRIP.json（7.66s 完整往返）。
- 基线：reports/phase6/m0/BASELINE.json（B1=859.3ms / B2=915.3ms 窗口形态）。

## 3. 缺口清单（证据锁定，非推测）

### G1【口径缺陷·中危】sync_window_poll 样本被聚合误归 natural_boundary

aggregate 分桶判序（L621-630）：llm_stream_interrupt → interrupt_receipt →
final_gate → gap_harvest → **else → natural_boundary**。窗口通道样本
consumed_via="sync_window_poll" 且 interrupt_receipt 恒 False（test_m3 L131-132
断言），落入 else。后果：sync 通道运行时样本混入 natural_boundary——**两桶同时失真**
（natural 被污染抬分位数；sync 自身不可见）。
测试未暴露原因：M3 验收直接读时间戳（见 §2），不走 aggregate。
影响面：仅观测口径诚实性，不触任何 Phase6 语义红线（消息必达/四态/单次结算均不经过此函数）。

### G2【暴露缺口】运行时面板前端为零（§1.5）

### G3【视图缺口】单 session 视图：无跨 session 汇总、无时间趋势切片

aggregate 签名按 session_id 逐个查询；数据本身含全局趋势所需全部时间戳（§1.2）。

### G4【口径对齐待裁决】"五桶"全集与聚合现有桶集差一桶

交接/本 Goal 的五桶不含 idle（gap_harvest），聚合现有五桶含 idle 不含
sync_window_poll。设计评审需裁决看板口径全集（6 桶全列 vs 目标 5 桶+idle 折叠）。

### G5【注入面差异】probe 仅 web 装配注入

interjection_pressure_probe 只在 web build_app 路径注入（§1.3）；CLI/feishu
装配下 run 回执段 pressure=unavailable。看板若复用该 probe 需注意口径或改为
直接读 hq。

## 4. M0 结论与下一步

现状 = 数据与聚合雏形已齐（含持久化历史），缺：正确分桶（G1）、面板（G2）、
全局/趋势视图（G3）、口径裁决（G4）。**无需新增采集管道**——最小路径是修 G1 +
聚合视图扩展 + webui 一个只读面板。

下一步：grill_me 设计评审（评审对象：桶口径裁决、视图范围、面板形态、
G1 修法与单测、验收门）；评审后定验收门再实施。

## 5. M0-2 设计评审记录（grill_me 第一层四域 + 盲点裁决，2026-10-14）

第一层四域回答核心（全文盘问见 grill_me 回执）：
- **edge_cases**：输入面=端点 query `session_id`（全局端点新增，空串→422 定死）+
  内部 items（老数据缺戳记已被现有 L603 过滤）；n=0→null 不造数（沿用）。
- **failure_modes**：最坏失败=G1 改错判序→看板口径误导（只读面，零语义损伤）；
  防线=单测逐桶归属锁定；面板拉取失败 fail-open。
- **scale**：keep_n=500 终态滚动=天然护栏；聚合 O(500) ms 级；无缓存需求（YAGNI）。
- **ux**：分桶表+分位数沿用 Phase6 报告既有术语；null→「无样本」≠0ms；
  insufficient_sample 徽标展示。

盲点裁决（B1-B7）：
- **B1 全局端点形态**：选独立端点 `GET /api/v1/chat/queue/metrics/global`。
  不改既有 Phase3 G2 契约（session_id 必填），零既有回归面；合并视图（不做
  per_session 明细，YAGNI）。
- **B2 负时延样本**（时钟回拨/多源时钟）：如实展示不滤，面板不用于达标判定；
  异常计数后续再说。
- **B3 鉴权**：事实——auth gate 中间件仅覆盖 /ui/v2（web/__init__.py L263-265），
  /api/v1 层现状=loopback 信任（auth.py L104-106）+OriginGuard。全局端点与现有
  API 同层，数据仅分位数/计数/时间戳无消息文本；不扩不降鉴权面（加全局 API
  鉴权是独立议题，不进本 Goal）。
- **B4 面板错误态**：拉取失败→区块显示 unavailable（fail-open，不阻塞其它 UI）。
- **B5 趋势窗口**：=最近 500 条终态（L557 compact 上限），面板标注
  「滚动窗口：最近 500 条终态」防误读全历史；按日切片首版不做（窗口内跨度
  有限）。真时间趋势（超 500 条历史）涉及存储扩容决策，列后续里程碑候选。
- **B6 G1 判序位置**：sync_window_poll 分支插在 llm_stream_interrupt 之后、
  interrupt_receipt 之前——精确值（consumed_via）优先于布尔标记
  （interrupt_receipt），与 L621-622 防跨轮残值同理；sync 样本 receipt 恒
  False，先后无行为差，防御性归位。
- **B7/G4 桶口径全集（裁决）**：**6 桶全列**（interruptible / natural_boundary /
  llm_stream / llm_stream_interrupt / sync_window_poll / idle）。理由：消费点
  全集即运行真相；Goal 文字里的「五桶」是 Phase6 主线叙事，idle（gap_harvest）
  是 Phase4 既有口径，折叠反而制造口径含混。

修订后设计（M1 实施蓝本）：
1. G1 修复：aggregate 分桶判序加 sync_window_poll（B6 位置）+ 单测（sync 样本
   独立桶、不落 natural_boundary 专项；既有桶归属回归不变）。
2. 新增全局端点（B1/B3/B5）：6 桶+三口径 P50/P95+`window_terminal_cap:500` 标注；
   空数据 n=0/null 不造数。
3. webui 只读面板：全局视图为主块、当前 session 视图复用既有端点；fail-open
   错误态；null=「无样本」；insufficient_sample 徽标；窗口边界标注；零写操作。
4. 明确不做：engine 写入逻辑、告警、超 500 条历史趋势、API 层鉴权扩展。

## 6. M0-3 验收门（M3 实施验收依此）

| 门 | 指标 | 门值 |
|---|---|---|
| V1 | 聚合口径单测 | 6 桶逐桶构造样本断言归属+n/p50/p95；sync_window_poll 不落 natural_boundary 专项断言；负值样本如实展示不滤 |
| V2 | 端点契约 | global 端点空数据→n=0/p50=null；多 session 合并正确；响应含 window_terminal_cap；既有单 session 端点契约零变化（既有测试绿） |
| V3 | 面板 | webui 测试：6 桶表渲染、null=「无样本」、insufficient_sample 徽标、错误态 fail-open、零写操作调用 |
| V4 | 零语义回归 | pytest 全量 0 failed；Phase6 红线单测（S/W 系列）绿 |
| V5 | 不设门项 | 生产样本充足性不设门——insufficient_sample 诚实标注本身即验收形态，不要求真实流量 n≥5 |

### 5.1 第二轮覆盖验证（2026-10-14）

修订版再提交 grill（depth=2，聚焦 edge_cases/failure_modes）：四域问题均被
第一轮 B1-B7 裁决覆盖（空数据 V2 锁、并发只读锁拷贝 ms 级、鉴权 B3 事实、
最坏失败=口径误导被 V1 逐桶单测锁、fail-open V3），无新盲点。评审闭环。

## 7. M1 实施记录（2026-10-14）

- **M1a G1 修复**（commit c1408d7a7）：aggregate 分桶判序加 sync_window_poll
  分支（B6 位置：llm_stream_interrupt 后、interrupt_receipt 前——精确值
  consumed_via 优先于布尔标记）；red（sync 样本断言独立桶，如实复现误归
  natural_boundary）→green 9 passed；phase4 桶集合断言适配六桶口径
  （Phase5 同款「断言=当前真相」演进）；ruff 0 error。
- **M1b 全局端点**（commit e97a6ec8e）：hq 聚合抽共享行构建器
  `_interject_metric_rows(session_id: str | None)`（单一事实源；rows+sessions
  二元组），单 session 视图零变化（既有测试绿）；新增
  `aggregate_interject_metrics_global()`：scope/session_id=None/n/
  sessions_in_window/window_terminal_cap + 三口径 P50/P95 + 6 桶，无 items
  明细（B1 合并视图 YAGNI）；路由 `GET /api/v1/chat/queue/metrics/global`
  （loopback+OriginGuard 同层鉴权事实，B3 不扩不降）；compact 常量化
  TERMINAL_HISTORY_KEEP_N=500。V2 契约测试（red=import 缺符号→green）
  3 项：空数据 null 不造数/多 session 合并（含 denied 干扰不混入、
  sessions_in_window 不计空 session）/既有端点 422+items 契约零变化。
  影响面：11 passed（M1b×3+M1a×3+phase3-M2×3+phase4-M3×2）+ruff 0。
  实施纪律记录：误用 `ruff format` 全文件重排引入 ~400 行噪声（HEAD 本就
  非 format-clean），已整文件还原+手工回滚 4 个 format-only hunk，最终
  diff routes.py +17/-0、hq 仅逻辑改动。
- **M1c webui 面板**（commit 7997949fc）：侧栏新增「📊 时延」视图
  （SidebarView + tab + 分支）；`InterjectMetricsPanel`：全局块（M1b 端点）
  +当前会话块（复用 Phase3 G2 既有端点，session_id 取 currentId）；
  fail-open（任一源失败仅该块「不可用」，B4）；null=「无样本」≠0ms；
  样本不足徽标（n<5）；窗口脚注「最近 N 条终态（滚动窗口，非全历史）」
  （B5）；零写（仅 GET 两端点）。V3 测试 4 项（红=组件缺→绿）：六桶渲染
  /null/徽标+零写/fail-open 独立性/无会话显式提示/手动刷新。tsc+vite
  build 过；全量 webui 282/282。
- **预存修复（独立提交 d8accba79）**：evolution-panel 测试断言漂移——
  e2ab47980 改批准守卫文案（加「或显式授权执行」）漏同步测试；3/3 复现
  +stash 路径限定 HEAD 复现确认预存后一行对齐，webui 套件恢复全绿。
- **M1d 全量回归+发布**：pytest 全量 **8712 passed / 0 failed**（132 skipped，
  610.6s，2026-10-14T11:3x；对照修复前 8707+5failed 精确对账）+ webui 282/282
  + ruff 0；publish（前端 dist 变更，本 Goal 首次非零前端改动发布）。
- **M1d 附带守卫书补（预存 5 失败修复，独立提交）**：全量首跑暴露 5 个
  非本 Goal 引入的守卫失败——4 处源于 web-carveout M3（6db89d6b5）提交时
  漏同步：factory.py 函数内 import 棘轮 63→64（外部注册模块加载，plugin
  语义补行内豁免标记）、豁免标记登记 5→3（删 2 内置注册标记未同步登记簿
  与断言，收支补记 -2+1=4）、runtime 环 providers↔web_provider_registration
  （真断环：ProviderSpec 条目校验移回所有权侧 providers.finalize，批次语义
  原样保留——known_cycles 登记与 exemptions 两路均被防篡改层封死，断环是
  唯一合规路径）；1 处源于 EVO-20261014-7299aec2（usage_net）：顶层能力文件
  未登记（top_level_units 补 Learning 归属）+ RULE-AI-31 台账漏登（rule-
  presence ledger 补行，锚 33→34）。守卫书补后 test_arch_guards +
  rule_presence 49 passed；providers 影响面 549 passed。
  实施纪律记录：守卫 _read_source 对 unstaged 外部漂移回退读 HEAD——
  修复须 stage 后复验（首验假阴性一次，定位后纠正）。
