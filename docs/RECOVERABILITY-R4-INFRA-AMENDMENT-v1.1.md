# Evidence Recoverability R4 — Infra Amendment v1.1

Date: 2026-08-26
Scope: **runner transport only**
Behavioral data from R4 v1 real attempt: **INVALID / NONE**

## Trigger

The first frozen R4 runner passed `ToolRegistry.schemas()` internal entries directly to `LLMClient`. Production does not do this: `LoopEngine` first converts each schema through `_schema_to_param()` into the OpenAI-compatible function-tool envelope.

Both providers rejected request JSON before model execution:

- DeepSeek: `tools[0]: missing field type`;
- MiniMax: `invalid tool type`.

All 36 rows had `source_execution_count=0` and `recovery_success_count=0`; therefore no R4 behavioral observation exists in the v1 attempt.

## Allowed v1.1 change

Only the runner transport adapter may change:

```text
{name, description, parameters}
→
{type:"function", function:{name, description, parameters}}
```

This must be byte-for-byte equivalent in structure to production `LoopEngine._schema_to_param()` semantics.

Also bump the machine frozen-pack filename/schema to v1.1 so the runner cannot silently accept the superseded v1 lock.

## Frozen inputs that MUST remain unchanged

- R4 pre-registration;
- fixture bytes / answer tokens;
- 36-run matrix/order;
- scorer and all gates;
- R3 v1.1 production Evidence implementation;
- provider/model parameters.

No prompt, task, oracle, score threshold or production Evidence code may change.

The invalid v1 real artifacts are preserved under `data/audit/evidence_r4/infra_invalid_v1/`.
