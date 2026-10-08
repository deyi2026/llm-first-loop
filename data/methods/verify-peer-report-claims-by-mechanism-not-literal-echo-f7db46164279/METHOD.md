---
method_id: verify-peer-report-claims-by-mechanism-not-literal-echo-f7db46164279
name: verify-peer-report-claims-by-mechanism-not-literal-echo
description: When a peer report asserts repo facts (new commits, test counts, 'X now handles cases A/B/C') and proposes next steps built on them, verify each load-bearing claim with the cheapest authoritative receipt before acting. Verify effect-level claims against the actual mechanism, not by grepping the report's named examples: a general coverage predicate can satisfy the claim while containing none of the named literals, so a literal-grep miss is a hypothesis to test, not a verdict of falsity.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:236:ff4ac420ed1e85fd39f3
evidence_refs: learning:learn:60c6b9f6a4d2
created_at: 2026-10-08T00:33:55.260313+08:00
updated_at: 2026-10-08T00:33:55.260313+08:00
---
## Trigger
A narrative completion/progress report from a peer agent or human asserts verifiable repo facts — commits, test numbers, implementation changes — and the proposed next phase depends on those claims being true.

## Discriminator
Every load-bearing claim maps to a cheap authoritative receipt already reachable from task start: git log/status for commit claims, a targeted test run for count claims, the named source region for implementation claims. For 'now covers A/B/C' claims, the early discriminator is the coverage mechanism in already-fetched source: if a general predicate (e.g., a character-class check over mode/flag values) subsumes A/B/C, the claim is true-in-effect even though none of the literals A/B/C appear — this predicate was visible in the first grep receipt, before any deeper reading.

## Short path
- Extract the report's load-bearing claims (commits exist, counts reproduce, mechanism X covers A/B/C); skip decorative sentences.
- Run the single cheapest authoritative check per claim: git log/status for commits, one targeted test run for numbers, read the named source region for implementation claims.
- On apparent contradiction (grep for the report's named examples finds nothing), treat it as hypothesis-not-verdict: locate the mechanism's coverage predicate and test whether it subsumes the claimed cases.
- Record each claim as verified / false / true-in-effect-but-implemented-differently, quoting the actual mechanism for the third case.
- Only after receipt-backed verdicts, execute the report's proposed next steps.

## Stop conditions
- All load-bearing claims carry a receipt-backed verdict (verified / false / true-in-effect).
- Each discrepancy is precisely characterized and annotated; stop verifying decorative claims.

## Verification
- Every claim later built upon cites a receipt: commit hash in log output, test-run exit code, or source lines.
- Each 'true-in-effect' resolution quotes the actual mechanism and shows it subsumes the claimed cases.
- Final answer separates narrative claims from receipt-verified facts.

## Counterexamples
- The report asserts a specific implementation ('the literals A/B/C are enumerated in a table') rather than an effect — absence of the literals IS the discrepancy; general-mechanism coverage does not rescue it.
- No authoritative receipt exists for the claim (subjective judgment or external system) — do not fake verification; request provenance instead.
- Read-only task where no later step builds on the report — verifying decorative claims wastes budget; verify only load-bearing ones.
- You are emitting a finality assertion about a resource with known concurrent writers — that emit-side case belongs to fresh-read-authoritative-record-before-finality-claim, not this consume-side method.
