# JEV wire optional-type guard — independent GLM-5.3 code review receipt

Date: 2026-10-15. Goal: 9956a550-f1ad-4281-aeb4-a4e797fe85ca.

## Exact authority
- Baseline main commit: `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`.
- Source patch SHA-256: `b31c73f5d8da7d5d001253c10414e59801b1a60b1eeb858bfeb1924a913ed331`.
- Source commit: `c0f577d181bb677109b7ced2b3474a5b1e87eedf`.
- Reviewer model: `glm/glm-5.3`; native private child `subagent_02e85983e7a7` (parent `review-parent-jev-wire-pyright-20261015`).
- Real child state: `completed`; result id `result-2545d6dcf46c40bfb1848d9ebb1c52b1`; EventStore one terminal `de6bfad4-3ce6-4fe3-aec3-3262c1019344`; live handle done and result identity verified.
- Final judgment: **PASS**, P0=0, P1=0, P2=0.
- Exact final candidate SHA trailer, count line and verdict line mechanically checked; `3675` bytes reviewed.
- Raw local JSON (ignored, not shipped): `data/jev-wire-pyright-narrowing-20261015/review-refined/glm-independent-review.json`; raw SHA-256 `a21a403031d3b44361e95db8017a584843f0ce3824d12b30a383cc5ab77a2edc`; answer SHA `4ffbff265b8b42d181312ee7808ce469f90e4428848fe86481b8b0684ad703fb`.

## Review scope limitation

Reviewer was genuinely independent, read-only, zero registered tools, one round, standalone private parent/EventStore, no parent steering. It assessed the exact frozen Git patch and supplied read-only source/SoT context. It **did not** run tests or inspect the full workspace on its own; the current main runner lacks the experimental `review_isolated=True` API, so this is not an OS-isolated guarantee. This approval is **only for source review** and cannot authorize merging main, pushing or deployment.

## Reviewer full judgment

【评审报告：JEV 两文件补丁（main c8e50）】

一、源码改动范围与行为等价性
wire.py 仅在 `_validate_choice` 与 `_validate_score` 的最终有效分支条件上追加 `isinstance(probabilities, dict)` 与 `isinstance(confidence, (int, float))`。由于进入该分支原本已要求 `probs_ok`（只在 probabilities 为 dict 且全部校验通过时置 True）与 `confidence_valid/conf_ok`（由 `_finite_in_unit` 保证，且 `_finite_in_unit` 内含 `isinstance(v,(int,float)) and not isinstance(v,bool)`），新加的 isinstance 判定在运行时恒为冗余真，不会放行任何新 payload，也不会拒绝任何原本有效值。bool 虽然能通过外层 `isinstance(confidence,(int,float))`，但被 `_finite_in_unit` 的 `not isinstance(v,bool)` 前置拦截，最终仍走 `_invalid` 路径并保留原 invalid_reasons。无异常吞路径、无新增 I/O、无路由/网络改动，属于纯静态收窄，符合“仅修 5 个 Pyright 诊断”的授权范围。`float("nan")` confidence 被 `math.isfinite` 拒绝，None 走 `confidence is not None else False` 分支，均保持旧 reason `confidence_missing_or_out_of_range`。

二、测试改动
新增 11 个参数化用例（2×4 confidence + 3 probabilities），直接断言精确 invalid_reason：None/list → `probabilities_missing_or_not_object`；值含 None → `probability_not_finite_or_out_of_unit`。相比此前被指出 P2 的宽泛 `startswith('probabilit')` 匹配，本版改为成员断言（`reason in fact.invalid_reasons`），粒度正确且未弱化既有断言；同时校验 status/置空字段，覆盖了 bool/None/字符串/NaN 的强制转换风险。choices 的 probabilities None/list 情形分别命中 `_validate_choice` 的 else 分支与 keyset 之前的类型检查，断言与实现一致。score 分支 confidence 用例经 `conf_ok=False` 正确落入 `_invalid`。未发现敏感数据。外部提供的 Pyright ratchet（new=0）与 124 项测试通过仅作背景采信，未亲自运行。

三、结论
无行为改变，无 P0/P1 阻断项。可选改进（非阻断）：a) probabilities 参数化可补一条合法但 sum 偏差的用例以锁住 sum tolerance 行为；b) 测试中 `_choice()`/spec 构造存在少量重复，可提取 fixture。均不影响本次合入。

VERDICT: PASS
P0=0 P1=0 P2=0
SHA256: b31c73f5d8da7d5d001253c10414e59801b1a60b1eeb858bfeb1924a913ed331

## Status

See `docs/results/RESULT-20261015-rule31-jev-main-c8e50-r9-closure.md` for independently executed Quick, full R9, known-red history and release boundaries.
