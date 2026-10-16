# HarmonyOS native LFL PoC — phase 2 validation (2026-10-11)

**Stage verdict: code/build and provider-free LFL bridge = PASS;
signed/device A2A, real mobile performance and production = NOT QUALIFIED.**

## Source isolation

- branch: `feat/harmonyos-native-agent-poc-20261011`
- base: `99cf68982`, isolated worktree under `.worktrees/`
- No `main` merge, push, Web restart, production chat, third-party credential
  or external provider call was authorized/performed.
- Source: `harmonyos/lfl-native/` (ArkTS App, pure protocol and Kit transport),
  plus additive cancel-generation guard in 3 Python LFL files and focused tests.
- Observed unsigned HAP SHA256 after API26 build: `ff4bc358f489abdff65b8b5cdd70fa88f2c472fa4a6fb9275b94894efe70f68f`.

## Verified at this stage

| Gate | Evidence | Verdict |
|---|---|---|
| Parser & native Transport on host with fake Kit | Node24, `node --test harmonyos/lfl-native/test/*.test.mjs`: **11 pass / 0 fail** | PASS (host only) |
| Real isolated LFL Web route | `tests/web/test_harmonyos_protocol_contract.py`: **3 pass**, includes actual loopback TCP/uvicorn FakeLLM SSE | PASS (provider-free) |
| Cancel safety | stale-generation HTTP409 + no budget cancellation; valid-generation cancel and legacy Web behavior verified | PASS (focused) |
| Existing Web & background runner regressions | six targeted suites: **121 passed / 1 warning / 0 failed** | PASS (focused) |
| Python lint and whitespace | Ruff on 5 relevant Python files + `git diff --check` | PASS |
| API 26 compile/package | `hvigor assembleHap`: **exit 0, BUILD SUCCESSFUL**, unsigned HAP | PASS (unsigned build) |
| Device / signing | `hdc list targets` was empty; no signingConfig | NOT TESTED |
| Official AFK A2A / Xiǎoyì | No actual A2A server/client or system dispatch receipt | NOT IMPLEMENTED / NOT TESTED |
| Artifact byte access | Only immutable URI candidate display; no byte-hydration/readback/SHA verification | NOT IMPLEMENTED |
| Native vs Web quality/latency/power | No device measurements, no experimental parity data | NOT TESTED |

## Prevented failure modes

- A stream transport `dataEnd` cannot be misread as successful completion
  without a valid `done` (or explicitly terminal `error`) frame.
- Multi-byte UTF-8 and SSE frames split on every byte are parsed.
- Generation mismatch prevents stale tabs from subscribing to/cancelling
  a newer Run. No automatic re-post when the first request outcome is unknown.
- A read-only history fallback is not asserted to prove the last Run succeeded.
- Artifact candidates are labeled `unverified_ref`; no fake A2A Artifact.
- A watchdog timer introduced during prototyping was cleaned up after dataEnd.

## Next phase (separate owner checkpoint)

Acquire/provision a compatible HarmonyOS phone/tablet and debug signing,
verify AFK A2A API type support and credentials under real SDK, implement
the formal A2A adapter and secured Artifact hydration as a separately
qualified capability. Freeze user-visible device tests and compare with
mobile Web before attempting any migration to Cangjie/Rust.


## Phase 3 (2026-10-17): offline adapter + verified artifact hydration

| Gate | Evidence | Verdict |
|---|---|---|
| Dispatch decision layer (host tests) | `node --test`: 40 pass / 0 fail (9 new dispatch cases) | PASS |
| Artifact hydration endpoint | pytest: 140 passed / 0 failed (17 new: positive, cross-scope 404, malformed 404, tamper 409) | PASS |
| Six-suite regression | included in the 140 above | PASS |
| Python lint / whitespace | Ruff all passed; `git diff --check` clean | PASS |
| API26 compile with adapter wiring | `hvigor assembleHap` BUILD SUCCESSFUL (CompileArkTS 1.37 s, unsigned HAP) | PASS (unsigned build) |
| Device / signing / live A2A EXECUTE | unchanged — no device, no signingConfig, no registered server | NOT TESTED |
