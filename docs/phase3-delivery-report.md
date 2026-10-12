# 阶段3「可插话任务助手」交付报告（2026-10-13）

> 依据《阶段3设计方案书》（docs/phase3-interjectable-assistant-design.md）按 M0→M1→M2 串行、
> M3/M4 独立推进、终局交付的顺序完成。全程独立审查子agent 把关（M0 一轮、终局一轮），
> M0 审查发现的 3 处失真已逐条复核修正并在报告中留痕。

## 1. 里程碑清单（commit 可核）

| 里程碑 | 内容 | 交付物 | commit |
|---|---|---|---|
| M0 验收基线 | 12 场景实测 + D7 补核 5 项 + 基线报告（审查修订版） | tests/phase3_baseline/、docs/phase3-m0-baseline.md、reports/phase3/ | 7098d7a03 |
| M1 插话分级回执 | received/applied/denied/cbf 分级 + 持久化二分 + 只读分级端点 | human_turn_queue.py/engine.py/routes.py + 9 测试 | 7098d7a03 |
| M2 生效时延度量 | 三口径 t_ack/t_persist/t_effect/t_applied + P50/P95 + Web 暴露 | aggregate_interject_metrics + 端点 + 对照数据 | 8d49c846d |
| M3 停止语义四态 | requested/dispatched_stopped/local_terminated + 副作用登记面 + 确认端点 | side_effects.py + 三工具登记 + 4 测试 | 023b0724e..8a1e1d3d8 |
| M4 事件谓词唤醒 | 闭集谓词 + 超时/事件双通道竞速 + armed 一次性即焚 | scheduler.py/schedule.py + 5 测试 | b3a3247a8 |

## 2. 验收数据（全部实测，可复跑）

**插话回执分级（M1，tests/web/test_phase3_m1_grades.py 9 用例）**
- 主路径 applied：工具派发点标记，detail=tool_call_dispatch（首个动作=消费点同轮派发）
- 终答出口 applied：final_answer_after_interjection（取消路径不误标——取消不触发）
- CBF 网关 applied：continued_before_final_gate（结算边界拦截本身即生效点）
- denied 附原因码（守卫拒绝→interject_denied+deny_reason，回执原因码不含正文）
- requeued 附来源（进程重启→interject_process_restart；run 结束→interject_run_ended）
- 持久化二分：写失败前=definitely_not_committed / 提交不确定=commit_outcome_uncertain（503 回执）

**生效时延（M2，3 样本实测）**

| n | P50 t_ack | P50 t_persist | P50 t_effect | P50 t_applied |
|---|---|---|---|---|
| 3 | 1.9 ms | 1994.7 ms | 1996.6 ms | 1998.8 ms |

基线对照：t_ack 毫秒级稳定（1.8–2.3ms）；t_effect 由轮边界等待主导（长工具在途≈工具剩余时长）——「回执≠生效」的量化本体。

**停止四态（M3，tests/unit/test_phase3_m3_stop.py 4 用例）**
- 生产装配（hook 对齐 factory.py:731）：cancel→job killed 0.1ms 级→dispatched_stopped→local_terminated
- 不可撤销副作用：external_unknown 可枚举（工具+目标+发起时间+人工核验指引）→ POST confirm 人工登记；无 TTL 自动确认（0.2s 后复查仍 unconfirmed）
- F5 双口径：cancel 回执 <500ms，本地终止被无撤销 in-flight 工具拖住（dispatched_stopped 状态可见拖尾期，工具自然结束后→local_terminated，精确时刻由 done/error 出口写入）

**事件谓词唤醒（M4，tests/unit/test_phase3_m4_predicates.py 5 用例）**
- 8a 事件先到：after=3600s 的条目在谓词满足时立即 claim，event_won=event，恰一次
- 8b 超时先到：event_won=timeout，armed 即焚，事件后到不二次唤醒
- 8c 同 tick 双真：事件分支确定性取胜（分支次序固定，非墙钟）
- 闭集外 kind 双层拒绝（登记器+add）；无 wake（无授权链）拒绝（D8）；周期条目拒绝
- scheduler 存量 85 测试零回归；老条目 JSON 形态逐字不变

## 3. 不变量遵守声明（§4.1 六条逐条）

1. **不改状态机迁移规则**：queue 状态机仅新增从 interject_pending 出发的分级终态字段（grade/applied_at/deny_reason），claim CAS/lease/reaper 回滚语义零改动；S02/S03/S11/S12 基线复跑全绿。
2. **Session 单写者**：engine 内消费点追加消息路径未动；M1 只在追加后回执 ack。
3. **消息必达**：denied→requeue、进程重启回滚、reaper 回收全部保留并测试覆盖（S12/m1_rerun）。
4. **授权语义零改动（D8）**：谓词唤醒仍要求 wake=True+wake_grant 委派链；M3 confirm 端点只登记人工确认事实，不产生任何撤销/执行授权。
5. **竞速不用墙钟（D3）**：M4 竞速=flock 内字段翻转（CAS 语义）；M1 CBF 分级基于结算边界事件非时间比较。
6. **D6 正文红线**：日志与登记项不含插话正文/页面正文（deny_reason 为原因码；side_effects.target 只含目标标识 job:url:name 截断）；测试 test_d6_no_content_leak_in_grades 钉住。

## 4. 过程事故与诚实记录

1. **M0 审查修订**（docs/phase3-m0-baseline.md §0/§2）：F1「停止不停后台 job」撤回——生产装配 factory.py:731 已有 JobRegistry cancel hook，原始观测系测试装配残缺；F4 原因码归因修正；S05 时序修正并新立 F5（run 终态可被无撤销工具拖住）。教训沉淀 experience 2 条。
2. **基线快照覆盖事故**：M1 开发中复跑覆盖原始 JSON（不可恢复）；已参数化输出目录+README 留痕；报告引用原始数字以成文版为准。
3. **运行时部署防护 stash 事件**：一次自动 stash 卷走 M2 进行中改动+外来 WIP，pop 产生 6 文件冲突；外来文件按 upstream（较新）侧解决并逐文件核过语义（均为注释/文档字符串级差异）；m0 目录被带回的 M1 版记录清理归位。
4. **前次会话遗留 WIP**：learning_plane.py 心跳写已按观测信号豁免登记（fail-open 非 durable SoT，先例 learning_runtime.py lockfile）；test_knowledge_endpoints.py 未用 import 移除；其 3 个隔离运行失败为顺序依赖（全量套内通过），非本任务引入。

## 5. 与设计书的偏差（已留痕）

1. M2 聚合落 HumanTurnQueue 而非 run_finalizer（engine 侧拿不到 Web hq 实例；意图不变，接缝按实测修正）——docs/phase3-m2-metrics.md §4。
2. M3 不新增 JobRegistry 按会话回收（M0 审查证明已存在）；改为登记面+四态查询+装配一致性钉子——M0 报告 §4。
3. M1 CBF 场景 applied_detail=continued_before_final_gate（比设计草图的终答判据更精确：生效点即结算边界拦截）——测试注释留痕。

## 6. 复跑与验收入口

- 全量：`.venv/bin/python -m pytest tests/ -q`（终局全量结果见 §7 终审后补记）
- 12 场景基线：`.venv/bin/python -m pytest tests/phase3_baseline/ -q`（PHASE3_REPORT_DIR 参数化）
- 分级/度量/停止/唤醒：tests/web/test_phase3_m1_grades.py、test_phase3_m2_metrics.py、tests/unit/test_phase3_m3_stop.py、test_phase3_m4_predicates.py
- 暴露面：GET /api/v1/chat/queue/item、GET /api/v1/chat/queue/metrics、GET /api/v1/chat/stop-state、POST /api/v1/chat/stop-state/confirm；schedule 工具 event_predicate/predicate_ref 参数

## 7. 终审后补记（2026-10-13 06:0x）

终审子代理判定「不通过：修复后才可交付」，P0×2 + P1×4 + P2×9。全部处置如下（提交链 fdcebe9ca…8ab06c540 + 本轮收尾）：

**P0（阻断项，已修）**
- P0-1 M3 浏览器副作用登记死代码（dict vs 属性）→ 抽 `_register_mutation_side_effects` 统一登记；02:52 针对性复跑 S05 绿。
- P0-2 M4 job_terminal 求值器终态词表错配 → 词表改 {"completed","failed","killed","orphaned"}（job_registry 本地终态 ∪ external_execution durable，side_effects.py `_JOB_TERMINAL_STATES` 同源）；02:52 复跑 S04 绿。

**P1（应修，已修）**
- P1-1 M1 applied 回执每会话桶跨 run 泄漏 → per-run 隔离（tests/unit/test_phase3_m1_receipts.py 钉子）。
- P1-2 race 竞态下 applied_detail 语义 → P0-2 词表修复后 S03 复跑绿。
- P1-3 stop-state 陈旧记录 + 自然完成 job 永挂 active → 新 run 清旧停止记录 + job 惰性终态结算（runner.py:540 接线 settle_session_stopped）。
- P1-4 side_effects.json 跨进程写纪律 → flock+重读合并+tempfile+os.replace（与 ScheduleStore 同型），durable registry 登记（见下「arch guard」）。

**P2（可接受但需留痕，已全部处置）**
- P2-1 口径映射回填 → 设计书 §7.1 已回填（指向 docs/phase3-m2-metrics.md §1 四口径机械推导）。
- P2-2 wake 工具环内零日志 → scheduler.py:248-286 已加。
- P2-3 子代理 horizon 判据缺 TTL → 保留人肉决策（授权语义），报告留痕。
- P2-4 settle_session_stopped 假定 hook 成功 → P1-3 接线后主路径覆盖；fail-open 属性留痕（观测面，停止路径不因登记失败中断）。
- P2-5 confirm 会话归属 → 会话级校验已加。
- P2-6 8b 语义两边不一致 → 设计书 §6 已回填：实现取「超时胜出仍交付完整 wake、事件后到不二次唤醒（armed 即焚）」，恰一次不变量两边一致并被测试固化；「事件后补记录」未实现，记为已知偏差。
- P2-7 闭集两谓词无生产求值器 → schedule.py schema 描述已明示「当前生产仅登记 job_terminal；另两 kind 登记前回退纯超时唤醒（一次性告警）」；不静默误导。
- P2-8 测试卫生 → m2 采集测试默认写 tmp（PHASE3_REPORT_DIR 显式采集，工作树不再被测试弄脏）；m4 谓词测试 autouse fixture 恢复进程级注册表（不再污染 factory 装配测试）。
- P2-9 no_content 分级未实现 → 设计书 §3 G1 已收口：入队端 `_require_payload` 拒纯空文本、纯附件属合法 received；漏网面已关，分级留作未来放开时的重评估项。

**arch guard（终审漏项，全量回归首次暴露，已修）**
- P1-3/P1-4 新增的 `src/llm_loop/core/loop/side_effects.py` 未登记 durability surface registry → 已登记 `side_effect_store`（T2/conform，tests/guards/function_size_baseline.json +10 行）；test_arch_guards 29 绿。

**终局数字（全部真实回执）**
- 终局全量回归：`tests/unit + tests/web + tests/phase3_baseline` → **8101 passed / 1 failed / 108 skipped**（397.42s）；该 1 failed 即上条 arch guard 漂移。修复仅改 guard 基线数据文件（唯一消费方即该测试文件），单独复跑 29/29 绿即闭合受影响面，不再重跑全量。
- 12 场景终局复跑（终审修复+P2 收尾后）：`PHASE3_REPORT_DIR=reports/phase3/m4_final2` → **12 passed in 28.87s**，S01–S12 全部 status=ok / verdict=pass，快照独立留痕 `reports/phase3/m4_final2/`（m4_final/ 保留为修复前历史快照）。
- 修复后针对性复跑（02:52，终审当夜）：S03/S04/S05 + m2 metrics 绿。

### 7.1 终局验收判定

五项里程碑验收门（设计 §6）：M0 无损基线 ✅（m4_final2 S01–S12）、M1 分级回执 ✅（m1 tests + S01/S02/S07）、M2 机械口径 ✅（m2 tests + metrics.json + S03/S04）、M3 可枚举+授权不变 ✅（m3 tests + S05/S06 + confirm 人工）、M4 恰一次唤醒 ✅（m4 tests + S08/S09：8a/8b/8c 覆盖）。D1–D6 红线全程无违反（终审 D3/D5 独立确认）。
