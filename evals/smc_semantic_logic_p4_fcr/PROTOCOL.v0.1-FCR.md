# SMC Semantic Logic P4-FCR v0.1 — Declaration-only A/B

## Scope

P4-FCR only measures the first provider-visible semantic declaration. It does not execute Browser tools, hydrate refs, launch a Browser runtime, retry, normalize declarations, use fallback, or judge task completion.

The frozen parent protocol is `docs/SMC-SEMANTIC-LOGIC-P4-AB-PROTOCOL-v0.1.json` SHA256 `d39a34053c9762ae6760e6bc65a43375ac6f4023966621963918890af78ab9f6`. P4-D qualified base is `596c4175dd6cb3f0bd27656735f886b923758c80`.

## Matrix

- five task families: `navigate`, `click`, `fill`, `select`, `scroll`
- four repeats per task per arm
- 40 total rows, 20 paired blocks
- repeat 1/3: A then B
- repeat 2/4: B then A
- fixed rotation:
  - r1: navigate, click, fill, select, scroll
  - r2: click, fill, select, scroll, navigate
  - r3: fill, select, scroll, navigate, click
  - r4: select, scroll, navigate, click, fill

Every A/B pair receives byte-identical task text. The task text contains an already-observed opaque exact ref and semantic values. Those refs are declaration fixtures only: P4-FCR never hydrates or executes them.

## Surfaces

Shared in both arms: `browser_perceive`, the five narrow typed waits, and `get_tool_schema`. Shared tool lazy schemas must be byte-identical.

Arm A adds current production `browser_semantic_execute(verb,target_ref,args)`.

Arm B adds five harness-only logical tools exactly matching the frozen P4 protocol: `browser_semantic_click`, `browser_semantic_fill`, `browser_semantic_select`, `browser_semantic_scroll`, `browser_semantic_navigate`. They are never registered in production Factory/registry.

## Measurement

The runner requests at most one model response per formal row. Returned tool calls are raw declarations and are never executed. Offline scoring records first semantic call structural validity, exact mechanical validity, targeted P4-X01/X02/X06/X07 cross-binding errors, and any `get_tool_schema` declaration. No scorer normalization or repair is permitted.

Arm B hard gate remains the parent protocol gate: 20/20 structural valid, 20/20 mechanical valid, targeted cross-binding errors zero, with tool execution, Browser runtime, fallback, normalization, retry, and task-completion judgment all zero.

## Preflight boundary

Before the first real model request, `run_fcr.py --preflight` must freeze `plan.json`, `execution-manifest.json`, and `preflight.json`; verify exact Git/P4 protocol identity, canonical provider contract, a single Ornith 8901 with prompt/decode concurrency 1, no established 8901 clients, exact shared/arm surfaces, and source hashes; and explicitly report `model_requests=0`, `tool_execution_total=0`, `results_present=false`, `qualification_gate_present=false`, `measured_row_dirs=0`.

P4-FCR model execution requires a separate owner decision after this preflight anchor is qualified.
