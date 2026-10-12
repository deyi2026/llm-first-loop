# FC2-C v0.1 — First-Call-Ready Qualification

This is a new protocol identity. It does not amend, reinterpret, or overwrite FC2-B v0.1 evidence.

## Objective

Qualify only the two FC2-C corrections before any Browser execution matrix:

1. canonical `SemanticObject.kind` vocabulary is a single source of truth shared by perception and the bounded operation contract;
2. the provider-visible first-call schema exposes enough closed grammar for Ornith to emit a correct first `browser_semantic_operation` declaration without schema-discovery repair.

This protocol does **not** qualify Browser task completion, grounding quality against a live page, mutation dispatch, wait sensor correctness, cloud providers, or cross-provider schema compatibility.

## Frozen treatment

- implementation: `c6c3f612ae634d19d333ef047ecbd9109f9f8453`
- model: `cognilocal/ornith-1.5-35b-a3b-mlx`
- Thinking: ON
- temperature: 0
- production universal system prompt
- provider-visible tools: exactly `browser_semantic_operation`
- `get_tool_schema`: not exposed
- `read_evidence`: not exposed
- tool execution: **zero**; the harness records the first provider declaration and never dispatches it
- fresh independent model request per row; serial only

The FC2-C lazy schema is mechanically derived from the strict full schema and exposes three first-call branches: object mutation (`click|fill|select|scroll`), page navigation, and object wait. The strict runtime full schema remains six verb-specific branches.

## Matrix

Three declaration shapes, two fresh repeats each:

1. navigate a page;
2. fill canonical `kind=input`, name `Project code`;
3. wait for canonical `kind=button`, name `Run check`, property `enabled`.

No prompt contains JSON, field names, enum lists, or a schema example.

## Gate

PASS requires all of the following:

- 6/6 rows return exactly one first tool call;
- tool name is exactly `browser_semantic_operation`;
- 6/6 arguments satisfy the pre-registered task-specific mechanical oracle;
- each task is 2/2;
- tool execution count is exactly zero;
- no fallback or second model is used;
- the model server identity, provider contract, prompt hashes, implementation commit, experiment commit, and lazy/full schema hashes remain frozen.

A failure remains evidence. The protocol, prompts, schemas, timeout, or oracle must not be changed after the first measured model request. Any change requires a new protocol identity.
