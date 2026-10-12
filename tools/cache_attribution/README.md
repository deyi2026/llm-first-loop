# Cache Attribution Scorer — 离线事实重放器 + 机械分类器

> 合同：输入冻结快照，输出 `schemas/cache_attribution_report.schema.json`（v1.0.0-draft2）。
> 语义规范：`docs/cache-attribution/schema.md`。
> 角色锁死：**不是策略层**。不读墙钟、不读环境、不输出任何"应该怎么办"。

## 组成

| 文件 | 角色 |
|---|---|
| `freeze.py` | 冻结源日志 → `extract.jsonl` + `manifest.json`（sha256/seq watermark/快照时刻=源 mtime 最大值，非墙钟） |
| `scorer.py` | 重放 + 分类 + 记账 + reconcile 自检；`score` / `verify` / `golden` 三个子命令 |
| `fixtures/51da0a7a-frozen/` | 真实会话冻结快照（过滤白名单：request.usage / request.meta / history.compaction / message.cache_compacted） |
| `fixtures/golden/51da0a7a.golden.jsonl` | Golden Regression 基线（220 请求，222 记录） |
| `tests/test_gates.py` | 七道 Gate，13 个测试 |

## 用法

```bash
# 1. 冻结（源可以是活会话目录；冻结后源怎么变都不影响已冻结结果）
python3 freeze.py <事件日志目录> <输出目录> --session-id <sid>

# 2. 产出报表（任意次重放，逐字节一致）
python3 scorer.py score <frozen_dir> -o report.jsonl

# 3. 仅验 Snapshot Gate
python3 scorer.py verify <frozen_dir>

# 4. Golden 回归（分类器/估算器任何行为变更必须 bump 版本 + --update 重产 golden）
python3 scorer.py golden <frozen_dir> <golden.jsonl>          # check
python3 scorer.py golden <frozen_dir> <golden.jsonl> --update # 显式重产

# 测试（两种跑法等价）
python3 tests/test_gates.py
python3 -m pytest tests/ -q
```

## 七道 Gate ↔ 测试映射

| Gate | 测试 |
|---|---|
| G1 Snapshot | `test_g1_snapshot_gate_rejects_tamper`（篡改→exit 2）；`test_g1_snapshot_gate_source_growth_irrelevant`（源增长不改冻结结果） |
| G2 Determinism | `test_g2_determinism_three_runs_byte_identical` |
| G3 Classification | `test_g3_real_session_manual_cases`（三组人工对账案例 + 分布）；synthetic route_switch / unknown / co-occurrence |
| G4 Accounting | `test_g4_reconcile_identity_and_rollup`；`test_g4_negative_excess_never_silent_gain`（负值只走 clamp） |
| G5 Controllability | `test_g5_eviction_never_controllable`（eviction 不进 controllable；rollup 重算对账） |
| G6 Idempotence | `test_g6_fixture_untouched_and_output_stable`（fixture 目录 hash 前后一致） |
| G7 Golden | `test_g7_golden_check_passes` / `test_g7_golden_drift_fails`（篡改 golden → exit 1） |

## 实现中锁死的结构证据规则（含实测教训）

1. **meta(N) ↔ usage(N) 按 seq 配对**（meta 在自身 usage 之前、上一 usage 之后；round 一致性）。不用墙钟配对。
2. **C1 route_switch 判据 = (model, provider)**。`provider_structure_fp` 是**逐请求**指纹（实测 221 请求 221 个值），进入 C1 会全场误判——已从判据中剔除。
3. **C4 fold 执行证据 = paired meta 的 `folded_results` 严格增加**。`fold_triggers` 非空只是 armed 状态（11:51:30 / 13:31:11 两度实证：armed 但未执行，折叠被 net-gain 门控挡下）。
4. **C5 eviction 三前提缺一不可**：`stable_prefix_fp` 未变 ∧ `prefix_changed=false` ∧ 无本地边界，且 hit=0 或 hit < 0.5×stable_prefix_tokens。会话首请求（无前驱）不判 eviction。
5. **types 含 `provider_eviction` → controllable 强制 `no`**，即便 primary 是 `new_run_cold_start`（冷启动 + TTL 驱逐共现时，excess 属服务端）。
6. **v1 excess 只记 primary**，不做多机制比例分摊（防滑向不可验证的反事实模型）。
7. **时间窗只生成 candidate，结构字段才能定案**；C3 用日志序窗口 `(prev_usage.seq, usage.seq]`，强于墙钟邻近。

## 真实基线（fixtures/51da0a7a，2026-09-14 晚间，glm/glm-5.3）

```
220 requests | tokens_in 4,785,906 | hit 4,188,864 (87.5%) | observed_miss 597,042
expected_append 336,211 | boundary_excess 266,502
  controllable    199,949   (compaction 126,937 + fold 73,012)
  uncontrollable   59,065   (eviction 29,079 + 4×TTL 冷启动驱逐 29,952 + 34)
  partial            7,488   (会话首请求冷启动)
  unknown                0
storm_cluster: 13:29:30→13:32:13, 4 txns, excess 75,611
```

三组人工对账案例（用户已逐条人工核实）：
- `11:47:49` → working_set_fold，excess 7,863
- `13:30:24 / 13:31:11 / 13:32:28` → history_compaction，excess 22,098 / 22,610 / 8,199
- `11:51:30` → provider_eviction，excess 29,079（uncontrollable）

## 版本化纪律

- `CLASSIFIER_VERSION = "v1-precedence"`、`ESTIMATOR_ID = "v1-linear-append"`、`SCHEMA_VERSION` 任一变更 → 必须显式 bump + `golden --update` + 提交说明，否则 G7 直接失败。
- 估算器参数（block 64 / growth_fallback 512 / stable_prefix 7488 fallback）被 golden 锁定；`--stable-prefix-tokens` 覆盖后必须重产 golden。
