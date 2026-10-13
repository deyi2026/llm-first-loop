# Phase4「生效时延优化（t_effect）」交付报告

- **Goal**: GOAL-20261013-9b1fa766（5/5 任务收口）
- **设计真值**: docs/phase4-effect-latency-design.md（r2 定稿 + §10 实施修订记录）
- **代码提交**: bb6d33de4（M1）→ 64647c192（M2）→ 3af8213fa（M3）→ 6c50a6a2e（M4-1）→ 138da6fb6（M4-2 终局，全量回归 8225 绿）
- **交付日期**: 2026-10-13

## 1. 结果对照（基线 → 交付）

| 场景/桶 | 基线 P50（M0） | 交付 P50 | 目标 | 结论 |
|---|---|---|---|---|
| S13 在途打断（interruptible 桶） | 1679.7ms | **72.1ms**（P95 81.2ms） | ≤500/≤1000 | **达成，23.3×** |
| S16 空窗收割（idle 桶机制时延） | 1428.5ms（S16 构造） | **34.7ms**（机制 P50，样本 26.4-39.1） | ≤50 | **达成** |
| S14 不可中断保守 | 1659.4ms | 1682.4ms（自然边界实测 m2/S14M2，零打断误标） | 行为保持 | 达成 |
| S15 竞速双分支 | 不存在机制 | natural_first×3 + interrupt_first×3 如实 | 两分支≥3 | 达成 |

四桶分桶实测（M3_ACCEPTANCE.json 实值，每桶 n=5，最近邻序法）：
- interruptible 72.1/81.2ms；natural_boundary 99.1/100.7ms（S15-A 类构造注入即 ~100ms 余量，如实）
- llm_stream 1240.1/1257.1ms（终答边界等待 LLM 窗口结束，无目标约束，Phase5 候选）
- idle 34.7/39.1ms（机制 P50 34.7；边界错失样本如实归 natural_boundary，到达-边界竞速口径在工件标注）
- 对照：S13 基线 1679.7ms → 72.1ms = 23.3×（工件 baseline_compare 机械推导）

## 2. 实施内容

**M0 基线扩展**（零核心代码）：tests/phase4 S13–S16 场景脚本；基线数据 reports/phase4/m0/
（S13=1679.7ms 量化本体差距 ≈ 工具剩余时长）。

**M1 间隙检查点（CK-A + 序列间隙收割）**：
- `runner.interjections_pending()`：只读 peek（同 `_guard`，代次同源，无内存标志）
- tool_cycle 分段执行：readonly 并行批 + mutating 逐调用段，物理序与 execute_many 等价
- 间隙检查点：序列头/每段间 peek 非空 → 剩余调用 `skipped_for_interjection` 回执 →
  回执落盘后轮内消费点（`_consume_gap_interjections`）→ 下一轮派发
- user_text 对齐：`run_state.interject_harvest_user_texts` 暂存-轮首合并
- 消费故障恢复：行级回插 `requeue_interjections_front` + 异常传播（审查 P1-1）

**M2 在途打断（CK-B/C）**：
- `registry._wait_with_interrupt_gate`：τ=200ms 分段等待（总超时语义不变）
- 判定 gate（engine 装配，§4.2 固定序）：stop 链优先 → peek 真值 → 闭集
  （INTERRUPTIBLE_TOOLS={execute_command}）→ 副作用面（run_generation 过滤）
- `_terminate_for_interjection`：单调用粒度定向取消（**三不**：不 cancel_session、
  不 _session_cancel_hooks、不写 StopRecord）+ 收割前 stop 复查 + 竞速机械判别
  （future.done() 同线程串行 + SUCCESS=自然完成）+ ToolResult.interrupted_for_interjection
  标注（content marker + Message.metadata 投影，不引用插话正文，D6）
- 剩余未启动调用由 M1 间隙检查点自然接续（skipped_for_interjection）

**M3 度量验收**：
- hq 条目消费点戳记（consumed_via/interrupt_receipt，机械打点零墙钟）
- aggregate 四桶派生 + buckets 汇总（n/p50/p95/insufficient_sample 诚实标注）
- 基线防覆写护栏（PHASE4_OVERWRITE_REPORTS=1 才强制重测）

## 3. 审查记录（子 agent 两轮）

| 轮次 | 发现 | 处置 |
|---|---|---|
| M1（47 tools） | P0×0；P1×1（消费故障吞持久化异常→静默丢行）；P2×6 | P1 行级回插+传播；P2-1/5/6 当轮处置；P2-2/3 留档（§10） |
| M2（52 tools） | P0×0；P1×3（片超时吞工具异常；副作用面未限 run；缺停止四态专项断言）；P2×7 | 全部当轮处置或设计裁剪留痕（§10）；实测 S13 P50 63.4ms→修复后 84-100ms |

## 4. 语义完整性

- **停止四态零变化**：打断通道零触碰 cancel_session/_session_cancel_hooks/StopRecord
  （专项测试 test_p1_3：钩子零触发+停止记录零写+终态 done）；phase3 12 场景全绿
- **D 红线**：五态回执全链（executed/interrupted/skipped/cancelled/blocked）；
  声明-结果对账含 skipped；D6 回执不引用插话正文
- **消息必达**：消费故障行级回插 + ack 未触发条目由持久队列兜底重投
- **闭集保守**：初始 {execute_command}；revocable=False 未结算（限当前 run）双重阻断

## 5. 遗留与后续

1. **P2-2**（skipped 调用无 started 记录）：与「未开始」语义自洽，对齐
   _synthesize_cancelled 先例，留档
2. **P2-3**（重复 tool_call_id 后写覆盖）：provider 契约域，留档
3. **终局评审 P2-4**（混合路径戳记时序）：轮内 gap 消费 ack 先于
   last_receipt_interrupted 置位——「同轮打断+剩余 skipped」混合路径的 hq 条目
   interrupt_receipt 可能读到上轮残值（错桶风险）；单工具 S13 主路径时序正确，
   已交付数字不受影响；留档待 Phase5 首个混合场景处置
4. **llm_stream 桶 ~1.24s**：终答边界等待 LLM 窗口（流式打断属 Phase5 候选，本阶段无目标）
5. **闭集扩张**（如 spawn_subagent）：需按设计 §7 度量门单独评估收益≈0
6. **自然边界桶**：随用户自然节奏，无优化目标（语义上也不应有）

**终局评审**（子agent 44 rounds/62 tools，只读，2026-10-13）：P0×1（报告
§1 数字与验收工件不符——工件被调试重跑无护栏覆写漂移；已处置：以工件实值
回填+M3 验收工件补 PHASE4_OVERWRITE_REPORTS 护栏钉死）+ P2×6（P2-1 护栏
已补/P2-2 占位符已回填/P2-3 S14 已改引实测/P2-4 留档§5.3；核心实现、
停止四态专项断言、遗留声明诚实性全部证实）。

## 6. 发布验证

- **发布**：service_control publish 已绑定 desired deployment
  （git_head=138da6fb6，config_hash 57a03543…，2026-10-13T12:11）
- **restart**：两阶段 barrier 已建（operation svc-5f43435c…，waiting_for_
  requester_exit——按机制等本 requester 会话退出后自动完成重启）
- **重启后核验**（下一会话执行，**已于 2026-10-13T13:0x 完成**）：
  - restart 自动收口：action svc-d1382470… 12:49:33 succeeded（web/feishu/
    learning 三 stage 全 succeeded，terminal_action_barrier=null）
  - generation=249 前进至 desired（lag=0，matches_desired_generation=true）
  - web 存活：pid 81233，127.0.0.1:8903，HEAD=138da6fb6（dirty=false），
    config_hash 57a03543… 与发布一致
  - 冒烟（127.0.0.1:8903 实测）：队列受理 **202**（queue_id=q_afed1ad950c1，
    验后即取消 200）；metrics **buckets 四桶字段在位**（interruptible/
    natural_boundary/llm_stream/idle，n/p50/p95/insufficient_sample）；
    插话端点无活跃 run 环境 return **409 interject_no_live_run**（协议正确
    路径；202 通道需活跃 run+run_generation 匹配，本冒烟环境不可复现，如实）
- **全量回归终态**：8225 passed / 0 failed / 132 skipped（tests/unit+web+
  guards+integration+phase3_baseline+phase4，502.86s）

