# Restart continuity main integration — 2026-10-07

The minimal current-main candidate passes its scoped validation, independently prompted GLM-5.3 static review, and one native recovery requalification. It is ready for the user-authorized fast-forward integration; the actual merge receipt is retained after execution. Production publication/restarts remain deferred until the original FR-1 T+24h first review passes.

## Change and identity

Base main: 424b298f255f1ad52e1bfb33a09b31eff0703b82. Original isolated product repair 9c4e259a278f9910dce324a62f6914165960fa12 was transplanted as 8be397460dee04d1f618791bda8b1aa545832c3e. Registration/final evidence commits change only documentation and validation records after that product commit. The tested native source HEAD is 141952c66029711cefd729ebdb3f8ad0e695c5ba; source hashes are recorded in evals/restart_continuity/results/main-integration-20261007.json. The original experimental branch's other 166-file delta was not integrated.

At genuine human ingress, the engine persists only the opaque identity of the completed visible answer that was already eligible. On restart, recent_continuity may cross matching contiguous output-free human ingresses; the first prior output must be that exact proven completed answer. Program/tool/partial/delegated output, missing/mismatched anchors and legacy unanchored pending histories stay fail-closed. Historical retired human instructions and hidden reasoning do not acquire provider authority.

## Verification

| Check | Actual result |
|---|---|
| Focused adjacent regression | 90 passed |
| Full non-real-LLM pytest after Web UI build | 7,508 passed; 3 failed; 116 skipped; 16 deselected; 309.02 s |
| Exact-main failed-file baseline with same UI artifact | The same 3 failures; 59 passed |
| Changed source/tests Ruff, compile, environment declaration | PASS; env declaration scanned 733 test files |
| Full Ruff comparison | Candidate 50; extracted baseline 52; zero introduced; 2 context-only import diagnostics differ in byte-identical files |
| Full Pyright comparison | 40 errors on both, identical diagnostic fingerprints |
| Independent supplementary GLM-5.3 static review | HTTP 200, model glm-5.3, terminal stop, visible PASS; low effort; full original inputs and receipts retained |
| Native GLM-5.3 pre-dispatch crash/restart | PASS: 22 mechanical checks and 9 unchanged oracle checks |

The full suite initially reported 9 failures (7,502 passed): 3 safety environment failures, 5 Web UI 404 failures and 1 idle-timeout test failure. The exact main failed-file baseline reproduced the 3+5 failures with the same missing UI artifact; the idle test passed both baseline/candidate focused reproductions. A real candidate Web UI build resolved the 404 environment, and a full repeat retained only the 3 exact-baseline failures. All first-run logs are retained; no test assertions or safety guard were changed.

The remaining safety failures are test_evo1_home_subpath_allowed_home_itself_blocked, test_rm_rf_tilde_subdir_allowed and test_rm_rf_home_var_subdir_allowed. The managed HOME is within /var, while the existing guard blocks destructive /var paths. HOME was not overridden and the guard was not weakened. Full CI/static status remains failing due to the recorded baseline debt; this report does not claim green CI.

The first max-effort GLM review received no provider response and timed out; the single identical-input streamed replacement exhausted 16,000 tokens with empty visible output. Both remain UNKNOWN. No private reasoning is used as a verdict. A separately registered identical-input low-effort review yielded a valid PASS without receiving prior validation outcomes. Its two low findings are fail-closed feature/persistence limits, not introduced defects: intervening program notices prevent restoration by contract; absent durable proof prevents crossing. Normal non-queued durable ingress is covered by the fresh-engine one/two-crash tests and event metadata serialization. This is static model review with documented unshown-dependency limits, not an owner signature, formal independent gate approval or an execution claim.

## Native wire evidence

One fresh run, no automatic rerun, retains the original case/oracle/protocol SHA256s from the pre-registered public native recovery case. A private byte-identical 23-file harness copy points through its native clean_env PYTHONPATH to this main candidate; the resolved source paths and hashes were verified.

Same persisted native session: 764a3835-4a0d-46ad-bcca-a3436fd786f3. Nine observer POSTs comprise 3 local non-generation probes, 1 captured pre-dispatch cancellation with zero upstream/tool effects, and 5 actual GLM-5.3 generations (all HTTP 200). Every generation uses max_tokens=16000 and reasoning_effort=max. Native cell wall time is 25.6901 s.

Resumed request roles are system/user/assistant/user. The exact remembered visible assistant fact QR53-H7K2-checked reaches the resumed provider wire. The removed input remains absent; native resume writes the exact result (total 227) once, without removed-input reread or execute_python. All owned process groups are removed and the container is quiesced then removed. No length truncation; final terminal stop.

Native usage: prompt 5,340; completion 531; total 5,871; cached prompt 4,352; reasoning 286 is a subset of completion, not additive. Actual coding-plan monetary cost remains UNKNOWN. Code-review usage is separate in raw receipts.

## Durable evidence and rollout readiness

LFL-GLM53-main-integration-evidence-20261007.zip: 473,135 bytes, 133 manifest-verified files, SHA256 65c4f618f3d9527c0d11367b02e65e556569b35deecee841e539cce2ca0ea702. Credential-byte scan passed. Durable reference: libfile_0ad23f4bbc2081919010b27413a45d5f.

See PLAN-20261007-restart-continuity-rollout.md for the entire live→candidate source census, effective configuration/model invariants, monotonic-generation managed CAS, Web→Feishu→Learning sequence and precise per-service rollback. Two clean detached rollback source worktrees and exact previous Web UI artifacts have passed read-only deployment-binding checks. Candidate artifact SHA256 equals the original artifact. Runtime processes, desired gen 181 and config remain unchanged during integration; root's existing working-tree changes are preserved.

The FR-1 read-only first review is scheduled at 2026-10-07 20:00 Asia/Shanghai. Follow-up rollout must wait for fresh durable PASS evidence; a clock time or T+0 record alone is insufficient. Full CI debt remains explicit and no safety/idle gate is bypassed.

Scope limits: this known public native pre-dispatch SIGKILL/restart case does not qualify remote in-flight cancellation/reconnect, partial streams or migration of old unanchored pending data. Earlier exact-output smoke failures, formal harness design gates/owner declarations and score 76 remain unchanged. No push, formal comparative run or production restart is performed by this evidence package.
