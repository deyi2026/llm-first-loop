# SMC Model-Friendly v02 Kickoff Triage — 2026-09-20

- v01 源：`docs/smc-model-friendly-v01-20260916` @ `55ea9cbe6`（73 commits，61 untracked 已归档
  `lfl-worktree-archives-20260920/smc-model-friendly-v01/untracked.tar.gz`（本机 Project 下归档目录，非仓库内））
- v02 基线：main @ `54b521f90`（PR #51 合并后），worktree
  `.worktrees/smc-model-friendly-v02-20260920`，分支 `feature/smc-model-friendly-v02-20260920`
- 目标：把 v01 的 model-friendly 语义操作线（MF4→MF5.3.4）按批移植到当前 main，
  逐批 TDD 验证；routing 诊断按 ceiling 文档冻结为回归证据，不再复测。

## 批次与处置（73 = 71 移植 + 2 已吸收）

| 批 | v01 commits | 内容 | 处置 | 状态 |
|---|---|---|---|---|
| A | 1-6 | MF4 定义/契约/编译/紧凑回执/边界 halt/AB | 移植 | ✅ 9 commits 无冲突，40 tests 绿 |
| B | 7-9 | MF5 provider source/common runtime/close | 移植 | ✅（并入上） |
| C | 10-21 | MF5.2 认知保全 actuation/wait 语法/lazy 面 | 移植 | ✅ 12 commits 无冲突，40 tests 绿 |
| D | 22-35 | MF5.3 只读架构+双能力面+lazy schema | 移植 | ✅ 14 commits，1 冲突（perceive wait facade 断言）已解，126 tests 绿 |
| E | 36-40 | MF5.3.1 root-direct perceive | 移植 | ✅ 5 commits，2 冲突（root-direct 契约×EVO 投影参数）语义合成已解，93 tests 绿 |
| F | 41-48 | MF5.3.2 capability identity+projection evidence | 移植 | ✅ 8 commits，1 冲突（projection window×quality order）合成已解，96 tests 绿 |
| G | 49-56 | B1 直 DOM 文本 + URL-role 分离 | 49-50 跳过（已由 PR #50 入 main）；51-56 移植 | ✅ 6 commits + 1 v02 适配 commit，60 tests 绿 |
| H | 57-65 | MF5.3.4 grounding-ref 统一 | 移植 | ✅ 9 commits 零冲突，122 tests 绿 |
| I | 66-73 | routing 诊断 R1-R4（A/B invalid + ceiling） | 冻结为回归证据 | ✅ 8 commits 零冲突；见下"冻结边界" |

## 冲突解决记录（语义合成点）

1. **D/#26 facade**：`test_smc_browser_predicate_wait_v01.py` — main 精确集合断言 × v01 wait 枚举，
   合并为全集合+wait。
2. **E/#37 root-direct**：`browser_perceive.py`/同测试 — v01 把 wait `condition` oneOf 重构为
   root-discriminated `_PROVIDER_BRANCHES`；main 侧 EVO-20260918 加了
   `projection_kinds/cursor/vision`。合成：root-direct 分支结构 + union/分支双列 EVO 三参数
   （分支 `additionalProperties=False`，不列则 oneOf 拒合法快照调用）；snapshot handler EVO
   支持保留。对应冻结断言适配见 commit `ef84f24a1`。
3. **F/#45 evidence-quality projection**：`perception.py` — v01 `_model_projection_order()`
   质量序投影 × main 投影窗口（kinds 过滤+cursor 分页）。合成：窗口基序改用
   `objects_projected`（质量序），窗口字段全保留；canonical 序仍按 ID。

## 冻结边界（遵循 ceiling 文档 §8）

- routing 残差以 `77c9cc4c7`（ceiling result）为准：工具名路由与延迟等待的残差不复测、
  不动产线；R2 A/B 结果按 invalid 冻结（并发死锁/数据竞争）。
- tool-name-only、action/do-only、ref-kind binding、Config Authority P1-C 保持独立工作线，
  不并入本 v02 批。

## 遗留与后续

- B1 双 commit（`ba2307bc0`/`058a5ae5e`）已在 main（PR #50），跳过不重复移植。
- routing 复现/A-B 测试绑定旧 v01 worktree 路径者为冻结证据（指向已归档 worktree），
  按 ceiling 不改写；若 CI 路径解析失败再按证据原样原则处理。
- 下一步：全量 pytest + ruff + pyright → PR + A.5 submission manifest（覆盖全部 changed
  paths + manifest 自身）→ 三检查 pass → `--merge --delete-branch=false`。
