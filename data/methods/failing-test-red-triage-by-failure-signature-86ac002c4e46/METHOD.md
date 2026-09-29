---
method_id: failing-test-red-triage-by-failure-signature-86ac002c4e46
name: failing-test-red-triage-by-failure-signature
description: When a repo has multiple failing tests, first run the failing tests to capture exact assertion/validation signatures, then follow each signature to the test, implementation/contract, and recent commits. Classify each red as environment, code regression, or fixture/contract drift before broad search or fixes.
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:afaf8a78-607b-4e8e-8fd2-0e3cc4e07be4:373:88db2cfc8fec736bdbbc
evidence_refs: learning:learn:ff076828893e
created_at: 2026-09-24T14:20:16.489824+00:00
updated_at: 2026-09-24T14:20:16.489824+00:00
---
## Trigger
A task asks to diagnose several failing tests or test-suite reds, especially guard/contract tests, and the cause is unknown.

## Discriminator
The fastest narrowing fact is the actual failure output: assertion text, validation message, or guard ID that points to a specific contract or fixture mismatch.

## Short path
- Confirm repo/branch/HEAD and working-tree cleanliness.
- Run the failing tests with the repo's interpreter and capture exact failure signatures.
- Use each failure signature to target the relevant test node, implementation, or contract file.
- Inspect recent commits touching that contract to identify whether implementation changed or fixture did not.
- Classify each red as environment, regression, or fixture/contract drift and propose a minimal aligned fix.

## Stop conditions
- Each failing test has an authoritative failure signature and a mapped contract/fixture cause.
- The distinction between environment and code/fixture drift is established.
- A minimal fix direction is identified without editing governance-sensitive files unless authorized.

## Verification
- Re-run the failing tests after the proposed fix or check that the failure signature matches the identified contract change.
- Confirm the fix does not raise guard baselines or weaken contracts merely to make tests pass.
- Check git status/diff to ensure only intended files are touched.

## Counterexamples
- A single test fails due to missing dependency, network, or interpreter mismatch; first repair environment before contract analysis.
- Tests are intentionally flaky or timing-dependent; failure signatures do not map to a stable contract.
- The task is to add tests for new behavior, not diagnose existing reds.
