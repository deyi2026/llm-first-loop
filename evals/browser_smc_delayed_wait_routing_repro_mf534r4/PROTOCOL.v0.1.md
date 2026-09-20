# MF534-R4 targeted delayed_wait routing reproduction protocol v0.1

Status: FROZEN TARGETED DIAGNOSTIC. This is not a production qualification.

## Purpose

Reproduce only the historical MF534 delayed_wait first-call cross-capability slip: `browser_perceive(action=navigate, url=...)` followed by recovery to `browser_operate(do=navigate, ...)`.

The experiment deliberately excludes click_commit and fill_submit so the independently frozen MF534-R3 ref-kind / intent-to-tool-JSON binding incident cannot contaminate this routing discriminator.

## Arms

- A: exact current compact descriptions.
- B: the already-frozen test-local compact-description-only peer-binding treatment from MF534-R1/R2.

No tool name, parameter schema, `action`/`do`, task prompt, fixture, runtime, Browser mechanics, retry policy, task-completion authority, or model setting changes between arms.

## Matrix

Eight paired repeats, sixteen rows total. Every pair runs the exact same `delayed_wait` prompt/fixture once per arm. Pair-first order alternates A/B, B/A across repeats 1..8. Every row uses a fresh Browser profile and fresh LFL session. Runs are serial against the single existing Ornith server on 8901.

No row may be selectively replayed under this protocol identity.

## Primary discriminator

The primary event is the first Browser capability call:

- valid navigation: `browser_operate(do=navigate, url=...)`;
- cross-capability failure: `browser_perceive(action=navigate, url=...)`.

A later recovery does not erase the first-call failure. Task success does not override routing failure.

## Diagnostic adjudication

Both arms must remain infra-valid, mechanically safe, and 8/8 on the external delayed_wait oracle for the measurement to be valid.

- If A has zero cross-capability first-call failures, result is `INCONCLUSIVE_CEILING`. The treatment effect is not adjudicated and no full A/B or production change is authorized from this run.
- If A reproduces at least one historical routing failure and B has fewer failures plus more first-call passes, result is `IMPROVED` as a targeted diagnostic signal only.
- Equal non-zero failure counts are `NO_OBSERVED_DIFFERENCE`; more B failures are `REGRESSED`; mixed metrics are `MIXED`.
- Any correctness/infra/mechanical-safety violation makes the diagnostic `INVALID`.

Regardless of signal, this protocol never authorizes production modification. Any later full qualification requires a fresh protocol identity.

## Preflight

Before any model request, freeze and verify:

- exact Git HEAD and tracked-clean state;
- MF534-R1 routing RED and MF534-R3 ref-kind RED are ancestors;
- no `src/` or `methods/` drift since the production compact-description anchor;
- 8901 is the unique intended Ornith runtime with prompt/decode concurrency 1/1 and max output 16k;
- A/B full provider surfaces and parameter schemas are byte-identical while lazy compact descriptions differ exactly as declared;
- frozen delayed_wait prompt and fixture hashes;
- exact 16-row static plan and source hashes.
