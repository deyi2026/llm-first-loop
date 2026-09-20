# MF-5.2 Cognition-Preserving Browser Actuation — Ornith 6-row Qualification Protocol v0.1

Status: **FROZEN BEFORE MODEL EXECUTION**

## Question

Can the model reason normally about the task and use `browser_semantic_operation` only as actuation, without schema/contract repair becoming part of the trajectory?

## Frozen model-visible surface

Exactly three tools:

1. `browser_semantic_operation`
2. `get_tool_schema`
3. `read_evidence`

`get_tool_schema` remains visible deliberately: a cognition-preserving PASS requires **zero** schema-repair calls on this already-known tool. Hidden atomic Browser tools remain unavailable to the model.

## Frozen tasks/order

1. click_commit r1
2. fill_submit r1
3. delayed_wait r1
4. delayed_wait r2
5. fill_submit r2
6. click_commit r2

Prompts and fixture bytes remain identical to MF-5 / FC2.

## Runtime

- model: `cognilocal/ornith-1.5-35b-a3b-mlx`
- Thinking ON; temperature 0
- input/output 184000 / 16000
- prompt/decode concurrency 1/1
- max rounds 12
- fresh session, DATA_DIR and Chrome profile per row
- serial only; no fallback; no second local model

## Hard treatment Gate

All conjunctive:

- task oracle 6/6, each task 2/2;
- first `browser_semantic_operation` call contract-valid 6/6;
- operation tool FAILURE=0 and ERROR=0;
- `get_tool_schema`=0;
- observable `protocol_repair_episode_count`=0;
- automatic mutation retry=0;
- direct model calls to hidden atomic Browser tools=0;
- runtime task completion judgment=0;
- undeclared structural-boundary continuation=0;
- exact surface, no fallback, no infra timeout/failure.

For this frozen qualification, `protocol_repair_episode_count` is a conservative observable proxy: every semantic-operation contract failure plus every schema lookup. It does not inspect or score hidden chain-of-thought.

Rounds/tokens/cache/read_evidence/argument+result chars and one-action-vs-multi-action horizon distribution are diagnostics, not substitutes for the hard Gate.

## Evidence discipline

No measured row is replayed or repaired in place. A code/schema/protocol change requires a new qualification identity. Failure remains failure even if later analysis explains it.
