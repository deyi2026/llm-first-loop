# Runtime Config C0-A Proof Gate + C0-B Startup SoT Qualification — 2026-09-16

## 1. Verdict scope

This record qualifies the local C0 convergence tranche on top of formal main:

- formal base: `32a9a26611e147a32d4dc0fcccdf10dbc0d40c06`
- C0-A exact commit: `472bfd47b9c3ce811ed48723e16a8a8931330d0d`
- C0-B implementation tip before this record: `5c44c3fa6ac79e3ebbffb7f184235bfe987325a9`
- branch: `fix/runtime-config-c0b-20260916`
- execution scope at authoring time: local only; no push, PR, merge, deployment,
  Web/Feishu restart, or 8901 restart was performed by C0-A/C0-B qualification.

The tranche exists to make later P1-C migration trustworthy.  It does not migrate
LLM/Web/Feishu call-time business keys itself and it does not move secrets into
`runtime.toml`.

## 2. C0-A — Proof Gate truth correction

The pre-C0 scanner reported `126 direct / 0 import-time` on formal main, but that
was not an authoritative inventory.  The scanner recognized only the literal AST
name `os`, so aliases such as `import os as _os` were invisible.  It also recorded
reads inside `_env_*` helper bodies rather than projecting literal helper call sites,
which hid module-import reads in Feishu.

C0-A changes the proof layer only.  It adds:

- alias-aware recognition for `os`, `os.environ`, and `os.getenv` imports;
- literal helper projection to the actual call scope;
- distinct direct/helper/effective counters;
- module-import direct/helper counters and signature ratchets;
- explicit dynamic-secret classification for mechanically recognizable credential
  indirection such as `api_key_env`;
- one-way ratchets that freeze already-existing debt but allow later migration to
  reduce it.

The corrected exact inventory on the C0-A/C0-B tree is:

- physical direct accesses: `134`
- direct files: `44`
- literal-helper accesses: `13`
- dynamic-helper accesses: `3`
- effective observations: `150`
- physical direct module-import accesses: `0`
- helper-projected module-import accesses: `5`
- effective module-import accesses: `5`
- dynamic-secret signatures: `6`

The five effective import-time reads are existing Feishu helper call sites.  C0-A
intentionally freezes them as visible debt instead of fabricating a zero; their
migration belongs to the later Feishu P1-C slice.

## 3. C0-B — formal startup single source of truth

Read-only audit found a startup split-brain possibility on formal main:

1. `restart_mirror.sh` directly spawned `python -m llm_loop.web` and
   `python -m llm_loop.feishu`;
2. those service mains load `.env` and then build real `Settings`;
3. runtime manifest production can independently resolve `runtime.toml`.

Therefore a conflicting `runtime.toml` / `.env` / stale-shell setup could truthfully
produce a manifest derived from TOML while the actual Engine Settings consumed a
lower-precedence compatibility source.

The existing `llm_loop.runtime.launch` already had the required canonical mechanism:
`resolve_effective()` -> identity check -> `apply_to_environ()` compatibility
projection -> manifest -> real service module.  C0-B does not create a second
resolver.  It changes the official restart spawn target to:

- `python -m llm_loop.runtime.launch web`
- `python -m llm_loop.runtime.launch feishu`

The restart script remains the process lifecycle owner.  Runtime config precedence
and provenance remain owned by the existing resolver/launch boundary.

For rollout and rollback safety, PID fallback detection accepts both the historical
direct-entry argv and the new canonical `runtime.launch` argv.  Web still has its
port listener anchor; Feishu still treats the fresh heartbeat PID as authoritative.

## 4. Conflict fixture / authority proof

The C0-B fixture supplies all three business sources with contradictory values:

- `runtime.toml`: TOML model/base URL/history budget/Web port;
- `.env`: different values for the same keys;
- inherited shell: a third stale set of values.

At the actual `runtime.launch` -> service-module boundary, the test invokes the real
`load_settings()` and reads the emitted runtime manifest.  Both independently show
the TOML values for already-migrated business keys; stale shell and `.env` business
values do not win.  Secret placeholders are not persisted to the manifest.

This proves one startup snapshot is consumed by both manifest provenance and real
Settings for the keys already covered by Runtime TOML.  It does not claim that
unmigrated P1-C keys or the future SecretProvider tranche are complete.

## 5. TDD and focused evidence

C0-A TDD RED demonstrated the old scanner failed all five new truth probes:

- module alias recognition;
- imported `environ` / `getenv` aliases;
- literal helper projection and true call scope;
- dynamic secret classification;
- direct/helper inventory separation.

After the minimal scanner change those probes passed, and the combined C0-A focused
set closed at `11/11 PASS`.

C0-B TDD RED then proved the only failing startup condition was the official restart
script bypassing `runtime.launch`.  The conflict fixture for `runtime.launch` itself
already passed.  A second RED exposed rollout risk: PID fallback matched only the old
argv forms.  The implementation updated both spawn and dual-form PID fallback.

C0-B focused/adjacent qualification then closed at `72/72 PASS`, covering startup
SoT, resolver, manifest, P0 config, env Gate, restart behavior, and Feishu entry
adjacency.

## 6. Committed-state qualification

C0-A exact `472bfd47...` committed-state evidence:

- focused: `11/11 PASS`;
- Ruff: PASS;
- env-pin gate: `580 test files / 0 undeclared COMPACT_RATIO dependents`;
- Pyright: `0 errors / 0 warnings / 0 informations`;
- tier0: PASS;
- xdist full: PASS;
- guard-report: PASS;
- `scripts/ci_gate.sh`: exit `0`;
- commit-hook security scan: PASS;
- worktree: clean.

C0-B exact `5c44c3fa...` committed-state evidence:

- focused/adjacent: `72/72 PASS`;
- Ruff: PASS;
- env-pin gate: `581 test files / 0 undeclared COMPACT_RATIO dependents`;
- Pyright: `0 errors / 0 warnings / 0 informations`;
- tier0: PASS;
- xdist full: PASS;
- guard-report: PASS;
- `scripts/ci_gate.sh`: exit `0`;
- commit-hook security scan: PASS;
- worktree: clean.

The recurring 39 test-side-effect provider-URL findings are existing non-blocking
fixture review warnings, not new C0 failures.

## 7. Runtime / remote non-interference during local qualification

After local committed-state qualification, independent read-only checks still showed:

- remote `lfl/main`: exact `32a9a26611e147a32d4dc0fcccdf10dbc0d40c06`;
- running Web manifest: exact `32a9a266...`, `identity_ok=true`;
- Web listener PID remained the previously deployed process;
- Feishu remained the previously deployed process;
- Ornith 8901 remained the single pre-existing listener.

No local development action activated C0-B in production.

## 8. Secrets and later P1-C boundary

C0 does not change provider-admin credential persistence and does not add any secret
field to `runtime.toml`.  Provider `api_key_env`, Web auth secrets, Feishu credentials,
and other secret handling remain outside this tranche and require a later independent
SecretProvider qualification.

After C0 is remotely qualified and separately canaried, the planned business-config
order remains LLM policy -> Web business settings -> Feishu business settings.  The
corrected Proof Gate is the mechanical baseline for measuring those reductions.

## 9. A.5 / remote review boundary

This record is accompanied by one branch-wide A.5 submission manifest covering the
exact formal-base-to-final-head changed-path set.  The A.5 checker performs mechanical
presence/coverage only; `semantic_quality` and `classification_truth` remain
`not_evaluated`.

Before remote publication, validate the staged qualification tree through a synthetic
Git commit object, then commit the records and rerun the real exact
`32a9a266...HEAD` A.5 gate plus security/full CI as needed.  Remote publication must
use ordinary non-force review refs.  Deployment and main promotion remain separate
human checkpoints.

## 10. Rollback

Before deployment, rollback is simply abandoning the C0 review line.  After any
future canary, C0-B can be rolled back by selecting the already-qualified prior code
root `32a9a266...` through the established dual-root restart procedure; no persistent
application-data migration is introduced by C0-A or C0-B.
