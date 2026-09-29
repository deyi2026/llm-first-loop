# Execution Efficiency v2.1 — execute_command portability contract A/B

Date: 2026-09-29
Disposition: **QUALIFIED_FOR_REPLICATION_NOT_PRODUCTION**

## Executive conclusion

EEv2.1 tested one narrow hypothesis while keeping the complete mechanically healthy
tool surface visible:

> Adding a short host/toolset portability fact to `execute_command.command` can reduce
> avoidable shell/tool portability failures without lowering correctness or First-Call-Ready.

The treatment is **directionally positive and worth replicating**, but this experiment
does **not** authorize a production schema/default change.

The frozen A/B surface contained the same 74 effective tools in both arms.  Arm B added
only 117 provider-facing JSON characters to `execute_command.command`:

> 命令运行在实际 host shell/toolset；不要假设 GNU-only 选项。涉及平台差异时优先
> POSIX/host-portable 写法，必要时先用 uname 或工具 help 核实。

There was no semantic tool hiding, domain projection, provider-routing change, runtime
default change, production publish, or service restart.

## Frozen protocol and evidence

The experiment was frozen at main `87c96de897f3c6bd9338d9d22780315c97be23b0`.

- matrix: 6 tasks × 2 arms × 3 repeats = **36 rows**;
- arms: `A-current` and `B-portability-contract`;
- frozen model: `deepseek/deepseek-flash`, reasoning effort `max`;
- current runtime default at freeze time: `cognilocal/qwen3.8-flash-next`;
- tool set equality: **true**;
- effective tools: **74 vs 74**;
- treatment surface delta: **+117 chars**;
- raw correctness: **36/36**;
- run errors: **0**;
- provider tool-surface wire match: **36/36**;
- provider model identity reconstructed from wire: **36/36**.

The frozen source hashes in `EEV21-MANIFEST.v0.1.json` match the actual scorer, runner,
task and surface source used to generate the rows.  The raw/wire/cache evidence is kept
outside Git under:

`data/private-archive/evals/eev21-portability-ab-20260929/`

Evidence hashes:

| Artifact | SHA256 |
| --- | --- |
| `EEV21-MANIFEST.v0.1.json` | `777a44a3aa70b0e4543c1c94565113f643ea8a8cec4d46c69686262d4c123c59` |
| `EEV21-RAW.v0.1.jsonl` | `258a9e6d37dc347c122bcd1b491c167e053aa493c3f7841ae0dbdc591df28655` |
| `EEV21-WIRE.v0.1.jsonl` | `01860b2a6ac67838ea3e63ea897fd851ddb5019fc652e62e6e15397a3d7c8638` |
| `EEV21-CACHE-WIRE.v0.1.jsonl` | `66e5bf19522401870ded6c4cb9358c8935a6e8dd69d019bcf22687b8a4a4e9df` |
| tracked result `EEV21-RESULT.v0.1.json` | `e5f273c5e7124df3db3a73b261b4fbec17100960d64ba717a4ea42096a7c52f1` |

## Whole matrix

| Metric | A-current | B-portability-contract |
| --- | ---: | ---: |
| Correctness | **18/18** | **18/18** |
| FCR-v2 | **16/18** | **16/18** |
| Wrong first-tool | 2 | 2 |
| First-action arg-oracle misses | 2 | 2 |
| Runtime failures | 14 | 10 |
| Repair sequences | 12 | 9 |
| Serial tool barriers | 68 | 60 |
| Median wall | 8.976 s | 8.641 s |
| Median uncached input | 1,466 | 1,575.5 |

The treatment therefore does not win by having fewer tools or a smaller schema.  It
adds a small amount of provider context while reducing failed/repair paths and serial
barriers at equal correctness/FCR.

## Target family: portability

The target family has 9 rows per arm.

| Metric | A-current | B-portability-contract |
| --- | ---: | ---: |
| Correctness | **9/9** | **9/9** |
| FCR-v2 | **9/9** | **9/9** |
| Host-portability failure rows | **4/9** | **1/9** |
| Runtime failures | 4 | 2 |
| Repair sequences | 4 | 2 |
| Serial barriers | 26 | 22 |
| Median wall | 8.896 s | 7.034 s |
| Median uncached input | 1,303 | 1,207 |

Paired by task and repeat:

- A-only portability failure: **3 pairs**;
- B-only portability failure: **0 pairs**;
- both fail: **1 pair**;
- neither fail: **5 pairs**;
- serial barriers: B−A sum **−4**, median pair delta **−1**;
- provider rounds: B−A sum **−4**, median pair delta **−1**;
- wall time: B−A sum **−12.229 s**, median pair delta **−0.852 s**;
- wall time improved in 6/9 pairs and worsened in 3/9.

The observed A failures include GNU/BSD option assumptions such as `stat -c`, `cat -A`
and `find -printf`; the treatment fact did not name those commands or flags.

This is the main positive result of EEv2.1.

## Tokens: no promotion claim

Token results are intentionally not used to promote this treatment.

The portability-family median uncached input improves from 1,303 to 1,207, and the
paired median B−A delta is −86 tokens.  However one B row has a +7,438 uncached-token
outlier, making the paired mean delta **+688** and the paired sum **+6,193**.

So EEv2.1 establishes **no token-efficiency win**.  The useful signal is fewer portability
failures/repairs/barriers at unchanged correctness/FCR.

## Wrong-tool holdout: no regression, but insufficient challenge

Both wrong-tool tasks selected the exact pre-registered first tool in all repeats:

- A: **6/6** exact first action;
- B: **6/6** exact first action.

This establishes that the portability contract did not perturb explicit tool adherence.
It does **not** demonstrate improved wrong-tool selection, because these prompts name or
strongly prescribe the required tool.  They have no baseline wrong-tool error headroom.

The next replication should add naturalistic selection tasks whose prompts express the
information/action need without naming the target tool.  The acceptable/negative tool
oracle must still be registered before the first model request.

## Edit-control: symmetric, but exact-first oracle is too strict

The edit control is correct in all rows: **3/3 vs 3/3**.  Exact-first FCR is **1/3 vs
1/3**, because two repeats in each arm call `search_files` before
`read_file(snapshot=true)`.

That is symmetric and treatment-independent, so there is no regression.  But a locator
search before the versioned read is defensible behavior.  A future control should
pre-register whether such locator/verification side steps are neutral rather than
retroactively treating them as wrong.

## Cache evidence is descriptive only

The resolved DeepSeek provider did not expose the local `cache_prompt=false` control
used by some local providers.  EEv2.1 therefore records provider-default cache behavior.
The wire/tool surface is fully auditable, but cache state was **observed rather than
experimentally controlled**.  Cache-hit/uncached-token metrics remain descriptive and
are not a promotion gate for this result.

## Decision

`B-portability-contract` is **QUALIFIED_FOR_REPLICATION_NOT_PRODUCTION**.

Why it advances:

1. source / matrix / wire provenance gates pass;
2. correctness stays 18/18;
3. FCR-v2 stays 16/18 overall and 9/9 in the target family;
4. true host-portability failure rows fall 4/9 → 1/9;
5. no B-only portability-failure pair appears;
6. target-family repairs and serial barriers both fall;
7. wrong-tool and edit-control families show no treatment regression.

Why it does **not** go to production:

1. only one resolved model/provider was tested;
2. the current default `cognilocal/qwen3.8-flash-next` has not replicated the result;
3. the sample has only three repeats per task;
4. cache behavior was not controlled;
5. the wrong-tool holdout is too explicit to measure natural tool-discovery mistakes;
6. token benefit is not established.

## Recommended next phase: EEv2.2 replication

Keep all mechanically healthy tools visible and reuse the **same +117-char treatment**.

Required changes to the benchmark, not to production:

1. replicate the portability family on current-default `cognilocal/qwen3.8-flash-next`;
2. keep the existing portability tasks for paired comparability;
3. add naturalistic wrong-tool tasks that do not name the desired tool;
4. freeze an explicit side-step policy for locator/search verification before the first
   action oracle is scored;
5. continue reporting correctness, FCR, wrong/rejected/repair calls, serial barriers,
   wall time and token metrics separately;
6. do not change production `registry.py` until replication passes.

The result continues to support the broader principle: **optimize correct first-use and
repair avoidance, not tool-count reduction.**
