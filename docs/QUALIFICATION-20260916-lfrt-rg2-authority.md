# LFRT -> LFL RG-2 Admission Authority Qualification — 2026-09-16

## 1. Verdict scope

This record qualifies the local/remote-review candidate that adds LFRT as an
**optional mechanical admission fact source** for the existing RG-2 local-runtime
resource path. It does not switch production authority by itself.

Exact identities:

- formal LFL base: `439ad55d9b2e69be5146877691a0bf409e2e4df4`
- read-only LFRT observer chain:
  - `ccae21f5` — read-only observer
  - `becdee1a` — shadow parity
  - `27d364cc5e203845ccdae43f2f2421cbf06d3d3f` — typed config + on-demand status wiring
- admission implementation anchor:
  - `c53755736991f34ef9cdde3e89c68ecf34981729`
  - `feat(resources): add LFRT admission authority`
- external LFRT machine-contract dependency:
  - repository `deyi2026/lfrt-runtime`
  - review ref `review/runtime-observation-v1-20260916`
  - exact final SHA `be8e54358b5a9e365a011ab4f1d9ceb70a90efd7`
  - contract `runtime-observation/v1`

The LFL implementation anchor is preserved remotely at
`review/lfrt-rg2-authority-c1-c8-20260916`. The qualification/A.5 record is a
review-only child of that exact implementation anchor.

## 2. Pre-cutover defects that had to be closed

Read-only cutover audit found that directly replacing the legacy local runtime
adapter would be unsafe:

1. `ProviderCallCoordinator` historically interpreted observer `None` as no
   qualified local scope and therefore yielded no lease. An authoritative LFRT
   failure could silently bypass RG-2.
2. `ResourceGovernor` retained an installed concurrency limit and had no explicit
   invalidation API. A previously observed capacity could survive a later failed
   observation.
3. Generic `acquire(timeout=None)` may wait indefinitely when a required fact is
   unknown. Managed-local authority failure therefore must be terminal before
   entering that wait path, not translated into a permanently deferred request.
4. The older rich LFRT `status --json` is a diagnostic surface: it includes HTTP,
   activity, memory, and repair-capable config behavior and is not a stable
   versioned admission contract.
5. Learning performs work between initial resource admission and its real provider
   transport; a runtime restart during that interval can change PID generation.

The candidate closes these mechanics without adding semantic task ranking or model
completion policy.

## 3. LFRT machine contract

LFRT `runtime-observation/v1` is the only LFRT wire contract accepted by the new
admission adapter. The final `be8e543...` contract is deliberately narrow:

- strict read-only config load;
- no config creation, repair, `.bak`, or default-write path;
- no `/v1/models` HTTP probe;
- no activity probe;
- no memory probe;
- only launchd, listener, and process observation;
- all valid-config states carry `managed_port`;
- `observed` requires managed port, launchd/listener/process PID agreement,
  exact `-m mlx_lm.server`, live model, and positive live prompt/decode
  concurrency;
- `stopped` requires mechanically confirmed stopped/unregistered service **and**
  no listener on the managed port;
- uncertainty/conflict never fabricates capacity.

Committed LFRT evidence after the `managed_port` follow-up:

- LFRT selftest: `31/31 PASS`;
- four LFRT unittest suites: `79/79 PASS`;
- `py_compile`: PASS;
- `git diff --check`: PASS;
- security/hygiene: PASS;
- real 8901 read-only sample: Ornith, port 8901, live concurrency 1/1;
- 12-run latency sample: median about `77.55 ms`, max about `80.3 ms`;
- LFRT candidate/live config hash+size+mtime unchanged;
- 8901 listener unchanged;
- no restart/switch/deployment.

## 4. Tri-state target contract

LFL admission uses three mechanical states:

- `NOT_APPLICABLE`: the selected local authority does not own this target;
- `MANAGED_BUT_UNKNOWN`: this is the managed local target but a required fact is
  unavailable, invalid, stopped, conflicting, or incompatible;
- `OBSERVED`: current mechanically complete runtime/capacity facts are available.

Only `NOT_APPLICABLE` may preserve the no-local-lease path. A managed local unknown
invalidates stale capacity and raises before provider transport.

No TTL cache is used in the initial authority implementation. Each request obtains a
fresh LFRT observation so a restarted PID/capacity is not hidden behind a stale cache.

## 5. Authority ownership and shadow veto

`local_runtime.admission_authority` is independent from diagnostic
`local_runtime.observer`:

- default: `legacy`;
- optional candidate mode: `lfrt`.

When `lfrt` is selected:

- LFRT is the only positive source of local-runtime capacity;
- the legacy lsof/ps adapter remains only as an independent shadow veto;
- explicit key/runtime-type/capacity/PID-generation disagreement yields
  `fact_conflict` and invalidates the capacity fact;
- absent/unavailable legacy observation is neutral and never supplies fallback
  capacity.

This prevents a partial LFRT outage from silently restoring the old adapter as an
unreviewed positive authority.

## 6. Capacity generation and Learning TOCTOU

`ResourceGovernor` now records optional `source_ref` and runtime `generation` with a
concurrency fact and exposes an explicit invalidation operation. Invalidation removes
the fact for future admission but never preempts an already active lease.

For Learning:

- authoritative `ResourceAdmissionError` cannot fall back to the RG-1 process lane;
- the initial resource request is still admitted through the shared Governor;
- immediately before reflection provider transport, the same request is revalidated;
- key, installed capacity, LFRT generation, and legacy shadow facts must still match;
- a changed/unknown generation invalidates the fact and requeues the job without
  consuming an attempt;
- a successful revalidation does not renew or widen the old lease.

This closes the delayed-transport PID-generation TOCTOU without semantic retry logic.

## 7. Deterministic and adversarial qualification

The branch-wide focused/adjacent set contains exactly `250` collected tests and
passed. Coverage includes:

- remote target does not invoke LFRT;
- managed other port is not applicable;
- config unavailable, stopped, command failure, malformed JSON, wrong contract,
  and partial runtime facts become managed-unknown;
- stale capacity is invalidated before failure;
- managed unknown never enters provider transport;
- LFRT is observed per request, with no TTL cache;
- legacy shadow PID/scope/limit mismatch vetoes LFRT positive authority;
- legacy unavailable never becomes positive fallback;
- default legacy mode never invokes LFRT authority;
- capacity generation replacement/invalidation keeps active leases non-preemptive;
- Learning does not fall back to RG-1 and revalidates immediately before transport;
- typed runtime TOML defaults to legacy and factory only creates the LFRT authority
  adapter when explicitly selected.

The runtime-env proof inventory remains exactly:

- direct: `134`;
- effective: `150`;
- effective module-import: `5`;
- direct/effective files: `44`.

The new typed setting therefore introduced no new direct environment-access debt.

## 8. Committed-state LFL qualification

Exact implementation anchor `c537557...`:

- worktree: clean;
- branch-wide implementation diff vs `27d364cc...`: 13 files, +1073/-22;
- broad focused/adjacent: PASS (`250` collected);
- Ruff: PASS;
- Pyright whole `src`: `0 errors / 0 warnings / 0 informations`;
- `git diff --check`: PASS;
- runtime-env ratchets: PASS;
- `scripts/ci_gate.sh`: explicit `rc=0`;
  - Ruff PASS;
  - env-pin PASS;
  - Pyright PASS;
  - tier0 PASS;
  - full pytest PASS;
- whole-tree `scripts/git_security_scan.sh`: `rc=0`.

## 9. Real 8901 authority canary

The canary uses exact committed LFL `c537557...` together with exact LFRT
`be8e543...`. It constructs only an in-memory Governor/Coordinator and sends **no
model request**.

Observed facts:

- resource key: `cognilocal / runtime / mlx-loopback:8901`;
- capacity: `1`;
- source: `lfrt-runtime-observation:8901:pid:<current-pid>`;
- generation: `pid:<current-pid>`;
- first lease: admitted;
- second lease while first is active: deferred / `concurrency_full`;
- second lease after release: admitted;
- final in-flight count: zero;
- listener before/after: same unique 8901 PID;
- canonical `runtime.toml`: unchanged;
- LFRT `config.json`: unchanged.

The exact PID is a runtime observation, not a source-code identity and is therefore
not pinned in this document.

## 10. Production non-interference

At final local qualification:

- formal LFL main remained `439ad55d...`;
- live runtime manifest remained exact `439ad55d...`, `identity_ok=true`;
- Web remained on canonical `llm_loop.runtime.launch web`;
- Feishu remained on canonical `llm_loop.runtime.launch feishu`;
- Ornith remained the single pre-existing 8901 listener;
- canonical production `runtime.toml` contained no `admission_authority` override.

Therefore production RG-2 remained `legacy` throughout C1-C8. No Web/Feishu/8901
restart or authority cutover was performed.

## 11. Explicit non-claims / later boundaries

This tranche does **not** qualify:

- multiple provider aliases sharing one physical 8901 as one lease key;
- a distributed semaphore shared across Web/Feishu/other LFL processes;
- GGUF/llama.cpp or remote self-hosted runtime authority;
- cloud provider concurrency/rate/quota authority;
- semantic task importance, completion, or model-selection policy.

Those require separate contracts and evidence.

## 12. Rollback and next gate

Before deployment, rollback is abandoning the review line. After a future canary,
mechanical rollback is setting `local_runtime.admission_authority = "legacy"` and
restarting only the LFL services through the established dual-root restart path;
8901 does not need to restart for an authority-source rollback.

Remote review must run branch-wide A.5 plus normal CI/security against the exact PR
head. A successful remote review still does not authorize deployment or main
promotion; production authority cutover remains a separate rollbackable human
checkpoint.
