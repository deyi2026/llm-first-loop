# Branch Governance Phase 19A — Private Exact-Ref Archive

- Date: 2026-09-29
- Source main: `ad56767ec7f8bcfc1fb2771fbbb76efb37814fa1`
- Result: **PASS — private archive + two independent restore drills**

## Archive

- Private ignored path: `data/private-archive/branch-governance/phase19a/retained-unique-tips-20260929`
- Git bundle: `retained-unique-tips.bundle`
- Size: **16,233,761 bytes**
- Bundle SHA256: `87184de9028935251e6b5ec8013db338b6cf9e3c15f188eec602031ff279d780`
- Scope: exactly **67** retained unique-patch branch refs from Phase 18.
- Protected `main`, production, and existing Phase14 archive refs are **not advertised** in this bundle.

## Verification

- `SHA256SUMS.txt`: **5/5 PASS** for bundle + manifest + heads + verify transcript + restore report.
- `git bundle verify`: **PASS**; bundle records a complete history.
- Bundle head manifest: **67/67 exact** against Phase 18/current local refs.
- Restore drill #1: fresh isolated bare repository, **67/67 exact**, `git fsck --full --strict` PASS.
- Restore drill #2: separately created fresh isolated bare repository, **67/67 exact**, `git fsck --full --strict` PASS.
- After archive creation, all 67 live local refs still equal the manifest exactly.
- Repository topology remains **70 local branches / 2 worktrees**; root clean; production remains **gen161 PASS**.

## Mutation boundary

The archive operation changed **none of the 67 target tip refs**, no remote refs, no merge/cherry-pick/rebase, and no production publish/restart. `main` itself advanced only for two controlled reasons during this phase: first to preserve a concurrent Learning candidate Method (`ad56767ec7f8bcfc1fb2771fbbb76efb37814fa1`, after 91/91 focused tests + security PASS), then for this tracked governance evidence. The private bundle does not advertise `main`.

## Next phase

**Phase 19B is destructive and is intentionally not executed here.** If explicitly authorized, immediately revalidate all 67 branch heads against the Phase19A manifest, then retire local refs only, never remote refs, and verify final topology plus production health. Phase18 found no `MIGRATE_TO_MAIN` or `KEEP_ACTIVE` tip, so after a successful authorized retirement the expected local branch topology would be the three protected refs only.
