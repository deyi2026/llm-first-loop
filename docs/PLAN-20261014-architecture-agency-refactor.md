# LFL 2026-10-14 架构优化与模型能力保障计划

Status: isolated candidate; not production authorization. Baseline `main@2fca1cba3`. Do not infer live deployment from local Git.

## North star

用户与模型决定语义、策略和完成判断；runtime 承担确定性协议、资源、恢复、审计。核心 Rule/Experience/Method/Skill 是能力来源，不能为追求较小 prompt 或更少工具调用而失联、静默截断或被程序语义取代。小而经验证的身份/工具原则可常驻；长卡片需 compact discovery → stable exact ref → authorized full hydration；必要的适用内容必须可供模型取得。成功以弱模型任务成功率、FCR、重试、whole-run tokens/latency、provider settlement 及可恢复性评价，不以文件行数或工具调用次数单独评分。

## Evidence snapshot

- 442 Python files / 7,181,509 bytes under `src/llm_loop` (file inventory 2026-10-14), top hotspots: `web/routes.py`, `runtime/service_control.py`, `core/loop/engine.py`, `llm/client.py`, `factory.py`, `browser/perception.py`, `subagent/runner.py`, `tools/registry.py`.
- Main working tree was dirty (reports plus knowledge artifacts); numerous active worktrees exist. No direct main edits, worktree deletion, release, or restart permitted by this audit.
- Main architecture guard: 25 pass / 4 fail, including `providers<->web_provider_registration` runtime cycle, factory local imports cap, stale 5-marker expectation, and undeclared root `usage_net.py`. This is a current source-state result, not a production-runtime failure finding.
- Existing architecture contract `docs/ARCHITECTURE-20261007-kernel-v1-contract.md` listed 22 backwards root edges on its historical baseline; remeasure on the final candidate rather than asserting that same number today.
- Older `docs/ASSESS-20261008-project-audit.md` contains partially repaired BUG-07/13b and unproved concurrency hypotheses; each must be rechecked on current HEAD before any repair claim. `docs/known-reds-20260909.md` distinguishes historical reds from current gate outcomes.

## Delivery phases and exit gates

| Phase | Priority | Responsibility and smallest safe slice | Exit gate |
|---|---|---|---|
| A | P0 | Restore true architectural gate correctness; break provider plugin registration cycle; centralize shared usage projection in knowledge domain; preserve compatibility on existing call paths | staged-candidate architecture guard green, provider/web registration and Method/Experience usage regression green, no new exceptions to ratchets |
| B | P1 | Audit exact provider-visible Rule/Experience/Method/Skill availability: stable identity kernel, retrieval recall, candidate exposure, exact hydration, lifecycle and `record_use` provenance. Fix gaps only with reproduced failures | representative strong and weakest supported model runs; necessary defaults visible; relevant knowledge accessible, no lost facts, no coercive semantic decisions; usage claims are not efficacy claims |
| C | P1 | Decompose `engine.py`/`factory.py` into narrow assembly, run-lifecycle, tool-dispatch and immutable DTO/Protocol ports. Keep kernel imports inward only | AST import-ratchet strictly shrinking; identical tool-wire/history/events and no extra provider calls |
| D | P1 | Separate session/history/episode storage authorities, recoverable durable source refs and exact paging; revalidate repeat-wait/wake and active-run identity with real lifecycle receipts | no duplicate execution, stale wake, lost response, silent truncation or abandoned jobs on retry/reconnect/restart |
| E | P1 | Separate SubAgent runner lifecycle/budget/transport/settlement and Learning queues/retries/qualification; ensure Model initiative remains free within actual authorization | agent/reviewer isolation, real task closure, fair retry/dead-letter, child physical usage facts, no fabricated success |
| F | P2 | Split Web routes/service_control into API adapters and managed deployment orchestration; decompose tools/registry/browser perception and unify recoverable faults | UX/browser responsiveness, real scrolling, Web/Feishu/Learning tests and deployment safe-idle/currentness gates |
| G | Release gate | Tier0 → focused → R9 final candidate → full suite → security → stage Web-only if appropriate → run and idle verification → controlled other planes | release SHA/desired/live and exact receipts agree; no collateral active-run interruption |

## No-regression invariants

1. Full content retained before projection; same exact source is discoverable and authorized to hydrate with monotone paging. No silent semantic truncation.
2. A few proven durable LFL identity/agency principles may be default-loaded. Method/Experience suitability remains model judged; deterministic runtime handles plumbing. No indiscriminate all-card prompt stuffing.
3. Tool capability stays enabled unless genuine security/authorization constraints require restrictions; do not confuse workspace root bugs with dangerous-tool grants.
4. Method `record_use` is a declaration, qualification is independent evidence, and automatic promotion/retirement requires separately validated conditions.
5. Managed deployment respects active sessions; source, release and live provenance separated; no unsafe restart to force a pass.
6. A reported bug must have a reproducible input, failing assertion and a regression, or be explicitly labeled a hypothesis / historical item. Do not enlarge guard baselines to silence errors.

## Initial candidate scope

Phase A was implemented in an isolated worktree. The plugin module no longer imports `ProviderSpec` back from providers at function runtime; the owning registry validates external provider specs before adopting them. Web factory imports now live at the module assembly boundary. The old 5 exemption markers expectation is updated to the 3 real markers remaining after previous web-carveout; shared `usage_net` implementation now resides under `knowledge/` with all known callers and its unit test updated. No provider calls, main merge, deployments or service restarts were authorized by this slice. Formal production approval is not implied.

## Follow-up investigation queue

Remeasure main reverse kernel imports; inspect provider registration error-isolation for mixed invalid/valid specs, and `sys.path` lifetime; check wait wake identity, missing scheduled receipts, reconnect duplication and active-run handoff; check Learning queue age, stuck leases and retries; run knowledge injection real provider-view evidence matrix; recheck prior BUG-07 / BUG-13b reproduction against current code; inventory large functions by cognitive coupling rather than arbitrary length alone. Each item needs current SHA, reproducer and chosen owner before implementation.

## 2026-10-14 third-stage progress

Focused 374 tests, Ruff and the historical-debt Pyright guard passed in isolated worktree. Two actual source defects were fixed with regressions: repeated Learning retry of durably deleted sessions and RULE-AI-31 exact hydration absorbing unrelated following headings. The existing search_records tool contract now exposes RULE-AI-31 task-level discovery criteria in full and compact wire descriptions (compact 430→394 chars; no global prompt expansion). Captured the complete test engine's first provider-bound packet without a paid provider call. Real provider behavior and Method efficacy remain unproven; RULE-AI-28 independent reviewer PASS and whole R9 remain prerequisites, not waived. Details and exact evidence: `docs/results/RESULT-20261014-architecture-agency-knowledge-learning-repair.md`.
