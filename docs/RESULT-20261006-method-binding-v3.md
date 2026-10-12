# RESULT-20261006 Method Subject-Binding v3 — 确证实验终局（line retired）

Date: 2026-10-06
Status: **FINAL — 预冻结判据已裁决，研究线关闭**
预注册: `docs/SPEC-20261005-method-binding-efficacy-preregistration.md`
确证 SPEC（冻结）: `evals/method_binding_efficacy_v3/confirmatory_provider_v1/SPEC.md`
权威数据: 同目录 `RESULT.json` / `SYNTHESIS.md` / `matrix.jsonl` / `status/`
落库: commits `5f0b794f9`（92/92 证据 + 审计）→ `b03e89968`（merge main）

---

## 1. 结论

**Disposition: `EFFICACY_NOT_QUALIFIED`。`production_promotion_authorized = false`。**

两个模型（strong=deepseek/deepseek-v4-flash，weak=cognilocal/qwen3.8-flash-next）方向性
均为正向，但都未达到预冻结 efficacy 阈值（net_flip ≥ 3 且 negative_flip ≤ 1）：

| model | challenge C0→C1 | +flip | −flip | net | 阈值 | 结果 |
|-------|----------------|-------|-------|-----|------|------|
| strong | 7/17 → 9/17 | 4 | 2 | 2 | net≥3 且 −≤1 | **FAIL**（两项均未达） |
| weak | 9/17 → 11/17 | 2 | 0 | 2 | net≥3 且 −≤1 | **FAIL**（net 差 1） |

护栏（reverse-risk / safety / cost）双模型全部 PASS：strong reverse-risk 4/6→6/6、
weak 6/6→6/6，new_harm=0；OTHER=0、technical retry=0、experience artifact 22/23 达标线全部满足；
token ratio 1.0205 / 1.0448（≤1.10）。

机械完整性：92/92 全部 attempt0、全部 mechanically_healthy=true、无 reserved、无重放；
92 行模型身份精确、binding 断言与臂一致、settlement/run.end 全通过。

## 2. 证据链（全链预冻结，无期中聚合）

1. dev 机会校准（C0-only, 44/44）PASS：v2 失败归因于测量任务过易，非机制无效
   —— `behavior_protocol_v2/RESULT.json`（freeze sha `c98d1810…`）
2. fresh confirmatory holdout 双盲标签资格 PASS：R1/R2 agreement=1.0、κ=1.0、
   challenge 双认证 17/18、reverse-risk APPLY 6/6、anti-leak=0
   —— `confirmatory_holdout_v1/LABEL-RESULT.json`（sha `1411bb01…`）
3. 确证 SPEC/provider-preflight 冻结（provider_calls_at_freeze=0）
   —— `confirmatory_provider_v1/FREEZE.json`（source_commit `e347fe3fa`）
4. 92-cell 正式矩阵一次性跑完（2026-10-06，LFL 接力执行 64–92）
   —— `matrix.jsonl` + `status/092` 终态文件
5. 一次性 `analyze.py` 裁决 → `RESULT.json`（schema `subject-binding-v3-confirmatory-result/v1`）

## 3. 为什么严格 no-promotion

- 阈值（net≥3、−≤1）在 provider 消耗前冻结于 SPEC.md，且 dev 校准已证明该幅度
  在机会带上"结构可达"（dev C0 负向错误集中在三个 family、0.45–0.80 难度带）；
  本次 strong −flip=2 超限、双模型 net=2 均差一档。
- 预注册判据不得事后放宽；任何"只差一点"的弱推广（如仅 strong 挂 flag、
  降阈重判）都会使整条证据体系失效。正向方向性信号只登记为后续研究线索，
  不构成生产依据。
- 生产状态不变：`LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL` 维持实验 flag 缺省 off，
  生产 surface 无任何变更（FREEZE.json production_mutations=0 全程成立）。

## 4. 线的处置与 reopen 前置条件

研究线 **retired**（worktree 已移除、分支已删、证据全量在 main）。
当前 23 例 holdout 已被确证消耗，不可复用。reopen 必须同时满足：

1. 修复生产 record_use 决策遥测缺口（自然 closeout 回路中 method 使用决策不可观测）
   —— 已登记 `experience:EXPERIENCE-20261006-record-use-subject-binding-reopen`（前置①）
2. 全新 fresh holdout + 全新预冻结 SPEC（含本次实际难度带信息，重新论证阈值可达性）
3. 明确的 operator 授权重新开线

## 5. 与预注册 SPEC-20261005 的关系

SPEC-20261005 是本线最早的 2×2 单模型预注册（40/arm）；执行前经 dev 校准
升级为 v3 双模型 92-cell 自然 closeout 设计（冻结于 eval SPEC.md）。
两版判据均未在本结果中被放宽或替换；本文按最终冻结版 SPEC 裁决。
