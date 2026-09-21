---
method_id: shape-preserving-edit-verified-through-canonical-parser-daf743642de4
name: shape-preserving-edit-verified-through-canonical-parser
description: Before programmatically editing a config field owned by a repo parser, a prior schema failure (KeyError) marks every shape assumption about that file unverified: inspect the field's native container type first; mutate in place (delete unwanted entries, never rebuild from a name-only projection, which silently turns dict into list); then verify through the canonical consumer by running the real parse/load function and asserting entry count and metadata survive. JSON write success and name echoes cannot detect shape-only corruption that loaders may drop silently with zero warnings.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cba0dcfa-4656-4850-921d-1fad481ce73d:881:1dcbd338986baa995a98
evidence_refs: learning:learn:aa8a7fef99b5
created_at: 2026-09-20T17:33:45.172071+00:00
updated_at: 2026-09-20T17:33:45.172071+00:00
---
## Trigger
About to programmatically edit a field inside a foreign structured config (JSON/YAML) whose parsing is owned by other code in the repo, especially when a structural assumption about this same artifact has already failed once (KeyError / type error on an assumed key or wrapper).

## Discriminator
A probe against this artifact already failed on an assumed schema (KeyError on a presumed wrapper key), yet the follow-up inspection only listed keys and never the target field's value type — so the field's native shape (dict-of-entries vs list-of-names) is an unverified unknown at edit time, while the edit script is about to rebuild the field from a name-only projection and write it back.

## Short path
- Treat the earlier schema-assumption failure as 'all shapes in this file unverified': before mutating, print the target field's container type and one sample entry (resolves the dict-vs-list unknown).
- Edit in place: remove only unwanted entries from the existing container, leave sibling entries untouched, and fix dependent references (e.g., default_model) in the same pass; never assign a container rebuilt from a name-only projection.
- Immediately verify through the canonical consumer: run the repo's own parse/load function on the edited file and assert the edited entity resolves with the expected entry count and per-entry metadata intact.
- Apply the same in-place edit + parser check to each sibling file (seed/template copy) instead of re-deriving or re-projecting structure.
- Only if the parser cannot run standalone, fall back to asserting the field's container type is unchanged before vs after the edit.

## Stop conditions
- Parser output shows exactly the expected surviving entries with their metadata, and all dependent references resolve to surviving entries.
- Field is confirmed schema-simple (plain scalar/name-list with a consumer documented to accept that form) — a plain read-back echo then suffices.

## Verification
- Run the actual loader/parser on the edited file and assert entry count and metadata for the edited entity — this catches silent shape corruption that a file echo cannot.
- Confirm untouched sibling entries are byte-identical pre/post edit.
- If a live service consumes the config, confirm its reloaded catalog still lists the edited entity (not zero/missing) before declaring the task done.

## Counterexamples
- Target field is a plain list of names by schema and the consumer accepts lists — dict inspection and parser round-trip are unnecessary overhead.
- File has no programmatic consumer (human-only notes/docs) — parser verification is overkill; simple read-back is enough.
- Canonical parser cannot run in isolation (requires full service boot with downtime cost) — use a container-type-unchanged assertion instead of booting the consumer.
- Edit goes through a schema-aware typed API/tool that structurally cannot change container shape — the discriminator (unverified shape + name-only projection) is absent.
