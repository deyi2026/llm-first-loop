# Execution Efficiency / First-Call-Ready — adversarially reviewed plan

> Status: **DESIGN / P0 NOT STARTED** (2026-09-25)
>
> This plan supersedes prompt/schema byte minimization as a primary optimization goal.
> It does **not** authorize a production default flip, deployment, or provider-visible
> behavior change by itself.

## 1. North star

Optimization order is strict:

1. **Verified Correctness** — external/task oracle, authorization, scope, protocol,
   currentness and side effects are correct.
2. **First-Call-Ready (FCR)** — the first task-relevant action selects an appropriate
   tool and supplies mechanically executable arguments.
3. **Total Execution Efficiency** — whole-run new-prefill/input/output tokens, rounds,
   schema rereads, rejected/failed calls, repairs, duplicate verification and wall time.

Provider-prefix bytes are an explanatory metric, not the objective.  A larger stable
contract wins when it produces a cheaper and more reliable whole task.

## 2. Corrected agency boundary

Historical wording sometimes collapsed two different goals into "program minimalism":

- **Correct:** the program must not invent the user's semantic goal, choose a
  semantically different task, silently decide open-ended relevance, or manufacture
  completion criteria.
- **Incorrect:** therefore every operation a model could reason through should be left
  to the model, and model-visible information should be minimized by default.

The replacement rule is:

> **Semantic authority belongs to the user/model; mechanically decidable work belongs
> to deterministic machinery when doing so preserves semantics and reduces error/cost.**

Program-owned work may therefore include JSON-schema validation, exact ref/version
binding, fixed-field compilation, lossless representation changes, deterministic
resolvers, declared-acceptance verification, and bounded retry of a mechanically known
idempotent/no-side-effect transient operation.  These are not semantic task selection.

Conversely, automatic high-impact retry, fuzzy target substitution, semantic task
replacement, hidden method selection, and program-invented completion remain outside
the boundary.

## 3. Historical assumptions explicitly rejected as promotion gates

The following may still be useful implementation properties, but are no longer valid
optimization goals by themselves:

- universal prompt `<400 chars`;
- compact description `<=160 chars`;
- lazy schema default justified only by "save tokens";
- `provider-visible program chars=0` interpreted as a universal virtue rather than a
  guard against untrusted strategy prose;
- "full schema reread after failure" treated as normal rather than an FCR miss when the
  missing fact was load-bearing and knowable beforehand;
- "the model decides completion" interpreted to forbid deterministic verification of
  acceptance criteria already declared by the user/task/tool protocol;
- "no automatic retry" interpreted to forbid safe deterministic transport/idempotent
  retry.

## 4. Information placement

### 4.1 Universal/common governance

Keep it deterministic, stable and task-authority safe.  Do not mirror the whole rule
book.  There is **no arbitrary character target**.  A stable item belongs here only if
real qualification shows broad benefit (correctness/FCR/anti-drift) that outweighs its
steady-state and cold-prefix cost.

### 4.2 Tool-local contract

This is the primary home for load-bearing operational facts:

- purpose and nearest-tool distinction;
- required fields, enum/range and legal state transitions;
- exact ID/ref/path provenance;
- currentness/version/scope rules;
- side-effect and idempotency semantics;
- precise failure meaning;
- one or two short canonical examples when historical failures prove they matter;
- known mechanical pitfalls.

"Compact" means **remove redundant prose**, not truncate by character count.

Before any formal arm is frozen, run a **contract-truth audit** across the actual tool
implementation, machine `parameters`, full description, compact description,
parameter-local compact facts, and adapter-projected wire form.  More text is not a
benefit if the text is stale or contradictory.  No arm may be called the "full truth"
merely because it contains the longest description; executable code/schema and current
runtime receipts remain authoritative for mechanical facts.

Canonical examples are treatments too.  They must use placeholders/stable refs rather
than environment-specific IDs, be justified by a real failure class, and include
held-out variants so the benchmark can detect example-copy overfitting.

### 4.3 Rule / Method / Skill / Experience

Do not dump full libraries into every request.  Also do not equate "not globally
dumped" with "invisible until after failure".

Qualification may test bounded candidate discovery (title/ref/one-line applicability
facts) followed by exact hydration.  Retrieval/ranking is an information service, not
task authority: candidates must be observable, attributable and ignorable by the model.

Candidate cards must preserve provenance/trust/verification/currentness facts.  A
retrieval hit never upgrades historical, model-authored or user-derived text into
system/tool authority.  Formal P2 must separately report candidate recall/coverage and
false-positive exposure on a frozen relevance oracle, including negative tasks where a
plausible-looking Method/Experience is intentionally inapplicable.

## 5. Experimental axes

Do not conflate provider surface and runtime mechanics.

### P1A — provider-facing contract axis

- **A current:** current lazy/compact behavior.
- **B FCR contract:** audited load-bearing tool-local facts, no arbitrary truncation.
- **D full-schema reference:** complete tool descriptions/parameters as an information
  upper reference, not a presumed production winner.

Runtime validation/retry behavior remains byte-for-byte equivalent across P1A arms.

### P1B — deterministic mechanical assistance axis

After choosing the best P1A surface, compare the same surface with mechanical precheck
OFF vs ON (required/type/enum/nesting and other demonstrably semantic-free checks).
This isolates repair/safety benefit from model-facing information benefit.

Do not treat today's `PreCheckLayer` as a universal validator: its current implemented
subset is required/type/enum/object-array recursion.  Range constraints, exact
ref/version/state, authorization and tool-specific transition checks may live in other
schema/provider/tool boundaries and must be measured/changed as separately identified
mechanical contracts rather than silently attributed to one switch.

### P2 — knowledge discovery axis

Compare the selected P1 configuration with and without bounded Rule/Method/Skill/Experience
candidate discovery.  When P1B has no qualified winner, the selected P1 configuration may
be the explicitly retained incumbent only if the handoff records P1B as inconclusive;
retaining that incumbent is not promotion evidence and must not be described as a P1B win.
Exact content is hydrated only after discovery; production promotion is separate from the
experiment.

The experimental exposure itself must be provenance-explicit and non-authoritative:
candidate cards are labeled reference/advisory facts, never fabricated as user text or
system policy, contain no imperative strategy prose, and cannot appear after the current
user truth in a way that changes task authority.  The experiment records the exact
origin/role/bytes seen by the provider so a retrieval benefit cannot be confused with a
new hidden instruction channel.

### P3 — model-specific presentation

Only create weak/strong-model profiles if the frozen data proves a stable interaction.
Do not assume in advance that strong models need less interface truth.

## 6. Qualification hygiene that was missing from the first draft

### Cache state

Stable prefix cost is different cold vs warm.  Every provider/model arm must report at
least **cold** and **warm/steady-state** results, with a frozen warm-up procedure.  Do
not hide larger cold prefill behind cache hits or ignore stable-prefix reuse.

### Context-pressure / compaction interaction

Record actual provider-visible schema/system bytes or tokens, context limit, history
budget, compaction/fold count, projected history chars and dropped/archived bytes.
Richer schema that forces destructive working-set pressure is a real regression.

### Exact wire surface

Hash and persist the actual provider-facing system/tools payload per arm (including
adapter transforms and dynamic boundary tools), not only source definitions.

This is load-bearing for local text-tool providers: `LLMClient._lms_tools_text()`
currently performs a **second compression layer** after registry projection (first-line
description truncated to 120 chars and a reduced parameter skeleton).  P1 must either
make this adapter transformation part of the explicit treatment or hold it identical
and report it as a limitation; registry `lazy/full` source bytes alone are not the
experimental surface seen by such a model.

### Subagents

Current SubAgentRunner hard-codes `schemas(lazy=True)`.  P1 must either propagate the
experimental surface into subagents or exclude subagent tasks from the first formal
matrix.  Mixed parent/full + child/lazy rows are invalid evidence.

### Knowledge contamination

Use an immutable knowledge snapshot per formal matrix.  Disable/redirect learning
writes so earlier repeats cannot teach later repeats.  Historical methods/experiences
derived from a benchmark task cannot be used to score that same task family unless the
protocol explicitly labels it as a reuse test; held-out families are required.

The knowledge snapshot also freezes trust/provenance metadata.  Do not compare arms
where one arm silently promotes an unverified Experience or untrusted document into a
higher instruction role.

### Ordering / variance

Randomize or Latin-square arm order within model/task, use fresh sessions/workspaces,
freeze model/reasoning/temperature/runtime identity, and report task-level paired deltas
rather than treating repeated rows as independent samples.

## 7. Metrics and anti-gaming rules

Reuse `evals/pilot` raw telemetry + offline scorer.  Extend it with:

- provider system/schema/knowledge bytes (and tokens when observable);
- get_tool_schema/schema-reread count;
- rejected/unexpected failure count;
- confirmed repair count;
- repeated-success verification / exact-call repeat count;
- Rule/Method/Skill/Experience discovery and hydration count;
- rounds/tool calls/wall time;
- input/cache-hit/new-prefill/output tokens;
- reasoning tokens when the provider exposes them separately;
- compaction/history-pressure facts.

Provider-independent physical metrics remain primary.  A frozen per-run provider price
snapshot may additionally derive billable monetary cost (including different cache/
input/output rates), but changing vendor pricing must not rewrite the cross-provider
technical conclusion after the fact.

FCR keeps **mechanical correctness** primary.  Directness is secondary: legitimate
current-fact verification (`get_goal`, `task_frontier`, equivalent scoped reads) must
not be optimized away merely to make the first call look direct.

## 8. Promotion gates

1. **Correctness hard gate:** no task-family, authorization, scope, protocol, data
   integrity or side-effect regression.
2. **Targeted FCR gate:** historical failure families must improve or remain closed;
   no pooled-average masking of a regression.
3. **Repair gate:** schema rereads, rejected calls, unexpected failures, repairs and
   redundant verification should fall or remain non-regressive.
4. **Whole-run efficiency gate:** compare successful paired rows on new-prefill + output,
   rounds, tool calls and wall time; report raw input and cache-hit separately.
5. **Cold/warm gate:** a treatment cannot be promoted from warm-cache results alone.

No single weighted score decides promotion.  Use correctness hard gates plus paired
Pareto evidence and explicit trade-offs.

## 9. Boundaries retained from agency-first

The review does **not** re-authorize:

- program-invented user goals or semantic task replacement;
- automatic high-impact/non-idempotent mutation retry;
- fuzzy/latest target substitution when exact identity is required;
- hidden completion criteria or program-authored claims that a semantic task is done;
- full memory/experience dumps into ordinary runs;
- program advice masquerading as user/reference/tool truth;
- provider-specific hidden semantic routing.

The correction is narrower: do not use these authority protections to justify hiding
mechanical truth, omitting reusable knowledge discovery, or forcing the model to pay for
deterministic work with extra reasoning/tool rounds.

## 10. Immediate cleanup vs deferred behavior changes

Safe cleanup now:

- remove arbitrary `<400` prompt and `<=160` compact-description CI gates;
- stop silently truncating explicitly reviewed compact descriptions;
- rewrite comments that claim lazy/compact is inherently cheaper/better;
- correct Rule-02 and agency-first prose to distinguish semantic authority from
  deterministic mechanical assistance;
- mark old cache-stability/minimal-injection conclusions as historical, not current
  optimization verdicts.

P0 audit work before model A/B:

- generate a tool contract matrix (`implementation / parameters / full / compact /
  adapter-wire`) and flag contradictions, silent truncation and missing load-bearing
  facts;
- classify every model-visible example/hint by provenance and authority layer;
- freeze knowledge-retrieval relevance/negative-control oracles separately from task
  completion oracles.

Deferred to frozen P0/P1 experiment:

- flipping `tool_schema_lazy` default;
- enabling mechanical precheck by default;
- changing subagent schema mode;
- reintroducing task-start/failure-time bounded knowledge candidates;
- expanding the universal prompt.

## 11. Adversarial review ledger (2026-09-25)

| Grill question | Failure mode if ignored | Ruling / protocol consequence |
|---|---|---|
| Is a shorter request necessarily cheaper? | More schema lookup, failures, repairs and rounds can increase total tokens/time. | No. Prefix bytes are explanatory only; whole-run cost is the objective after correctness/FCR. |
| Does a stronger model need less interface truth? | Hidden/private tool facts still have to be rediscovered by trial/error. | No default assumption. Measure model × treatment interaction; profiles only after evidence. |
| Does agency-first mean the program should do as little as possible? | Models pay tokens for deterministic type/ref/state work; mechanical mistakes are mislabeled “autonomy”. | No. Minimize **semantic authority**, not deterministic assistance. |
| Does “model decides completion” forbid program verification? | Already-declared acceptance/evidence conditions get repeatedly reinterpreted by the model. | Program may verify declared mechanical acceptance; it may not invent open-ended completion criteria. |
| Is all automatic retry anti-agency? | Harmless deterministic transport/transient recovery is needlessly surfaced to the model. | No. Bounded, mechanically proven idempotent/no-side-effect retry is eligible; high-impact/semantic retry is not. |
| Is full schema the truth arm? | Full prose may itself be stale or contradictory. | D is an information-upper reference, not a truth oracle. P0 contract-truth audit is mandatory. |
| Is compact safe if parameters remain executable? | Ref provenance/state/failure semantics can be lost even when JSON is schema-valid. | Compact must preserve load-bearing semantics; arbitrary character truncation is disallowed for reviewed contracts. |
| Can source-level lazy/full bytes define the treatment? | Provider adapters may perform another compression/rewrite. | No. Persist/hash the **actual wire** after adapter transformation. |
| Can parent and subagent use different schema modes in one row? | Mixed treatment makes attribution impossible. | No. Propagate the arm or exclude subagent tasks. |
| Can warm-cache data alone justify a larger prefix? | Cold-start regressions get hidden by cache reuse. | No. Freeze and report cold + warm/steady-state cohorts. |
| Can a richer stable prefix always be accepted if FCR improves? | It may steal working-set budget and trigger compaction/evidence loss. | No. Context-pressure/compaction is part of the hard regression surface. |
| Is a knowledge retrieval hit equivalent to useful guidance? | Stale/irrelevant/untrusted history can distract or become instruction injection. | No. Preserve provenance/trust/currentness; measure recall and false-positive exposure; hit never upgrades authority. |
| Can benchmark repeats learn from one another? | Later arms/repeats get an unfair Experience/Method advantage. | No. Freeze/redirect learning writes; immutable knowledge snapshot; held-out families. |
| Is a canonical example harmless? | Models can copy IDs/shape and overfit instead of understanding the contract. | No. Examples require real failure evidence, placeholders and held-out variants. |
| Should “direct first call” be maximized? | Useful current-fact verification gets penalized and unsafe guessing is rewarded. | No. Mechanical correctness is primary; directness remains secondary with explicit legitimate-side-call rules. |
| Can one aggregate score decide promotion? | High success loss can be hidden by token savings, or one easy task family can mask another. | No. Correctness hard gate + per-family FCR/repair gates + paired Pareto cost evidence. |
| Can provider price be the efficiency metric? | Vendor pricing changes and cache tariffs distort architectural conclusions. | No. Physical metrics primary; frozen price snapshot is secondary billable-cost reporting. |
| Can we add more schema text without provider compatibility checks? | Provider schema/description limits or wire behavior may reject the supposedly better arm. | No. P0 freezes provider capability/size limits; any real rejection is a treatment regression, not infra noise. |
| Does zero program-authored model text remain a universal target? | Useful factual contracts/reference discovery are prohibited together with bad strategy nudges. | No. Keep the ban on hidden strategy/authority prose; judge explicit factual/reference surfaces by qualification. |
| Does passing unit tests qualify the optimization? | Tests can only prove contracts, not model execution efficiency. | No. Production promotion requires frozen real-model behavioral A/B plus external task oracles. |

Any implementation proposal that contradicts a ruling above must either amend this plan
with new evidence before the formal rows start or be treated as a different protocol
identity.  It cannot silently change the active experiment after results are visible.
