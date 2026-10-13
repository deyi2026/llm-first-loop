# Phase6 交付报告：同步 chat 通道异步化

- 日期：2026-10-13　状态：交付（全量回归/发布见 §4/§5）
- 设计：docs/phase6-sync-async-design.md（M0 定稿 + §9/§10 实施修订）
- 前序：Phase4（生效时延，GOAL-20261013-9b1fa766）→ Phase5（流式打断，gen251）

## 1. 问题与结果

无 `chat_stream` 的外部 client（deepseek-web / chatgpt-web，Playwright 页面
transport，单窗口可达 120s）此前走引擎同步内联分支：窗口内插话/Stop 无任何
检查点，只能等 final_gate 或调用返回（m0 基线 B1=859.3ms / B2=915.3ms，
窗口形态随真实 web 窗口线性放大至 120s）。

本 phase 后（M3 实测，fake 窗口 1.2s、t+0.3s 注入/取消、n=10）：

| 门 | 指标 | 基线 | 实测 | 门值 |
|---|---|---|---|---|
| T1 | 窗口内插话 t_effect P50/P95 | 859.3ms | **29.6 / 59.5ms** | ≤100 / ≤200ms |
| T2 | 窗口内 Stop 生效 P50 | 915.3ms | **30.1ms** | ≤100ms |
| T3 | 零语义降级 | — | S/W 单测锁定 + 全量回归 | 0 新增 failed |

## 2. 交付内容

### 2.1 M1 引擎侧（15640062d）
- provider 调用移入 worker 线程（contextvars 拷贝保预算门控等上下文绑定），
  run 线程 40ms 轮询 Stop/插话检查点（`engine.py` 同步分支内）。
- 命中语义：插话 → 即时置 received/consumed（`consumed_via=sync_window_poll`
  新口径）→ INTERRUPTED 结算 → 下一轮全量消费（含批量）；打断轮文本/工具
  调用不进下一轮 provider 投影（P1-6 同口径，S1/S8 锁定）。
- Stop → 协作取消 → `_CANCELLED_ANSWER` 即时终态（不等 worker，daemon 残余
  后台自然结束；settle 幂等由 S7 单次结算断言锁定）。
- 取消协议：探测 client 对象 `cancel()` 钩子（与 Phase5 探测 chat_stream
  同风格）；无钩子 → 检测即时 + 残余等待（guard 语义安全）。
- 竞态边界（§8.6）：worker 完成检测点补无节流终检——命中优先，即使 worker
  已完成、窗口内插话已到即打断（S9 锁定；实现期真缺陷，red 发现修复）。
- peek fail-open：窗口轮询对 `interjections_pending` 的调用遵守 Phase4 §4.4
  保守降级契约（`_sync_interjection_peek`；裸调会把诊断管道故障升级为 run 级
  error，test_d 回归锁定；观测 per-window 至多一条 warning）。
- 配置门：`tool_runtime.sync_chat_interject_checkpoint`（默认开，
  `LFL_SYNC_CHAT_INTERJECT_CHECKPOINT` 逃生舱）；关闭回退内联窗口形态
  （S3 + m0 基线关闸断言）。
- chat_stream 通道零行为改动（共享改动仅 `_interrupt_via` 口径变量，默认值
  保持 llm_stream_interrupt；phase5 G1/G2 场景回归绿）。

### 2.2 M2 web client 侧（36a372c66）
- deepseek/chatgpt 页面 transport 各持取消 Event；exchange 开始清零（取消只
  作用在途轮次）；client.cancel() 三层 fail-open 委托置位（Event.set 线程
  安全，不上 executor、不触碰 Playwright 对象）。
- 页面 adapter send 确认/assistant 等待循环顶部检查事件 → 抛
  `DeepSeekPageCancelledError` / `PageCancelledError`（契约错误子类，语义=
  引擎主动取消）；engine worker 按打断轮丢弃，guard 随线程退出释放
  （W3 断言取消后第二次 chat 不阻塞）。
- 停止按钮释放：**必须由等待循环在页面线程执行**（Playwright 线程绑定），
  best-effort 点击后早退（W1/W4 断言点击发生）。
- 停止按钮建模：deepseek `stop_button_count` 硬编码 0 → 选择器探测（失败
  记 0，不猜 DOM）；chatgpt 复用 `STOP_BUTTON="停止"` 契约常量。
- 无真机浏览器单测 W1-W4（等待早退+释放点击/事件同对象/全链委托+guard
  释放/镜像）。

### 2.3 M3 度量验收（1b37c14bb）
- reports/phase6/m3/：T1/T2/T3 全过（§1 表）；四态之「取消在途=终态 0 字节
  0 工具」逐样本断言；样本明细入库。

## 3. 测试与不变量

- tests/phase6/：m0 基线（关闸守护回退形态）/ m1 S1-S9 / m2 W1-W4 /
  m3 度量，共 15 项。
- 既有断言适配（语义目标为旧边界机制，显式关闸保留原意）：phase3 CBF
  结算边界、phase4 序列头收割、phase4 m0 基线；phase4 m3 `llm_stream` 桶
  归属更新为 sync_window_poll（构造↔归属机械一致的当前真相）。
- 不变量：消息必达（interruptible/自然边界桶回归）、停止四态（S2/T2）、
  P1-6 退役纪律（S1/S8）、单次结算（S7）、guard 无死锁（W3）。
- red→green：M1 主体 6 failed→10 passed（engine 改动 stash 对照）。

## 4. 全量回归

（回填：全量 pytest + ruff 改动面）

## 5. 发布与验证

（回填：publish generation / restart / 真机抽查 best-effort）

## 6. 遗留与候选

- **phase5 流式检查点裸调 peek（预存）**：engine.py L1852 附近
  `interjections_pending` 无 fail-open，同类管道故障会冒泡 run error；
  M1 承诺 chat_stream 通道零改动未修。候选：与 M1 同法收敛。
- **test_b 时序脆弱（预存，M1 收窄余量）**：phase4 gap 收割测试 ~40ms 注入
  余量偶发翻面（无语义损伤，miss 时插话由下一合法边界消费）。候选：加固
  注入锚点或标注 known-flake。
- **停止按钮真机验证**：选择器探测/点击释放的环境可行性未证（W1/W4 为
  fake page 验证）；真机可用时抽查回填。
- **web 通道续答残余窗口**：无停止按钮可用时，打断后下一轮 exchange 在
  guard 上等待残余 turn（设计 §4.4 诚实口径：消费即时、续答受残余窗口
  约束）；M2 页面线程释放点击旨在缩短该残余，真机效果待抽查。
