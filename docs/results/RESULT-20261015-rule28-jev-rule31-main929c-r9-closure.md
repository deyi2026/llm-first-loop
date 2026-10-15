# Rule28 + JEV + Rule31 on main 929c — isolated full R9 closure

Date: 2026-10-15. Goal: `312ddf41-6e44-4346-8676-c700baba77b6`.

**Decision: ISOLATED_CODE_PASS + REVIEWER_PASS + CANONICAL_FULL_R9_EXIT_0, XDIST_ALL_GREEN.**
**Not merged into main, not pushed, not published, not restarted.**

## Authority and conflict resolution

- Actual main baseline `929c8d83698fb12f5b2751ee38d52c7ec2045f23` already contained Rule28 Host `review_admission` (including `ToolRegistry.execute` preflight), the dedicated JEV `wire.py` validated blob `32a1d4c41d4c26acddce07b21fcbbb0e54ad4d92`, the true Rule28 SoT, backup frozen-clock fixture, dynamic OS-reserved-port browser negative test, and WebUI source-binding patch. These were **preserved, not cherry-picked over**.
- Older JEV+Rule31 10-file isolated qualification was against a **different** main (c8e50). Its old tests/Reviewer/fullR9 do not qualify the current main and were not recycled.
- On one **new** clean isolated worktree `fix/rule28-jev-rule31-929c-20261015`, imported exactly six Rule31-specific paths (ledger, registry introspection, RuleIndex H2 parser, `search_records` Full/Compact description, 2 regression files); did **not** replay the old 2 JEV files or the 2 superseded backup/browser fixtures.
- Source commit `692ea63a53e124454adae66fe9401a70775576fd`, parent exactly `929c8d83698fb12f5b2751ee38d52c7ec2045f23`, six-file patch **21,698 bytes**, SHA-256 `c07138d43a0fc81c3519f10b54f3a2b2a33558f31e13be0b6962b18cdf149220`. No main or existing Rule28/JEV/Rule31/WebUI Agent worktrees were changed.
- Freeze proof: three newly transferred tests first actually **FAILED** against current main (Rule31 bounded first-tool packet and two RuleIndex sibling-H2 hydration tests). After minimal source delta, same tests passed. Original RED log SHA `30a3ebba899da1fb9703b2e4ae97a80b4e48b57a8904aee4f770d84ac1c53724`.
- Latest `git_security_scan.sh --staged` **6 PASS** and staged Git diff whitespace check clean.

## Joint focused / reviewer and current execution boundaries

- Rule28 Host admission/Wiring/Runner, review obligations, review-gate negative cases, Rule31 registry/full-compact/H2/ledger, JEV validation, backup retention, browser attestation and UsageNet: **331 passed** (16 exact test files). Source log `data/rule28-jev-rule31-929c-20261015/focused-pathfixed.log` SHA `0c622cf2b95fb9f36bbaf30e607f171037b77acf84487140ab56fd0b0b8d46c7`.
- An **initial** focused run was **330 passed / 1 failed** because a child `pytest --version` from `ExecuteCommandTool` resolved `/opt/homebrew/bin/pytest` rather than the project venv and that tool lacked its own pytest dependency. The venv PATH was corrected **only in the isolated test invocation**, without editing tests, assertions or CI scripts; the exact same restricted Python socket guard then gave **331 passed**. Do not describe the initial red as a Rule28 false-block.
- Native `bash scripts/ci_gate.sh --quick` ran to true **exit 0**: Ruff PASS, EnvPin **863 scanned**, Pyright PASS (no new/touched diagnostics), candidate WebUI source-bound build PASS, Tier0 **319 passed / 8,817 deselected / 3 warnings**. This was development preflight, **not** the commit gate. Ignored Quick log SHA `2897b46bd7482cda7e7cb19b1e9fa42f4a716b28f1a1d54c8b70e912a5e8175c`.
- Real independent GLM-5.3 child `subagent_1d5656615c27` completed `completed` with unique EventStore terminal `51e8fb77-c1da-4983-9d47-94d7d0d98c87`, **PASS P0=0/P1=0/P2=3** for exact six-file Git patch SHA. Separate receipt: `docs/governance/receipts/RECEIPT-20261015-rule28-jev-rule31-main929c-glm53-review.md`.

## Original canonical full R9 on the reviewed staged code

| Native stage | Exact physical result |
| --- | --- |
| Ruff | **PASS** |
| Test environment declaration | **PASS**, 863 test files |
| Pyright | **PASS**, no new/touched diagnostics |
| WebUI candidate build | **PASS**; source binding manifest generated |
| Tier0 | **319 passed, 8,817 deselected, 3 warnings** |
| Four-worker xdist full selection | **8,974 passed, 146 skipped, 0 failed, 13 warnings** in 176.23s |
| Serial fallback | **Not used**; xdist itself green |
| Guard-report | **1 passed, 29 deselected** |
| Native `ci_gate.sh` process | **exit 0**, `ci_gate 全链路通过` |

Original ignored full output: `data/rule28-jev-rule31-929c-20261015/full-r9.log` SHA-256 `fbe1f30cf98c2817b203d0e2179f263179e6fbfcfe310500b8ae41fbedd9be0d`. The full run was launched only after the exact Reviewer PASS, with no parallel full CI. The original CI/test/ratchet/safety guard was **not modified**, skipped, replaced or made easier to satisfy.

## WebUI provenance and runtime release separation

- On the isolated candidate, the actual `verify_webui_source_binding(code_root, dist_root)` validator **PASS**. Candidate tracked WebUI source SHA `578c17b2e6349c5c5753798ebd17b1f5e01ac29be4e5500f3812414fcce299cd`, 104 files. The `webui/dist/.lfl-webui-source.json` was present, and generated CSS contained `v2-services-grid` and `v2-services-view` selectors. These are isolated build facts, not live production smoke.
- Temporary **ignored** Python-only socket guard SHA `a66fd43421b2f3232bbd5b7960339ea3e988c6c47aa8a442283a9ae110866961`; spawned multiprocessing Python/httpx outbound canary denied remote egress while allowing local loopback and AF_UNIX. **Not OS-level egress isolation:** native non-Python children were not proven unable to contact network. Full CI Provider-key environment variables were unset and this worktree has no `.env`; only the separately approved GLM-5.3 code-review model request used Provider access.
- Exactly 18 phase3–6 tracked report mutations from full CI were matched to an explicit list after the process terminated and only those were restored, leaving the frozen source patch unchanged. No test report restoration occurred while CI ran.

## Additional required gates BEFORE any future activation

1. Frozen main/branch drift, concurrent process, SessionStore in-flight tasks, release generation/PID and exact current source SHA must be rechecked. This isolated code qualification is **not** a grant to merge or push.
2. A future **main integration** requires a separate explicit owner authorization and a scoped final SHA/code review if that integration tree differs. Git push needs its separate Rule28 **Push Reviewer** plus exact remote/ref/user authorization; the repository has `lfl` main remote and legacy `origin`.
3. Future publish/restart requires an **independent Web-only** authorization, current `service_control` release identity, reproducible WebUI source/build manifest check, safe Web active-session drain and rollback plan. Web-only canary must verify real Rule28 Host preblocks / qualified single allow, Rule31 first tool packet/exact rule hydration/record-use, WebUI service+Learning scroll and normal-tool no-overblock. Feishu/Learning are out of scope.
4. Rule28 Host can only guarantee the actually instrumented `execute_command`/review_admission and explicit article Publish surfaces; do **not** claim global DSH/nested shell or all external publishing channels are physically blocked. Review P2 findings remain open.

This report documents **isolation acceptance**, not production activation. The separate postcommit `ci_gate.sh --quick` terminal outcome is captured in the persistent Goal checkpoint and final delivery summary; it supplements the original full gate and cannot replace it.
