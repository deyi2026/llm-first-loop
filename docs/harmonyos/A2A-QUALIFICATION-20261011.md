# LFL HarmonyOS A2A — API26 qualification and Task identity contract

Date: 2026-10-11. Branch: `feat/harmonyos-native-agent-poc-20261011`.
Status: **SDK-native A2A NO-GO (not installed/qualified); offline mapping PASS.**
This is read-only SDK research plus isolated offline code, not a live A2A deployment.

## Updated Release installation audit (2026-10-11, 08:48 local)

The user has installed a genuine **OpenHarmony 26.0.0 Release SDK**, but it is
not interchangeable with a Huawei HMS A2A Kit distribution:

- New root: `~/Library/OpenHarmony/Sdk/26.0.0`; components `ets`, `js`,
  `native`, `previewer`, `toolchains`. SDK tree directory last modified
  on 2026-10-11 around 08:15 local.
- `ets/oh-uni-package.json` and `toolchains/oh-uni-package.json` both
  report `apiVersion=26`, `releaseType=Release`,
  `version=26.0.0.38`. This confirms the Release **OpenHarmony component**.
- Its `ets/api/@ohos.app.agent.AgentExtensionAbility.d.ts` and
  `ets/api/application/AgentHostProxy.d.ts` are present. They belong to
  **Ability Kit** (API24+), not proof of HMS Agent Framework Kit A2A.
- This separately installed root has **no HMS package**, no
  `@hms.ai.A2A.d.ts`, and no `@kit.AgentFrameworkKit.d.ts` A2A export.
- The actual `/Applications/DevEco-Studio.app` app still reports
  `26.0.0.461` (Beta1) from its Info.plist. Its embedded HMS SDK is still
  `26.0.0.23 Beta1`; the IDE app and the newly installed OpenHarmony SDK
  are distinct artifacts. No second Release IDE app was found in common
  installed-app locations. The running process points to the Beta1 app.

The read-only probe `node harmonyos/lfl-native/scripts/probe-a2a-sdk.mjs
~/Library/OpenHarmony/Sdk/26.0.0` reports `openHarmonySdkReleaseType=Release`,
`openHarmonySdkVersion=26.0.0.38`, `agentExtensionPresent=true`,
`hmsAgentFrameworkKitInstalled=false`, `a2aTypesQualified=false`,
exit code **2** (intentional, qualification not satisfied). Running the
same probe on the old DevEco embedded `default` root also returns exit **2**.
The revised dual-layout probe and its regression test were executed on the
real installed SDK, and the total host suite passed **27/27**.

**Decision:** The user-installed Release component is real, but a native HMS
`createA2AServer` compilation remains **NO-GO**. Install/enable the matching
official **HMS Agent Framework Kit** A2A declarations through an authorized
SDK distribution and re-run the exact type gate. Do not fabricate declarations,
merge incompatible SDK fragments, or substitute Ability Kit's distinct
`AgentExtensionAbility` and label it HMS A2A. Actual A2A host authorization,
device dispatch and signing remain unverified.

Official API references:
- https://developer.huawei.com/consumer/cn/doc/doccenter-release-notes/js-apidiff-agentframeworkkit-7002
- https://developer.huawei.com/consumer/cn/doc/doccenter-references/api/js-apis-inner-application-agenthostproxy
- https://developer.huawei.com/consumer/en/doc/harmonyos-releases/deveco-studio-new-features-2600

## Authority and observed facts

1. Huawei Agent Framework Kit public API difference record (updated 2026-07-28):
   https://developer.huawei.com/consumer/cn/doc/doccenter-release-notes/js-apidiff-agentframeworkkit-7002
   lists `api/@hms.ai.A2A.d.ts`, `createA2AServer`,
   `AgentOperation` (EXECUTE/CANCEL/CLEAR_CONTEXT/PERCEPTION_SUGGEST),
   `Server.start/stop/updateStatus/addArtifact`, `RequestContext`,
   `Task/TaskStatus/TaskArtifactParam` and numeric `TaskState`.
   The documentation describes this as a **Beta** interface. Public
   documentation does not confirm permission on this developer account.
2. Huawei Harmony Intelligence public landing page:
   https://developer.huawei.com/consumer/cn/harmonyos-ai
   explicitly distinguishes device A2A and cloud A2A. These are separate
   distribution/execution modes; neither implies an already approved LFL App.
3. Installed DevEco SDK inspected on this Mac:
   `/Applications/DevEco-Studio.app/Contents/sdk/default`.
   `hms/ets/uni-package.json`: `apiVersion=26`,
   `releaseType=Beta1`, `version=26.0.0.23`.
   `hms/ets/api/@hms.ai.A2A.d.ts`: **ABSENT**.
   `hms/ets/kits/@kit.AgentFrameworkKit.d.ts`: exists but exports only
   AgentController/BaseOptions/FunctionController/FunctionOptions/ButtonType/
   FunctionComponent — **no A2A**.
   The separate OpenHarmony AbilityKit
   `@ohos.app.agent.AgentExtensionAbility.d.ts` (since API24) **exists**;
   this is *not* the HMS `createA2AServer` declaration or interoperability
   verification.
4. Local `hdc list targets` returned `[Empty]`. The PoC has no configured
   signing profile, no verified developer entitlement, no installed HAP and
   no real Xiǎoyì/A2A request. Do not infer user account restrictions
   from lack of a connected device.

## Reproducible read-only preflight

```sh
node harmonyos/lfl-native/scripts/probe-a2a-sdk.mjs \
  /Applications/DevEco-Studio.app/Contents/sdk/default
```

Observed exit code **2**. `a2aTypesQualified=false` because the HMS A2A
declaration and Kit export are absent; the capability probe does not inspect
secrets or account identifiers, install SDK components, or contact a provider.
Even a future exit **0** means only that the local type surface appears
present — a native compile, actual device runtime and platform permissions
must still be verified independently.

## Offline A2A Task mapping (NOT a running A2A server)

Source: `harmonyos/lfl-native/entry/src/main/ets/bridge/A2ATaskContract.ts`.
This file intentionally does not import `@hms.ai.A2A`.

- `EXECUTE`: require an authenticated host principal and a **backend-issued,
  durable, atomic per-task reservation receipt** before permitting one human
  ingress. Current LFL lacks this Task CAS issuer; live admission therefore
  remains unimplemented. `RequestContext.getAgentId/getClientSessionId`
  are references, not cryptographic authorization.
- Identity key is the A2A `taskId`, with frozen `contextId`,
  `clientSessionId`, `agentId`, principal and SHA256 of exact request;
  duplicate matching task is idempotent, changed payload or caller rejected.
- A2A Task binds **only** on a real LFL SSE `run_started` with exact
  `session_id + run_generation`. One Run cannot be bound to two tasks.
  Mismatched generations never become a valid reattach/cancel target.
- `CANCEL`: only a matching authenticated bound Task can issue one
  `/api/v1/chat/cancel` payload with `session_id/run_generation`.
  HTTP cancel acknowledgment is not physical Stop settlement; publish
  `CANCELED` only after a separate paired authoritative receipt.
- `done`: only an exact bound Run with `run_incomplete=false` and no
  unresolved cancellation can publish `COMPLETED`.
  An incomplete terminal maps to `FAILED`; cancellation/normal done race
  stays `UNSPECIFIED` pending authoritative reconciliation. Transport
  disconnect does **not** manufacture any terminal state or new Run.
- `CLEAR_CONTEXT` and `PERCEPTION_SUGGEST` have no authorized LFL
  equivalent in this PoC. No implicit session deletion, workspace mutations,
  provider calls, credential bridging, shell/CDP or task escalation.
- `addArtifact`: a textual `artifact://v1/<32hex>` URI is not sufficient.
  An authenticated immutable byte hydration endpoint with scoped authorization,
  SHA256 and actual readback must first be qualified; no file payload is
  constructed from an unverified reference.

The host contract uses the public numeric TaskState surface only as a
**shadow compatibility table**; it is neither an SDK stub nor native
registration. Identity state is in memory, while new Run admission requires
an external durable CAS receipt with `newlyReserved=true`; on restart an
already-reserved Task must fail closed rather than replay a human message.

## Gate to re-open native integration

1. Install/provision a **matching official** Agent Framework Kit release in
   an isolated SDK selection; verify actual A2A .d.ts exports and compile a
   minimal `createA2AServer` test under that SDK. Do not copy invented .d.ts
   or bypass SDK Manager entitlement prompts.
2. Verify developer enrollment and the A2A App/agent registration process
   with a real authorized account; no assumed Xiǎoyì distribution or app
   listing.
3. Obtain a signed debug HAP, compatible real HarmonyOS test device, and
   authentic Agent-to-Agent EXECUTE/CANCEL/TaskStatus receipts.
4. Add and qualify a durable backend Task admission CAS authority and
   principal-to-LFL session authorization; validate negative replay/tenant
   cases before host dispatch.
5. Complete verified Artifact byte delivery and mobile Web performance,
   privacy, correctness and recovery comparison before promoting production.

No merge to `main`, push, signing, production restart or public listing is
authorized at this phase.

**Progress after the initial SDK gate:** a standalone provider-free LFL
durable Task reservation store now exists at
`src/llm_loop/web/a2a_task_admission.py`, with initial 17 focused tests
passing. This is *not* a registered A2A endpoint or verified caller
authorization and does not remove the above integration gate. See
`docs/harmonyos/A2A-TASK-CAS-20261011.md`.

## Phase evidence receipts

- `node --test harmonyos/lfl-native/test/*.test.mjs`: **26 passed / 0 failed**.
  This includes 11 pre-existing SSE/Transport tests, 11 Task mapping tests
  and 4 SDK-preflight tests. Both the Kit adapter and API mapping are host
  tests, not a real system A2A dispatch.
- `python -m pytest -q` targeting the six Web/Runner/Cancel/bridge suites:
  **121 passed / 1 warning / 0 failed** (isolated FakeLLM only).
- `DEVECO_SDK_HOME=.../Contents/sdk hvigorw assembleHap ...`:
  **BUILD SUCCESSFUL**, debug HAP remains unsigned and uninstalled.
- Read-only local SDK probe: **exit 2**, A2A d.ts and Kit export absent.
  Distinct official public release API notwithstanding, native A2A is NO-GO.
- LFL `main`, provider runtime, signing material, Huawei developer account,
  external model credentials and public publishing were not modified.
