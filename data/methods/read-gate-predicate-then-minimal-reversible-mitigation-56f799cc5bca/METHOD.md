---
method_id: read-gate-predicate-then-minimal-reversible-mitigation-56f799cc5bca
name: read-gate-predicate-then-minimal-reversible-mitigation
description: When a hard validation gate (e.g. 'worktree must be clean before publish') is expected to block an action, and current state spans multiple candidate violation classes (tracked modifications vs untracked files), do not guess the gate's strictness. Locate the gate's enforcement code by content search on its error vocabulary, read the exact predicate including flags (--untracked-files=no), then mitigate only the blocking class with a reversible mechanism (stash push/pop), restoring unrelated in-flight work immediately after the gated action succeeds.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:40eeca85-e561-4f26-9faf-efda5823cb4b:216:a5b29b97c07e0fe5b318
evidence_refs: learning:learn:aa51edaf91ac
created_at: 2026-10-11T01:24:02.255133+08:00
updated_at: 2026-10-11T01:24:02.255133+08:00
---
## Trigger
An action is or is expected to be blocked by a state-validation gate whose exact scope is unknown, while the environment contains both foreign in-flight work that must not be lost or claimed and potentially-exempt state classes (e.g. dozens of untracked files alongside one tracked modification).

## Discriminator
Two facts visible at decision time: (1) class-separating status tooling already splits candidates (git status porcelain: 'M' tracked-modified vs '??' untracked); (2) the gate is enforced in the same codebase, so its exact predicate is reachable via one content search on gate vocabulary ('must be clean'), not by guessing exact file paths.

## Short path
- Enumerate violation classes with class-separating status tooling (git status --porcelain); unknown: what state could trip the gate.
- Locate the enforcing check by content search on gate vocabulary in the owning module, not by stat-guessing a canonical path; unknown: which classes the gate counts.
- Read the exact predicate including flags (git status --porcelain --untracked-files=no means untracked files are exempt); unknown resolved: only the single tracked modification blocks.
- Mitigate only the blocking class reversibly (stash push tracked changes); never commit or discard others' in-flight work.
- Re-run the gate's own check to confirm clean, execute the gated action (publish), then immediately restore (stash pop) and verify restoration.

## Stop conditions
- Exact predicate and blocking set identified from enforcement code — stop investigating, start mitigating.
- The gate's own check command returns clean immediately before the gated action.
- After restore, pre-existing in-flight changes are verified back unchanged (same files, same diff).

## Verification
- Run the gate's exact check command (same flags) pre-action and require clean output.
- Confirm the gated action's receipt binds the intended source (git_head matches target commit) before proceeding.
- Post-restore, status/diff shows the stashed changes returned intact; no foreign work was committed or dropped.

## Counterexamples
- The blocking dirty files are part of the content being released — stashing would publish wrong code; commit/resolve them instead.
- The gate is external or opaque (binary, remote service; predicate unreadable) — do not source-dive; use the safest reversible default or ask.
- The predicate actually counts untracked files too — a tracked-only stash would not clear the gate; this is exactly why the predicate is read first.
- No unrelated in-flight work is at risk — just commit your own changes; the stash dance adds no value.
