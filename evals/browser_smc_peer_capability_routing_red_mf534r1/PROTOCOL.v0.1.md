# MF534-R1 peer-capability routing deterministic RED protocol v0.1

Status: TEST-ONLY DETERMINISTIC RED. No model request is permitted.

## Purpose

Freeze the already-observed MF534 Row3 first-call routing defect independently from its later self-recovery and final task success. The historical trace is evidence replay, not a new model reproduction.

The protocol also defines one narrow compact-description-only A/B hypothesis. It does not rename tools, change `action`/`do`, alter parameter schemas, modify runtime behavior, or claim that the B wording has causal model-quality benefit.

## Frozen historical replay

Source identity: `MF534-ORNITH-v0.1-MEASURED-03d012b5`, row `03-delayed_wait-r1-peer-capability-quality-projection`.

The privacy-safe fixture preserves only tool name, status, argument-key shape, action/do identity and argument hashes. It intentionally omits raw URL, page content and grounding values.

Required deterministic verdict:

- first Browser call: `browser_perceive(action=navigate, url=...)` -> routing FAIL;
- later `browser_operate(do=navigate, url=...)` success -> `recovered_later=true`;
- external task oracle remains `task_pass=true`;
- later recovery/task PASS MUST NOT overwrite the first-call routing FAIL.

## Compact-description A/B

A = exact current provider-visible compact descriptions from `ToolRegistry`.

B = test-local string-only treatment that adds explicit peer ownership in both directions:

- Perceive names its closed `action=snapshot|hydrate|diff|wait` family and points navigation to `browser_operate(do=navigate,url=...)`;
- Operate explicitly binds navigation to `browser_operate(do=navigate,url=...)` and names Perceive as the read-only action family.

A/B invariants:

- tool names identical;
- parameter schemas identical;
- only compact description strings differ;
- deterministic boundary score: A RED, B GREEN on the frozen hypothesis.

A RED/B GREEN proves only contract-visibility separation. It does not prove that the model will route correctly; any model reproduction or causal qualification requires a separate later protocol and authorization.
