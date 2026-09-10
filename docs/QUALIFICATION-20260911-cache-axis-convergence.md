# Cache Prefix Axis Convergence Qualification — 2026-09-11

> **Verdict:** PASS / ADMIT selected R1–R4 axis fix + prompt-neutral axis telemetry.
> **Integration parent:** `integration/convergence-20260911@d0729730ebc4defe4f49af2831fc445f1fa4272e`.
> **Source candidate:** `fix/cache-prefix-surface-contract-20260910@2ec6875cada17f3e77f57bccaa8806af6d57aead`.
> **Rule:** source branch is not a merge unit. Only independently requalified cache-axis deltas are admitted.

## 1. Selected scope

Replayed from the source lineage because each item is directly required by the R1–R4 cache-axis contract or its qualification:

- `88f402c` + `812dd9d`: cache prefix surface design contract and closed design questions;
- `465da6a`: conformance contract tests;
- `2d08f08`: prompt-neutral system/tools axis attribution counters;
- `e1d0bcd`: R1–R4 double-axis runtime correction;
- `0dd833e`: session-scope compatibility coverage;
- selected part of `5b0db0e`: bounded in-process request-prefix axis event telemetry and test-name normalization only.

The selected `5b0db0e` port intentionally excludes every `prefix_unit` / replay-related hunk inherited from `dae2bcc`.

## 2. Rejected/HOLD source deltas

### 2.1 `610ebe5` — REJECT AS CACHE OPTIMIZATION

Qualified Learning Plane semantics before this source commit are explicit:

- Reflection receives its own reflection `system` instruction plus one episode-facts user payload;
- Reflection calls use `tools=[]`;
- `learning_plane.py` declares: `A ReflectionRun has no user channel, no normal agent tools`.

`610ebe5` changes the auxiliary model request itself. With a captured main-request context it sends:

- the main task's system message before the Reflection request;
- the main task's full projected tool schema array;
- the Reflection facts and Reflection instruction as a trailing user message.

The same pattern is introduced for archive summarization. Therefore the change is not compute-only: it changes provider-visible semantic inputs and exposes normal task tool schemas to a plane whose qualified contract excludes them. A cache-hit objective does not authorize that semantic change.

Disposition: preserve the source commit as historical/experimental evidence, but do not admit it through the cache convergence line. Any future attempt requires its own semantic experiment and must not be justified by cache-hit gain alone.

### 2.2 `dae2bcc` — HOLD WITH REJECTED REPLAY LINE

`dae2bcc` packages the `610ebe5` replay head as `RequestPrefixHead`. The abstraction is mechanically tidy but its only current production consumer is the rejected auxiliary replay behavior. It therefore has no independent convergence entitlement.

### 2.3 `2ec6875` measurement bundle — PRESERVE SOURCE, DO NOT REPLAY AS QUALIFICATION

The source report measures an `after=5b0db0e` tree whose ancestry includes `610ebe5` and `dae2bcc`. Its deterministic axis observations are useful historical evidence, but that tree is not byte/behavior equivalent to the selected convergence candidate. The old measurement JSON/report is therefore not copied as if it qualified the new tree.

## 3. Behavioral qualification

### 3.1 Double-axis probe

Using the exact integration parent and selected candidate with the same deterministic input sequence:

```text
parent signature:    preflight(session_id, stable_fp, skeleton_fp)
candidate signature: preflight(session_id, system_fp, tools_fp)

TOOLS-ONLY CHANGE
parent:    drift=1, tools_count=N/A
candidate: drift=0, tools_count=1, force_head_keep=false, gate_note=false

SYSTEM-ONLY CHANGE
parent:    drift=1, force_head_keep=false
candidate: drift=2 at preflight+postcheck observation granularity,
           force_head_keep=true, gate_note=true
```

For identical system/tools inputs, the combined `stable_fp` values are identical parent vs candidate. The correction changes axis classification/control, not the combined physical cache-boundary fingerprint.

### 3.2 Prompt/tool/provider surface identity

An actual `build_engine` comparison used the same isolated Settings and the same canonical JSON representation on parent and candidate:

```text
registered provider params
  parent    62 tools / 23652 bytes / SHA 8b8fb78b1552e7990fa0ddc5317c34299cce9bd1196ead16360921bd5c7aef37
  candidate 62 tools / 23652 bytes / SHA 8b8fb78b1552e7990fa0ddc5317c34299cce9bd1196ead16360921bd5c7aef37

runtime-health projected provider params
  parent    60 tools / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8
  candidate 60 tools / 22978 bytes / SHA d0eb3cf4faa7a0aa4a0da872ac1f396ee56f9cd4fb3c19545ab33ffeedd42ea8

Universal Prompt
  parent    192 chars / SHA ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e
  candidate 192 chars / SHA ea88fe6a8d5d1bd0ad3978625980f788ac350c7281f2bfdcaf009fd5b6d4fd5e
```

No auxiliary wire replay symbols are present in the selected source/test delta.

## 4. Static / regression gates

```text
cache/provider focused+adjacent       118/118 PASS
Ruff selected changed Python surface  PASS
Pyright repository                    0 errors / 0 warnings / 0 informations
py_compile changed runtime            PASS
git diff --check                      PASS
full pytest tests -q -m 'not real_llm' explicit RC=0 (~161s)
Git security hook on local telemetry commit PASS
```

The full run emitted only existing dependency deprecation warnings.

## 5. LLM-First / governance ruling

The admitted correction is mechanical:

- program observes exact system/tool fingerprints;
- `tools_fp` change is treated as request-surface fact, not semantic drift;
- `system_fp` change is the cache-head drift condition for the existing reversible head-keep mechanism;
- combined `stable_fp` continues to own physical cache-boundary invalidation;
- prefix-axis events are bounded facts and do not feed an automatic semantic policy.

The program does not choose tools, providers, task value, Method applicability, or completion. Historical archived evidence remains recoverable through the existing archive/evidence retrieval surfaces if compression changes the provider view.

## 6. Admission result

**PASS** for selective integration of the R1–R4 double-axis correction and bounded axis telemetry.

**NOT ADMITTED** through this workline:

- `610ebe5` auxiliary wire-prefix replay;
- `dae2bcc` replay-prefix unit;
- the whole `2ec6875` source branch;
- unrelated p0a/restart/default-model/learning commits in that source ancestry.

A final post-port committed-state gate must run on the single unified integration ancestry before this phase is considered integrated truth.
