# Subject-Binding v3 — Natural Closeout Behavior Protocol v2 (development)

v1 is invalid for applicability inference because linked-worktree sidecar state quarantined all knowledge writes. v2 changes only execution isolation and save-experience currentness wording; task/carrier/Method content and C0-only dev case plan remain unchanged.

- Each row uses an external state root under `/tmp/lfl-sb-v3-natural-v2-e347fe3fa/`, with `data/`, `methods/`, and `experiences/` as sibling stores outside the linked worktree.
- Provider registry snapshots remain copied read-only from canonical runtime into row `data/`.
- The candidate Method card is copied into row `methods/`; usage and experience writes must stay there.
- Before provider execution, `inspect_knowledge_health` must report `status=healthy`, `writes_enabled=true`, `reasons=[]` for the external fixture.
- Prompt still requires exactly one record_use and one save_experience. The lesson solution must contain a concrete currentness action: re-read the current task and RESULT.md before future closeout.
- C0 only until opportunity gate passes. No C1 on dev before then.

Feasibility probe: first 4 frozen rows. Continue the remaining 40 only if all four are mechanically healthy and at least 3/4 produce exactly one successful record_use plus at least one successful experience artifact. Otherwise HOLD and revise under a new protocol version.

Full opportunity gate after 44 rows: >=90% exactly-one successful record_use, >=90% successful experience write, Weak negative-decision accuracy 0.35–0.80, malformed/missing decisions <=10%, all latest rows mechanically healthy.
