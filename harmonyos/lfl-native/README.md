# LFL HarmonyOS native agent bridge (isolated PoC)

This is an **unsigned, uninstalled** API 26 ArkTS/ArkUI native-client experiment.
It retains the existing Python LFL LoopEngine and Web API as the only provider
of agent decisions, memory, methods, experiences, tools, and evidence.
**Do not claim AFK A2A registration, Xiǎoyì dispatch, on-device LLM,
privacy/performance advantage, or production readiness from a build result.**

## DevEco / SDK reproducible build

Requires a complete HarmonyOS **API 26** SDK and compatible DevEco Studio.
On the known macOS installation:

```sh
cd harmonyos/lfl-native
DEVECO_SDK_HOME=/Applications/DevEco-Studio.app/Contents/sdk \
  /Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw \
  assembleHap --mode module -p module=entry@default -p product=default --no-daemon
```

Output (unsigned): `entry/build/default/outputs/default/entry-default-unsigned.hap`.
The DevEco SDK HOME must be `.../Contents/sdk` and **not** `.../sdk/default`.
The API26 `build-profile.json5` format is `"26.0.0"`, not `"26"`
or legacy `"5.0.0(12)"`. No signing credentials are embedded or generated.

## Provider-free verification

At the LFL repository root, using Node.js 24+ and a repo virtualenv:

```sh
node --test harmonyos/lfl-native/test/*.test.mjs
python -m pytest -q tests/unit/test_harmonyos_cancel_generation.py \
  tests/web/test_harmonyos_protocol_contract.py \
  tests/web/test_stream_endpoint.py tests/web/test_api.py \
  tests/unit/test_runner_background.py tests/unit/test_background_cancel.py
```

The Node tests execute the *same* TypeScript bridge and protocol source
(`StreamProtocol.ts` and `LflTransport.ts`) with fake Kit implementations,
**not** a real HarmonyOS device. The Python integration test exercises the
actual isolated LFL FastAPI routes with FakeLLM, including one real local
127.0.0.1 TCP/uvicorn stream; it never calls a real external model/provider.

## App workflow

1. Enter an authorized HTTPS LFL origin and, if required, a Bearer credential.
   No production hostname or credential is supplied by default; the token
   stays in volatile UI state, not in persisted preferences.
2. Submit once: `/api/v1/chat/stream`. `run_started` binds the session to
   one exact run generation. Partial text is tentative until `done`.
3. Stop uses the **generation-bound** optional API extension:
   `POST /api/v1/chat/cancel`, body `{session_id,run_generation}`.
   It is not a claim of provider physical termination.
4. On disconnect, query stream/status, at most one automatic exact-generation
   resume; or load read-only history after run completed. Never resubmit a
   human message automatically, and never treat session history alone as an
   exact Run completion receipt.
5. Manual Recover accepts a session ID (after App reload, if the user saved
   it). It must not reveal another user's session. The current LFL backend
   session/tenant authorization remains the security authority; exposing
   this client to untrusted multi-user traffic requires a separate audit.
6. `artifact://v1/...` values in the answer are displayed as **unverified
   references only**. There is no authenticated immutable byte hydration,
   SHA verification, or downloadable Artifact support in this PoC.

See `CONTRACT.md` for normative boundary and unresolved A2A requirements.
**No shell/CDP/process execution runs inside the App sandbox.**

## A2A development gate (separate from this SSE client)

The public Huawei API 26+ documentation contains a Beta A2A server API, but
the installed **26.0.0.23 Beta1** SDK does not include `@hms.ai.A2A.d.ts`.
Before attempting native server registration, execute this **read-only** gate:

```sh
node harmonyos/lfl-native/scripts/probe-a2a-sdk.mjs \
  /Applications/DevEco-Studio.app/Contents/sdk/default
node --test harmonyos/lfl-native/test/*.test.mjs
```

The observed gate result is exit **2**, i.e. no complete local A2A type
surface. The `A2ATaskContract.ts` import in the App is only an **offline
compile and identity-mapping proof**, not a registered A2A service. This
contract requires a future authenticated platform caller and backend durable
admission receipt; real `EXECUTE` remains disabled. See
`docs/harmonyos/A2A-QUALIFICATION-20261011.md`.

**Updated 2026-10-11:** A separate OpenHarmony 26.0.0 Release SDK
(`26.0.0.38`) was found under `~/Library/OpenHarmony/Sdk/26.0.0`.
The probe now also accepts this SDK layout:

```sh
node harmonyos/lfl-native/scripts/probe-a2a-sdk.mjs \
  ~/Library/OpenHarmony/Sdk/26.0.0
```

It confirms the Release OpenHarmony SDK, but returns exit **2** because it
does **not** include Huawei HMS Agent Framework Kit A2A declarations.
`AgentExtensionAbility` belongs to the separate Ability Kit API24+
surface. The installed DevEco Studio application under `/Applications`
still reports Beta1 build 26.0.0.461; do not confuse either of these SDK
roots with a verified `createA2AServer` compiler or running service.

An **offline-only** backend CAS record implementation was subsequently
added to `src/llm_loop/web/a2a_task_admission.py`. It preserves exact
human request bytes and returns an idempotent receipt after durable
create-if-absent. This module has no public route and does not establish
trusted platform principal/session scope. See
`docs/harmonyos/A2A-TASK-CAS-20261011.md` for the remaining security
conditions and exact replay tests.

## Outstanding external and product gates

- Actual HarmonyOS phone/tablet + debug signing, App install/launch,
  real TLS stream and cancel/reconnect tests.
- Official Agent Framework Kit A2A server/client availability under the
  provisioned SDK/API version, developer eligibility and Xiǎoyì entry approval.
- A2A Task/Artifact mappings and signed, verified workspace artifact delivery.
- Controlled same-task **device** comparison versus mobile Web: success,
  p50/p95 latency, recovery, data transfer, energy and device privacy.
- Security hardening (session ownership, key entry, TLS and sensitive data
  retention) before any user- or production-facing pilot.

Do not merge to `main`, push, deploy, restart services or publish without
separate authorization and full downstream qualification.
