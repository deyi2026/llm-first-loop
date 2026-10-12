# Evidence Recoverability R2 — Frozen Execution Pack v1

Date: 2026-08-26
Status: **FROZEN BEFORE FIRST REAL PROVIDER REQUEST**
A3 status: **STOPPED / NOT PART OF R2**
Production Evidence mode: **unchanged / not activated by this experiment**

## Frozen experiment

R2 is a paired fresh-provider effectiveness confirmation for the upstream Evidence recoverability fix. It compares:

- **B0** legacy compacted projection with no stable exact recovery handle;
- **E1** the same task/source bytes with provider-neutral Recovery Manifest + `read_evidence`.

The source action remains available in both arms. R2 contains no Action Guard, duplicate suppression, or model-visible anti-repeat rule. F6 is a freshness-change control that requires a legitimate new source read, preventing "never reread" from being scored as success.

## Frozen matrix

- providers: MiniMax `MiniMax-M3`, DeepSeek `deepseek-v4-flash`
- seeds: F1..F6
- conditions: B0 / E1
- repetitions: 3
- total: **72 real-provider runs**
- fixed shuffle seed: **20260826**
- matrix SHA-256: `de47c6b4ce322561f12ffa6bd68eff815a828607833b4c899a6fcf8ed8205dcf`
- fixture bytes SHA-256: `f00e268dc1fa3c621ad4e46346352f002f4e049b37808eeeebe23229b2ed0135`

The machine-readable artifact lock is `tests/fixtures/evidence_r2/frozen_v1.json`. The real runner verifies every frozen artifact hash before any request.

## Dry verification before freeze

Final dry execution using the same runner path:

- 72/72 execution PASS
- reusable E1 F1..F5: source executions = 1, bounded Evidence hydration exercised across the ~13K observations
- F6 E1: old v1 capture -> stale -> one legitimate v2 source refresh -> hydrate v2
- B0 dry behavioral baseline: source action re-executed; no `read_evidence`
- F4 E1: duplicate side-effect count = 0

Frozen scorer dry result passes every preregistered gate. Dry B0 behavior is not itself a gate; it is the paired observational baseline.

## Frozen scorer

`score.py` was implemented before the first real request. It mechanically scores:

- E1 safety: duplicate side effects / stale-as-current;
- reusable exact-answer rate;
- reusable source-once rate;
- Evidence hydration usage among successful reusable runs;
- F6 legitimate refresh per provider;
- B0 vs E1 reusable source-reexecution rates;
- Wilson 95% intervals and conservative interval for the paired rate delta.

Behavioral failures are data and do not abort the 72-run execution. The real runner retries only an `INFRA_FAILURE`, at most once under the identical frozen row, and continues scoring only after the full matrix is available.

## Protocol correctness

The runner preserves one assistant message containing the provider's complete tool-call list, then appends one matching tool result per call. DeepSeek `reasoning_content` is carried back on tool-call turns when present. This avoids assuming only one tool call per model round.

Every source execution is subjected to the same projection rule; repeating a source action never bypasses projection. E1 receives a new stable EvidenceRef for each new acquisition; B0 receives the same legacy compact notice.

## Atomic real-request preflight

Before a real `--all` run, the runner must pass both checks **before request #1**:

1. every artifact in `frozen_v1.json` still matches its SHA-256;
2. credentials for **both** frozen providers are available.

This prevents a partially executed matrix caused by one missing provider key.

Freeze-time process environment did not auto-export the provider keys, but a secret-safe presence check subsequently confirmed that repository `.env` contains both `MINIMAX_API_KEY` and `DEEPSEEK_API_KEY`. Loading `.env` into the real-run subprocess satisfies the atomic credential preflight without changing any frozen experiment artifact. No key value is recorded in R2 artifacts.

The runner also writes each completed real row atomically to `data/audit/evidence_r2/real_runs_v1/<run_id>.json` and resumes already completed rows. This is crash recovery only; it does not change fixtures, ordering, scoring, or the provider conversation for any row.

## Verification

- R2 unit tests: **6/6 PASS**
- targeted Ruff: **PASS**
- targeted Pyright: **0 errors / 0 warnings**
- final 72-run dry matrix: **PASS**
- frozen dry scorer: **PASS**
- prior full Evidence regression before final freeze: **97/97 PASS**; final post-freeze regression is run separately as an integrity check.

## Next action

When both provider credentials are available in the same execution environment, rerun the readiness snapshot, allow the atomic preflight to verify the frozen pack, execute all 72 real runs, and apply the already-frozen scorer. Do not alter fixtures, matrix, runner, scorer, gates, A3, or provider-specific recovery wording after this freeze.

## Infra-only amendment v1.1

After the first real batch began, `R2-011` exposed a runner classification defect for a model-supplied invalid EvidenceRef. The batch was paused after 13 persisted rows; the permitted infra-only amendment is recorded in `docs/RECOVERABILITY-R2-INFRA-AMENDMENT-v1.1.md`. Fixtures, matrix, scorer, gates, prompts and tool schemas are unchanged. The frozen machine lock was updated only for the v1.1 runner/test plus amendment record before resume.
