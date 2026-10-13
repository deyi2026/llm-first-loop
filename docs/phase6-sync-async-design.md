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

## 9. M1 实施修订记录（2026-10-13，TDD red→green）

评审回填断言落地（`tests/phase6/test_m1_sync_interrupt.py` S1-S9；red 证据：
撤除 engine 同步分支改动后 S1/S2/S6/S7/S8/S9 六项失败，恢复后 10 passed）：

- **共享路径改动列明（§4.6 披露义务）**：共享收割分支 `via="llm_stream_interrupt"`
  改为 `via=_interrupt_via`（默认值不变，仅同步分支轮内改置 `sync_window_poll`）。
  流式通道行为零变化（默认值路径等价）。
- **R6 实现缺陷修复**：初版 worker 完成分支直接 break，插话检查受 40ms 节流跳过时
  worker 完成可抢占已 pending 的窗口内插话（违反 §8.6 命中优先）。修复：完成检测点
  补一次**无节流终检**，窗口内插话仍可见即打断，晚到完整响应按打断轮丢弃。
  S9 以「插话仅在 worker 完成后可见」的确定性构造锁定该语义。
- **R1 断言口径**：测试注入记录型 SpyCallCoordinator，断言打断轮恰好一次
  INTERRUPTED 结算、每 call 单次结算、下一轮正常 success；journal 幂等守卫
  （同 outcome 幂等/异 outcome 报冲突）由资源层既有实现保证。
- **R5 断言**：工具轮窗口打断，响应含 tool_calls 也不执行（spy tool 零调用），
  下一轮仅消费插话。
- **S3 配置门**：`sync_chat_interject_checkpoint=False` 回退 final_gate 窗口形态
  （m0 基线测试同步改为关闸断言回退路径）。
- **peek fail-open 一致性（全量回归发现）**：窗口轮询对 `interjections_pending`
  的调用遵守 Phase4 §4.4 保守降级契约（peek 失败不收割、不冒泡），收敛为
  `_sync_interjection_peek`（test_d 锁定；裸调会把诊断管道故障升级为 run 级
  error，违反零语义降级红线）。观测走 per-window 至多一条 warning（40ms
  轮询频率下逐次告警会刷屏）。
- **既有语义目标测试的关闸适配**：注入时点落在同步 LLM 窗口内、且断言旧
  边界语义的测试（phase3 CBF 结算边界、phase4 序列头收割），显式
  `sync_chat_interject_checkpoint=False` 保留其机制测试原意；旧边界仍服务
  晚到插话与关闸回退。phase4 gap 收割（test_b）注入在工具执行期，与窗口
- **test_b 时序敏感（预存脆弱性，M1 收窄余量）**：phase4 gap 收割测试注入在
  工具执行期（与 LLM 窗口无关），不适配关闸；但其 0.74s/0.8s 的 ~40ms 注入
  余量为预存脆弱面，M1 每轮线程化开销（spawn/join + 轮询粒度）进一步收窄，
  偶发 miss 时插话改由下一合法边界消费（窗口轮询/final_gate），0-skip 形态
  断言翻面。无语义损伤（消费/模型可见/终态均正确）；HEAD 3/3 过、带改动
  单跑与文件级跑多数过、重载下偶发失败。M4 承接：加固其注入锚点或标注
  known-flake。
- **m3 桶归属断言更新**：phase4 `llm_stream` 桶（同步 LLM 窗口内注入）归属
  从 final_gate 更新为 sync_window_poll——该测试断言的是"构造↔归属机械
  一致"，新归属即当前默认真相（§5.6 T1 度量依据）；final_gate 归属保留
  给晚到插话与关闸回退（S3/m0 基线关闸断言覆盖）。
- **发现未修（M1 边界外）→ 已处置（遗留处置 L1，2026-10-13）**：Phase5 流式
  检查点对 `interjections_pending` 的裸调（peek 故障冒泡 run error）已修复：
  `_sync_interjection_peek` 通用化改名为 `_interjection_peek`（新增 `where`
  通道标注：sync_window / llm_stream，供分桶诊断），流式检查点调用点替换
  （同 §4.4 保守降级；正常路径零变化）。red→green 锁定：
  `tests/phase6/test_m4_stream_peek_failopen.py`（裸调版 failed=run error
  冒泡 / 修复版 passed；构造复刻 S17-M1，`_boom` 替换 peek，断言 done、
  consumed_via=final_gate、无半截行、续跑轮含插话、终答=续跑完整响应）。
  审查：专门代码审查子 agent approve_with_comments，blocking（测试断言⑤
  假红：终答为续跑轮响应而非第一轮流文本）与 4 项 comment（warning 通道
  误标、双编号溯源、rename 注记、行号漂移）全部采纳。

## 10. M2 实施修订记录（web client 协作取消，2026-10-13）

- **取消事件归属**：`DeepSeekWebPageTransport` / `ChatGPTWebPageTransport`
  各持一个 `threading.Event`；`exchange` 开始清零（取消只作用在途轮次，
  不预取消未来轮次——无在途轮次时 cancel 为无害 no-op）；engine 经
  client→_ThreadBound→_SurfaceOwned→页面 transport 三层 fail-open 委托
  置位。Event.set 线程安全、不上 executor、不触碰 Playwright 对象。
- **早退点**：页面 adapter 的 send 确认循环与 assistant 等待循环顶部检查
  事件 → 抛 `DeepSeekPageCancelledError` / `PageCancelledError`（契约错误
  子类，语义=引擎主动取消而非页面契约破裂）；engine M1 worker 将其按打断
  轮丢弃，guard 随线程退出释放（W3 断言取消后第二次 chat 不阻塞）。
- **停止按钮释放必须在页面线程**：点击不能从 engine 线程发起
  （Playwright 对象线程绑定；executor 正被阻塞的 exchange 占用）——由
  等待循环在看到取消事件后自行 best-effort 点击再抛出（W1/W4 断言点击
  发生）。
- **停止按钮建模（best-effort，不设门）**：deepseek `stop_button_count`
  从硬编码 0 改为选择器探测（aria-label 停止/Stop，失败记 0，不猜 DOM）；
  ChatGPT 复用既有 `STOP_BUTTON="停止"` 契约常量。环境可行性未证，真机
  验证留 M3 抽查。
- **测试**：tests/phase6/test_m2_web_cancel.py W1-W4（无真机浏览器）：
  W1 等待循环早退+释放点击；W2 transport.cancel() 置位的事件即 adapter
  收到的同一对象（exchange 即刻取消结束）；W3 client 全链委托+guard 释放
  （第二次 chat 不阻塞）；W4 chatgpt 镜像。受影响面回归：phase6 14 +
  deepseek/chatgpt web 单测 362 全绿。
