# M1-SIM-002 paired experiment — cost and Host authorization HOLD

Status: **HOLD / NOT AUTHORIZED / 0 of 60 paired episodes run**.
This is an operational gate record, not a change to the frozen preregistration.

## Completed prerequisite

- Real UID463 Host L3 B2 recovery on previously unused engineering smoke seed 6:
  `place_host_verified`, grasp and place both `VERIFIED_BY_ORACLE`.
- Receipt: `experiments/embodied/m1/m1-sim-002/l3_probe_smoke_B2_06_b7930805ddce8beb2636ad84c20b1a20.json`.
- Receipt SHA-256: `6b0afe7ddf5bc0ff7bed0f604b07723da37886d0a95c45dd13628035befd6528`.
- Real model `glm/glm-5.3-flash`, 5 Provider attempts, 7 tool actions, 68.956 seconds.
- This is diagnostic-only, with a disclosed scripted first physical fault and
  smoke-only public lift hint; it is **not** a paired outcome or effect estimate.

## Frozen comparison and operational ceilings

- Frozen preregistration: `experiments/embodied/prereg-m1-sim-002.json`,
  SHA-256 `e4aefedd413874c547c6ab01aebb8c2019491b07b1a887bf7266621fa0c1b5ae`.
- B1/B2: 30 each, paired seeds `20261117..20261146`, learning off.
- Maximum **60** episodes, **360** real Provider attempts, **480** tool actions;
  each episode retains 6 Provider attempts, 8 actions and 180-second deadline.
- **Operator-approved budget ceiling (2026-11-20): USD 20.00 total**,
  **USD 0.05 per-call reservation ceiling**. At 360 reservations the
  nominal reserved allowance is USD 18.00, leaving USD 2.00 headroom.
  Both the root Host grant validator and the client cost gate reject higher
  ceilings. A smaller separately authorized grant remains valid.
- Reference GLM-5.3-Flash list tariff: USD 0.15 / 1M uncached input tokens,
  USD 0.50 / 1M output tokens; cached input USD 0.03 / 1M.
  Source checked 2026-11-20: https://docs.z.ai/guides/overview/pricing .
  The Host grant must not use lower input/output rates without an explicit
  subsequent reviewed policy change. Confirm the *actual* API endpoint,
  account-specific billing and key type before installation; a highest-tier
  subscription does not by itself prove zero API charges.
- Client records Provider-reported input/output/total tokens. Missing usage,
  timeout or unqualified tariff is **unknown**, never zero or free.
- USD is a **tariff-based estimate**, not the Provider's final invoice.
  The operational threshold reserves a configured per-call USD allowance before
  the call; unknown billing or a reserve overrun stops subsequent admissions.
  Do not claim an account-level exact billing hard cap without qualified
  Provider pricing and request upper bounds.

## Separate batch authorization — not yet executed

The source Host helper has an independent `authorize-batch` action and a
paired-only trial issuance guard. The root-owned grant is SHA-pinned to the
frozen experiment, exact candidate, model, expiry, tariff and USD thresholds.
Root-issued trial identities cannot be reused and stop at 60. Smoke Host
authorization does **not** authorize paired trials.

Before any grant or paid paired run, an operator must independently approve:

1. Exact frozen candidate SHA and scoped Host installation security preflight;
   the **final** independent Reviewer remains after the paired experiment.
2. Authoritative GLM tariff source/date and USD input/output rates; any
   applicable currency conversion or cache pricing must be qualified.
3. Approved upper bounds are now `max_total_usd <= 20.00` and
   `reserve_per_call_usd <= 0.05`; the precise signed Host grant and
   request-size suitability are still **NOT INSTALLED / NOT VERIFIED**.
4. Expiration, root-staged grant manifest SHA, protected cost ledger and
   one-time Host installation/authorization scope.
5. A **separate** affirmative approval to start the 30 B1/B2 paired trials.

The new root helper is **source code only** until independently reviewed and
installed through a separately approved Host-only operation. The active Host
remains on engineering smoke; no batch grant, root ledger or paired run has
been installed or started. Do not advance to final Reviewer/R9/remote CI/
protected `main` merge/unified deployment before the paired results and
all required gates pass.
