# Evidence Recoverability R0 — Phase 0/1/2 Result v1

> Date: 2026-08-26
> Scope: offline deterministic implementation only; no real provider calls
> Contract: `.codeartsdoer/specs/ev_recov/spec.md` + `design.md` v1.1
> Runtime rollout: `EVIDENCE_MODE` effective default remains `off`

## 1. Status

R0 has completed the contract/oracle foundation, Phase 1 persistence primitives, and Phase 2 opt-in shadow dual-write path.

This is **not** an ERC completion claim. Capture-before-projection enforcement, model-visible recovery capsule, discovery/search, source freshness probing, compression/provider integration, and legacy migration/GC orchestration remain later R0 phases.

Current promotion state:

```text
R0 contract/oracle       READY
Phase 1 store/ledger     PASS
Phase 2 shadow capture   PASS
Phase 3 enforce          NOT IMPLEMENTED (explicitly rejected)
Production mode          OFF
```

## 2. Frozen deterministic oracle

`tests/fixtures/evidence_recoverability_r0.json` defines R0-1..R0-12, binds the v1.1 contract SHAs, and states `provider_calls_allowed=false`.

The phase assignment prevents an implementation from weakening future gates merely to make an early phase green.

## 3. Phase 1 implementation

`src/llm_loop/memory/evidence.py` implements:

- immutable content-addressed `BlobRef` (`blob://sha256/...`);
- owner-scoped logical `EvidenceRef` / immutable `EvidenceRecord`;
- mutable `EvidenceState` separate from capture identity;
- `OwnerScope(workspace_id, session_id)` authorization boundary;
- atomic blob persistence using temp file + fsync + rename;
- deterministic replay-safe EvidenceRef derivation;
- owner-aware durable `EvidenceLedgerStore`;
- exact bounded `EvidenceHydration` for Unicode text-char and line ranges;
- bounded queryless `RecoveryManifest` projection;
- shared-blob refcount primitives for later owner-aware GC.

Mechanical invariants already proven include:

```text
same bytes -> same BlobRef
same bytes + different owner/capture -> different EvidenceRef
BlobRef != model-facing read credential
cross-owner hydration -> denied
state update != record mutation
same capture replay -> idempotent
concurrent same capture -> one logical record
blob corruption -> detected
shared blob survives first owner deletion
command/URL locator secrets are not emitted in manifest labels
```

## 4. Phase 2 shadow implementation

`src/llm_loop/tools/evidence_shadow.py` plus the optional Registry hook provides a dual-write observer.

Important behavior:

```text
legacy tool execution
    -> pre-trim raw observation retained only when shadow hook is installed
    -> Evidence shadow dual-write
    -> existing tool-internal trim / Registry summary / Archive behavior unchanged
    -> existing model-visible bytes unchanged
```

`ToolResult.raw_observation` is internal-only and is not emitted by `to_message()` / `to_llm_dict()`.

The following tools expose a pre-internal-trim observation only while the shadow ContextVar is enabled:

- `read_file`
- `execute_command`
- `web_search`

Default path has the ContextVar `False`, so normal calls do not retain an additional large raw string.

Shadow failures are fail-open **only for recoverability**: they are logged but never rewrite an already-successful source action into failure or trigger an automatic re-execution.

## 5. Factory rollout control

`Settings.evidence_mode` / `EVIDENCE_MODE` supports:

```text
off      legacy behavior; no Evidence store/hook
shadow   opt-in dual-write; prompt/tool-visible output unchanged
enforce  recognized but explicitly rejected at startup until Phase 3 exists
```

Invalid values fail safe to `off`.

`Settings.to_status_dict()` exposes only `evidence_mode`, not refs/paths/content.

`.env` was not changed and contains no `EVIDENCE_MODE`, therefore the effective runtime mode remains `off`.

`.env.example` and `docs/configuration.md` document the rollout semantics.

## 6. Verification

### ERC targeted

- ERC oracle + Phase 1 + Phase 2 + factory targeted suites: PASS.
- Phase 1 adversarial tests cover authorization, corruption, concurrent idempotency, refcount, owner isolation, state immutability, and safe manifest labels.
- `ruff`: PASS for new/touched ERC code.
- `pyright`: `0 errors, 0 warnings` for config/factory/evidence/shadow core paths.

### Affected legacy regression

A 251-test directly affected regression set passed, covering:

- builtin tools / command trim / env scrub;
- ToolRegistry pipeline and unregister;
- run-context propagation;
- background cancellation/runner;
- path registry;
- ArchiveStore search/index/segments/GC;
- history/layering;
- SessionStore;
- ERC tests.

### Full repository regression

Plain `pytest -q` currently cannot collect because the already-stopped A3 development test `tests/unit/test_action_guard_a3.py` imports unavailable `scripts.calib.action_guard`. This blocker predates and is unrelated to ERC; A3 is formally development-only/stopped, so ERC did not patch it merely to make collection green.

With only that stopped-A3 test ignored:

```text
pytest -q --ignore=tests/unit/test_action_guard_a3.py
-> exit 0
-> 100% complete
-> no failures
```

Third-party deprecation warnings remain and are unrelated.

## 7. Current artifact hashes

```text
5801c435a8db1899fc9f8ae0ce59e95df6bc974c7a4d4f674685984c6657e4a7  src/llm_loop/memory/evidence.py
0738657d1178d5902b2462146306eab158cf928a8cc40d3249d6cc2d47386070  src/llm_loop/tools/evidence_shadow.py
ee8927e80386af7e241aa1f83b21d6c37cf637d3b19779bbf8abe6fff59f47c9  tests/fixtures/evidence_recoverability_r0.json
97c22518487f06321531d3ec9261060199ed483306ffa55663b6b20ba6d94771  .codeartsdoer/specs/ev_recov/spec.md
95243f1c4cf1afa2391a8f9e106f3f097c599e6c18ba1761db8b9a4a78afa19b  .codeartsdoer/specs/ev_recov/design.md
```

## 8. What remains before ERC can affect model behavior

Do not enable `enforce` yet.

The next phase must implement and mechanically verify:

1. a real capture-before-projection boundary where tools no longer discard raw observation before canonical capture;
2. explicit action-status vs recoverability-status propagation;
3. deterministic model-visible Evidence capsule without destabilizing the stable prefix;
4. temperature/representation orthogonality (HOT does not force full content);
5. R0-7 and R0-11 gates.

Only after that should R0 move to discovery/hydration tools (`search_evidence`, `read_evidence`, `list_evidence`) and later compression/provider invariance.

Action Guard remains P2 and is not part of this repair stage.
