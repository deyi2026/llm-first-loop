# MiniMax index-schema compatibility receipt — 2026-11-15

This is a **bounded live Provider wire-compatibility probe**, not a reproduction of the historical round-103 context-capacity incident and not an authorization to deploy.

- Provider/model: `minimax/MiniMax-M3.1-Flash`, configured OpenAI-compatible wire.
- Exactly one Provider request, no retry, no model-selected tool execution.
- Tools on the request: 101 distinct callable names. One `get_tool_schema` has machine-readable `tool_name` string property and `required=["tool_name"]`; the remaining 100 have emergency-index `parameters={"type":"object"}`.
- Provider accepted the request and returned a visible final response of 2 characters; declared tool calls: 0; elapsed time: 1.9 seconds.
- No credentials, tool outputs, private session data, or production code were included in the request. Probe data were synthetic.
- Exact local evidence: `/tmp/lfl-context-capacity-minimax-schema-smoke-20261115.json` (not checked into Git). The test was executed outside the production Web process.

This proves the **tested MiniMax endpoint accepts this schema wire shape**. It does **not** establish that all providers accept it, that the local 32K model can use 101 tools reliably, or that the MiniMax round-103 in-process projection mismatch has been explained.
