# Phase5 设计方案书：LLM 流内插话打断 + P2-4 混合路径戳记时序修复（r2 定稿）

- 日期：2026-10-13　状态：r2（评审处置后定稿；评审=独立子代理实读代码，2B/6Q/8C 全处置，映射见 §10）
- 上游：docs/phase4-effect-latency-design.md；docs/phase4-delivery-report.md §5.3（P2-4）/§5.4（llm_stream 桶）
- 阶段目标：① LLM 生成窗口内在途插话（llm_stream 桶 P50 1240.1ms）改为流内检查点打断收割；② 处置 P2-4 混合路径戳记时序。
- 零语义降级（继承 Phase4 §8 全量）：消息必达、停止四态、D 红线、停止即时性、P1-6 断连不伪装完整——全保持。

## 1. 现状与不变量（HEAD 代码事实）

### 1.1 插话消费点拓扑（现六处）
| 消费点 | 触发 | consumed_via | Phase4 桶 |
|---|---|---|---|
| 轮首（轮循环顶部，engine.py:996 一带，at_final_gate=False） | 每轮 LLM 请求前 | round_start | natural_boundary |
| 工具段间 CK-B（registry `_wait_with_interrupt_gate` 分段等待） | 分段等待间隙 | round_start | natural_boundary |
| 工具段间 CK-C 打断收割（tool_cycle M2） | 工具在途被打断 | round_start（interrupt_receipt=True） | interruptible |
| 轮内 gap 收割（tool_cycle.py:547-555） | 分段间隙发现挂起插话+剩余 skipped | gap_harvest | idle |
| 终答前 final gate（engine.py:2376，at_final_gate=True，CBF） | LLM 窗口结束、终答确认前 | final_gate | llm_stream |
| （CK-B/C 收割后落 user 文本的辅助暂存：run_state.interject_harvest_user_texts，tool_cycle.py:913-914；engine 轮内 996 消费点补空取） | | | |

- ack 通道：`InterjectionConsumer.ack()` → `runner.acknowledge_interjection(..., via, interrupt_receipt)`（签名 kw 即 `via`，interjection_consume.py:29-32）→ `hq.mark_interject_received()` CAS；`interrupt_receipt` 取值=消费时 `run_state.last_receipt_interrupted`（interjection_consume.py:132-138，唯一读点）。
- 该标志唯一写点 tool_cycle.py:557（仅工具轮、无复位；run_state per-session）⇒ 除 §1.3 P2-4 外还存在**跨轮残值窗口**（轮首消费读上轮值）——留档 P2-5，M2 处置（§2.2.5）。
- 桶派生：human_turn_queue.py:618-625——interrupt_receipt→interruptible（优先级最高）→ final_gate→llm_stream → gap_harvest→idle → 缺省 natural_boundary。
- 半截产物机制：`InterruptedCapture.fire`（interrupted_capture.py:266，`_fired` 单次防重；轮级实例 engine.py:1726）→ `_on_llm_interrupted`（events.py:1290）落 llm.interrupted 审计+半截行；该行固定 stamp `llm_interrupted=True` 且被 provider 投影退役（events.py:1317/1440；episode_history/recent_continuity/interruption_resume 各投影均退役）——**中断行不进下一轮 LLM 请求历史是既有纪律**。

### 1.2 llm_stream 桶成因
插话在 LLM 生成窗口内在途时，Phase4 不打断流（r1 N8），等流自然结束后终答前 final gate 消费 → t_effect≈流剩余时长（P50 1240.1ms）。流内已有取消检查点（每 delta 后 `_background_cancel_reason`，仅 Stop）；`runner.interjections_pending()`（mailbox peek）现成；cancelled 收口先例=engine.py:2182-2188（settle INTERRUPTED+finalize+break）。

### 1.3 P2-4 时序缺陷（tool_cycle.py:533-560 代码序）
recorded_results 518-533 构建 →（540-545 同步 save，无 yield）→ 547-555 `_consume_gap_interjections` ack **读**标志 → 557-560 **置位**。混合路径（同轮打断+剩余 skipped）下 ack 读上轮残值，双向错桶（True 污染/True 漏标）。

## 2. 设计

### 2.1 M1：P2-4 修复（最小 diff，先行）
把 556-560 注释+置位**整体前移**至 547 `if _gap_skipped:` 之前（即 recorded_results 构建完成、save 之后）。评审代码级核实：前移不开任何交错窗口（读写全集三点；两候选位之间无 yield）；不改 ack 读取、不改戳记语义、不改桶派生。
- 防御回归 S18 双向断言（§4）。
- 跨轮残值窗口（P2-5）超出本修复范围，M2 处置（§2.2.5）。

### 2.2 M2：流式打断
#### 2.2.1 流内插话检查点（engine.py 流内 while 循环）
- 每 delta 后：先 `_background_cancel_reason`（Stop 优先不变），后 `interjections_pending(session_id)`；节流≥40ms（间隔可注入，测试可设 0）。
- 检查位固定：`next(it)` 返回 d 之后、`cap.on_delta(d)` 之前；命中即收割，**该 d 丢弃**（未消费，口径固定不再二选一）。
- 仅 `chat_stream` 分支生效；同步 chat（FakeLLM 缺省/第三方）保守 final_gate 不变。
- **flag 为 run 函数内局部变量**（session 是 dataclass，禁止 sess[...] 写）。

#### 2.2.2 打断收割路径（run 不终止，轮边界收割）
命中后序（对齐 fire→close 先例 engine.py:1799→1802）：
1. `cap.fire(sess, "interjection_interrupted", rounds)`（半截限量落盘）；
2. close stream（同 cancelled 路径 1802-1809 处理 close 异常）；
3. 置局部 flag=True；break 流循环。
流循环后（**统一插在 engine.py:2182 `if cap.cancelled:` 之前**——评审 Q1 核实：插晚会错记 SUCCESS 且 2218 `resp.truncated` AttributeError；engine 无「空响应终止分支」，r1 该句作废）：
4. `_provider_call_coordinator.settle_shadow_call(_provider_call, ProviderCallOutcome.INTERRUPTED)`；
5. `self._tool_cycle._reachability_finalize("interjection_interrupted_provider")`；
6. `_consume_live_interjections(session_id, sess, via="llm_stream_interrupt", at_final_gate=False)`——消费实现需同步把收割的 user 文本并入 `run_state.interject_harvest_user_texts` 暂存（否则下轮 996 补空取丢插话，评审 Q2）；
7. `continue`（rounds 由轮循环顶部 1011 自增，不手动+=1，防双计跳号）。
- 下一轮 LLM 请求历史=既有历史+插话 user 消息。**半截行不进 provider 投影**（对齐 B1 决策：维持既有「中断行退役」纪律，wire 零改动；打断语义由插话消息承载）。
- GeneratorExit 交叠：fire→continue 段无 yield（评审核实），不可交叠；断连路径零改动。

#### 2.2.3 戳记与桶派生（B2 双保险）
- ack 调用点：`via="llm_stream_interrupt"` 时**强制 interrupt_receipt=False**（该消费点无工具回执参与，戳记只记事实）；
- 桶派生：`consumed_via=="llm_stream_interrupt"` 判序**最前**（先于 interrupt_receipt，防跨轮残值劫持新桶样本）；分桶汇总 tuple 与 web hq 视图同步追加。
- 原 llm_stream 桶保留（节流窗内自然结束/同步 chat 保守路径）。

#### 2.2.4 P2-5 轮首复位（并入 M2）
轮循环顶部（LLM 请求前）`run_state.last_receipt_interrupted=False`——语义定死为「**本轮回执**是否含打断」，轮首时本轮无回执。M1 修复覆盖轮内时序，本复位消除跨轮残值；S18-M3 断言跨轮场景。

#### 2.2.5 FakeLLM chat_stream（缺省关闭）
`stream_config={"deltas": [...], "delta_delay_s": ..., "on_delta_n": {...}}`；on_delta_n 支持确定性同步钩子（注入 ack 落盘完成事件后再推进流），消除 Q4 flaky。

### 2.3 运行开关
`LLM_STREAM_INTERJECT_CHECKPOINT`（缺省开）：关闭即回退保守 final_gate 路径（发布异常时配置级回滚，不动代码）。

## 3. 不变量清单（验收红线）
1. 消息必达：只前移消费点；ack/CAS/inbox 排队零变化（评审已核实）。
2. 停止四态：Stop 检查优先/时机零变化；S17-M3 矩阵含「打断已 fire 后 stop 到达」变体（Q6）。
3. D 红线：不动工具链路。
4. P1-6 对齐：半截行必须 `llm_interrupted=True` 标注+内容=已生成部分（不伪装完整）；S17-M2 断言半截行**存在且不进下轮请求历史**（B1 口径）。
5. 保守路径不回归：S17-M4 用**开关关闭**变体测保守真实形态（Q3）。
6. 老数据兼容：无戳记老条目缺省 natural_boundary 不变。
7. 打断轮计量口径（Q5）：打断轮 provider_call settle=INTERRUPTED，usage/reasoning 不完整归集属打断固有（与 cancelled 同口径），报告如实标注。

## 4. 场景规格（tests/phase5/，n≥10）
- S17-M1 打断生效：chat_stream 窗口 on_delta_n 确定性注入（第 3 delta 后注入完成再推进）→ t_effect P50≤500ms、consumed_via=llm_stream_interrupt、hq interrupt_receipt=False。
- S17-M2 半截语义：半截行落盘（llm_interrupted=True、文本=已生成部分）且**不在**下轮 LLM 请求 messages；下轮 messages 含插话 user 文本。
- S17-M3 stop 优先矩阵：①同窗 stop+插话→cancelled 接管；②打断已 fire 后 stop 到达→run 终态 cancelled、审计含 interjection_interrupted 行+cancelled 收口、hq 不误消费。
- S17-M4 保守回归（开关关闭+中途注入）→ final_gate 消费，桶=llm_stream。
- S18-M1 混合路径正向：2 工具，第 1 个 CK-C 打断+剩余 skipped → gap 消费 ack interrupt_receipt=True（本轮事实）。
- S18-M2 残值反向：上轮 True → 本轮纯 gap 收割 → interrupt_receipt=False。
- S18-M3 跨轮复位（P2-5）：上轮 True → 下轮轮首消费（无工具轮）→ interrupt_receipt=False。

## 5. 风险与对策
| 风险 | 对策 |
|---|---|
| 半截行可见性争议（模型不记得半答） | B1 定稿：维持退役纪律；插话 user 消息承载打断语义；真机 M4 抽查续答质量 |
| 每 delta peek 锁开销 | ≥40ms 节流+开关；S17-M1 对照断言流速率无明显劣化 |
| 打断/取消/断连交叠 | 收割段无 yield（不可 GeneratorExit）；S17-M3 双变体；断连路径零改动 |
| 跨轮连续打断无 run 级上限 | 明示：连续打断=用户意图，每轮收割至多一次（flag 保证），风暴由 inbox 排队+用户侧限速承载，不加 run 级上限（C7） |
| FakeLLM chat_stream 破坏存量测试 | 缺省关闭仅 S17 开启 |
| P2-4 前移副作用 | 评审三点读写全集核实空集；Phase4 S13 组回归为准 |

## 6. 实施切分
- M1（先行）：P2-4 前移 + S18-M1/M2 green + Phase4 S13/M2 组回归。
- M2：P2-5 轮首复位 + 流式打断（检查点/收割/via/桶派生/开关）+ FakeLLM chat_stream + S17 组+S18-M3 green。
- M3：度量验收报告 reports/phase5/m3/（§7 门）。
- M4：全量单测+ruff+web 发布验证（真机打断抽查）+ docs/phase5-delivery-report.md。

## 7. 度量门
| 门 | 判定 | 口径 |
|---|---|---|
| G1 打断生效 | llm_stream_interrupt 桶 P50≤500ms、P95≤900ms（n≥10） | 新桶独立统计（判序最前） |
| G2 保守不回归 | 开关关闭变体 llm_stream 桶 P50≤1550ms | S17-M4 构造 |
| G3 语义门 | S17-M2 断言全绿（半截退役纪律） | 结构断言 |
| G4 停止四态 | S17-M3 双变体+Phase4 停止回归组全绿 | 行为断言 |
| G5 P2-4/P2-5 | S18 三场景绿（轮内双向+跨轮复位） | 戳记断言 |
| G6 全量回归 | 全量单测绿+ruff 0 error | CI |

## 8. 非目标
- 不动 Stop 链路/停止四态；不做工具段流式化；不做同步 chat 异步化；
- 不改 CBF/终答门；不改 ack/ingress/inbox 排队语义；
- 不做打断策略分级；不动 injection_span.py:721 / recovery_controller.py:206 既有 chat_stream 面（C6 点名）；
- 不改中断行 provider 投影退役纪律（B1 定稿）。

## 9. 发布与回滚
- 发布：M4 全绿后 service_control publish（单 commit 前置全量回归绿）。
- 回滚：LLM_STREAM_INTERJECT_CHECKPOINT 配置级关闭→保守 final_gate；M1 时序修复无行为面风险。

## 10. 评审处置映射与实施修订记录
- 2026-10-13 r1：初稿。
- 2026-10-13 r2 定稿（评审 2B/6Q/8C 全处置）：
  - B1→§2.2.2/§3.4/§4(S17-M2)：半截行维持退役纪律，断言改「存在且不进下轮历史」；
  - B2→§2.2.3 双保险（新 via 强制 False+桶派生判序最前）+ §2.2.4 P2-5 轮首复位 + S18-M3；
  - Q1→§2.2.2 收割分支插点=2182 前、rounds 顶部自增不手动+1、r1「空响应终止分支」表述作废；Q2→via 直传+harvest 暂存；Q3→S17-M4 开关关闭变体；Q4→on_delta_n 确定性钩子+节流可注入；Q5→§3.7 计量口径声明；Q6→S17-M3 变体②；
  - C1→局部 flag；C2→fire→close 先例序；C3→检查位+丢弃口径固定；C4→采纳（单文件+老数据兼容核实）；C5→§1.1 表重写按代码事实；C6→§8 点名；C7→§5 明示；C8→采纳（M1 先行）。

- 2026-10-13 实施修订（r2 落地后发现，全部有测试锁定）：
  - **§2.2.4 复位位置修订**：轮首复位原定于轮内消费点之前——实施中实测发现
    该消费点（via=round_start）正是 Phase4 M3 interruptible 桶样本的收割路径
    （S13 形态：工具打断后下一轮轮内消费，戳记=读上一轮置位 True，这是
    **特性而非残值**）。复位移至轮内消费点**之后**（rounds+=1 前）：既保留
    interruptible 桶口径，又消除其后（本轮 LLM 流/final_gate/跨 run）的残值
    读取。S18-M3 锁定跨 run 消除，Phase4 M3 回归锁定桶语义不回归。
  - **S18-M2 构造修订**：原「时序窗口注入」（c3 完成前 ~100ms）在连跑负载
    下 flaky（首败实测）。改为不可取消工具 phase4_locked_sleep（revocable=
    False）作 c3——注入时机无窗口约束（gate 不取消、必然自然完成），确定性
    纯 gap 收割；4 连跑全绿。
  - **Phase4 M3 桶集合断言扩展**：test_m3_aggregate_endpoint_buckets 的桶
    集合断言从四桶扩为五桶（+llm_stream_interrupt）——Phase4 四桶语义与
    全部既有断言不变。
  - **FakeLLM chat_stream 注入线程模型**：on_delta_n 钩子在 run 线程内直接
    TestClient.post 会 portal 死锁（实测超时）；改为跨线程事件同步（run 线程
    hook 只发就绪信号并阻塞，主线程完成注入后放行），确定性不降。
  - **runner 终报形态**：cancelled 语义经 type=done + result.run_incomplete/
    final_answer=「已停止」表达（非 type=cancelled）——S17-M3 断言按实测形态
    锁定。
