# Restart continuity: current-main integration and deferred rollout

Authorization: user “按顺序执行” on 2026-10-07 (Asia/Shanghai), after the ordered proposal to create a minimal current-main candidate, review and revalidate, merge if no new failures, and deploy only after FR-1 T+24h passes. GLM-5.3 is the only permitted live test model; no push is authorized.

## Scope registered before current-main model calls

Integration base is 424b298f255f1ad52e1bfb33a09b31eff0703b82. Only repair commit 9c4e259a278f9910dce324a62f6914165960fa12 is transplanted as 8be397460dee04d1f618791bda8b1aa545832c3e. The earlier repair plan describes its original isolated-candidate phase; this plan records the subsequently authorized main-integration phase. No unrelated harness-branch source is integrated, and root working-tree changes are preserved.

Run all 90 adjacent deterministic tests and the full non-real-LLM suite on this main-based tree. Compare full Ruff and Pyright diagnostics against the exact main base; reproduce existing failing tests on that base. Retained baseline failures must be reported as failures, not relabeled green. Changed source/tests must pass Ruff, compile, test-environment declaration and architecture/security/diff checks.

One independently prompted GLM-5.3 code-review call receives the source change, complete continuity module, ingress/serialization/retirement context and regression tests, plus boundary contracts. It receives no prior validation outcome or proposed verdict. It reviews completion proof, runtime-owned metadata, repeated crash chains, intervening output, legacy unanchored histories, protocol and authority isolation. This model review is an additional check, not an owner signature or an independent formal-harness gate approval. Resolve any reproducible blocking finding before merge.

Then perform exactly one fresh native LFL recovery requalification on this main-based source using the unchanged pre-registered qualification-recovery-v1 case, oracle and protocol from harness commit 91013cec26ee2f82aa866f69bd9197a1605779d5. The private copied harness must remain byte-identical, and its PYTHONPATH must resolve to this integration tree. Profile: GLM-5.3, max_tokens=16000, reasoning_effort=max; original 16 POST/240 second budget; zero outcome-based automatic reruns. Require the original mechanical checks and oracle, resumed visible facts, one output write, no removed-input reread or execute_python, and complete owned process/container cleanup. This is the known public pre-dispatch recovery case; no claims about remote in-flight reconnect, partial streams, legacy pending-data migration, exact-output smoke or formal scores follow.

## Main merge and deployment boundary

Merge only the clean minimal branch, using fast-forward and a compare-and-swap check that main remains at the recorded base and existing root working-tree content is unchanged. Do not stash, reset, force, push or restart production as part of integration. Capture evidence and remaining baseline failures in RESULT-20261007-restart-continuity-main-integration.md.

Production remains under the existing FR-1 first observation window. Its scheduled first read-only review is 2026-10-07 20:00 Asia/Shanghai; elapsed time alone is not a PASS. Before any subsequent deployment, require durable T+24h evidence that satisfies the original FR-1 criteria, review the entire actual live-source-to-candidate delta, verify runtime model/config invariants and idle/admission gates, prepare rollback to the previous desired deployment and service-specific live identities, and use managed authority with expected_generation CAS. Deploy one service canary before sequential remaining services. A failure or unknown gate blocks rollout and is reported without modifying the observation configuration. Later-run instructions must be recorded separately; this document alone does not perform a deployment.

Rollback for this code fix is a revert of the isolated source change; old code ignores the opaque metadata. Production rollback must use the recorded managed deployment and service identities, not overwrite user working-tree changes.

## Registered review transport replacement

The initial independent review request reached the observer once, with no provider HTTP status, no returned byte, no completion and a TimeoutError. Observer-local HTTP 503 is not a provider verdict. Its full request/empty response/settled receipt remain retained. Before a replacement call, register one streamed replacement with identical review messages/source input and unchanged GLM-5.3/max_tokens=16000/reasoning_effort=max. The transport change avoids waiting for the entire reasoning answer before any response. This is one explicitly registered technical replacement, not outcome-based retrying, and does not change or rerun the native qualification protocol. If it also yields no valid review, the review remains UNKNOWN and merge is blocked.
