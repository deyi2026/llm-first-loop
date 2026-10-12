# Evidence Recoverability R3 — Consumption Amendment v1.1

Date: 2026-08-26
Reason: full-production holdout design audit found a stale-content bypass in discovery.
Status: **FROZEN BEFORE IMPLEMENTATION OF THIS AMENDMENT**
Provider calls after R3 v1: **0**

## Discovery

R3 v1 made `read_evidence` safe-by-default for probeably stale FILE Evidence, but production enforce also exposes `search_evidence` and the `search_archive` compatibility alias.

Current `EvidenceSearchTool.execute()` refreshes each hit's freshness and then still emits the match-centered snippet even when that refresh says `stale`. Therefore a model can avoid the new `read_evidence` stale block by searching the stale Evidence and consuming the old snippet as current truth.

This violates one logical invariant:

> A probeably stale FILE must not expose stale domain bytes through one recovery entry point while another entry point blocks them.

## v1.1 requirement

For `search_evidence` and `search_archive→search_evidence`:

- add `allow_stale: boolean`, default false;
- when a hit is a probeable FILE and freshness refresh returns `stale`, default output may include ref/source/freshness/currentness metadata but MUST NOT include the stale snippet;
- default metadata MUST state `currentness=historical_only` and `historical_search_requires=allow_stale=true`;
- `allow_stale=true` may return the exact historical snippet, but it remains tagged `freshness=stale currentness=historical_only`;
- current/unknown non-stale search behavior remains unchanged;
- owner isolation and search grammar remain unchanged.

This is a consistency amendment to the R3 data contract, not a prompt patch or Action Guard.
