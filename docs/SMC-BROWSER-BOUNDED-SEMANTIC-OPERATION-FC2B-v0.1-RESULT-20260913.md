# SMC Browser FC2-B Bounded Semantic Operation v0.1 — Formal Result (2026-09-13)

**Status: `NOT_QUALIFIED_BY_FC2B_V0.1`**

Implementation: `5789d767199d570893cba3304b8e463f6c36bcb7`
Frozen experiment: `3e7c1dfa9cf28d067151249cd734331b075799b7`
Frozen Gate: **FAIL** — task oracle **3/6**.

## 1. Verdict

FC2-B v0.1 is **not qualified**. The formal six-row Ornith matrix completed without infra invalidation or timeout, but only 3/6 tasks passed and the preregistered zero-contract-friction conditions also failed. No row was replayed, the Gate was not weakened, and production was not changed after measurement began.

The useful positive result is narrower: the button-only delayed readiness path completed **2/2**, including real typed wait followed by real single-dispatch click. The failure is therefore not a collapse of the underlying Browser perception / wait / stale-version / ActionReceipt stack.

## 2. Six-row matrix

| Row | Task | Repeat | Status | Rounds | Ops | Op FAIL | Halt | nav ok | object ok | wait satisfied | Evidence reads |
|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | click_commit | 1 | TASK_FAIL | 12 | 3 | 2 | 0 | 1 | 0 | 0 | 7 |
| 2 | fill_submit | 1 | TASK_FAIL | 12 | 7 | 2 | 4 | 1 | 0 | 0 | 4 |
| 3 | delayed_wait | 1 | PASS | 9 | 4 | 1 | 0 | 1 | 1 | 1 | 3 |
| 4 | delayed_wait | 2 | PASS | 10 | 4 | 2 | 0 | 1 | 1 | 1 | 4 |
| 5 | fill_submit | 2 | TASK_FAIL | 12 | 6 | 4 | 1 | 1 | 0 | 0 | 5 |
| 6 | click_commit | 2 | PASS | 12 | 7 | 3 | 2 | 1 | 1 | 0 | 4 |

Per-task: `click_commit=1/2`, `fill_submit=0/2`, `delayed_wait=2/2`.

## 3. Frozen Gate failures

- Task oracle: **3/6**, required 6/6.
- Mechanical rows: **FAIL**.
- Operation tool failures: **14**, required 0.
- Operation halted receipts: **7**, required 0.
- Unparsed operation results after FAILURE/ERROR projections: **14**, required 0.

The Gate did **not** fail on infrastructure or safety: `infra_valid=true`, exact surface=true, fallback=0, SecurityAgent=0, direct atomic Browser calls=0, ActionReceipt automatic retry=0, scope blockers=0, and task-completion violations=0.

## 4. Root-cause evidence

### 4.1 First-call contract friction is systematic

The first `browser_semantic_operation` call failed in **6/6 rows**. The recurring first shapes used undeclared clause concepts such as `kind=browser`, `kind=page`, or `kind=action` before the model fetched the full schema. Across the matrix the model made **7** `get_tool_schema` calls and **27** exact Evidence hydration calls. This is strong evidence that the lazy top-level contract plus progressive disclosure is currently expensive for Ornith; it is not evidence for adding program-side semantic routing.

### 4.2 A deterministic identity-vocabulary mismatch makes the input task unrepresentable

The real Browser perception bundle represents the actionable **Project code** control as canonical `kind=input`, `role=textbox`. Browser perception's `_KINDS` vocabulary explicitly contains `input`. FC2-B v0.1, however, requires identity `kind + name` while its closed kind enum is `button | textbox | select | link | text | region | document` — it does **not** contain `input`.

Therefore the current contract cannot express the exact canonical identity of that input object. The program correctly returns `exact_identity_match_count:0` instead of guessing or rebinding; `fill_submit` consequently finished **0/2** with zero object mutation dispatches. This is a contract bug, not a reason to introduce fuzzy matching.

### 4.3 The bounded button path is viable

`delayed_wait` passed **2/2**. Both successful rows produced real navigate ActionReceipts, a satisfied bounded wait clause, and a real object click with no early click. This proves that once the model declares a representable exact identity, the bounded `observe → ground → wait → single-dispatch` mechanics can work repeatedly.

## 5. Aggregate diagnostics

- 67 model rounds; 65 tool calls; 31 bounded-operation calls.
- 14 operation FAILURE, 0 ERROR, 7 halted receipts.
- 7 exact-zero matches; 0 ambiguous (>1) matches.
- 333,541 input tokens; 11,489 output tokens; 280,388 cache-hit tokens.
- Matrix wall time: 487.425s.

## 6. Safety / LLM-First boundary

- No fuzzy/best-match target substitution was introduced.
- No auto-target/latest/rebind/retry was performed.
- No direct atomic Browser tool was visible or called by the model.
- ActionReceipt retry remained false throughout; no scope/version blocker was hidden.
- `task_completion` remained `not_evaluated`; the program never declared the user task complete.
- No cloud provider, second local model, or SecurityAgent path was used.

## 7. Evidence identity

- `execution-manifest.json` — SHA256 `8e8ce90598328a50955ba12b6a20b4e0319955814c4d062fa3351db69e5877cb` — 50683 bytes
- `plan.json` — SHA256 `6e07cb857f2adc9047755411c01856623d1112212ba8dd84d3e8b834554f629c` — 1213 bytes
- `results.jsonl` — SHA256 `563c9c67538b0f41b0d4e6394e96879b086a33613375e8791a9772986aa1163c` — 33267 bytes
- `qualification-gate.json` — SHA256 `daf5e4c62ce783d767ce7d7d77414b75c22c1a6364951cc970933c4a4557c876` — 3106 bytes

## 8. Closure

**FC2-B v0.1 is closed as FAIL and must not be retrospectively repaired.** A future change, if separately authorized, needs a new protocol identity and a fresh full matrix. The first two design targets are mechanical: align the model-facing identity kind vocabulary with canonical `SemanticObject.kind`, and reduce first-call schema/progressive-disclosure friction without adding semantic target selection or completion authority.

No FC2-C/v0.2 implementation or cloud qualification is started by this report.
