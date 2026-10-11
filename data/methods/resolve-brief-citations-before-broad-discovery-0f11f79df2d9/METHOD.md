---
method_id: resolve-brief-citations-before-broad-discovery-0f11f79df2d9
name: resolve-brief-citations-before-broad-discovery
description: When the authoritative task input (approved proposal/issue/receipt/record hit) already cites concrete artifacts by filename, file:line or symbol, treat those citations as provenance edges: resolve each with one bounded scoped lookup (find limited to source roots, or ls of the implied package dir) and read directly at the cited anchor. Do not launch full-tree find/scan or wildcard searches over huge workspaces — that is where the 60s timeouts and no-match calls came from. Widen discovery only after citations fail to resolve, and even then keep bounds (subdir/maxdepth).
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6011132d-5da7-46ed-9be9-40d1379ec22d:588:6fac2c8674c14dd7be62
evidence_refs: learning:learn:6db69880f09e
created_at: 2026-10-11T12:46:03.007934+08:00
updated_at: 2026-10-11T12:46:03.007934+08:00
---
## Trigger
Starting implementation of a task whose input text explicitly cites artifacts (filename[:line], symbol, or exact path) while the workspace is large enough that unbounded scans are slow or time out.

## Discriminator
Before any filesystem discovery, the task input/record hits already contained exact code anchors (tools_task.py method_use_gate; registry_experience.py:227 _experience_use_declaration; knowledge_runtime.py:139; data/methods/usage.jsonl). Each anchor narrows 'where to look' from the whole repo to one bounded path resolution plus a ranged read.

## Short path
- Fetch the full authoritative records/proposal text first (status verification stays; the receipts demand it).
- Extract every explicit citation from the input text: file names, line numbers, symbols, data paths.
- Resolve each citation with one bounded lookup scoped to source roots (e.g. find src -name '<file>') or direct ls of the implied package dir — never full-repo or full-data scans.
- Read each resolved artifact at/near the cited anchor; confirm location by finding the cited symbol in-file (tolerate line drift).
- Begin implementation only once all cited artifacts are read; discovery ends there.

## Stop conditions
- All citations resolved and read; each cited symbol found at or near its anchor in the current file version.
- A citation fails 1-2 bounded resolution attempts — only then escalate, and escalate with bounds (named subdirs, maxdepth), not a bare full-tree scan.

## Verification
- Every artifact named in the brief appears as an explicit read in the trace, and the cited symbol (not just the line number) is located in-file.
- Trace contains no unbounded discovery command (full-repo find, whole-data scan, content-less wildcard search) executed after citations were in hand; no 60s discovery timeouts.
- Proposal acceptance points map onto the read code before edits start.

## Counterexamples
- Task input cites no concrete artifacts ('investigate why the gate misbehaves') — broad discovery is then the correct first move, this method does not apply.
- Cited file genuinely absent under scoped roots (renamed, generated, or on another path) — after bounded scoped attempts fail, wider search is warranted; do not keep probing guessed paths.
- Line anchors may be stale because the file changed since the brief was written — trust the symbol and read around the anchor; never patch at the literal cited line.
- Small or fast workspace where a full listing costs milliseconds — bounded-discovery discipline is needless overhead there.
