# Continuity Kernel v1 Final Qualification

Date: 2026-09-07

Baseline under qualification: `7f3e00f158232c21bcf77d1e8f745b2aa1a42f35`

## 1. Ruling

Continuity Kernel v1 is qualified for the current committed LFL mirror as a **mechanical durability and recovery kernel**.

The qualified claim is intentionally narrow:

- durable Session/EventLog truth survives the supported restart/recovery paths;
- provider interruption state, tool protocol/WAL, SubAgent lifecycle, external execution lifecycle, execution effects and workspace artifacts have explicit mechanical owners;
- representation changes do not authorize semantic relevance, completion, retry, tool choice or task strategy;
- unknown execution/effect state remains unknown and is never converted into automatic re-execution;
- session deletion cannot erase ownership facts for unfinished external execution;
- workspace artifacts outlive the producer Session by explicit workspace-retention contract.

This qualification does **not** enable cross-restart process reclaim/restart and does **not** enable a production WorkingStateCheckpoint producer.

## 2. Authority boundary

The gate checks durable protocol facts and recovery precedence only. It must not score or enforce:

- answer quality or semantic equivalence;
- evidence quality/relevance/sufficiency;
- tool strategy or tool-order quality in nondeterministic model decisions;
- hidden reasoning quality;
- cache-hit rate, latency or prefill efficiency as a correctness criterion.

Program code may validate identity, pairing, provenance, source version, exact transcript/provider/model boundary, hashes and resource bounds. The model retains semantic judgment.

## 3. Deterministic qualification matrix

The original CK1 G4 matrix remains authoritative for prompt/recovery precedence. CK-FINAL extends it with the durability work completed after CK1.

| Domain | Qualified invariant | Authoritative deterministic coverage |
| --- | --- | --- |
| recent human continuity | nearest real model state + current genuine human remain the final continuity suffix | `test_recent_continuity.py` |
| provider interruption/truncation | exact partial/reasoning/native replay is preserved; unfinished output never becomes completed merely because of restart | `test_recent_continuity.py`, `test_selective_evidence_s1.py`, `test_fork_pairing_disconnect.py`, `test_llm_client.py` |
| tool WAL | declaration/start/finish/receipt commit ordering is durable; started-unknown is never auto-reexecuted | `test_tool_execution_restart.py` |
| execution effect facts | edit effect prepared/observed hashes are mechanical; uncertain causation stays unproven; generic shell has no inferred write-set | `test_tool_execution_effects.py` |
| SubAgent topology | parent/generation ownership is durable and stale generations cannot be reclaimed as current | `test_subagent_topology_restart.py` |
| SubAgent delivery | steer/report/result facts survive restart without false delivery/terminal claims | `test_subagent_delivery_restart.py` |
| SubAgent settlement | settlement requires the durable parent receipt binding; stale/wrong generation cannot settle | `test_subagent_settlement.py` |
| external execution | fresh runtime may report durable orphan facts but never gains automatic reclaim authority | `test_external_execution_restart.py` |
| session deletion fence | unfinished external execution blocks physical deletion; terminal execution releases the fence | `test_session_external_resource_delete_fence.py` |
| workspace artifact | opaque artifact ref is workspace-scoped, immutable, hash-verified and restart-stable | `test_workspace_artifacts.py` |
| session delete + artifact retention | deleting producer Session does not delete workspace artifact; later same-workspace Session with known ref can hydrate exact bytes | `test_workspace_artifacts.py`, `test_continuity_kernel_final.py` |
| D0 + D0.5 composition | external job must become durably terminal before Session deletion, while the workspace artifact remains independently recoverable afterwards | `test_continuity_kernel_final.py` |
| WorkingStateCheckpoint producer | consumer/validation path exists, but production contains no call to `build_working_state_checkpoint` | `test_continuity_kernel_final.py` |
| cross-restart auto reclaim | external lifecycle events remain factual and carry `auto_reclaim=false`; PID/PGID/workspace identity do not become control authority | `test_external_execution_restart.py`, `test_continuity_kernel_final.py` |

## 4. Qualification execution

The focused CK-FINAL closure test adds three cross-phase gates:

1. D0 deletion fence + terminal release + D0.5 artifact retention in one composed lifecycle;
2. production WorkingStateCheckpoint producer remains HOLD;
3. external lifecycle events never grant `auto_reclaim` authority.

The broader deterministic qualification set is the union of the CK1 continuity/replay tests and the ST2/EW2/D0/D0.5 suites listed above. On this baseline the curated qualification suite completed with exit code 0.

A fresh detached candidate built from exact `7f3e00f` plus only this report and `test_continuity_kernel_final.py` also passed: curated qualification exit 0; Ruff PASS; repository Pyright `0 errors / 0 warnings / 0 informations`; `py_compile` PASS; `git diff --check` PASS; full `pytest tests -q -m 'not real_llm'` exit 0 in about 154.1s. The universal prompt remained exactly 192 chars with SHA256 `ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e`, and the candidate changed no `src/` runtime file.

## 5. Explicit HOLD / deferred capabilities

### ST2-D1 cross-restart reclaim/restart — HOLD

Current durable facts establish ownership history, not a safe fresh-runtime control capability. PID/PGID, command hash and workspace path/id are observations and must not authorize signal/attach/restart. Reopen only after a separately reviewed supervisor/control-capability design proves process incarnation and ownership mechanically.

### WorkingStateCheckpoint production producer — HOLD

The runtime may consume a mechanically valid existing checkpoint. It must not produce semantic checkpoints from token pressure, cache state, fold thresholds, program-selected “important evidence”, or a program judgment that state is “clean”. A future producer, if any, remains a separately gated model-authored capability.

## 6. Closure criterion

For Continuity Kernel v1, **correctness = durable-fact integrity + explicit ownership + fail-closed recovery precedence + no automatic semantic authority**.

With the deterministic matrix green and the two deferred capabilities explicitly outside scope, the Continuity Kernel v1 workline may be closed. The next independent phase is a test-only **Durable Fact Equivalence Harness** that can compare two execution arms after removing an explicit allowlist of compute-only telemetry. That later harness must preserve provider-visible payload identity and must not become a semantic evaluator.
