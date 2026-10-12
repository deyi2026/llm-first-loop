# 阶段3 M0 验收基线报告（2026-10-13 实测；01:53 审查修订版）

> 依据《阶段3设计方案书》§6 验收矩阵。执行载体：`tests/phase3_baseline/test_m0_scenarios.py`。
> **版本说明**：本报告初稿成文于 01:34（基于 01:32 原始运行）；01:35–01:45 独立审查发现
> 3 处实质失真（F1 结论错误 / F4 归因颠倒 / S05 时序颠倒）及基线快照被 01:41 的 M1 复跑
> 覆盖。本版为审查后修订：F1 撤回重写，错误已逐条修正并附生产装配重跑证据（01:53）。
> 逐场景 JSON：`reports/phase3/m0/`（01:32 原始版已不可恢复，见该目录 README 事故记录；
> 现存 S03/S04/S05 为生产装配修正重跑，S01/S02/S06–S12 引用 01:32 原始数字）。
> 重跑：`.venv/bin/python -m pytest tests/phase3_baseline/ -q`（输出目录可用
> `PHASE3_REPORT_DIR` 参数化，防再覆盖）。

## 0. 审查事故与修订记录（诚实优先）

| 时间 | 事件 |
|---|---|
| 01:32 | 原始 M0 运行（pre-M1 代码），12 场景记录落盘 |
| 01:34 | 初版报告成文（含 3 处失真，详见 §2 修订对照） |
| 01:38–01:41 | M1 开发；01:41 复跑测试**过失覆盖**了原始 JSON |
| 01:45 | 独立审查报告指出失真 + 覆盖事故 + 测试装配与生产装配差异 |
| 01:53 | 逐条复核成立：生产装配确有 job 回收 hook（factory.py:731）；S03/S05 记录重读证实誊写错误；S04/S05 按生产装配重跑取证；本版修订 |

## 1. 十二场景：预期 vs 实测

| # | 场景 | 预期（方案书） | 实测 | 判定 |
|---|------|--------------|------|------|
| S01 | 长工具(2.5s)运行中插话 | ACK 快，生效等轮边界；消息进上下文 | ACK=2.0ms；**生效=2492.9ms**（工具跑完后轮边界消费）；模型第2次调用以 user 消息看到（元数据 `human_interjection`/`human_turn_queue_id`）；终态 `interject_received`（01:32 原始值） | 符合；回执≠生效量化实证 |
| S02 | 空闲插话（无 live run） | 409 + 不动队列 | 409 `interject_no_live_run`；条目保持 `queued`，`claimed_by=None` | 符合 |
| S03 | 临界竞态（错代/结束后） | 409 分级；消息不丢 | 运行中错代→409 **`interject_run_changed`**（端点先做 generation CAS，routes.py:1768–1777）；并发认领冲突才是 `interject_claim_conflict`（routes.py:1784，见 S11）；run 结束后→409 `interject_no_live_run`；条目最终均 `queued` 不丢 | 符合；**初版把两个原因码写反，已修正** |
| S04 | 停止后台 execute_command job | terminate_session 停 job | **两口径**：①01:32 原始（测试装配，无 cancel hook）：cancel 返回 0、job 持续 running——系 tests/conftest.py 装配缺 `add_session_cancel_hook` 所致，非生产行为；②01:53 生产装配重跑（对齐 factory.py:731 注册 `JobRegistry.cancel_session`）：cancel 触发 1 个 hook，**job 0.1ms 内 killed** | 符合（生产口径）；初版 F1「停止不停后台 job」**撤回** |
| S05 | 无 terminate_session 副作用工具 | run 停了工具仍跑 | cancel 立即回执，但 **run 终态事件等待 in-flight 工具自然结束**（cancel→done=4022.8ms，工具 4s 自然跑完）；即本地终止可被无撤销工具的时长拖住 | 符合（盲点实证）；**初版时序写反，已修正**；G3 t_stop_local 口径输入 |
| S06 | 前台长工具停止 | 快停，无后续 LLM 调用 | cancel→run 终态 21.8ms；进程 SIGKILL(-9)；`llm_call_count=1` | 符合 |
| S07 | 预算 CAS 失败注入 | 行为由存量测试定义 | `test_task_budget_transport_stop.py` 通过（33 passed） | 符合 |
| S08 | wake 一次性 | 行为由存量测试定义 | `test_schedule_wake.py`+`test_wake_jobs_projection.py` 通过 | 符合 |
| S09 | wake 重启恢复 | 行为由存量测试定义 | `test_schedule_restart_recovery.py`+`test_schedule_durability.py` 通过（52 passed） | 符合 |
| S10 | 空内容/超长插话 | 引擎层过滤空内容；超长现状未核 | 空消息+无附件：**入队即 422**「message 或 attachments 至少提供一项」（护栏在 enqueue 层）；100k 字符：**无上限接受**，2.8ms 入队，直达模型上下文 | 空内容护栏比方案假设更靠前；长度上限缺失确认为真实缺口 |
| S11 | 并发 100 次 interject 同一 queue_id | 恰一次 202 | 1×202 + 99×409 `interject_claim_conflict`（并发认领冲突码，与 S03 错代码 `run_changed` 是两个不同原因码）；总耗时 142.8ms；消息只消费一次 | 符合；CAS 无重复投递 |
| S12 | 重启 interject_pending 恢复 | 回滚 queued 不丢消息 | 重载→`queued`（`requeued_from=interject_process_restart`）；孤儿回收→`queued`（`requeued_from=interject_run_ended`）；消息原文完整 | 符合 |

## 2. 偏差与修订对照（初版 → 本版）

| # | 初版主张 | 本版结论 | 证据 |
|---|---------|---------|------|
| F1 | ~~「停后台 job 并不存在；停止路径无任何 JobRegistry 调用；M3 必须新增 JobRegistry 按会话回收」~~ | **撤回**。生产装配在 factory.py:731 注册 `registry.add_session_cancel_hook(JobRegistry.instance().cancel_session)`；`registry.cancel_session` 末段遍历 `_session_cancel_hooks`（registry.py:651+）。S04 原始观测是**测试装配残缺**（tests/conftest.py:355 只注册了 subagent hook）。生产装配重跑：job 0.1ms killed | 01:53 S04 重跑（本报告 §1）+ factory.py:731 + registry.py:651-670 |
| F2 | 空内容护栏在入队端 422 | 维持（非初版失误） | S10 endpoints |
| F3 | 100k 字符无上限直达上下文 | 维持 | S10 |
| F4 | ~~「S03 错代返回 claim_conflict 而非 run_changed，构成偏差」~~ | **改写**。实测与源码一致：错代=`interject_run_changed`（generation CAS，routes.py:1768），并发认领=`interject_claim_conflict`（routes.py:1784）。初版把两个码写反并误标为「偏差」；实际**与设计 §3 预述一致**，不构成偏差 | S03 记录（两版一致）+ routes.py 源码 |
| F5（新增） | —— | **run 终态可被无撤销工具拖住**：cancel 回执快（<25ms），但无 terminate_session 的 in-flight 工具自然结束后 run 才终态（S05：4022.8ms）。影响 G3 四态的 t_stop_local 口径与「本地终止」定义（回执时刻≠本地终止时刻） | S05 修正重跑 |

**根因记录（防复发）**：F1 错误源于 ①检索被 `head -15` 截断且只 grep 了 `JobRegistry.instance()` 字面量（factory 用变量名 `_job_registry.cancel_session`）；②只追了 `terminate_session` 单一路径，未检索其他 hook 机制（`add_session_cancel_hook`）。结论「机制不存在」必须有穷尽式检索支撑，字面量 grep+截断不构成。

## 3. D7 补核清单结果（已同步修订设计书 §9.2）

1. **Web 鉴权层**：全部 v1 路由 `Depends(require_api_key)`（web/__init__.py:250），session cookie/Bearer API key；loopback 受信豁免（auth.py:106）。✔
2. **长度上限**：`QueueEnqueueRequest.message` 无 max_length（schemas.py:118）；100k 字符实测全链路无阻（F3）。✔
3. **`_save()` IO 异常**：原实现 raise 原始 OSError 未分级（M1 已按 D2 补二分，见 M1 交付）。✔
4. **时间戳字段**：有 created_at/interject_requested_at/received_at/terminal_at 等；received_at 即轮边界消费点（S01：ACK 2.0ms vs 生效 2492.9ms）。✔
5. **副作用工具盘点（修订）**：停止回收分两层——①in-flight 工具 `terminate_session`（execute_command.py:260、spawn_subagent.py:108）；②**会话级 hook**：factory.py:731 注册 JobRegistry.cancel_session（后台 job 按会话回收，含 dsh_task bg）；subagent 由 factory.py:2342 覆盖。**无撤销面**：浏览器 mutation、playwright、send_feishu、文件写入。测试装配（conftest）与生产装配不一致是本次审查暴露的新事实，M3 需补装配一致性验证。✔

## 4. 对 M1–M4 的输入（修订版）

- **M1**：现状 409 已细分两码（run_changed=generation CAS / claim_conflict=并发认领），G1 的增量=applied/denied/cbf 语义分级 + D2 持久化二分 + 受理≠生效提示（已在 01:38–01:41 落地，测试 `tests/web/test_phase3_m1_grades.py` 9 用例）。
- **M2**：t_ack/t_effect 口径可直接复用现有字段；t_persist 需 engine 侧埋点。S01 对照组：2.0ms vs 2492.9ms。
- **M3**：~~需新增 JobRegistry 回收~~ → **已存在**（factory.py:731）。M3 真实待办：①四态可查（requested/dispatched_stopped/local_terminated/external_unknown）；②副作用登记 hook 与清单可枚举（浏览器/dsh_task/文件等无撤销面）；③**装配一致性**：tests/conftest.py 与 factory.py 的 hook 集合对齐或显式声明差异；④t_stop_local 口径纳入「回执时刻 vs 本地终止时刻」两口径（F5）。
- **M4**：schedule 无事件谓词参数（schedule.py 已核，S08/S09 语义稳固）。

## 5. 复跑与原始数据

- 复跑：`.venv/bin/python -m pytest tests/phase3_baseline/ -q`（可设 `PHASE3_REPORT_DIR` 指定输出目录）
- 记录目录：`reports/phase3/m0/`（含 README 事故说明；S03/S04/S05 为 01:53 修正重跑，S01 等其余引用 01:32 原始数字，见各 JSON `ran_under` 字段）；`reports/phase3/m1_rerun/`（01:41 M1 行为复跑，M1 证据）
- 环境：本仓库工作树（M1 改动进行中；M0 基线数字均取自 01:32 pre-M1 运行）
