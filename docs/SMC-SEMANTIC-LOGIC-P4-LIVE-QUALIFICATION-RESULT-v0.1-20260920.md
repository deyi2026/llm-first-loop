# SMC P4-LIVE ActionRef LIVE Qualification Result v0.1

> Date: 2026-09-20
> Frozen base: `afba3e2e3c52b2b3de141c2bfa14cc223ef720bd`
> Result: **NOT_QUALIFIED**

## 1. Executive result

The zero-action P4-LIVE preflight passed on the exact remotely frozen G2-S5 base. The first real-model + real-Browser row, **L02 click**, then produced a valid fail-closed result and is frozen as-is. Ornith declared the exact typed `browser_semantic_click(action_ref=...)` call, but the ActionRef execution path rejected it before physical dispatch with `browser_target_precondition_mismatch`. The DOM click counter stayed zero and no Browser running/terminal receipt was emitted.

The failure is **not a model-selection error and not a qualification harness target-selection error**. Read-only causal audit plus a zero-mutation real-Chrome diagnostic mechanically confirms a production R12 identity-representation mismatch.

## 2. Frozen L02 facts

- Real model requests: **1**
- Model declaration: exact typed `browser_semantic_click` with the issued ActionRef
- Prompt tokens: **985**
- Completion tokens: **92**
- ActionRef execution bridge: reached **PREPARED**
- Inner action id: `sact-702739567c8182809b275d5e`
- Production rejection: `browser_target_precondition_mismatch`
- Physical Browser dispatches: **0**
- Observed click effects: **0**
- Browser running/terminal receipts: **none**
- Automatic retry: **none**

Per the frozen protocol, this row is not retried or substituted. Later LIVE rows are not executed after the first valid LIVE failure.

## 3. Root cause adjudication

The real Browser path uses two different representations for the same CDP target identity:

1. Real Browser capture obtains the raw CDP target id.
2. Perception canonicalizes it as `page_token = "target:<raw_target_id>"`.
3. `ActionRefIssuer._issue()` passes that **page token** as `browser_target_id`; the binding stores SHA-256 of `target:<raw_target_id>`.
4. `CdpBrowserMutationActuator.bind_observed_target()` resolves the page from `/json/list`, obtains the **raw target id**, hashes that raw id, and compares it with the binding hash.
5. `sha256("target:<id>") != sha256("<id>")`, so a correctly observed ActionRef is deterministically rejected before dispatch.

A separate zero-model / zero-mutation real-Chrome diagnostic confirmed all four mechanical facts: capture page token had the `target:` prefix, the binding hash matched the prefixed page token, the binding hash did not match SHA-256 of the actuator raw id, and the two hashes were unequal.

This is therefore a **production R12 target-identity representation bug** exposed by LIVE qualification. The earlier fake-only S2/S4 GREEN tests did not reproduce this real-boundary formatting difference.

## 4. Safety outcome

The defect fails closed. No unintended Browser mutation occurred. The test did not search, guess, normalize, rebind, substitute a target, or replay the action. No production configuration, Web/Feishu/8901 service, main branch, deployment, or restart was changed.

## 5. Qualification ruling

P4-LIVE v0.1 is **NOT_QUALIFIED** on exact S5 `afba3e2e3...` because success-row L02 cannot reach its required single physical effect. This qualification Goal does **not** patch production to make the canary pass. The production fix must be handled in a separately governed RED -> minimal GREEN slice, after this negative qualification result is frozen and remotely preserved.

## 6. Required follow-up

The next production slice should establish one canonical Browser-target identity representation across capture, ActionRef binding, execution bridge, and actuator first-bind, with a deterministic test that uses the real `target:<raw id>` capture representation. After that fix is independently qualified, a **new** P4-LIVE qualification run should be frozen rather than retrying this L02 row inside the current run.
