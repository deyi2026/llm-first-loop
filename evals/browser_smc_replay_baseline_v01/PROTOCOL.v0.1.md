# PROTOCOL v0.1 — Browser SMC replay baseline (M6, FR-5c / Q6)

Frozen metric definitions for the mechanical replay of persisted browser
action receipts, diff groundings and semantic operation cards. Source of
truth for the acceptance wording in `docs/DESIGN-20261007-browser-semantic-guard.md`
(M6: "eval 重放基线：每步全取次数 / verdict 分布 / diff 可比率；含 Q6 兜底报表口径").

## Corpus (read-only inputs)

| surface | path | schema |
|---|---|---|
| action receipts | `data/browser_action/*/*/receipts.jsonl` | `smc.action_receipt.v0.1` |
| diff groundings | `data/browser_perception/diffs/*.json` | `smc.browser_diff_grounding.v0.1` |
| semantic op cards | `data/browser_semantic_operation/*/*.json` | response cards |

Malformed rows/docs are counted under `sources.malformed` and never raise.
An action's terminal receipt = the max `receipt_seq` row of its store
(append-only store contract).

## Metrics (pre-registered)

### 1. captures per step (每步全取次数)

`captures = (1 if before_version else 0) + (1 if after_version else 0)` on the
terminal receipt, aggregated as n / mean / median / max / histogram, split by
action status. **Boundary (honest):** this counts only receipt-chain full
captures (the mechanical action surface FR-1/FR-5b optimize). Model-initiated
`perceive` snapshots are not persisted and are outside this metric.

### 2. verdict distribution (verdict 分布)

- `action_status`: terminal status counts (`ok` / `rejected` / `failed`).
- `rejection_classes`: `completeness.reasons[0]` of rejected receipts.
- `failure_reasons`: class token of `retry.reason` (before `:`) of failed receipts.
- `guard`: receipts with a `guard` key classify as `pass` / `pass_exempted`
  (FR-1 exemption observable) / `reject_timeout` (reason starts `guard_timeout`) /
  other raw verdict. Receipts without the key count as `not_recorded`.
- `wait`: receipts with a `wait` key classify by `wait.verdict`
  (`settled` / `timeout` / `unavailable`); others `not_recorded`.

**Era honesty (hard rule):** `not_recorded` buckets are never folded into
verdict counts and never read as a verdict (e.g. pre-FR-1 receipts are not
"zero guard rejects"). Reports carry `era_note` stating this.

### 3. diff comparability (diff 可比率)

Terminal receipts with `observed_effects.diff_ref` resolve
`grounding://browser/v0.1/{to}/diff/{from}` against the diff docs:

- `comparable` / `not_comparable`: `canonical_diff.comparable` true/false.
- `doc_missing`: referenced diff doc absent (retention expiry) — excluded from
  the ratio denominator, reported separately.
- `not_available_no_diff_ref`: no diff at all (pre-capture rejections).

`ratio = comparable / (comparable + not_comparable)`. Not-comparable causes
split `canonical_diff.reason` on `;`. The FR-5b inline
`observed_effects.diff_summary` is reported in its own bucket
(`comparable_true` / `comparable_false` / `comparable_unknown` when the
`comparable` key is absent) with its own `not_recorded` counter.

## Q6 fallback report policy (兜底报表口径)

Report-only. The replay emits `anomalies` (failed actions, non-comparable
diffs capped at 20) **for model review**. No pass/fail gates, no automatic
judgment, no automatic lesson filing: per the closed Q6 decision the model
reviews anomalies and files lessons itself; the program stays mechanical.

## Runner

```
python3 evals/browser_smc_replay_baseline_v01/replay_baseline.py [--tag TAG]
```

Writes `results/baseline_<tag>.{json,md}` and refreshes `results/latest.json`.
Unit tests: `tests/unit/test_browser_smc_replay_baseline_v01.py` lock the
metric definitions on a synthetic mixed-era corpus.
