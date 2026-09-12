# SMX focused v1.2 A/B result

Date: 2026-09-13. Protocol: `SMX-FOCUSED-AB-v1.2.md` / `smx_focused_v1_2.json`.

> **Result status: completed, qualified with two execution-governance deviations; no observed causal invalidation.** The 30-run matrix completed 30/30 PASS and independently re-judged 30/30 PASS. The adoption gate passed exactly at its minimum threshold (5/9 positive ON runs). Wait/predicate use was real; broad efficiency benefit was mixed. Diff behavior was not exercised because the model adopted `smx_perceive` in 0/3 diff ON runs.

## 1. Evidence identity and acceptance

- execution commit: `34df2dce736708aeb27281306a318100510c97f8`
- plan SHA256: `2f925980a5715ce7ccbd95c9c8c9f6df74c8b44c1e71b90c905a574284f47027`
- formal results SHA256: `1775db0f722a2526485bf2ea30e032fc6dd7d379f3a160c037f38dacdc56c952`
- execution-manifest file SHA256: `9848d78622250609bbd53c22cd83e570f0ce35689ff2942d0ec39d732f162e79`
- execution-manifest canonical/declaration SHA256 used by all 30 rows: `d97bd0a3d84fb603c5181024e0c5385e7d0e84fa9e85ea1bccf69e7a6983b0b6`
- executor wrapper SHA256: `57e5a881ba062e23a2e83800050b854c405c8f4e53e66975b3d1d7e628310606`
- 18/18 protocol frozen source hashes matched before execution; protocol self-check 6/6 PASS.
- plan indices are exactly `0..29`, once each; arms are 15 OFF / 15 ON; each of 5 tasks × 2 arms × 3 repeats appears exactly once.
- runner exited naturally; no second benchmark runner was observed; 8901 remained the same physical listener PID 38473 from start through post-run acceptance.
- independent post-run deterministic re-judge: **30/30 PASS**.
- local raw evidence is retained under the untracked `.formal-v1/smx-focused-v1.2/` evidence area; only privacy-safe aggregate evidence is committed.

The first attempted formal launch is **not part of the dataset**: an executor concurrency guard incorrectly matched its parent shell and exited before manifest creation/model call (`0` result rows). That failed workdir was preserved and never reused. The corrected wrapper was dry-self-checked again and the official matrix used a fresh workdir.

## 2. Runtime consistency and treatment isolation

The pre-run manifest correctly pinned the model process, model-directory fingerprint, LFL CLI model override, frozen sources, plan, and OFF/ON registry surfaces. It recorded registry inventory hashes:

- OFF: 65 registered tools, `smx_perceive=0`, SHA `de2331ddd104a3cf461e7d5f7ec708673e389385043c8dd368fb68e70951f1bb`
- ON: 66 registered tools, `smx_perceive=1`, SHA `80038c065b272224b0b951d477ad66138ddaaaee3d9239b5da6b7739d290c772`

Across **193 provider requests**, per-run `request.meta` gives a stronger effective-runtime check:

- exactly one reasoning config: model `cognilocal/ornith-1.5-35b-a3b-mlx`, reasoning mode `auto`, control `chat_template`, effort `high`;
- exactly one generation contract: provider `cognilocal`, model `ornith-1.5-35b-a3b-mlx`, `temperature=0.0`, `top_p=1.0`, `top_k=0`, `min_p=0.0`, `max_tokens=16000`, OpenAI wire protocol;
- one source-tree fingerprint across both arms: `f41e5465bffbe582b87a5d433061626280fad57ef4ebb8af7523608b4c1b05c5`;
- effective provider-visible tools were stable at 63 OFF vs 64 ON; the only tool-registry fingerprint difference is the predeclared OFF/ON treatment;
- schema reserve was 24,145 chars OFF vs 25,039 ON (+894); effective history budget correspondingly 141,455 vs 140,561 chars (-894).

Thus no model/reasoning/source/runtime drift was observed inside the matrix. The extra schema bytes are part of the treatment cost, not a hidden confound to subtract away.

### Qualification deviations

**Q1 — manifest capture deviation.** The execution manifest's env-only `runtime_contract` fields for resolved sampling/reasoning values were null instead of materializing the resolved values required by the protocol manifest checklist. This is a governance/capture defect. It does not become an observed causal invalidation because all 193 provider requests independently record one identical effective reasoning and generation contract, interleaved across both arms. A future focused protocol must persist the resolved contract in the manifest **before** the first model call rather than rely on post hoc per-request evidence.

**Q2 — external executor addendum.** v1.2 froze the protocol/plan/sources but the repository had no runnable focused executor for the three `sx_*` tasks. A thin executor was created outside the repository, dry-self-checked, SHA-pinned into the execution manifest, and held immutable during the matrix. It only prepared the frozen fixtures, set the predeclared arm environment, invoked the frozen LFL runner capability, called the frozen judges, and appended raw rows. It did not modify any of the 18 frozen sources or task semantics. Future protocol versions should commit and freeze this executor itself.

Neither Q1 nor Q2 is hidden; this result is therefore **qualified**, not represented as a perfectly protocol-clean execution.

## 3. Outcome and adoption gate

All task judges passed:

| domain | OFF | ON | SMX adoption in ON |
|---|---:|---:|---:|
| `sx_wait_existing_writer` | 3/3 | 3/3 | **3/3** |
| `sx_background_worker` | 3/3 | 3/3 | **2/3** |
| `sx_bulk_rename_diff` | 3/3 | 3/3 | **0/3** |
| `ap_t06_log_count` negative control | 3/3 | 3/3 | 0/3 |
| `ap_t09_big_file_line` negative control | 3/3 | 3/3 | 0/3 |

Positive ON adoption = **5/9**, exactly the predeclared minimum. Therefore the overall adoption gate passes, but with no margin. Per-domain interpretation remains mandatory: the wait domain was adopted 5/6, while the diff domain was treatment-absent 3/3.

## 4. Wait hypothesis — mixed/partial support

Per protocol, only pairs whose ON run actually adopted SMX are used for the wait-mechanism comparison (n=5):

| task / repeat | rounds OFF→ON | explicit sleep calls OFF→ON | post-trigger observations OFF→ON | wall s OFF→ON |
|---|---:|---:|---:|---:|
| writer r1 | 8→7 | 1→0 | 1→1 | 52.4→48.2 |
| writer r2 | 6→7 | 1→0 | 1→1 | 42.4→49.4 |
| writer r3 | 5→6 | 1→0 | 1→1 | 33.2→44.8 |
| background r1 | 6→6 | 1→0 | 1→1 | 49.7→55.5 |
| background r2 | 11→6 | 2→0 | 5→1 | 105.1→60.6 |

Mechanical reading:

- explicit sleep calls: **6→0**, improved in **5/5** adopted pairs;
- rounds: ON better 2/5, flat 1/5, worse 2/5; paired median delta = **0**;
- post-trigger observation calls: four pairs flat, one pair (background r2) 5→1; total 9→5, entirely driven by that one pair;
- wall time: ON faster 2/5 and slower 3/5; paired median delta = **+5.8s** (ON slower). The large background-r2 improvement makes the mean look better, so mean wall time is not used as a positive claim.

**Verdict:** SMX wait has clear mechanical value as a replacement for explicit `sleep` polling, but this experiment does **not** establish a general reduction in model rounds or latency. The strongest efficiency win is concentrated in one background-worker pair and should not be generalized from n=5.

## 5. Diff hypothesis — not evaluable

`sx_bulk_rename_diff` ON adoption was **0/3**. All six task runs passed, but the model used ordinary shell observation in both arms. Therefore:

- no benefit claim is permitted;
- no non-benefit claim is permitted;
- P7/P2 diff-contract work remains a correctness/design matter, not something this matrix behaviorally validated.

The failure to adopt is itself actionable evidence: simply making `snapshot/diff` available did not cause this model to choose it on the bulk-rename task.

## 6. Negative controls and treatment cost

Both negative controls retained task success: **12/12 PASS**, and ON made **zero** SMX calls. There is therefore no functional spillover failure.

However, tool availability was not behaviorally free:

- paired wall-time ON-OFF deltas across the 6 negative-control pairs: `+9.5, -0.1, +6.1, +9.6, +0.5, -2.6s`; median **+3.3s**;
- paired round deltas: `+2, -1, +1, +1, +1, -1`; median **+1 round**;
- ON adds exactly one provider-visible tool and 894 chars of schema reserve.

With n=6 and noisy local latency this is **not** a statistically supported overhead claim. It is a concrete caution against default-enabling the capability when the model does not need it. The current opt-in design remains justified.

Descriptive cache telemetry does not show a large cache collapse: median run-level hit ratio was about 96.63% OFF vs 96.52% ON. Cache/tokens remain secondary because the treatment intentionally changes provider-prefix bytes.

## 7. First-call and failure evidence

- first mechanically valid action occurred in round 1 for **30/30** runs.
- positive `sx_*` tasks have no frozen first-tool oracle in v1.2, so selection/FCR is **not invented** for them.
- the inherited AgentPilot negative-control oracle defines `read` as the first-tool class: `ap_t09` satisfies it 6/6; `ap_t06` starts with `execute_command` 6/6 and therefore scores 0/6 under that frozen oracle. This split is identical across OFF/ON and is not a treatment effect.

Raw tool failures = **5** (ON 3, OFF 2), all unexpected by the task oracles and all repaired before successful judge completion:

1. ON writer r3: pre-trigger compound probe read artifacts that did not yet exist; trigger/wait/read recovered.
2. ON t06 r1: macOS/BSD `cat` rejected `-A`; `od -c` verified the file next turn.
3. ON background r3: poll/list compound command exited 1 after the first background launch failed to materialize outputs; the job state was inspected and the worker was relaunched successfully.
4. OFF diff r3: process-substitution syntax was rejected by `/bin/sh`; a simpler verification command succeeded.
5. OFF t09 r3: model called nonexistent `write_file`; `execute_command` wrote the exact content and `read_file` verified it.

**Q3 — telemetry blind spot.** Background commands composed as `nohup ... > missing/dir/file &; echo ...` can yield a successful outer tool receipt even when the child never starts because redirection fails. Rows background r2/r3 expose this. `tool_failure_count_raw=5` is therefore truthful raw telemetry but not a complete detector of child-start failures. This is a harness mechanical-observability backlog item, not evidence that SMX caused the failures.

Reliability remains **insufficient** by the predeclared rule: both arms are at the task-success ceiling (15/15), so this focused experiment is not an H3 reliability qualification.

## 8. A/B ruling and SMC-ADAPT-SMX consequence

The evidence supports these bounded conclusions:

1. **Keep SMX perception opt-in.** There is real wait adoption and no functional negative-control regression, but the capability has nonzero provider-prefix/attention cost and no broad latency win.
2. **P4 Predicate/wait now has the strongest empirical priority.** Wait was adopted 5/6 and consistently removed explicit sleep polling, even though rounds/latency were mixed.
3. **P7 scope comparability and P2 diff completeness remain important contract correctness work, but are not behaviorally validated by this experiment** because diff adoption was 0/3.
4. P8/P5/P0 remain after the first three; no evidence here argues for moving canonical wire (P0) earlier.

For implementation ROI, the evidence-based order is therefore proposed as:

**P4 → P7 → P2 → P8 → P5 → P0**

This is a deliberate update from the pre-A/B `P7 → P4 → P2` ordering: it changes priority because new evidence shows actual model uptake for Predicate/wait and zero uptake for diff. It does **not** weaken the normative importance of P7/P2 before any future claim of canonical diff correctness.

## 9. Machine-readable companion

`smx_focused_result_v1_2.json` contains the 30 privacy-safe compact rows, adopted-pair deltas, failure catalog, runtime-consistency proof, qualification notes, evidence hashes, and the proposed next priority. It intentionally excludes raw prompts, local absolute home paths, credentials, and full event logs.
