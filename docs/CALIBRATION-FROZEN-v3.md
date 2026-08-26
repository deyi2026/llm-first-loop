# Calibration Measurement Freeze v3

> 状态：**C0 MEASUREMENT FROZEN — READY FOR C1 PRE-REGISTRATION**
> 说明：v2 继续作为 C0 raw experiment input freeze；v3 冻结 C0 后校准得到的 scorer-v1.1。
> C0 raw MiniMax outputs 未重跑、未修改；仅 scorer regrade。

## 1. Measurement Decisions

- `task_success` 与 `novel_stage` 解耦。
- N4 严格要求 N3 前置；无实际 source request 不得判 N4。
- 合法 DRU 跳过验证记录 `verification_waived_decision_irrelevant=1`。
- stale/ambiguous 判定从“字符串出现”改为“明确采信/晋级”。
- Cohen kappa 在全 positive marginal 下报告 undefined，不伪造 0.000。

## 2. C0 v1.1 Result

```text
task_success: 30/30
fatal: 0/30
constraint: 0/30
novel: N4×29 / N2×1
blind agreement (task/fatal/constraint/stale/source-conflict): 30/30
```

## 3. Governance

- v1 scorer/reports 已在 `data/calib/runs/scores.pre-v1.1.json` 与 `report.pre-v1.1.json` 保留。
- C1 首个 DeepSeek 请求前必须独立 pre-register。
- C1 开始后若修改 scorer-v1.1，必须 version bump；禁止边看 DeepSeek 结果边调 scorer。
- 本 freeze 不产生任何 Architecture effectiveness / global promotion claim。

## 4. SHA-256

| Artifact | SHA-256 |
|---|---|
| `scripts/calib/scorer.py` | `5f832313b273ff28b69189a1ce273e20a294f010052a9c49781102ca840a3b50` |
| `scripts/calib/run_calib.py` | `62e19e744b004106ab9d40aa8ca01f898f58f688d90b1d84806c5921a6f3dec1` |
| `tests/unit/test_calib_scorer.py` | `6c0e0e14a1a103447f4b638f2f501256eb10740bf1efd272e1c5184fa5805f88` |
| `docs/CALIBRATION-SCORER-v1.1.md` | `ec8bdd09a23951fe922f601b10b39ffe9e54d75577a78f8e969e116c082513dd` |
| `docs/CALIBRATION-C0-RESULT-v1.1.md` | `06aaa7a9a25ed78e4d28b035d373a0457c94f96420182db5dac9b90d67b501f2` |
| `data/calib/blind_review_adjudication-v1.1.json` | `290c22406307576f76cfe7f9df958f14641cd6412fba02ed6a7aac1f4af7dc90` |
| `data/calib/runs/report.json` | `22642d5728bb64349f01ca5ac754ebb87b86224851e17e8f2f2be75e4ff59e1a` |

## 5. Next

```text
C0: COMPLETE / GO-WITH-REVISIONS
C1: PRE-REGISTRATION NOT YET FROZEN
Next action: design and freeze C1 DeepSeek cross-style calibration fixture family before any request.
```
