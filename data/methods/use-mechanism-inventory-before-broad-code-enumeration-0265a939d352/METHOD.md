---
method_id: use-mechanism-inventory-before-broad-code-enumeration-0265a939d352
name: use-mechanism-inventory-before-broad-code-enumeration
description: When comparing mechanisms across two systems, first look for an explicit mechanism inventory, known-gaps, or truth/status table. Treat it as a join key: extract named mechanisms, claimed status, and code anchors, then verify only those anchors in code. Use broad directory enumeration only when no inventory exists or an inventory item lacks an anchor. This prevents free-text search misses from turning into whole-repo scanning.
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:6aec21cb-8703-4ef8-9229-f57e73cdb86e:27:c1f50b451f7f483ab19c
evidence_refs: learning:learn:848da860c5c4
created_at: 2026-09-24T00:14:25.627344+00:00
updated_at: 2026-09-24T00:14:25.627344+00:00
---
## Trigger
Comparing two codebases or systems for mechanism/implementation differences, especially when free-text documentation search misses or docs are numerous and named by run IDs rather than mechanisms.

## Discriminator
An already-visible artifact exposes an explicit mechanism inventory, known-gaps, truth table, or status table that names mechanisms and points to implementation status or code anchors.

## Short path
- Fetch the explicit mechanism inventory/status table before broad directory listing.
- Extract mechanism names, claimed status, and any file/function anchors from it.
- For each mechanism, inspect only the referenced code or run targeted searches for those anchors.
- Compare claimed status with observed code behavior and mark unverified items.
- Only if an inventory item has no anchor or the inventory is absent, broaden to directory enumeration.

## Stop conditions
- Every requested mechanism has either a verified code anchor or an explicit targeted-search miss.
- The user only needs high-level positioning and inventory/positioning docs answer it.
- The inventory is absent or contradicted by code, and targeted code verification has established the truth.

## Verification
- Each comparison row cites an inventory entry plus a code anchor, or an explicit miss from targeted search.
- Status labels distinguish implemented, partial, design goal, and unverified.
- No final claim relies solely on broad directory listing or stale documentation.

## Counterexamples
- No explicit inventory/truth table exists, so broad discovery is needed to find anchors.
- The inventory is known to be stale and the task requires runtime behavior, so code-first inspection is primary.
- The comparison is purely conceptual or positioning, not implementation status.
