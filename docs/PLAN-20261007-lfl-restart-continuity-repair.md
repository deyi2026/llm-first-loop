# LFL pre-dispatch restart continuity repair — 2026-10-07

User authorization: the latest instruction “需要修复” authorizes necessary product changes on the isolated candidate. This is an explicit change to the earlier FR-1 source-freeze boundary for this candidate only. Main, service generations, deployment, and scheduled FR-1 review remain unchanged. GLM-5.3 is the only live model authorized.

Baseline: b4a59b65c9588f0b933b0cc80bdcf98fe945771b, retaining the failed original recovery qualification and its evidence. Candidate remains chore/harness-evidence-20261006.

## Cause and ownership

The failed native recovery kept the read receipt and completed answer in durable history. Episode retirement removed their default provider eligibility. Existing recent-continuity correctly restored the final answer before the crash, but stopped at the output-free user ingress recovered after restart. The second human boundary therefore hid the very same answer. This is an adjacency failure, not missing persisted facts.

Repair reuses recent_continuity and the existing stable completed-episode identity. At genuine human ingress, before message.appended, the engine records the opaque identity of the completed answer already eligible at that moment. On restart, only contiguous output-free ingresses carrying that same anchor can be crossed; the first preceding output must be that exact proven completed model answer. Missing/invalid/mismatched anchors, program/delegated/interrupted answers, and intervening tool or assistant output block recovery. Legacy pending ingresses remain fail-closed. No semantic interpretation of “continue,” answer extraction, summaries, or new action authority is introduced.

Only existing bounded visible-assistant projection is reused. Hidden reasoning, old resolved human instructions, tool protocol, episode retirement, and current user intent keep their existing contracts. Pending user text already eligible in native history is not relabeled or scrubbed.

## Verification registered before live calls

The deterministic reproduction uses fresh LoopEngine, SessionStore, and EventStore instances: complete a facts answer, persist a subsequent human ingress, interrupt without model output, recreate the engine, and inspect the real provider wire. Baseline fails because the answer is absent; repaired code must preserve the exact visible answer while excluding old retired human instructions and hidden reasoning. Repeated crash and protocol/boundary tests accompany it.

Run the existing focused adjacent tests, full non-real-LLM pytest suite, Ruff, Pyright, compile, diff/security scans, and exact A.5 coverage. Compare unrelated pre-existing static failures against the baseline; do not modify unrelated source or weaken checks. Report any remaining failure explicitly.

After committing the fix, run exactly one LFL cell with the existing preregistered qualification-recovery-v1 case, oracle, and protocol unchanged. Use GLM-5.3, max_tokens=16000, reasoning_effort=max, 16 observer POST limit, 240-second cell budget, and zero automatic reruns. Use a fresh native data directory and the same persisted native session for the preparation, captured pre-dispatch SIGKILL, and restart. Require the original oracle, exactly one output write, no removed-input reread, no execute_python, no upstream dispatch of the captured interrupted request, full process-group cleanup and Docker quiescence. Inspect raw resumed provider wire for the remembered facts. Preserve all raw request/response/event/receipt/native-state evidence.

This is a repair requalification of one known public case, not a new formal score, an independent holdout, or a retry selected for promotion. Earlier Pi/OpenCode controls and LFL failure remain recorded. Remote in-flight cancellation/reconnect remain outside this test scope. Exact-output smoke failures and unowned design gates are not cleared by this fix.

Pre-live validation completed: 90 focused checks passed. Full non-real-LLM suite: 7,515 passed, 3 failed, 116 skipped, 16 deselected; the same three safety tests fail on the exact baseline because the managed home is under /var. Changed-file Ruff, compile, diff, staged security, and A.5 coverage pass. Full-tree Ruff retains 48 existing diagnostics; extracted-baseline import classification yields 50, with no introduced diagnostics and both differing test files proven byte-identical. Pyright reports the same 40 errors on baseline and candidate, with no introduced or removed diagnostics. These existing broad-check failures remain explicit and do not become passing gates.

Rollback: revert the repair commit in the isolated candidate. The new opaque metadata is ignored by old code; no session rewrite or schema migration is needed.
