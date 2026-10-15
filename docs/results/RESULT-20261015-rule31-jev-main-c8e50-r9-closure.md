# Rule31 + JEV — frozen main c8e50 full-R9 isolation closure

Date: 2026-10-15. Goal: 9956a550-f1ad-4281-aeb4-a4e797fe85ca.

**Status:** ISOLATED_CODE_QUALIFIED; INDEPENDENT_REVIEW_PASS; CANONICAL_R9_EXIT_0; XDIST_ALL_GREEN. **Not merged into main, not pushed, not deployed, not restarted.**

## Exact Git chain

- Frozen main baseline: `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`, captured when the target main was tracked-clean. No production or global configuration mutation.
- Independent JEV worktree/branch: `fix/jev-wire-pyright-narrowing-20261015`; local source commit `c0f577d181bb677109b7ced2b3474a5b1e87eedf` (parent `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`), 2 files, **3,675 bytes**, patch SHA `b31c73f5d8da7d5d001253c10414e59801b1a60b1eeb858bfeb1924a913ed331`.
- Combined Rule31+JEV worktree/branch: `fix/rule31-jev-main-c8e50-20261015`; local Rule31 commit `13b4b87f237ef8ace66c60f92931eb3fcb0a2bf4` (parent = exactly JEV `c0f577d181bb677109b7ced2b3474a5b1e87eedf`), 8 files, **24,049 bytes**, patch SHA `705c094eb0c4b3d6bc82a69bacc0190e0d126d30df8eb9094cc10ddedd681e4f`.
- From `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac` to `13b4b87f237ef8ace66c60f92931eb3fcb0a2bf4`, tested combined 10-file source patch was exactly **27,724 bytes**, SHA `fac61923ced5c770a162bbf75b826f709ee18abb3cfcadc70abf227b689e0cb0`, matching the original independently reviewed and full-tested staged bytes. Split commits **did not change the final file tree**.
- Prior Rule31 worktrees, Rule28 worktrees and other Agent files/branches were left intact. No main merge/cherry-pick, no push and no Web/Feishu/Learning restart.

## Why an isolated JEV preflight was necessary

The prior untouched main c8e50 had **5 new Pyright ratchet errors** solely in `src/llm_loop/knowledge/jev/wire.py` (Unknown|None passed to float or .items). A separate clean-main detached comparison reproduced the same 5. The new JEV patch adds only explicit type narrowing in the existing valid choice/score branches plus 11 parametrized invalid-input regression cases. Actual original Pyright ratchet went from **new=5** to **new=0**, while preserving the validation/reason contracts; Ruff and EnvPin 858 also passed.

JEV original reviewer after a test-assertion refinement: child `subagent_02e85983e7a7` real terminal `de6bfad4-3ce6-4fe3-aec3-3262c1019344`, **PASS P0=0 P1=0 P2=0**, bound to `b31c73f5d8da7d5d001253c10414e59801b1a60b1eeb858bfeb1924a913ed331`. Raw reviewer JSON SHA `a21a403031d3b44361e95db8017a584843f0ce3824d12b30a383cc5ab77a2edc`. The first Reviewer also passed but flagged a weak test prefix matcher; the final test now asserts **exact reason codes**, was re-reviewed, and does not reuse the initial review SHA.

## Preserve the standalone failed CI — do not misreport it

The **standalone JEV branch** ran the original unmodified full `scripts/ci_gate.sh` and genuinely **exited 1**: xdist **8,850 passed, 146 skipped, 2 failed**, then serial **40 passed, 2 failed**. The two failures were entirely outside the two-file JEV patch:
- `tests/unit/test_backup_store_durability.py::test_orphan_tmp_and_lock_invisible_to_scan_surfaces` — fixed backup fixture date 2026-10-08 had crossed real seven-day retention boundary.
- `tests/unit/test_browser_attestation_v01.py::test_attest_dead_port_fail_closed_real` — test falsely presumed hardcoded port 39099 had no listener; a real external process owned the port.

Both are already covered in the previously independently reviewed **Rule31 eight-file patch**, without touching production retention logic or browser attestation verdict requirements. Therefore **JEV standalone full R9 was not green**; integration qualification required the combined ten-file candidate and its own independent review/full R9. JEV standalone original ignored log SHA-256 `8881d08af696741d3f727909f06c37f28b5a4d8634e0828132100b1e1f58527c`, located only at `fix/jev-wire-pyright-narrowing-20261015` under `data/jev-wire-pyright-narrowing-20261015/full-r9.log`. Exactly eighteen test-generated tracked report changes from that run were restored after its real terminal, not during it.

Historical independent latest-main Pyright NO_GO receipt was preserved byte-for-byte: `docs/results/RESULT-20261015-rule31-main-c8e50-admission-no-go.md` SHA `ae3a30dfaefcb26d5d5af40e911d72a6297ef96f7da825b76e794626e57ff24b`.

## Verified combined ten-file candidate

- Combined JEV/Rule31/backup/browser/UsageNet focused: **214 passed**.
- Original `bash scripts/ci_gate.sh --quick` against full ten-file stage: **exit 0**, Ruff PASS, EnvPin **858** PASS, Pyright PASS **new=0**, WebUI build PASS, Tier0 **319 passed / 8,698 deselected**.
- Native independent GLM-5.3 Reviewer `subagent_9f7178c45dd2`, one EventStore terminal `8feea6cb-8eb8-4e61-9026-3a4d08c30d50`, live parent result, exact full source SHA `fac61923ced5c770a162bbf75b826f709ee18abb3cfcadc70abf227b689e0cb0`: **PASS P0=0 P1=0 P2=4**. All four P2 findings are preserved as the Reviewer stated them. The "full-R9-not-yet-run" evidence gap (P2 #1) was subsequently closed by the physical PASS recorded below; the ledger-count/RuleIndex-H2/browser-import suggestions remain advisory and are not falsely marked fixed. Full independent text lives in `docs/governance/receipts/RECEIPT-20261015-rule31-jev-combined-glm53-independent-review.md`. Raw JSON SHA `2ed4c19f4b618c105915144023bb50a531b7de75ac70a42c2429883e0ed99198`.

### Actual original canonical full R9 after independent Reviewer PASS

| Gate | Original physical result |
| --- | --- |
| Ruff | PASS: changed-file new0 |
| Test environment declaration | PASS: 858 scanned |
| Pyright | PASS: current/new diagnostic ratchet, **new 0** |
| WebUI candidate build | PASS |
| Tier0 | **319 passed, 8,698 deselected, 3 warnings** |
| Four-worker xdist full suite | **8,855 passed, 146 skipped, 0 failed, 13 warnings**, 190.90 sec |
| Built-in serial recovery | **Not used**, xdist itself had no failure |
| Final guard-report selection | **1 passed, 29 deselected** |
| Native full `ci_gate.sh` process | **exit 0**, `ci_gate 全链路通过` |

No test was skipped beyond existing 146, no baseline/ratchet/test assertion/CI script was changed to obtain this result. Exact ignored log in the combined isolated worktree: `data/rule31-jev-main-c8e50-20261015/full-r9.log`, SHA `56c16179835c9c81bd2c9f931e1cffb792a95ea538dd35fd0bb2b81657228c79`. Post-review original full R9 exit0 was physically observed; 4-worker xdist has no failure. The integration commit ancestry preserves exact prior reviewed Git patch SHA.

## Isolation, cleanup and network limits

- Full R9 waited for another Agent's Rule28 canonical CI to exit; none of those processes were stopped or modified. A launch attempt during their execution had been **rejected before starting any test**.
- Each physical full run created exactly 18 tracked report updates (12 phase3, 1 phase4, 2 phase5, 3 phase6), and only after its process ended these were checked against an explicit whitelist and individually restored. No user's main checkout, Rule28 or older Rule31 worktree artifacts were overwritten.
- CI had no Provider API-key environment variables, the isolated tree had no `.env`. Ignored temporary Python-only outbound-socket guard `sitecustomize.py` SHA `a66fd43421b2f3232bbd5b7960339ea3e988c6c47aa8a442283a9ae110866961`: spawned-Python/httpx external connect denied; localhost/Unix permitted. **Not an OS-level outbound firewall and does not prove native non-Python egress cannot happen.** Multiple intentional authorized independent GLM-5.3 reviewer attempts did use the configured Coding-plan Provider (initial JEV review, refined JEV review, then combined review); none changed provider/budget/security config.
- Two functional source commits have been made solely in isolation. The separate documentation commit and postcommit Quick R9 are verified after this source-level closure; neither is a substitute for the physical full R9 above.

## Release boundary and follow-up

This is **isolated qualification only** against `main@c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`. Any later drift in main requires fresh overlap/security checks, an exact post-integration candidate Review, canonical full R9, and separate owner approval before any main merge, push, release or restart. Preserve the raw R9 and independent-review receipts for forensics. Do not treat this isolation as production activation.
