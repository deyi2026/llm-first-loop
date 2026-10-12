---
method_id: snapshot-first-diagnostic-4ed119eb92b4
name: snapshot-first-diagnostic
description: When the user requests a health/status/diagnostic check and a dedicated status/architecture/runtime tool exists, treat its comprehensive snapshot as the primary signal for the scope it covers. Only call additional tools for aspects the snapshot does not address, and skip broad keyword searches that overlap with snapshot data.
status: candidate
source_model: minimax/MiniMax-M3
source_episode_refs: episode:3b65f693-b562-4773-a72f-76d98cd53dab:0:96ffe8231c96c9be0a56
evidence_refs: learning:learn:bdbe0e1b58a6
created_at: 2026-09-17T15:38:10.023191+00:00
updated_at: 2026-09-17T15:38:10.023191+00:00
---
## Trigger
User requests a system health / diagnostic / status check, and the runtime exposes a dedicated status/architecture/runtime_snapshot tool whose output already covers most requested dimensions.

## Discriminator
The dedicated status tool's snapshot returns an explicit healthy/normal state for the requested dimensions (e.g., model_fact_integrity.healthy=true, current_phase non-error, no exception indicators), so broad searches like 'error exception fault' or 'process versions runtime' will not add information already present.

## Short path
- Call the dedicated status/architecture tool to obtain the comprehensive snapshot
- Read the snapshot and partition its fields into 'covered by snapshot' vs 'gaps not covered'
- If snapshot shows healthy=true and no error indicators, skip broad keyword searches that re-probe the same dimensions
- Run only targeted supplementary tools for the gaps (e.g., host shell for OS/load, fs ls for paths the snapshot names like runtime_root)
- Compose the report by citing snapshot fields directly and supplementing only for non-covered items

## Stop conditions
- Snapshot fields covering the requested scope are collected and reportable
- No supplementary tool call returns information that contradicts or adds to a covered dimension
- Gaps are explicitly marked rather than re-probed via broad search

## Verification
- Every reported line is traceable to either the snapshot or an explicit gap-filling tool call
- Path/file references match fields the snapshot already names (e.g., runtime_root), not guessed subpaths
- Conclusion states 'healthy' only when snapshot's healthy flag and absence of exception indicators are both true

## Counterexamples
- User asks for a specific subsystem not covered by the snapshot (e.g., 'check Feishu connectivity') — must do targeted connectivity probes, not just rely on the snapshot
- Snapshot returns unhealthy / inconsistent / error state — broad investigation is then warranted because the snapshot itself flags a problem
- User asks for trends, history, or diffs over time — snapshot is a single point; historical queries are required, not redundant broad search
- No dedicated status tool exists for the requested domain — then targeted probes or broad discovery are the only option
