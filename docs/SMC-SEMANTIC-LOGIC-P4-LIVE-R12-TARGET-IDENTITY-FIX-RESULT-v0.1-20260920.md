# SMC P4-LIVE R12 Target Identity Production Fix Result v0.1

> Date: 2026-09-20
> Negative qualification anchor: `9a11fe4c43cc83f53bf2baf62d0782c91e1d4242`
> RED: `19cd1ceacf31c961a59008002f951697cc266f5e`
> GREEN: `f1efef6b57ef90562410a93cd310bae98e33a983`
> Result: **QUALIFIED PRODUCTION FIX / PRE-LIVE STOP**

## 1. Result

The R12 target-identity production defect exposed by the frozen P4-LIVE L02 failure is fixed in the isolated production-fix branch. This result does **not** reclassify or rerun the frozen L02 negative qualification, and it does **not** claim that P4-LIVE itself is now qualified. It establishes only that the production defect has passed the required deterministic, adjacent, static, security, real-Chrome zero-dispatch, and baseline-regression checks needed before starting a new LIVE qualification version.

## 2. Root cause and canonical contract

Real Browser perception deliberately represents page identity as `page_token = "target:<raw CDP target id>"` for page/document generation tracking. The prior ActionRef issuer incorrectly hashed that private page-token representation as the Browser target identity, while `CdpBrowserMutationActuator.bind_observed_target()` hashed the raw `/json/list` target id. The values therefore could never match in the real path.

The fix leaves perception page-token semantics unchanged. A narrow mechanical helper now owns the representation bridge and target digest:

- real `target:<raw>` page token -> exact `<raw>` CDP target id;
- synthetic non-prefixed fixture tokens remain byte-for-byte compatible;
- empty/malformed prefixed identity fails closed;
- ActionRef binding and actuator both use SHA-256 of the exact raw target id;
- no search, similarity, fallback, successor substitution, silent rebind, or model-semantic logic is introduced.

Production scope is limited to `target_identity.py`, `action_ref.py`, and `cdp_action_host.py`.

## 3. RED -> GREEN

The RED uses production `ActionRefIssuer`, `ActionRefResolver`, and `CdpBrowserMutationActuator`. With `page_token="target:target-A"` and `/json/list id="target-A"`, the pre-fix code deterministically raised `browser_target_precondition_mismatch` before websocket open or dispatch.

After the minimal GREEN, the same production-class case binds `target-A` successfully without opening a websocket or dispatching. Additional tests prove an empty `target:` identity rejects at issuance and historical non-prefixed deterministic fixtures preserve their prior digest semantics.

## 4. Real-Chrome zero-dispatch proof

On committed GREEN `f1efef6b...`, an isolated headless Chrome run performed only read-only capture plus ActionRef issuance/resolution and actuator target binding. The real capture produced the expected `target:<raw>` token; the actuator bound the same raw target successfully. Websocket opens = 0, Browser dispatches = 0, model requests = 0.

No LIVE semantic action was executed.

## 5. Verification

Current S1-S5 descendant + Browser/ActionRef/recovery adjacency selection: **173 tests, 173 PASS, 0 failures/errors/skips**. The one historical S2 test that asserts the hidden bridge is not factory-registered remains excluded exactly as in the frozen S5 qualification because later S4/S5 intentionally superseded that premise.

Ruff passed. Pyright reports 0 errors / 0 warnings. `git diff --check` passed. `scripts/git_security_scan.sh` passed.

The repository-wide `scripts/ci_gate.sh` remains red on this frozen S1-S5 lineage. To classify it correctly, the exact same gate was run on parent `9a11fe4c...`: parent and candidate each have **72 failures with identical failure sets**; candidate-only failures = 0 and parent-only failures = 0. The shared failures are pre-existing frozen-stack/historical-shadow expectations, including tests that still require ActionRef production wiring to be absent. Therefore the full-CI status is **baseline-equivalent red, no new regression**, not a GREEN claim.

## 6. Governance boundary

The original NOT_QUALIFIED artifacts are unchanged. No model request, Browser mutation, deployment, restart, PR merge, or main modification occurred in this production-fix Goal.

The next phase must be a **new P4-LIVE qualification version**. It must not overwrite or retry the frozen L02 record inside the old qualification run. This result stops before that new LIVE boundary.
