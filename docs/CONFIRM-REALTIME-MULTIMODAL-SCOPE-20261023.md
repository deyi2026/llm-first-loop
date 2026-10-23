# LFL 实时多模态 阶段声明边界与变更范围最终确认（T-REV-3）

> - 特性：`realtime_multimodal`　日期：2026-10-23
> - 前置：`T-REV-1/2`（审查回执 `docs/REV-REALTIME-MULTIMODAL-CODE-REVIEW-20261023.md`）
> - 依据：`docs/SPEC-20261023-realtime-multimodal-requirements-v1.md`（v1.2 / 163 条）、`docs/DESIGN-20261023-realtime-multimodal-architecture.md`（v1.3）、`docs/TASKS-20261023-realtime-multimodal-implementation.md`（v1.1）

## 1. 阶段声明边界（与证据分级一致）

| 声明 | 口径 | 证据 |
|---|---|---|
| **M0 不以 mock 完成** | M0 探针 C 通过（真实 `read_file` 运行时校验值核对）；A/B **部分解除、未通过** | `docs/M0-REALTIME-MULTIMODAL-READINESS-20261023.md`、`docs/M0-CAPABILITY-PROFILE-LOCAL-VOICE-STACK-20261023.md`、`tests/realtime/test_m2_gate.py` |
| **M3 前不宣称 MVP 交付** | 浏览器链路（采集/16k 重采样/播放/VAD/打断）未接通 → 相关条目**未验收** | `RTM-EVD-03/05/06` |
| **性能分离「已测 / 达标」且已测为浏览器链路口径** | 服务级 12.23s 仅登记为**服务级基线**；`PerformanceReport` 按层分组、`may_declare_pass` 需浏览器真实达标 | `evidence_grading.py`、`evidence_report.py`、`tests/realtime/test_gates.py` |
| **服务级不混算** | `mixed_computation_count()` 结构性为 0；服务级数值不充当浏览器验收 | `RTM-PRF-01…04`、`RTM-OBS-09` |
| **本地栈为唯一链路** | 无远端空适配器、无 WebRTC；`WS /v1/realtime` 仅转写 | `provider_adapter.py`（D2 仅 Protocol）、`tests/realtime/test_local_voice_stack_adapter.py` |

## 2. 本次变更范围（精确路径）

**源码（服务端）**
- `src/llm_loop/realtime/`：`__init__.py`、`media_usage.py`、`provider_adapter.py`、`local_voice_stack_adapter.py`、`task_bridge.py`、`dual_asr_corrector.py`、`event_normalizer.py`、`turn_aggregator.py`、`media_session.py`、`keyframe.py`、`media_registry.py`、`committed_input.py`、`tool_orchestrator.py`、`realtime_persistence.py`、`capability_profile_check.py`、`evidence_grading.py`、`evidence_report.py`、`delivery_boundary.py`
- `src/llm_loop/web/realtime_ws.py`、`src/llm_loop/web/realtime_routes.py`
- `src/llm_loop/web/__init__.py`（`build_app` 装配 realtime registry/REST/WS）

**测试**
- `tests/realtime/`（9 个测试文件）、`tests/web/test_realtime_routes.py`

**文档**
- `docs/SPEC-20261023-realtime-multimodal-requirements-v1.md`、`docs/DESIGN-20261023-realtime-multimodal-architecture.md`、`docs/TASKS-20261023-realtime-multimodal-implementation.md`
- `docs/M0-REALTIME-MULTIMODAL-READINESS-20261023.md`、`docs/M0-CAPABILITY-PROFILE-LOCAL-VOICE-STACK-20261023.md`、`docs/REV-REALTIME-MULTIMODAL-CODE-REVIEW-20261023.md`、本文件

## 3. 提交清单（精确路径，不整目录 `git add`）

- 上述**源码/测试/文档**路径逐项提交（`CommitPlan` 拒绝 `.`/`-A`）。
- 核验：`data/knowledge_scores/runner_state.json`、`data/runtime/learning_admission.json` **tracked=no、ignored=yes** → **不清理、不回滚、不提交**（`T-OPS-1`）。

## 4. 未验收项（显式，`RTM-EVD-06`）

- 浏览器链路：麦克风采集、16k 重采样、客户端 VAD、本地停播、本地 TTS 播放 → **未接通、未验收**。
- 依赖浏览器链路的时间/性能指标（首声延迟、停播延迟、端到端）→ **未验收**（仅服务级基线已登记）。
- 观察项：原生全双工 VoiceChat-11B → `first_release=false`。

## 5. 浏览器环境可用性评估（M1 前置）

| 能力 | 可用性 |
|---|---|
| Node v22.22.3 / npm 10.9.8 | ✅ |
| `webui/node_modules` 与 **vitest**（`npm test`） | ✅ 可运行（验证：`src/core/clipboard.test.ts` 7 passed） |
| 前端**纯逻辑**（重采样/队列/事件编解码/VAD 决策）验证 | ✅ 可用 vitest 单测 |
| 真实**麦克风/扬声器**、`getUserMedia`/`AudioWorklet`、真实延迟 | ❌ 当前环境不可验证 → 列**未验收** |

> 结论：M1 前端可推进**可测纯逻辑层 + vitest 单测**；**真实设备与延迟一律不得以单测结果冒充验收**。

## 6. 最终确认

- 阶段声明与证据分级**一致**；变更范围与提交清单**已确认**（精确路径）。
- 本次变更**不扩大首版范围**；163 条需求与 R01–R20 追溯不变。
- 审查发现 R-1/R-2/R-3 已修复、R-4 已清理（`docs/REV-…`），回归 **232 passed**、`ruff` 全绿。