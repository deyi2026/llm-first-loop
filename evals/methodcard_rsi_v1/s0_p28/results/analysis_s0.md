# S0 offline analysis — read-only snapshot
- generated_at: 2026-10-19T20:13:20+0800 (now_injected=True)
- calls: results/calls.jsonl sha256=bf0aec406e03c8c23c016c796072b4c5288b0e4a3692c428637cd1631fb62e89
- lines: total=242 ok=240 fail=2 unparsable=0
- duplicate ok keys: 0 (extra rows dropped: 0)
- paired: 120/120  missing pairs: 0 (keys → JSON meta.missing_paired_keys)
- amendment: GATE-AMENDMENT-v2.md sha256=de47ee878cca9c9c87771f2e235cdc274cfd7d2bf82cbd090a41a1bd3026b9c3

## per-grader paired results（D/R 以 run_s0.summarize_one 为准）
| grader | paired | D | R | D-R | both_pass | both_fail | identical | mcnemar_exact_p | D>=30 |
|---|---|---|---|---|---|---|---|---|---|
| v1.0 | 120 | 6 | 25 | -19 | 5 | 84 | 0 | 0.000878 | False |
| v1.1 | 120 | 10 | 24 | -14 | 7 | 79 | 0 | 0.024307 | False |
| v1.2 | 120 | 19 | 21 | -2 | 10 | 70 | 0 | 0.874629 | False |
| v1.3 | 120 | 28 | 16 | 12 | 26 | 50 | 0 | 0.096142 | False |

## per-arm（case_pass 的 Wilson 95% CI）
| grader | arm | n | case_pass | rate | wilson95 | c1 | c2 | c3 | c4 | median_chars |
|---|---|---|---|---|---|---|---|---|---|---|
| v1.0 | no_card | 120 | 30 | 0.2500 | [0.1811,0.3344] | c1=0.6917 c2=0.5583 c3=0.6000 c4=1.0000 | 353 |
| v1.0 | orig_card | 120 | 11 | 0.0917 | [0.0520,0.1567] | c1=0.7167 c2=0.2917 c3=0.6000 c4=0.7083 | 496 |
| v1.1 | no_card | 120 | 31 | 0.2583 | [0.1884,0.3433] | c1=0.6917 c2=0.5583 c3=0.6083 c4=1.0000 | 353 |
| v1.1 | orig_card | 120 | 17 | 0.1417 | [0.0904,0.2152] | c1=0.7167 c2=0.2917 c3=0.8833 c4=0.7083 | 496 |
| v1.2 | no_card | 120 | 31 | 0.2583 | [0.1884,0.3433] | c1=0.6917 c2=0.5667 c3=0.6083 c4=1.0000 | 353 |
| v1.2 | orig_card | 120 | 29 | 0.2417 | [0.1739,0.3255] | c1=0.7167 c2=0.3417 c3=0.8833 c4=1.0000 | 496 |
| v1.3 | no_card | 120 | 42 | 0.3500 | [0.2705,0.4388] | c1=0.6917 c2=0.8750 c3=0.6083 c4=1.0000 | 353 |
| v1.3 | orig_card | 120 | 54 | 0.4500 | [0.3639,0.5392] | c1=0.7167 c2=0.6833 c3=0.8833 c4=1.0000 | 496 |

## c3 length strata（按 no_card 回复字符数；每层四版 D/R）
| bin | n_pairs | v1.0 D/R | v1.1 D/R | v1.2 D/R | v1.3 D/R |
|---|---|---|---|---|---|
| [0,300) | 30 | 1/6 | 3/6 | 6/5 | 7/4 |
| [300,600) | 80 | 4/15 | 6/13 | 12/11 | 18/9 |
| [600,inf) | 10 | 1/4 | 1/5 | 1/5 | 3/3 |

v1.3 各层两臂 case_pass：
| bin | n_pairs | arm(v1.3) | case_pass | rate |
|---|---|---|---|---|
| [0,300) | 30 | no_card | 8 | 0.2667 |
| [0,300) | 30 | orig_card | 11 | 0.3667 |
| [300,600) | 80 | no_card | 27 | 0.3375 |
| [300,600) | 80 | orig_card | 36 | 0.4500 |
| [600,inf) | 10 | no_card | 7 | 0.7000 |
| [600,inf) | 10 | orig_card | 7 | 0.7000 |

## no_card 长度四分位（v1.3；cuts=[299.5, 353.0, 391.0]；statistics.quantiles(n=4, method='exclusive')（R type-7 同族））
| quartile | len_min | len_max | n_pairs | D | R |
|---|---|---|---|---|---|
| Q1 | 177 | 299 | 30 | 7 | 4 |
| Q2 | 301 | 353 | 31 | 7 | 4 |
| Q3 | 354 | 391 | 30 | 6 | 3 |
| Q4 | 396 | 1418 | 29 | 8 | 5 |

## c2 负向审计（v1.0 c2=False 集合内 v1.3 c2=True 的原因分类；每类前 10 id → JSON）
| arm | v1.0 c2=False | flipped→v1.3 True | a | b | c | d | e | zero_marker(两版均False) |
|---|---|---|---|---|---|---|---|---|
| no_card | 53 | 38 | 0 | 38 | 0 | 0 | 0 | 15 |
| orig_card | 85 | 47 | 20 | 23 | 4 | 0 | 0 | 38 |
- (a|b) 与 run_s0.C2_V13 逐行等价: True

## gates（两套口径并列；标签逐字取自 GATE-AMENDMENT-v2.md §2）
- 旧口径 gate_both（四版 D>=30）: False  per-grader: v1.0=False, v1.1=False, v1.2=False, v1.3=False
- 新冻结口径: v1.3 D=28（>=30: False）；方向一致性 D>=R: v1.0 6/25→False, v1.1 10/24→False, v1.2 19/21→False
- label: S0 no detectable effect under this instrument

## data quality
- fail rows: 2 ['s0|orig_card|P28-002|r1', 's0|orig_card|P28-117|r1']
- duplicate ok keys: 0 {}
- missing paired keys (0): []
- strata consistency: {'pairing_structure_matches_summarize_one': True, 'v1.0': {'bin_paired_sum_equal': True, 'bin_D_sum_equal': True, 'bin_R_sum_equal': True}, 'v1.1': {'bin_paired_sum_equal': True, 'bin_D_sum_equal': True, 'bin_R_sum_equal': True}, 'v1.2': {'bin_paired_sum_equal': True, 'bin_D_sum_equal': True, 'bin_R_sum_equal': True}, 'v1.3': {'bin_paired_sum_equal': True, 'bin_D_sum_equal': True, 'bin_R_sum_equal': True}, 'quartiles_v1_3': {'D_sum_equal': True, 'R_sum_equal': True, 'pairs_sum_equal': True}}
[out] results/analysis_s0.json
