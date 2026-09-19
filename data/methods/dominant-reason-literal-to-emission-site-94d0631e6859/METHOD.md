---
method_id: dominant-reason-literal-to-emission-site-94d0631e6859
name: dominant-reason-literal-to-emission-site
description: For a subsystem stuck in a repeated requeue/retry/fail loop whose journal or log records a reason literal per event: read the reason-field distribution first — it arbitrates competing causal hypotheses in a single read. Then grep the DOMINANT literal in the source of the line that actually runs (deploy worktree/branch, not the mirror/repo head); a machine-written reason literal maps to one emitting site. Read only that branch and its callee's concrete failure conditions; skip guards whose reason strings have zero occurrences, and do not re-verify already-excluded branches.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:658:b803f6cc6959a61ba946
evidence_refs: learning:learn:a20c6fa0b53a
created_at: 2026-09-17T15:32:21.457460+00:00
updated_at: 2026-09-17T15:32:21.457460+00:00
---
## Trigger
A background/async component shows many repeated requeue/retry/failure events, its journal logs a discrete reason (or error-code) literal per event, and multiple candidate guards in the code could plausibly explain the loop.

## Discriminator
Journal reason distribution: one reason literal accounts for ~100% of events while alternative reason strings the code can emit have zero occurrences. This is observable before reading any source and collapses N candidate guards to the single branch that actually fires — it also prevents mis-attributing the loop to a guard that merely looks suspicious in code (e.g. prominent foreground/priority checks).

## Short path
- Aggregate journal events for the affected job/event class and read the reason-field distribution; resolves: which failure branch actually dominates, arbitrating competing hypotheses in one read.
- Grep the dominant reason literal in the source tree of the running deployment (worktree/deploy branch — runtime literals are emitted by running code, not the mirror head); resolves: which site emits it.
- Read the emitting site with surrounding context; resolves: under what condition that branch fires and which callee it wraps (e.g. a revalidation call and how its expected-state argument is computed).
- Read only that callee's rejection conditions; resolves: which concrete check can fail for this caller's actual inputs.
- Cross-check that alternative reasons have zero occurrences, correct any earlier mis-attribution, and stop once the exact failing condition is identified.
- If the journal stores only a coarse reason (not the underlying error message), propose a controlled reproduction of the single call to capture the specific failure string before proposing a fix or a new observation window.

## Stop conditions
- The emitting branch's concrete failure conditions are identified and are reachable from the caller's actual inputs.
- Competing hypotheses whose reason literals have zero journal occurrences are explicitly ruled out.
- The user's design-vs-runtime-behavior question is answered from the verified emission chain — stop discovery and report, including any correction of prior claims.
- Do not launch monitoring/observation windows over a pipeline already proven structurally blocked; the failing condition must be reproduced and fixed first.

## Verification
- Grepping the dominant literal in the running tree yields a unique (or very few) emission site, and the site's mark/log call string matches the journal literal exactly.
- Reason counts are internally consistent: every looped event carries the dominant reason; alternative reasons total zero.
- The callee's failing condition is actually triggerable by the caller's inputs (e.g. an always-None expected-state argument reaching a mismatch check).
- After any fix, re-aggregating the journal shows the reason distribution change (loop events stop or shift reason).

## Counterexamples
- Journal reason strings are coarse or shared by several emission sites — the distribution no longer pinpoints one branch; all candidate guards must be read, or finer-grained reasons added.
- A one-off failure with a direct traceback: the traceback's function/line is already the provenance edge; reading event distributions adds nothing and should be skipped.
- Running source is unavailable or version-drifted from the journal (the literal moved or was renamed between versions) — literal search on the wrong tree misleads; confirm version alignment first.
- No machine-written reason field exists (silent retries) — fall back to code-reading the loop's guards or a controlled reproduction; this method has no anchor.
