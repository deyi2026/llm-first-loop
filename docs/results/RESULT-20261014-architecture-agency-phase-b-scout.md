# LFL Architecture / Knowledge / Wait / Learning Phase-B Scout

Date: 2026-10-14; isolated candidate `fix/architecture-guard-and-agency-20261014@fdf280c6f` (initial); newer main observed `d3ad5eaa9` and left unchanged.

## Reproduced issue and correction

The current SOT `docs/ai_rules.md` contains RULE-AI-31, while the rule-presence ledger at `.codeartsdoer/specs/rule_presence/rule-presence-ledger.md` lacked that rule. The rule-presence test failed with `missing=['RULE-AI-31']` (59 other scoped tests passed). The tracked ledger has been amended using SOT exact text as authority; this does NOT claim rule injection into provider-visible messages. The containing `.codeartsdoer` directory matches an ignore rule, but `git ls-files` proves this particular ledger is already tracked and the correction is included in commit `8ffa396f8`. No new force-add, prompt expansion or baseline exemption was necessary.

## Offline test receipts

- Knowledge/method/rule, wait main lifecycle, architecture guard: `89 passed` after local ledger fix.
- Learning channel, queue, idle, journal, admission, scheduled wake and wake projections: `91 passed`.
- Phase-A staged candidate providers/factory/usage/architecture suite: `157 passed`, Ruff clean; commit `fdf280c6f`.
- These are scoped offline tests; there has been NO real provider-view trace comparison, production Learning queue inspection, weak-model A/B, formal whole-suite R9 or production restart in this iteration.

## Remaining priority and qualification gaps

1. P1 verify RULE-AI-31 task-trigger path against a real provider-visible request and actual exact Rule/Method/Experience hydration; distinguish source presence, tool discoverability, and true model receipt. Preserve model semantic discretion. User's priority is not to remove important default knowledge for token savings.
2. P1 inspect current production Learning queue/leases/ages and real wait wake receipts before claiming a stall fixed. Scope of the passing 91 tests does not prove live service healthy.
3. P1 compare strongest and weakest supported model task FCR/retries/full costs using frozen comparable test cases. Neither more prompts nor fewer calls alone count as efficacy proof.
4. Execute independent review as required by RULE-AI-28 before full R9; then final candidate R9, security and exact code SHA gates; only thereafter consider managed release and safe-idle.

No active worktree removed, no main changes, no provider calls and no deployments. The ledger edit is versioned in the isolated branch and must not be mistaken for production provider-view coverage.
