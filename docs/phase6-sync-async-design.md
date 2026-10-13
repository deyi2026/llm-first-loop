# Phase6 设计方案书：同步 chat 通道异步化

- Goal: GOAL-20261013-35007287
- 日期: 2026-10-13
- 状态: M0 设计（评审已过，见 §8）
- 前序: Phase4（生效时延优化，GOAL-20261013-9b1fa766 已交付）→ Phase5（LLM 流内插话打断，已交付 gen251）

## 1. 问题与动机

Phase5 使 `chat_stream` 通道获得流内检查点打断（真机 t_effect=93ms）。但无 `chat_stream`
的客户端走 engine 同步分支（`engine.py` L1893+）：

- `foreground_task_provider_chat` 内联阻塞调用（`provider_calls.py` L493-533，lease 内直接 `call(**kwargs)`），
  窗口内无任何 Stop/插话检查点；
- 插话只能等 final_gate（`engine.py` L2452，无工具回复的结算边界）收割；
- Stop 只能在调用返回后被观察（`engine.py` L1940 `_background_cancel_reason`）。

**生产真实影响**：
- `DeepSeekWebModelClient` / `ChatGPTWebModelClient` 仅实现 `.chat()`（无 `chat_stream`），
  经 `ModelClientPool.external_client_factories` 注入（`factory.py` L532-558）；
- `.env` 中 `DEEPSEEK_WEB_ENABLED=1`（活跃通道）；
- 其 transport 为 Playwright 页面自动化（`deepseek_transport.py` L60 `DeepSeekWebPageTransport`，
  L170+ `exchange` 阻塞轮询等待，L14 `turn_timeout_s=120`）——单窗口可达 120s；
- 页面层无生成级停止能力（`deepseek_surface.py` L225 的 stop 仅 Playwright 会话收尾；
  `deepseek_page.py` L262 `stop_button_count=0` 硬编码）；
- 客户端 guard 锁串行化 exchange（`deepseek_web.py` L160 `with self._guard`），页面状态粘滞。

真实 LLMClient（HTTP）恒有 `chat_stream`，不受影响——本 phase 只改同步通道。

## 2. M0 基线实测（reports/phase6/m0/BASELINE.json）

复用 Phase4/5 度量骨架（FakeLLM callable 响应项模拟阻塞窗口 window=1.2s，t+0.3s 注入/取消，n=5）：

| 场景 | P50 | 形态 |
|---|---|---|
| B1 同步通道窗口内插话 | **859.3ms**（845.8-883.4） | 窗口形态，consumed_via=final_gate×5 |
| B2 同步通道窗口内 Stop | **915.3ms**（910.2-922.7） | 取消仅在 chat 返回后观察 |
| （对照）Phase5 G1 流式检查点 | 3.7ms | 检查点形态 |

窗口形态随真实 web 窗口线性放大（上界 120s）。断言基线形态（>700ms）已入库
（`tests/phase6/test_m0_baseline.py`）。

## 3. 路线选型

### A. 引擎级工作线程 + 检查点轮询 + 协作取消（核心，选定）
同步分支将 provider 调用移入 worker 线程；run 线程以 ~40ms 轮询
`_background_cancel_reason` + `interjections_pending`。命中时：

- **插话命中**：即时置 received/consumed（t_effect 收益点）→ 请求取消 → 等待 worker 结束
  （有取消支持的 client 快速返回；无支持者等残余窗口，等价于 guard 语义，页面安全）→
  当前 provider call 以 INTERRUPTED 结算（Phase5 M2 同口径）→ 下一轮消费全部插话
  （含批量）→ 正常续跑。
- **Stop 命中**：请求取消 → 以 `_CANCELLED_ANSWER` 结算并发出终态事件，不等待 worker
  （daemon 化，残余调用后台自然结束，FakeLLM sleep 无害，web 残余 turn 后台完成）。

取消协议：探测 client 对象的 `cancel()` 协作钩子（`getattr(client, "cancel", None)`，
与 Phase5 探测 `chat_stream` 同风格）。无钩子 → 退化为「检测即时 + 残余等待」，
语义安全、收益保留消费时延部分。

### B. 传输层取消（web client 分阶段增强，M2 承接）
`DeepSeekWebModelClient`/`ChatGPTWebModelClient` 实现 `cancel()`：transport 等待循环
加取消事件早退。页面仍生成完毕（input 期间被禁用、guard 保证下一 exchange 安全）。
**点击页面停止按钮释放页面**（需 deepseek_page 停止按钮建模，现为硬编码 0）作为
真机 best-effort 增强目标，不设门（环境可行性未证）。

### C. DOM 流式轮询 chat_stream（否决）
给 web client 造 chat_stream 需重构 request/response 形 transport 与页面增量契约，
工作量与风险远超收益；且引擎级 A 已覆盖消费时延目标。

## 4. 关键语义决策

1. **打断的轮次内容不投递**：插话打断命中后，即使后台调用完成，其文本不入会话终答，
   与流式打断丢弃剩余 delta 同口径；轮次记录 llm_interrupted 语义（P1-6 退役纪律：
   不进下一轮 provider 投影）。
2. **usage/reasoning 不完整归集**：打断轮未完成调用 → 按打断固有口径
   （Phase5 交付报告 §4 已定，P2-3 同源），不新增补收。
3. **Stop 四态不变**：用户取消在途=终态 0 字节 0 工具、已停止不再派生等四态断言沿用
   Phase4 口径，仅时延变化。
4. **残余窗口语义（web 通道，无停止按钮时）**：打断后下一轮 provider 调用在 guard 上
   等待残余 turn——诚实记录为「消费即时、续答受残余窗口约束」，不做假即时。
5. **多插话批量**：窗口内多插话全量消费（P1-3 同口径）。
6. **chat_stream 通道零改动**：引擎改动限定在同步分支内部（L1893-1942），共享改动
   （若有）需在本设计评审记录列明。

## 5. 验收门（M3 依此实测）

| 门 | 指标 | 基线 | 门值 | 说明 |
|---|---|---|---|---|
| T1 | 同步通道窗口内插话 t_effect P50 / P95 | 859.3ms | ≤100ms / ≤200ms | consumed_via 新口径 sync_window_poll；窗口=1.2s fake，t+0.3s 注入 |
| T2 | 同步通道窗口内 Stop 生效（cancel→终态事件）P50 | 915.3ms | ≤100ms | 四态语义断言同步通过 |
| T3 | 零语义降级 | — | 全量回归 0 failed；流式 G1 场景不回归；打断轮不进下一轮 provider 投影（断言）；guard 无死锁（打断后立即续发）；四态断言通过 | |

真机抽查（deepseek-web 可用时）：真实窗口内插话/Stop 的 t_effect 回填交付报告；
停止按钮点击为 best-effort，不设门。

## 6. 里程碑

- M0 现状调查 + 本设计 + 基线实测 ✅（本文档）
- M1 引擎侧：worker 线程 + 轮询 + 取消协议 + INTERRUPTED 结算 + Stop 即时终态（TDD red→green）
- M2 web client 侧：cancel() 协作钩子（transport 等待早退）+ 停止按钮建模 best-effort
- M3 度量验收 T1/T2/T3（对照基线）
- M4 全量回归 + 发布 + 交付报告

## 7. 风险与边界

- worker 线程并发面：provider_calls lease 记账线程安全；engine 轮询仅在 run 线程（无新共享写）
- 打断后 FakeLLM 状态：callable 响应项在 calls 列表 append 时已序号定位，后台完成不影响下一轮取数
- 非 Goal：不改 chat_stream 通道行为；不做 C 路线；停止按钮释放页面不设门

## 8. 设计评审记录（M0，2026-10-13）

grill_me 盘问（edge_cases/failure_modes/scale）+ 自查，回填 4 项：

1. **shadow call 双结算竞态**：Stop daemon 化 worker 的晚到结果会尝试再次结算——
   settle 必须幂等（settled 标志守卫），晚到结果仅作 orphan 记录（usage 按打断固有
   不完整口径，不补收）。M1 需专项断言：打断后 provider_call 记录单次结算。
2. **worker 异常/取消钩子异常降级**：worker 内 provider 异常经结果槽传回 run 线程，
   行为与今日内联异常一致；client.cancel() 抛错 → 捕获记日志，退化为残余等待，
   不影响打断语义。
3. **无工具回复的口径变化显式化**：今日 final_gate 将窗口内插话的响应记录为完整轮次
   后续跑；新设计打断丢弃响应、轮次记 llm_interrupted（对齐流式 P1-6 口径）。
   这是**有意的语义对齐**（同步通道与流式通道行为一致），非回归；M1/M2 需断言
   「打断轮不进下一轮 provider 投影」且会话历史含 interrupted 标记。
4. **配置门对称**：新增 `tool_runtime.sync_chat_interject_checkpoint: bool = True`
   （默认开，逃生舱），与 Phase5 `llm_stream_interject_checkpoint` 同模式；
   关闭时回退今日窗口形态（final_gate 保守路径），行为可回滚。
5. **工具轮打断一致性**：窗口内插话命中时即使响应含 tool_calls 也不执行工具、
   整轮打断——与流式检查点打断「剩余 delta 丢弃 + 工具不执行」口径一致。
6. **竞态边界定义**：poll 循环以「worker 完成」或「命中」先到者为准；命中优先
   （即使 worker 已完成，检测到窗口内插话即打断）。worker 先完成且无命中 →
   走既有路径（final_gate 仍适用于晚到插话）。
