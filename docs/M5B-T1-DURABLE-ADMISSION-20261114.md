# M5-B: T1 Web real-entry durable admission and presend refusal

Status: isolated candidate only. No merge, deploy, restart or automatic resume.

Base M5-A: bd424f0f7d6b9d18284eff3947a073d2aca30483; independent GLM-5.3 PASS (P0=0/P1=0/P2=4); original full R9 exit 0 (15,027 passed, 158 skipped, 3 xfailed; WebUI 600 passed). M5-B is new code and must pass fresh review and R9.

## 1. Actual admission path

- Only the actual 0600 operator-config T1 Web loader sets durable_run_admission_required=True. No browser/model-controlled switch, second ledger or extra authorization.
- Existing core/loop/lifecycle.py _on_human_event runs under the cross-process Session.run_lease, after authenticated human EventStore append.
- prepare_t1_web_event_budget first checks operator revocation and target SHA and issues/activates the existing TaskBudgetStore root by CAS. Then it strictly appends run.durable.opened and run.durable.admission_fenced, each fsynced and independently read back. Only after both succeed does it arm the local execution.
- Every Provider/Tool T1WebBudgetExecution.reserve checks that the execution was armed and independently rereads exact original JSONL facts under the per-session strict lock. The source is checked against its opened file descriptor (inode, ownership, mode, hardlink count, bytes), relative path containment, complete JSONL rows, sequential IDs, and exactly one adjacent matching opened/fenced pair. Any missing/corrupt/duplicated/mismatched evidence denies dispatch and attempts a durable budget stop.
- The existing TaskBudgetStore CAS, Provider transport controls, tool allowlist, FileService CAS and operator-config revocation remain authoritative. This stage does not expand budget or tool permissions.

## 2. Crash and negative evidence

| Fault window | Evidence and disposition |
| --- | --- |
| Budget issued/activated, before opened | One-use root exists; no fence, no external dispatch; no replay |
| Opened persisted, before fenced; subprocess os._exit(37) | Only opened; fresh process cannot issue another root |
| Fenced persisted, before Provider; subprocess os._exit(38) | Both facts; fresh process cannot reuse authorization; no auto resume |
| Append fails before or after physical write | TaskBudgetDeniedError, budget stop attempt, no Provider/Tool action |
| Later event corruption or duplicate protocol fact | Next Provider/Tool reserve fails closed; no new reservation |
| Provider or Tool already performed | Remains UNKNOWN/HOLD; local settlement or matching target SHA does not prove causation |

The production T1 path does not yet issue run.durable.terminal. Any real Provider/Tool Run is therefore still UNKNOWN/HOLD under the M5-A recovery projection. This is intentional until M5-C evidence joins and M5-D recovery control are complete.

## 3. Test evidence and remaining work

Offline tests include real Engine + LLMClient with synthetic 3 Provider attempts and 2 Tool invocations, real loader plan wiring, direct injection of strict append failures, no-Provider-on-failed-admission, cross-process crash windows, corrupted/duplicate event facts, and the original M5-A strict recovery tests. No live GLM invocation in this test suite. The pre-M5 F18 revocation fixtures retain their original synthetic run-1 generation, explicitly opting out of M5 strict mode; a separate real-loader test proves production opt-in.

M5-C: exact Provider call/transport/budget reservation and remote settlement evidence, Tool effect_prepared/effect_observed/receipt_committed + target SHA/CAS and causal ownership, with UNKNOWN held.
M5-D: read-only restart recovery projection and Web/SSE/queue display, never automatically reissue an old Run.
M5-E: dual worker, authorization revocation, SIGKILL at every Provider/Tool/finalizer boundary, real-process receipts and zero duplicate side effects.

Gate for this new candidate: independent GLM-5.3 completed/PASS P0=P1=0, then original full R9 exit 0, then Host review_admission/remote CI/A.5/privacy verification before considering main/push. Mac/Deepin managed release/restart requires separate permission. Old M4-C Provider debt remains QUARANTINED_UNRESOLVED/HOLD.
