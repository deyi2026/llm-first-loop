# Provider / Model Admin Convergence Qualification — 2026-09-11

> **Verdict:** PASS / ADMIT the qualified converged control plane.
> **Integration parent:** `integration/convergence-20260911@82e412b73f46443b5f406ef78ea8eb6c0d33ae02`.
> **Source feature evidence:** `feature/web-model-provider-admin-20260909@e7f33e7b64cf8f6c38784194921cc3fc4cdb0a1f`.
> **Qualified implementation commits:** `721b06cfdbbb3e43f7f326da7600e664cb14217f` + `16d90e8c388650f3ff8090fbe75d6636051a0ab3`.
> **Rule:** the old feature branch is evidence, not a merge unit. Its control-plane intent is ported onto the unified integration ancestry and the defects below are corrected before admission.

## 1. User-visible capability

The qualified implementation provides an authenticated Web control plane for Provider/model configuration:

- list, add, update, enable/disable, and delete Providers and models;
- write local Provider configuration to ignored `data/providers.local.json` as a **full local snapshot**, without modifying tracked `data/providers.json`;
- write credential plaintext only through the configured secret environment variable in local `.env` / process environment; provider JSON and API snapshots expose only credential presence/source facts;
- test one Provider/model connection with a bounded no-tools request;
- explicitly hot-reload the effective Provider registry;
- change the configured default `LLM_MODEL` while honestly reporting when the startup default client still requires restart;
- immediately refresh both the settings catalog and Composer model selector after a successful registry mutation;
- preserve a session's selected model when that Provider is later disabled/deleted, while reporting `current_available=false` and rendering that stale choice as disabled rather than pretending it remains selectable.

Authenticated operators may configure localhost/private-network HTTP(S) Provider endpoints. This is an intentional capability for local-model and private-gateway use; the schema still requires `http|https`, a hostname, and rejects embedded URL username/password credentials.

## 2. Source defects found during convergence review

### 2.1 Source branch was not an admissible merge unit

The source feature diverged from `d59169f` while the unified integration ancestry had already absorbed Human Turn queue, file collaboration, continuity, ERR1214 recovery, and other changes. A dry-run `cherry-pick --no-commit b4a90fb` onto the integration line produced a real content conflict in `src/llm_loop/web/routes.py`.

**Correction:** all non-conflicting feature content was replayed onto a fresh worktree based on `82e412b`; `routes.py` was manually ported by narrow hunks only. Existing queue, attachment, WebAuth, and per-session model semantics were retained.

### 2.2 Connectivity-test errors reflected untrusted provider material

The source `test_provider()` returned `str(exc)[:300]` after masking only the configured API key and a Bearer pattern. A deterministic RED proved URL userinfo, query-string secrets, and arbitrary provider response-body text could still be reflected to the Web client.

**Correction:** provider/library exception text is never reflected. Failure responses expose only the exception type and, when mechanically available, HTTP status or timeout category. The raw provider response body, URL credentials, and transport error string remain outside the API response.

### 2.3 Runtime manifest did not describe the effective Provider source

Actual registry priority is:

```text
MODEL_PROVIDERS environment JSON
    > data/providers.local.json full local snapshot
    > data/providers.json tracked seed
    > synthesized legacy L0
```

The source manifest still derived `providers_effective_hash` and Provider metadata from local/base files, so `MODEL_PROVIDERS` could own the running registry while the manifest claimed a different effective source. It also treated `providers.override.json` as effective even though no runtime `ProviderRegistry` consumer reads that file.

**Correction:** one effective `MODEL_PROVIDERS` observation is shared by hash and Provider-info construction. External process environment wins; before service dotenv load, the same `EffectiveConfig.env_file` is read so launch and service manifests use one source contract. `providers_env_hash` is explicit. `providers.override.json` remains a diagnostic hash only and is never labelled effective. Malformed higher-priority input produces unknown/empty effective facts rather than fabricating a lower source.

### 2.4 Session `current` was conflated with model availability

The prior `/api/v1/models` implementation inserted `current` into `models` whenever it was absent. After hot-disable/delete, that converted a stale session fact into a false “available model” claim.

**Correction:** `current` remains the session/runtime fact; `models` and `catalog` contain only the effective registry; `current_available` reports their relationship. The program does not silently rewrite the user's session model selection.

### 2.5 Settings and Composer held independent stale catalogs

The source ProviderManager refreshed its own settings view after mutation, while Composer fetched `/api/v1/models` only at mount. Hot Provider changes could therefore be visible in Settings but absent from the main model selector.

**Correction:** a single WebUI catalog-change event is emitted after successful registry mutation. Composer subscribes and re-fetches the effective catalog but never overwrites an already-selected session model.

### 2.6 Registry replacement could report rollback after the commit point

`ModelClientPool.replace_registry()` commits the new registry and clears the dynamic-client cache under its lock, then retires old clients. If old-client retirement raised, the exception escaped after the new registry was already committed; Provider admin could then roll back the local file and leave runtime/file truth split.

**Correction:** registry swap + cache clear is the commit point. Old-client retirement is post-commit resource cleanup and is fail-open with a warning. A deterministic RED that forces `_retire_client` to raise now leaves the new registry committed and returns normally.

### 2.7 Provider JSON and dotenv CAS were not atomic under concurrent Web requests

The source re-read `config_version` before writing, but did not lock the `compare -> atomic write -> runtime reload` interval. Two writers based on the same version could both pass the comparison and both commit. Credential/default `.env` operations had the same read-modify-write lost-update risk.

**Correction:** all Provider-control-plane writes share one mutation lock. A process-local `RLock` always serializes threads; on POSIX/macOS/Linux a `0600` data-dir lock file plus `flock` also serializes duplicate control-plane processes. Lock acquisition failure is a typed 503 fail-closed write error. The lock covers Provider JSON CAS, credential writes, default-model writes, and explicit reload.

Deterministic concurrency tests prove:

- two Provider writers based on the same version result in exactly one success and one `provider_config_conflict`, with one file write;
- concurrent API-key and `LLM_MODEL` dotenv updates preserve both keys instead of losing one writer.

## 3. Configuration and authority boundaries

The qualified control plane owns configuration mechanics, not model-quality judgment.

- `MODEL_PROVIDERS` environment JSON is the highest-priority operator/deployment owner. When present, Web Provider mutation is read-only and refuses shadowed writes.
- `providers.local.json` is a complete local snapshot, not a semantic merge overlay. This keeps the effective local Registry deterministic.
- tracked `providers.json` remains a seed/reference source and is never modified by Web admin.
- API-key plaintext is owned by its declared `_API_KEY` / `_TOKEN` / `_SECRET` environment variable. Arbitrary environment-variable names are rejected for credential writes.
- `ModelClientPool` owns live dynamic registry/client mechanics. The startup default client remains a startup snapshot; changing `LLM_MODEL` reports restart truth rather than pretending an unrelated client hot-switched.
- Provider/model capability fields are operator-configured facts. The control plane does not infer which model is “better”, select models by task meaning, or decide semantic completion.

## 4. Security boundaries

Provider admin reuses the existing Web security envelope rather than creating a second authentication mechanism:

- remote control-plane routes remain behind WebAuth;
- existing exact-Origin / CSRF rules still govern writes;
- Provider `base_url` accepts only HTTP(S) with a hostname and rejects URL userinfo credentials;
- local/private endpoints remain allowed for authenticated operator use;
- secret plaintext is not written to Provider JSON, returned in snapshots, or reflected from connectivity-test exceptions;
- local snapshot / dotenv writes are atomic; Provider control-plane concurrent writes are serialized by the shared mutation lock;
- repository tree security scan on the fresh committed candidate reports no sensitive/error content.

## 5. Provider-visible invariants

The 31-file implementation delta from `82e412b` to `16d90e8` contains no Universal Prompt, core prompt-building, tool-registry, or tool-schema files. Provider admin changes configuration/selection/control-plane facts; it does not inject new semantic instructions or hidden task-policy rules into model messages.

The stale-current repair is likewise API/UI truth only: a removed model is not reintroduced into the effective Registry, and no session model is silently rewritten. Local/private endpoint support is preserved as operator capability rather than turned into a program-side model-routing policy.

## 6. Qualification gates

Implementation topology:

```text
integration parent    82e412b73f46443b5f406ef78ea8eb6c0d33ae02
pool hardening        721b06cfdbbb3e43f7f326da7600e664cb14217f
provider admin        16d90e8c388650f3ff8090fbe75d6636051a0ab3
candidate tree        5bbc6c656f61e13546b927fc0e2de5ef568ebdf3
implementation delta  31 files, +3196 / -64
```

Focused / adjacent evidence before commit:

```text
provider-admin focused test functions                 13
runtime-manifest focused test functions               10
LLM client close/retirement focused test functions    20
provider/model/auth/queue adjacent suite               242/242 PASS
full WebUI                                             20 files / 111 tests PASS
Vite production build                                 PASS
```

Fresh detached committed-state evidence at `16d90e8`:

```text
worktree                                               clean
git security tree scan                                1542 files PASS
full ci_gate                                           RC=0
  Ruff                                                 repository full PASS
  test env-pin gate                                    522 files, 0 undeclared
  Pyright                                              0 errors / 0 warnings / 0 informations
  tier0                                                PASS
  xdist full submission gate                          PASS
full WebUI                                             20 files / 111 tests PASS
TypeScript + Vite production build                     PASS (66 modules)
git diff --check                                       PASS
```

Existing React `act(...)`, bundle-size, third-party deprecation, side-effect-audit advisory, and Pyright-update messages remain warnings only; none is a Provider-admin correctness failure.

No live Web/Feishu restart and no local-model (`8901`) change was performed for this qualification. The evidence boundary is the isolated/fresh committed tree; live rollout remains a separate owner-controlled operation.

## 7. A.5 governance declaration (G1–G4)

### G1 — Necessity

Authentication, secret storage, file-version CAS, lock ownership, config-source precedence, registry replacement, and whether a configured model physically exists in the effective Registry are mechanical facts. They cannot safely be delegated to model judgment. In particular, duplicate/lost config writes and secret reflection are hard safety/data-integrity boundaries.

### G2 — Ownership / non-duplication

The Web admin layer owns only Provider/model configuration facts and presentation. `ProviderRegistry` remains the effective model registry; `ModelClientPool` remains runtime client ownership; existing WebAuth/Origin middleware remains authentication; SessionStore remains per-session model-choice truth. No parallel model router, task classifier, semantic completion engine, or second secret store is introduced.

### G3 — Evidence / veto / recovery exit

Every mutable Provider snapshot is versioned for compare-and-write. Deployment-owned `MODEL_PROVIDERS` vetoes Web mutation. Lock failure vetoes writes. Invalid/degraded registry reload does not pretend success. A stale session model remains visible as `current_available=false`, giving the operator/user a truthful recovery path without deleting their previous selection. Credential state exposes presence/source but never plaintext.

### G4 — Rollback / verification

The generic runtime cleanup hardening is isolated in `721b06c`; the Provider-admin capability is isolated in `16d90e8`. Both are locally revertible. The source feature branch remains evidence only. Fresh committed-state security, Python full gate, WebUI full suite, and production build all pass before integration admission. No live runtime was altered during qualification.

## 8. Verdict

**PASS / ADMIT** `721b06c + 16d90e8` as the qualified Provider/model admin convergence implementation.

Do **not** merge the original `feature/web-model-provider-admin-20260909` branch as a unit. The integration action is a fast-forward of the single unified convergence branch to this qualified ancestry after this document itself is committed and its docs-only committed-state checks pass.
