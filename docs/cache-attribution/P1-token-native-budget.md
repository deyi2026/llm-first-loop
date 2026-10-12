# P1 Token-Native History Budget — Design & Deterministic Qualification

Status: implementation candidate. Base: `006f59aa` cache-attribution scorer.

## 1. Current data flow (read-only audit)

Primary request path today:

1. `RoutingService._resolve_history_budget()` resolves physical/provider facts:
   - physical `context_window`;
   - 90% safety margin;
   - concrete output reserve (`max_tokens`);
   - optional provider/model `max_input_tokens`.
   The result `allowed_input_tokens` is already the correct physical/operational token authority.
2. The same resolver immediately converts that token authority to chars with provider
   `chars_per_token`, falling back to global `0.6`, and exposes that char value as
   `model_window_budget/effective_budget`.
3. `AttemptExecutor.plan()` consumes the char budget. After a real provider overflow it
   mechanically multiplies the char budget by `0.5` for one rebuild.
4. Engine projects the model-visible tool schema, measures its serialized JSON **chars**,
   and `reserve_tool_schema_from_history_budget()` subtracts those chars from the same
   char budget.
5. `build_history_messages(... max_chars=effective_budget)` uses that char cap for
   compaction/projection. System + messages are inside this projector cap; tools are not.
6. There is no local exact pre-send tokenizer guard. `LLMClient` performs structural
   wire validation, but physical context capacity is finally adjudicated by the provider.
   A real overflow triggers deterministic shrink + lossless rebuild; if the provider rejects
   the mechanically mandatory-only projection, the run records `projection_cannot_fit`.

This means the current physical authority is token-native at step 1, but authority is
prematurely converted to a fixed char heuristic at step 2. For the frozen GLM-5.3 long-run
fixture the observed `provider_visible_chars / tokens_in` distribution is approximately:
min 2.617, P10 2.949, P20 3.046, P25 3.104, median 3.339, weighted 3.338. The fallback 0.6
therefore converts a 184k input-token cap to only 110,400 chars before tools.

## 2. P1 contract

P1 changes **capacity accounting**, not semantic history selection:

- `allowed_input_tokens` remains the authority for physical/provider input capacity.
- Tool schema is reserved in **tokens first** using a conservative projection density.
- `history_token_budget = allowed_input_tokens - tool_schema_reserve_tokens`.
- Existing char-based history projection remains in place as a bridge:
  `token_projected_history_chars = floor(history_token_budget * projection_chars_per_token)`.
- Explicit operator/provider `history_*_chars` caps remain valid independent char caps and may
  further reduce the projector cap; they never expand token capacity.
- No local estimate may claim the request physically fits. Provider overflow remains the final
  hard authority and retains the existing deterministic shrink/rebuild lifecycle.
- No tool is semantically hidden/selected by this change.

## 3. Mechanical density observation

The bridge density is mechanical telemetry only. It is keyed by provider/model/wire protocol
and updated from completed **primary** requests where both facts exist:

`ratio = provider_visible_chars / prompt_tokens`.

Rules:

- bounded recent window; no raw prompt/content is stored;
- minimum sample count before an observed value can replace configured/default fallback;
- conservative lower statistic = min(P20(recent ratios), EWMA * 0.90);
- decreases apply immediately (safer); increases use a dead-band + bounded step hysteresis;
- invalid/missing usage does not update state;
- estimator state is process-local mechanical calibration, not session/task authority;
- provider/config `chars_per_token` remains the cold-start fallback.

The density observation must never alter `allowed_input_tokens`; it only changes the char
projector bridge and the token estimate of tool-schema reserve.

## 4. Required telemetry

`request.meta.input_budget` must expose enough facts to reconstruct the decision:

- `requested_input_tokens`
- `allowed_input_tokens`
- `tool_schema_reserve_tokens`
- `effective_history_budget_tokens`
- `projection_chars_per_token`
- `projection_density_source`
- `projection_density_samples`
- `pre_tool_history_budget_chars`
- `tool_schema_reserve_chars` (descriptive compatibility fact)
- `effective_history_budget_chars`
- `limited_by`

## 5. Deterministic qualification matrix

| Gate | Requirement |
|---|---|
| Q1 token authority | changing density never changes `allowed_input_tokens` |
| Q2 tool reserve | tool schema chars are converted to tokens with `ceil(chars/cpt)` and deducted exactly once |
| Q3 char bridge | history char cap derives from remaining tokens × conservative cpt, then explicit char cap may only reduce |
| Q4 cold start | no samples => existing configured/default cpt behavior |
| Q5 hysteresis | one high observation cannot jump directly to workload median; lower evidence can tighten immediately |
| Q6 frozen replay | replay of `51da0a7a` produces deterministic density states and materially less premature char pressure without changing scorer attribution baseline bytes |
| Q7 final authority | provider overflow lifecycle remains unchanged: one deterministic shrink, mandatory-only rejection => cannot-fit |
| Q8 no semantic routing | tool count/content is not pruned or ranked by P1 |
| Q9 telemetry | all token-authority + bridge fields reconcile mechanically |
| Q10 regression | existing routing/history/overflow/cache-attribution gates remain green |

P2 low-water convergence and P3 working-set projection timing are deliberately out of P1.

## 6. Implementation and qualification result (2026-09-14)

P1 is implemented on branch `fix/cache-token-native-budget-20260914`, based on
cache-attribution scorer commit `006f59aa`. The implementation changes mechanical
capacity accounting only; P2 low-water convergence and P3 working-set timing remain
out of scope.

### 6.1 Implemented mechanics

- `allowed_input_tokens` remains unchanged by density calibration and is the physical/provider
  input-capacity authority.
- Tool schema is reserved exactly once in token units with `ceil(tool_schema_chars / cpt)`.
- Remaining history tokens are bridged to the existing char projector; explicit char caps may
  only reduce this projection.
- Density calibration is process-local and bounded: 32 recent ratios per surface, at most 64
  provider/model/wire surfaces, minimum 8 samples before observed relaxation.
- Only a successful normal primary request can teach density. ERR1210 transformed retries and
  successful fallback responses do not reuse the primary request's visible-char observation.
- Fallback candidates rebuild from durable truth and apply their own token-native tool reserve.
- Provider overflow remains the final capacity authority; the existing deterministic shrink and
  `projection_cannot_fit` lifecycle is unchanged.

### 6.2 Frozen replay qualification

Using the scorer golden fixture (`51da0a7a`, 220 GLM-5.3 requests), with
`allowed_input_tokens=184000` and `tool_schema_chars=24881`:

| Decision point | projection cpt | tool reserve tokens | history tokens | history char projector |
|---|---:|---:|---:|---:|
| requests 1-8 (cold) | 0.600000 | 41,469 | 142,531 | 85,518 |
| request 9 | 0.750000 | 33,175 | 150,825 | 113,118 |
| request 16 | 2.861023 | 8,697 | 175,303 | 501,545 |
| request 32 | 3.035372 | 8,198 | 175,802 | 533,624 |
| after all 220 observations | 2.617985 | 9,504 | 174,496 | 456,827 |

The first eight requests intentionally retain the cold fallback. Across the frozen replay,
212/220 request decisions have a projector capacity above the former ~85.5K-char boundary,
while the token authority is exactly 184,000 for every decision. These are deterministic
projector-capacity facts, **not** claims about actual sent-history size or a live hit-rate gain.
The scorer attribution golden remains byte-identical; P1 changes neither its classifier nor its
historical baseline.

### 6.3 Verification

- P1 unit/routing/runtime/overflow/fallback/scorer adjacent suite: 69 tests PASS.
- Changed production Pyright: 0 errors / 0 warnings / 0 informations.
- Changed-code Ruff and `py_compile`: PASS.
- Cache-attribution golden: byte-identical.
- Architecture focused guard: PASS.
- Full `scripts/ci_gate.sh`: Ruff PASS; env-pin 569 files / 0 undeclared; src Pyright 0/0/0;
  tier0 PASS; xdist full suite PASS; architecture guard report PASS.
- First full-CI attempt exposed only a linked-worktree environment prerequisite:
  ignored `data/providers.json` was absent. Copying the mirror's same local fixture into the
  linked worktree made the exact failing test pass; the fixture remains ignored and is not part
  of this change.

No live-provider cache-rate improvement is claimed by P1 qualification. A future live/canary
run may measure outcome, but it must use the attribution scorer rather than total hit rate alone.
