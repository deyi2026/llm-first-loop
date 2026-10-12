# BEHAVIOR-BASELINE-R824（行为基线固化）

> **状态**: 已固化（fixed-point 达成）
> **固化时点**: 2026-09-01（R9 第 1 批 Phase 0 三批切换收口）
> **快照层**: `tests/fixtures/wire/baseline-r824/baseline-snapshot.json`（内容寻址元数据）
> **约束（spec §6.1）**: **Phase 3-7 期间本基线只读**——后续重构提交以本基线为对照，任何修改基线语义的变更须先解除本约束并登记理由。

## 1. 三批切换回执链

| 批次 | 门 | commit | 翻转面 | 观测回执摘要 |
|---|---|---|---|---|
| 1/3 capsule | H4 | `79376ef` | `evidence_enforce.py:40` on→off | W1: 完成 7/7·dup 0%·read_file 21 与基线持平；episode hydrate 6 次 success；CORE9 终判对齐 |
| 2/3 guidance | H3 | `cfda166` | `registry.py:40` on→off | W2: 完成 4/4·dup 4.3%·失败自恢复 3/3 零 advisory 依赖（事实性回执驱动）；元认知区分"诊断保留/引导退出" |
| 3/3 perf | H6 | `6a137ef` | `guard.py:56` on→enforce | W3: 完成 5/5·guard 判定 63 条全 ALLOW（would_block=0 零误拦）·失败自恢复 6/6；privacy BLOCK 照旧 |

每批独立可 revert；批间以观测回执为门（B1-P0-02/04/06 判读全达标，回执见 `.codeartsdoer/specs/r9_arch_refactor/b1-execution-log.md` §6-§10）。

## 2. 六门实测终态（对照终验报告 §1 原 3 PASS/3 FAIL）

| 硬门 | 默认态实测 | 判定 |
|---|---|---|
| H1 wire 程序散文 chars | =0（zero_prompt 9+5 + GATES 组二 2 用例承载） | **PASS** |
| H2 潜语义通道 chars | =0（LATENT off；latent_channel_exit 10 用例 E-G1~G6） | **PASS** |
| H3 advisory chars | =0（guidance off→四源 chars=0） | **PASS**（翻转） |
| H4 capsule chars | =0（capsule off→complete 回执无拼接） | **PASS**（翻转） |
| H5 suspect provenance chars | =0（quarantine 生效 + guard enforce fail-closed） | **PASS** |
| H6 性能类 BLOCK | =0（enforce→WARN/submit_ratio_perf/would_block=True；privacy 五类硬拦照旧） | **PASS**（翻转） |

七开关终态：guidance=off / capsule=off / leak_quarantine=off / leak_guard=enforce / latent=off / cog_freeze=1 / perf_block=enforce。

## 3. 常驻断言层（基线的测试承载）

- `tests/unit/test_r824_final_gates.py`（GATES）13 用例翻转后形态全绿——三开关默认值 + 六门机制双面锚点
- `tests/fixtures/wire/` 6 fixtures + `test_wire_fixtures.py` 47 用例（wire 层对照）
- 六门承载全集 99 用例全绿（GATES + zero_prompt 9+5 + latent_channel 10 + factualization + reclassification + quarantine 22）
- 全量 xdist 0 failed（外部级 2 项除外：D-07/D-08，均外部混合层中间态，与本批零关联）

## 4. 复现口径

```bash
uv sync --frozen --extra dev                       # B1-IMM-03 可复现安装
env -u LFL_TOOL_GUIDANCE -u LFL_EVIDENCE_CAPSULE -u LFL_LEAK_QUARANTINE \
    -u LFL_LEAK_GUARD_MODE -u LFL_LATENT_CHANNEL -u LFL_COG_ENFORCE_FREEZE \
    -u CACHE_GUARD_PERF_BLOCK \
  .venv/bin/python -m pytest tests/ --dist loadfile -n 8   # 干净进程全量（B1-WF-02）
bash scripts/ci_gate.sh                             # 三件套门禁（B1-WF-03）
```

活体 API 基线跑（`scripts/run_fixture_baseline.py`，本地 27B，单轮 10-30min）为可选补充手段，不属本静态快照层（偏差 D-10：tasks.md 对该脚本"生成快照"的描述与实际活体跑功能不符，以实际代码为准）。

## 5. 附录：B/E19 残口登记表（B1-P0-08）

| 项 | 状态 | 证据 |
|---|---|---|
| B 包：wire 零程序注入（动态） | **已闭合** | test_runtime_zero_prompt.py 9 用例全绿 |
| B 包：wire 零程序注入（静态） | **已闭合** | test_runtime_zero_prompt_static.py 5 用例全绿 |
| B 包：loop mixin 拆分 B 相关断言 | **已闭合** | test_loop_mixin_split.py 全绿（`_base=1361` 旧守卫退役属 Phase 2，本批不动） |
| E19：潜语义通道退出（E-G1~G6） | **已闭合** | test_latent_channel_exit.py 10 用例全绿 |
| E19：producer 注册表 census | **已闭合** | 干净进程实测三授权槽 `{memory_authorized, program_recovery, task_active}` 在场；7 类幽灵 producer（memory/tip/hotcard/gate_note/anchor/digest/experience）零注册 |
| E19：canary（E5⑪） | **本批解除**（见 §6） | R8.24-E-latent-semantic-channels.md:209-212 批条款；三门翻转+终验全绿+观测达标 |

**未登记的开放残口零带入重构期**（验收 R9-P0-06a）。

## 6. canary 解除与 R9 解锁（B1-P0-09 / R9-P0-05）

- 三门翻转完成（79376ef / cfda166 / 6a137ef，每批独立可 revert）
- 终验重跑全绿（六门承载 99 用例 + 全量 xdist）
- 三窗口观测达标（§1 回执链）
- **判定：behavior canary 解除 BLOCKED；R8.24 fixed-point 达成；R9 结构重构（Phase 1/2 前置 → Phase 3+）解锁**

## 7. 基线外遗留观察项（不阻塞，Phase 1+ 可复评）

| 项 | 来源 | 说明 |
|---|---|---|
| r5/r9-replay runner 未钉 capsule | D-06 | 同族启用 enforcer 但无测试门禁、real 数据已固化，未动 |
| flip_task.py 跨节计数错位 | D-09 | 已弃用改手工；待修复 |
| 外部级 D-07/D-08 | §3 | 外部混合层中间态（factory.py 超基线 / SUMMARY_MODE flaky），入库后自愈或 Phase 1 清偿 |
| 活体 API 基线跑 | D-10 | 可选补充，依赖本地 27B 服务 |