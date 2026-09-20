# MF-5.3.1 root-direct Perceive + Operate measured qualification protocol v0.1

Status: **FROZEN BEFORE ANY MF-5.3.1 MODEL REQUEST**
Date: 2026-09-16
Implementation anchor: `1cb9ad2bddd8b44ca31dd38ff1b30c9dd42c01e0`

## Purpose

Qualify the MF-5.3.1 root-direct Perceive correction after MF-5.3 v0.1 reached 6/6 task correctness but failed the frozen Gate on Perceive wire repair. The model keeps ordinary task reasoning and receives only two Browser concepts:

- `browser_perceive`: seven closed root-direct branches: snapshot / exact hydrate / exact diff / four flat read-only wait kinds;
- `browser_semantic_operation`: one already-decided direct mutation.

`get_tool_schema` and `read_evidence` remain visible only as support tools. Low-level typed wait tools, `browser_action`, `browser_semantic_execute`, and legacy Playwright are not provider-visible.

## Frozen task matrix

Six serial fresh-state rows, identical task prompts and fixture bytes to MF-5.2 and MF-5.3 v0.1:

1. click_commit r1
2. fill_submit r1
3. delayed_wait r1
4. delayed_wait r2
5. fill_submit r2
6. click_commit r2

Every row receives a fresh LFL session, DATA_DIR, Chrome profile and fixture state. No row replay is permitted under the same qualification identity.

## Hard Gate

All conditions must hold simultaneously:

- infrastructure complete and valid for 6/6 rows;
- external fixture oracle 6/6, with 2/2 for each task family;
- first Browser call contract-valid 6/6;
- `browser_perceive` provider schema is root-direct with exactly seven closed branches, has no nested `condition`, and does not expose `interval_ms`;
- exact frozen provider surface on every row;
- no model fallback or SecurityAgent spawn;
- zero `browser_perceive` failures/errors;
- zero `browser_semantic_operation` failures/errors;
- zero `get_tool_schema` calls and zero observable protocol-repair episodes;
- zero ground-probe amplification (`target_not_found` / ambiguous-target actuation probes);
- zero duplicate successful mutations;
- zero hidden atomic Browser calls;
- zero automatic mutation retry/replay;
- zero runtime task-completion judgment;
- zero undeclared structural-boundary continuation;
- zero unparsed operation receipts.

The Gate does **not** inspect hidden chain-of-thought and does not infer task success from receipts.

## Frozen diagnostics, not correctness substitutes

Report separately:

- perceive calls split by snapshot / hydrate / diff / wait;
- operate call count;
- Browser argument/result visible chars;
- ground-probe amplification count;
- duplicate successful mutation count;
- post-operation compact-delta escalation: delta-only / exact hydrate / snapshot / hydrate-then-snapshot;
- read_evidence calls;
- rounds, input tokens, output tokens, cache-hit tokens.

No diagnostic can compensate for a failed external oracle row or any hard safety/cognition Gate.

## Identity and execution discipline

- model: `cognilocal/ornith-1.5-35b-a3b-mlx` on the unique existing 8901 server;
- prompt/decode concurrency: 1/1;
- thinking on, reasoning effort medium;
- max input 184000, max output 16000, temperature 0, top_p 1, top_k 0, min_p 0;
- max iterations 12;
- serial model runs only;
- no second local model;
- no fallback;
- tracked worktree must be clean;
- implementation anchor must remain an ancestor and `src/` + `methods/` must be byte-identical to the implementation anchor;
- the root-direct Perceive branch set is frozen before rows run; provider lazy/full branch shapes must agree;
- execution manifest hashes the exact experiment HEAD, runtime sources, harness files, fixture, prompts, provider surface and live 8901 identity before rows run.

`--max-new-rows 0` is the only allowed zero-model preflight. It may build/freeze the execution manifest and surface manifest, but it must make **zero model generation requests**.
