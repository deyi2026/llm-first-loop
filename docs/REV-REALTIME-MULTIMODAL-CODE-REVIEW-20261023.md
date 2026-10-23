# LFL 实时多模态 关键实现代码审查回执与一致性回顾（T-REV-1 / T-REV-2）

> - 特性：`realtime_multimodal`　日期：2026-10-23
> - 权威依据：`docs/SPEC-20261023-realtime-multimodal-requirements-v1.md`（v1.2 / 163 条）、`docs/DESIGN-20261023-realtime-multimodal-architecture.md`（v1.3）、`docs/TASKS-20261023-realtime-multimodal-implementation.md`（v1.1）
> - 审查对象：`src/llm_loop/realtime/`（10 模块）+ `src/llm_loop/web/realtime_ws.py`、`realtime_routes.py`
> - 门禁证据：`tests/realtime/` **232 passed**；`ruff` **All checks passed**

## 1. 结论摘要

- 关键实现点（唯一执行链、原子认领、WS 握手、状态机、本地栈适配器、终稿校正）均**有独立审查意见并落盘**（`T-REV-1`）。
- 审查发现 **4 项缺陷**，其中 **3 项已修复并附回归测试**（R-1/R-2/R-3），1 项为代码整洁（R-4，已清理）。
- 8 项实现契约与 **D1–D28** 决策逐项核对：**无实质漂移**；仅 **D27（客户端 VAD/打断）** 的浏览器侧未接线，属**未验收**而非漂移。
- 阶段声明保持边界：M0 不以 mock 完成；**M3 前不宣称 MVP 交付**；性能/证据分级，服务级不充当浏览器验收。

## 2. 发现与处置

| 编号 | 位置 | 严重度 | 问题 | 处置 | 回归测试 |
|---|---|---|---|---|---|
| **R-1** | `media_registry.create` | 中 | **显式接管（take_over）未关闭旧写入者** → 同会话并存两个活动 writer，`active_writer_conflict` 永真、`count_active` 增长（违反 `IDN-03`/`LIF-05`） | `create` 增 `take_over` 参数，接管时在锁内关闭旧记录 | `test_take_over_closes_previous_writer`、`test_without_take_over_previous_writer_stays_open` |
| **R-2** | `task_bridge.dispatch_tool` | 中 | **归属校验失败返回游离 `ClaimRecord`**（未写入 store）→ 恢复时查不到、可能误导「已认领」（违反 `TOL-04`/`REC-06` 事实一致性） | 归属失败返回 `record=None`；`ToolDispatchResult.record` 改为可选 | `test_ownership_failure_leaves_no_record_in_store` |
| **R-3** | `committed_input.CommittedInputBridge` | 低–中 | **去重缓存无界增长**（长会话内存持续增长，违反 `LIF-05`） | 改为有界 LRU（`max_tracked`，默认 1024） | `test_dedup_cache_is_bounded`、`test_max_tracked_must_be_positive` |
| **R-4** | `tool_orchestrator.initiate` | 低 | 函数内重复 `import ClaimRecord`；拒绝分支同样构造游离记录 | 移除函数内 import；拒绝分支 `record=None` | 既有 `test_tool_outside_bridge_surface_is_denied`、`test_model_veto_prevents_dispatch` |

## 3. 观察项（非缺陷，明确标注）

| 编号 | 项 | 说明 | 结论 |
|---|---|---|---|
| O-1 | `realtime_ws._serve` | 目前为占位循环（仅 accept 后收 disconnect），文本/音频二进制帧处理待 M1 接线 | **已登记**，不影响契约层；M1 落地 |
| O-2 | `turn_aggregator.apply_correction` | `COMMITTED` 后仍可更新 `_final` | 符合设计「**未执行**动作可更新」（`mark_executed` 后拒绝改写）；已发出的 `CommittedTurn` 为不可变快照，不受影响 |
| O-3 | `local_voice_stack_adapter._validate_frame` | 格式判定的 PCM16 分支在当前唯一取值下恒真 | 保留为显式格式前置（CAP-14 可读性），非缺陷 |
| O-4 | `media_session` 有界重连 | 抖动退避时长（0.5/1/2s）由客户端实现 | 服务端只保证**有界与不循环**；时长在前端 `MediaSessionClient.ts`（M1） |

## 4. 一致性核对（8 项实现契约）

| 契约 | 落点 | 关键断言 | 状态 |
|---|---|---|---|
| 1 唯一执行链 | `task_bridge.py` | 桥接只提交任务；工具只在引擎内派发；双层标识绑定 | ✅ |
| 2 工具幂等 | `task_bridge.py` | `call_key` 非参数哈希；原子 `claim_if_absent`；`claimed` 重启不重派；`outcome_unknown` 不盲重试 | ✅ |
| 3 Provider 适配器（D1/D2） | `provider_adapter.py` + `local_voice_stack_adapter.py` | D1 唯一实现、仅转写、无 `response.create`；D2 仅 Protocol | ✅ |
| 4 WS 握手鉴权 | `realtime_ws.py` | accept 前校验；`4401/4403/4404`；先决失败不查归属（防枚举） | ✅ |
| 5 输入状态机 | `turn_aggregator.py`、`event_normalizer.py`、`dual_asr_corrector.py` | `Collecting→…→Committed`；`delta` 只显示；`FinalPass` 高精度；保守兜底带标注 | ✅ |
| 6 连接状态机 | `media_session.py` | `ready`=握手+传输就绪；全活动态可关闭；非可重试不循环；**四事实分离** | ✅ |
| 7 关键帧 | `keyframe.py` | `current_validity` × `retention_state` 正交；`Stale` 仍可答历史 | ✅ |
| 8 预算计量 | `media_usage.py` | 不改 `BudgetDimension`；`incomplete` 不标零；残留并发上限 | ✅ |

## 5. 一致性核对（D1–D28）

| 决策 | 落地 | 状态 |
|---|---|---|
| D1–D22（v1.2 既有） | 由契约组 1–8 与 M0/M2 模块承接 | ✅ 无漂移 |
| **D23** 本地栈唯一链路 | `provider_adapter` 无远端实现；`LocalVoiceStackAdapter` 单实现 | ✅ |
| **D24** 转写会话型 D1 | `local_voice_stack_adapter`（`configure/append/commit/recv/transcribe_final/flush_close`） | ✅ |
| **D25** 音频输出/工具编排 | `tool_orchestrator`（唯一入口）+ `committed_input`（编排发起） | ✅ |
| **D26** 双 ASR 终稿校正 | `dual_asr_corrector` + `turn_aggregator.FinalPass`/`ConservativeFinal` | ✅ |
| **D27** 客户端 VAD/打断 | 服务端 `media_session` 具备四事实与全活动态关闭；**客户端侧未接线** | ⚠️ 未验收 |
| **D28** 服务级/浏览器链路分级 | `evidence_grading` + `evidence_report`（混算=0、禁提前 PASS） | ✅ |

## 6. 未验收项（显式）

- `AUD-01/03`、`PLY-02/07`、`PRF-02/03`、`SCN-*`、`A11Y-*` 中依赖**浏览器链路**的条目：采集/16k 重采样/播放/客户端 VAD/打断**未接通** → **未验收**（`RTM-EVD-06`）。
- 服务级基线（12.23s）仅作**服务级**口径，**不充当**浏览器链路验收、**不混算**（`RTM-OBS-09`）。

## 7. 阶段声明边界

- M0 探针 A/B：**部分解除、未通过**；探针 C 通过（真实 `read_file` 校验值核对）。
- **M3 前不宣称实时多模态 MVP 已交付**；性能分离「已测 / 达标」且**已测为浏览器链路口径**。
- 交付边界：设计/任务/评审交付物**仅文档**；运行文件（`data/…runner_state.json`、`learning_admission.json` 等）**未被 Git 跟踪且被忽略**，**不清理、不回滚、不提交**（`T-OPS-1`）。

## 8. 复审建议

- M1 客户端接线完成后，重跑 R-1（接管）、R-2（归属失败无游离记录）、R-3（缓存有界）回归，并补客户端 VAD/打断与本地 TTS 播放证据。
- 建议后续把 `realtime_ws._serve` 的帧处理与 `media_registry` 接管纳入 M1 验收项，避免长期占位。