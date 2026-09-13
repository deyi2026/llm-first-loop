# FC2-C v0.2 — First-Call-Ready Qualification

This is a new protocol identity. It does not amend, reinterpret, or overwrite FC2-C FCR v0.1 evidence.

## Objective

Re-run the exact frozen FC2-C FCR v0.1 matrix after one narrow provider-visible treatment change: the compact first-call schema now mechanically derives the exact mutate/wait field sets from the strict full schema and explicitly states that wait has no `verb` or `args`.

The purpose is to test whether that field-boundary visibility closes the v0.1 wait-only FCR defect. This protocol does **not** qualify Browser task completion, live grounding, mutation dispatch, wait sensor runtime, cloud providers, or cross-provider schema compatibility.

## Frozen treatment

- implementation: `3c1899de437b1d2b5f8a69cb25863263410440b7`
- model: `cognilocal/ornith-1.5-35b-a3b-mlx`
- Thinking: ON
- temperature: 0
- production universal system prompt
- provider-visible tools: exactly `browser_semantic_operation`
- `get_tool_schema`: not exposed
- `read_evidence`: not exposed
- tool execution: **zero**; the harness records the first provider declaration and never dispatches it
- fresh independent model request per row; serial only

The strict runtime full schema is unchanged from v0.1. The first-call lazy schema remains the same three-branch grammar (object mutation, page navigation, object wait); only its mechanically derived `clauses` field-boundary description is added. No normalization, branch reordering, retry, rebind, or completion logic is added.

## Matrix identity

The generated six-row plan MUST remain byte-semantically identical to frozen v0.1 (`plan_sha256=c802cf5137511c28a6875421ab18233c7976b79c12f82a10e5af380e4559d59c`). Same three prompts, same row order, same external task-specific oracle:

1. navigate a page;
2. fill canonical `kind=input`, name `Project code`;
3. wait for canonical `kind=button`, name `Run check`, property `enabled`;
4. repeat wait;
5. repeat fill;
6. repeat navigate.

No prompt contains JSON, field names, enum lists, or a schema example.

## Gate

PASS requires all of the following:

- 6/6 rows return exactly one first tool call;
- tool name is exactly `browser_semantic_operation`;
- 6/6 arguments satisfy the unchanged v0.1 task-specific mechanical oracle;
- each task is 2/2;
- tool execution count is exactly zero;
- no fallback or second model is used;
- model server identity, provider contract, prompt hashes, implementation commit, experiment commit, and lazy/full/wire schema hashes remain frozen.

A failure remains evidence. The protocol, prompts, schemas, timeout, or oracle must not be changed after the first measured model request. Any further change requires another protocol identity.
