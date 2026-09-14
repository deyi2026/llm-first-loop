# Gate E Official Canary / Promotion Qualification — 2026-09-15

## Verdict

**Gate E: PASS for the currently deployed combined candidate `b9b312c16ddf2af55fbf981f92f5b3cb71d7f001`.**

This report is a post-qualification, docs-only evidence record. It does **not** rewrite the earlier
P7 report or pretend that Gate E had already been run when that report was frozen.

The evidence chain is deliberately split:

- `docs/QUALIFICATION-20260914-context-integrity-p7.md` remains the historical Gate A–D report and
  correctly says Gate E was **NOT RUN** at that time;
- this file records the later authorized official restart/canary/promotion work;
- the runtime-qualified source SHA remains the exact code that was tested and deployed. This
  documentation commit is not itself a runtime qualification target.

No main-branch merge, release tag, or GitHub Release is claimed by this report.

## 1. Qualified lineage and current promotion target

The Context Integrity implementation was first promoted through Gate E on branch
`fix/active-run-ingress-1214-20260914`. The final successful Context Integrity canary source was:

`a655217ace0ab5f5e0227da46b46859a6d1e0d0c`

Two cache-capacity commits were then rebased directly on top of that exact qualified source:

| Commit | Parent | Scope |
|---|---|---|
| `8d42de539a949781444c66d309e333b265aaac6f` | `a655217a` | deterministic cache-attribution scorer |
| `b9b312c16ddf2af55fbf981f92f5b3cb71d7f001` | `8d42de53` | token-native history budget |

Therefore the currently deployed combined candidate contains the qualified Context Integrity
runtime unchanged in ancestry, plus the separately qualified cache-attribution and token-capacity
changes.

Current official promotion branch:

`integration/cache-token-native-promotion-20260915@b9b312c16ddf2af55fbf981f92f5b3cb71d7f001`

## 2. Gate E attempt 1 — correctly failed after restart

The first authorized controlled canary used the then-qualified source
`7a23fae58c0707d1198603a2b7d157e4460b9566` and the new dual-root restart contract:

- runtime root stayed the canonical mirror root so durable state/config remained in one place;
- code root came from a clean linked worktree;
- Web and Feishu were restarted together;
- the existing 8901 Ornith process was outside the restart scope and was not replaced or doubled.

The official `all` restart itself returned `rc=0`, and Web/Feishu came back. Gate E nevertheless
**failed**, because the post-restart manifest exposed a real configuration-authority regression:

- expected config hash before the restart:
  `b572a531c60849338f5a6fe33b9cbc4a4e1a990db96e87e7065d9e89664d8bdb`;
- observed hash after the first dual-root restart:
  `7b36981eaa57675a4fc9b337733099fdbabbd537a8839807d0cd8448fa15a14b`;
- `LLM_MODEL`, provider identity, provider endpoint, input/output window facts, model context and
  history budget disappeared from the effective manifest instead of remaining dotenv-owned.

### Root cause

`LFL_WORKSPACE_ROOT` had been intentionally repointed at the clean **code** worktree. The runtime
resolver still used that same value as the default location of `.env`. Because the clean code
worktree intentionally had no `.env`, values previously loaded from the canonical runtime root
were classified as stale shell values and ignored.

This was a mechanical source-of-truth bug, not a model/provider problem and not a prompt issue.
The canary was therefore rejected even though service processes were alive.

## 3. Rollback qualification corrected a historical false assumption

The originally planned exact rollback target was
`2d247ba793d939df7f4ceedf4d01100f72914e53`.

The official preflight correctly refused to stop the running services because an exact checkout of
that commit did not contain `llm_loop.runtime.knowledge_health`. This proved that an older observed
"2d restart success" had depended on later dirty-root files and was not an exact reproducible
rollback.

A clean, independently restartable stable fallback was then qualified instead:

`2139faa87148159ca52c8811fbe9a8c03bfc988e`

The stable worktree had the complete official restart contract, healthy Knowledge binding and the
expected GLM operational configuration. After explicit owner authorization, Web and Feishu were
returned to this exact stable source before the resolver fix was implemented.

This incident changed the rollback rule: a rollback SHA must be proven restartable from an exact
clean tree; historical process labels are not sufficient evidence.

## 4. Resolver TDD fix and Context Integrity Gate E retry

The dual-root failure was reproduced with a deterministic red test. The minimal production fix was
committed as:

`a655217ace0ab5f5e0227da46b46859a6d1e0d0c` — `fix(runtime): bind config to runtime root`

The corrected authority split is:

- `LFL_RUNTIME_ROOT` owns the normal runtime `.env` / operational configuration root;
- `LFL_WORKSPACE_ROOT` owns source/build identity;
- an explicit `workspace_root=` argument remains an explicit override for resolver callers.

A clean candidate worktree with **no local `.env`** then reproduced the real launch order and
restored the exact expected config hash:

`b572a531c60849338f5a6fe33b9cbc4a4e1a990db96e87e7065d9e89664d8bdb`

The same preflight restored:

- model: `glm/glm-5.3`;
- provider: `glm` / `open.bigmodel.cn`;
- maximum input tokens: `184000`;
- maximum output tokens: `16000`;
- model context fact: `1000000`;
- configured history char cap: `1000000`;
- data/config roots: canonical runtime root;
- Knowledge health: healthy, writes enabled.

### a655 requalification before retry

Before the second controlled canary, exact `a655217a` passed:

- whole-tree security scan;
- repository Ruff;
- env-pin audit;
- Pyright `0 errors / 0 warnings / 0 informations`;
- tier0 and full pytest xdist gate;
- exact dual-root config/identity preflight;
- P7 adversarial concurrency stress: `20/20`;
- real GLM-5.3 delegated-ingress / compaction qualification: `3/3` first-request successes;
- real existing 8901 Ornith Context Integrity non-regression: `4/4`.

Privacy-safe live-result hashes from that requalification:

- GLM 3-trial result:
  `db79ae50b429192eddb57192c5d0cd4a4a1e18b1e2841da5241a3284bc9c09a7`;
- Ornith non-regression result:
  `0926971c8b50142536b83f257ba461dd51feacbc57662dd275e39e031370b076`.

The second official `all` canary then passed. Receipt, runtime manifest and process-version records
all resolved to exact `a655217a`; the config hash remained `b572a531...8bdb`; Web and Feishu were
healthy; Knowledge remained healthy; Feishu was connected and idle; the original single 8901
Ornith listener remained unchanged.

A post-restart real GLM smoke also passed on the first physical request. Privacy-safe result hash:

`9cd77429016b2c81cfda14835547e6565c150b31874f39ffc3d2c7cf994fbae9`

Current-PID startup log slices contained no new hard error. Gate E for the Context Integrity line
was therefore closed only after the failed first attempt, rollback, TDD fix, complete
requalification and successful retry.

## 5. Combined cache promotion to b9b312c1

After Context Integrity Gate E closed, the cache work was promoted as two narrow commits on top of
exact `a655217a`.

### 5.1 Deterministic attribution scorer

`8d42de53` adds frozen-snapshot scoring and the cache-attribution schema/fixtures. The scorer keeps
mechanical classifications separate from semantic task judgment and distinguishes controllable
miss from provider-side/uncontrollable effects.

### 5.2 Token-native history budget

`b9b312c1` keeps provider input capacity token-native instead of converting the 184K input-token
authority immediately into a fixed `0.6 chars/token` cap. The existing char history projector is
retained as a bridge; provider overflow remains the final hard capacity authority.

The committed deterministic P1 document records, among other gates:

- 184,000 allowed input tokens remain invariant under density calibration;
- tool-schema reserve is converted to tokens exactly once;
- the first eight observations retain the conservative cold-start density;
- the frozen 220-request replay preserves the cache-attribution golden byte-for-byte;
- full repository CI passed on the P1 implementation line;
- no live cache-rate gain was claimed by deterministic qualification alone.

### 5.3 Live post-promotion observation

The later real GLM canary exercised a 12-request / 11-tool-read chain and completed with the
expected terminal marker. Privacy-safe aggregate observations were:

- maximum provider-visible history: `92,101` chars;
- this crossed both the former ~72.7K compaction trigger and the former ~85.5K effective history
  budget without changing the 184K token authority;
- after density warm-up, the projected char bridge expanded mechanically rather than forcing the
  old premature char-pressure path;
- history compactions during this canary: `0`;
- tool-working-set folds during this canary: `0`;
- scorer warm append-only requests: `11`;
- controllable excess miss across those warm requests: `0`.

These are canary observations, not a general claim that all workloads will obtain a specific cache
hit percentage.

## 6. Official b9b runtime evidence

The combined candidate was ordinary-pushed to the formal `lfl` remote and deployed with the same
qualified dual-root restart contract.

Canonical durable evidence currently records:

- `data/restart-receipt.log` — official `all` restart at `2026-09-15T07:17:35+08:00`, exact full
  SHA `b9b312c16ddf2af55fbf981f92f5b3cb71d7f001`, `rc=0`;
- `data/audit/proc_versions.jsonl` — Web and Feishu starts on `b9b312c1`, clean source identity;
- `data/runtime/runtime_manifest.json` — exact full b9b SHA, `identity_ok=true`, build clean,
  config hash `b572a531...8bdb`, 184K input and 16K output facts;
- current Feishu heartbeat — connected with queue depth 0;
- current official status — Web healthy, Feishu healthy, primary 8902 intentionally absent;
- the existing 8901 Ornith server was not restarted by the promotion.

The current build identity is truthfully exposed as a development build derived from v0.6.13,
rather than pretending the untagged candidate is a formal v0.6.14 release.

## 7. WebUI artifact boundary discovered during promotion

A clean linked worktree does not contain `webui/dist` because that directory is intentionally
Git-ignored. The first exact-code Python deployment therefore proved an additional release
requirement: deploying the source SHA alone does not manufacture the WebUI production artifact.

The correction was mechanical and did not change tracked source:

1. build `webui/dist` from the **exact b9b source**;
2. keep the artifact ignored/untracked;
3. perform an official Web-only restart still using exact b9b code identity.

The final receipt at `2026-09-15T07:24:10+08:00` remained exact b9b with `rc=0`. Current anonymous
HTTP behavior is normal WebAuth behavior:

- `/auth/status` → `200`;
- `/ui/v2/` → `303` to login;
- `/` → `303` to login.

The earlier missing-dist `404` is therefore not present in the final deployed state.

**Release implication:** WebUI test/build is a distinct promotion gate. The current GitHub Python CI
workflow does not run the WebUI test/build commands, so a future main merge or release must not infer
WebUI deployability from Python CI alone.

## 8. Main-merge boundary

At the time this report was prepared:

- official `lfl/main` = `b5717ac0ce743a96acf71361206b4f70ddaacd2a`;
- combined candidate = `b9b312c16ddf2af55fbf981f92f5b3cb71d7f001`;
- main is an exact ancestor of b9b;
- b9b is 129 linear commits ahead and 0 behind main;
- there are no merge commits in that 129-commit range;
- a three-way merge-tree scan has no conflict markers;
- a disposable `git merge --ff-only b9b312c1` from exact main produced exact b9b and a clean tracked
  tree;
- the source delta is large: 428 files, approximately +68.9K / -1.4K lines.

The large delta includes the accumulated v0.6.14 convergence line: Browser/SMC work, runtime and
Context Integrity P4–P7, Web/Feishu/WebUI changes, deterministic cache attribution and token-native
budgeting. Therefore "no textual conflicts" is not by itself a release-approval claim.

As an independent WebUI merge gate, the disposable fast-forward tree passed:

- Vitest: `22` test files / `137` tests;
- TypeScript + Vite production build: PASS.

The build emitted only non-blocking existing React test `act(...)` warnings and the standard Vite
large-chunk warning.

No PR or main merge is executed by this report. Main integration remains a separately authorized
release-governance action.

## 9. Rollback anchors

The qualified rollback hierarchy after this work is:

1. `a655217a` — immediate pre-cache, fully Gate-E-qualified Context Integrity ancestor of b9b;
2. `2139faa8` — older independently restartable stable fallback used during the first Gate-E failure;
3. `2d247ba7` — **not** an exact official rollback target; an exact tree lacks the current
   `knowledge_health` restart prerequisite.

Rollback should use a clean exact worktree plus canonical runtime/data/config binding. A process
label from a historically dirty root is not sufficient proof of reproducibility.

## 10. Privacy / evidence boundary

This report deliberately excludes:

- raw GLM or Ornith prompts, answers and hidden reasoning;
- raw provider HTTP bodies;
- credentials or secret values;
- private session identifiers;
- trace-leak quarantine payloads;
- temporary live-result JSON bodies.

It records only exact commit identities, mechanical aggregate facts, privacy-safe hashes and
canonical evidence paths.

## 11. Gate status

| Gate | Verdict | Evidence boundary |
|---|---|---|
| A — deterministic/unit | PASS | historical P7 + cache deterministic suites |
| B — ownership/integration | PASS | P1–P6/P7 ancestry + exact provider/run ownership gates |
| C — static/security/full CI | PASS | exact qualified implementation candidates |
| D — real GLM / Ornith / adversarial | PASS | privacy-safe live aggregates/hashes |
| E1 — Context Integrity official canary | PASS after one rejected attempt | 7a fail → rollback → a655 TDD fix → successful retry |
| E2 — combined cache promotion | PASS | exact b9b remote/runtime identity + live P1 canary |
| E3 — WebUI production artifact | PASS | exact b9b build + Web-only restart + current HTTP behavior |
| main merge | **NOT RUN** | separate PR/release authorization required |
| release tag / GitHub Release | **NOT RUN** | not part of this qualification |

## Final qualification statement

The evidence supports **Gate E PASS for exact b9b312c1 as the current combined canary/promotion
runtime**. It does not by itself authorize a main merge or tag. The main merge must preserve the
qualified lineage and must include the independently required WebUI gate in addition to the
repository's Python CI.
