# SMC Semantic Logic P1-A Result — Typed FactGraph IR

> Date: 2026-09-17
> Status: **PASS / shadow-only**
> Baseline: `main@19e253edfe4d3fcbeb268830b90d00fd273a6262`
> Branch: `feature/smc-semantic-logic-p1a-20260917`
> Design baseline commit: `942c7655`
> Implementation commit: `2e99b99f5232d1b16bdc01754a9fefa787015629`
> Production consumer: **none**
> N3 reasoner: **not installed / not used**
> P1-B: **NOT_STARTED**

## 1. Scope

P1-A implements only the first layer frozen by `SMC-SEMANTIC-LOGIC-P1-HYBRID-PROTOCOL-v0.1.json`:

```text
current Python canonical output
        |
        v
Typed FactGraph IR
        |
        v
lossless shadow reconstruction
```

The implementation MUST NOT participate in:

- provider-visible schema;
- Browser routing or target selection;
- semantic planning;
- Predicate semantic choice;
- mutation dispatch;
- retry/rebind;
- permission/admission;
- task-completion judgment;
- ActionReceipt authority.

Existing Browser/SMX/FileService Python paths remain canonical and authoritative during P1.

## 2. Implementation

New shadow package:

- `src/llm_loop/semantic_logic/__init__.py`
- `src/llm_loop/semantic_logic/ir.py`

New qualification test:

- `tests/unit/test_smc_semantic_logic_p1a.py`

The IR contains:

- `FactContext`;
- `FactProvenance`;
- `SemanticFact`;
- `ContainerShape`;
- `FactGraph`;
- `project_document()`.

### 2.1 Representation contract

`project_document()` accepts a JSON-compatible canonical Python document and mechanically projects it into:

```text
typed leaf facts
+ explicit object/array container shapes
+ mechanically visible context/provenance metadata
```

The source document can then be reconstructed without semantic loss.

Explicit container markers are required so empty objects and arrays survive round-trip projection.

### 2.2 What `asserted` means

P1-A `SemanticFact.truth_state="asserted"` means only:

> the frozen/current Python oracle emitted this exact leaf in this exact oracle document.

It does **not** mean that the fact is timeless world truth, current across another snapshot, or authorized for execution.

### 2.3 Context and provenance

Context/provenance metadata is inherited only from mechanically visible ancestor fields such as:

```text
domain
source
scope_ref
snapshot_id
observed_version
grounding_ref
sensor_contract_ref
```

P1-A does not infer missing source, scope, version, relevance, intent, or permission.

### 2.4 Fail-closed representation boundary

The projector rejects:

- non-JSON values;
- non-string object keys;
- non-finite floats.

It does not coerce these values into a representation.

## 3. Frozen fixture execution

The P0 manifest freezes 15 cases across five gates. P1-A does not manufacture separate expected JSON for these cases.

Instead, the qualification test invokes the existing Browser canonical classes/APIs to build the actual case bundle, then projects that bundle into Typed FactGraph IR and reconstructs it.

### S1 — Grounding Closure

3/3 projected:

- object GroundingRef compile;
- resource GroundingRef compile;
- cross-session/wrong-projection/expired fail-closed behavior.

### S2 — C28 Source Conflict

2/2 projected:

- DOM/AX field conflict;
- identity-fusion ambiguity.

The projection separately verifies that conflict observations retain DOM/AX source provenance and grounded references.

### S3 — Predicate Honesty

3/3 projected:

- complete vs partial negative absence;
- unknown/snapshot-local identity;
- lower-bound object count.

### S4 — Version / Staleness

4/4 projected:

- same-generation target change;
- unchanged object in newer observation;
- document-generation change;
- incomplete missing target + expired expected version.

### S5 — Receipt / Single Dispatch

3/3 projected:

- running → terminal append-only sequence;
- duplicate action rejection with one physical dispatch;
- transport ambiguity with no automatic replay.

Result:

```text
frozen cases represented = 15 / 15
round-trip semantic loss = 0 observed
production consumers = 0
```

The claim above is deliberately limited to P1-A representation of the frozen/current Python oracle documents. It is not a claim that a new semantic rule engine already reproduces those rules; semantic closure remains future work.

## 4. Qualification results

### 4.1 New P1-A focused suite

```text
tests/unit/test_smc_semantic_logic_p1a.py
21 / 21 PASS
```

The 21 tests include:

- exact 15-case manifest coverage;
- lossless projection/reconstruction for every case;
- deterministic projection for one identical concrete oracle document;
- conflict source/grounding provenance preservation;
- empty-container and scalar-type preservation;
- AST proof of zero production imports;
- fail-closed non-JSON/non-finite handling.

### 4.2 P1-A + frozen Browser oracle adjacency

Exact collection:

| Test file | Count |
|---|---:|
| `test_smc_browser_action_v01.py` | 18 |
| `test_smc_browser_perception_v01.py` | 47 |
| `test_smc_browser_predicate_wait_v01.py` | 20 |
| `test_smc_browser_semantic_diff_v01.py` | 13 |
| `test_smc_browser_semantic_execute_v01.py` | 7 |
| `test_smc_browser_version_pressure_v01.py` | 14 |
| `test_smc_semantic_logic_p1a.py` | 21 |
| **Total** | **140** |

Result:

```text
140 / 140 PASS
```

The original frozen Browser oracle subset remains **119/119 PASS**.

### 4.3 Static qualification

```text
Ruff: PASS
py_compile: PASS
Pyright: 0 errors / 0 warnings / 0 informations
git diff --check: PASS
```

### 4.4 Whole repository gate

Executed with the repository's canonical shared interpreter explicitly selected for the linked worktree:

```text
PY=<repo>/.venv/bin/python
PY="$PY" bash scripts/ci_gate.sh
```

Result:

```text
Ruff full gate: PASS
env-pin: 588 test files / 0 undeclared COMPACT_RATIO dependents
Pyright src: 0 errors / 0 warnings / 0 informations
tier0: PASS
full xdist: PASS
ci_gate: PASS
```

The repository's recurring 41 `audit_test_side_effects` entries remain warning-only and did not block the gate.

## 5. Production-consumer proof

P1-A includes an AST test that scans production `src/llm_loop/**/*.py` outside the new package and rejects any import of:

```text
llm_loop.semantic_logic
```

Result:

```text
production semantic_logic consumers = 0
```

Independent source diff inspection also shows no change to the audited canonical paths:

- `src/llm_loop/browser/**`;
- `src/llm_loop/tools/builtin/browser_semantic_execute.py`;
- `src/llm_loop/tools/builtin/browser_wait.py`;
- `src/llm_loop/workspace/file_service.py`.

## 6. Implementation hashes before result-doc commit

```text
src/llm_loop/semantic_logic/__init__.py
  sha256 6b9a0afdf0aadc1125cf48185be647342ce22bc303a326236588ecb4ddc151ee

src/llm_loop/semantic_logic/ir.py
  sha256 4c91407e151577f85578321ec7e55ffc3a37f9e335d873f13c847c5540c9f688

tests/unit/test_smc_semantic_logic_p1a.py
  sha256 ba4ef43da59f95a1480e4e29a8def31bdf4a6eab3b2dcef43efbbee441100723
```

## 7. Architecture verdict

**P1-A PASS.**

The implementation identity qualified by this report is:

```text
2e99b99f5232d1b16bdc01754a9fefa787015629
```

The evidence supports the first Hybrid premise:

> Existing SMC canonical outputs can be represented by a typed, local, dependency-free, shadow-only FactGraph without changing existing Browser behavior or losing the frozen 15-case oracle documents.

P1-A does **not** yet prove:

- semantic rule equivalence;
- N3 serialization correctness;
- N3 reasoner correctness;
- proof-chain equivalence;
- cross-domain Browser + Filesystem portability;
- production authority eligibility.

Those belong to later phases.

## 8. Stop boundary

After this result is committed and committed-state gates pass:

```text
P1-A = COMPLETE
P1-B = NOT_STARTED
P1-C = NOT_STARTED
P1-D = NOT_STARTED
```

No N3 dependency, provider-visible behavior, deployment, service restart, or runtime authority change is part of P1-A.
