# Calibration 30-Run Matrix v1

> 状态：FROZEN CANDIDATE
> Randomization seed：`202608252244`
> Design：10 paired seeds × 3 variants = 30 runs

| Seq | Run ID | Seed | Slot | Variant | Isolation Tag |
|---:|---|---|---:|---|---|
| 1 | CAL-01 | S01 | 1 | V1-Contract | `iso-s01-1` |
| 2 | CAL-02 | S01 | 2 | V2-Full | `iso-s01-2` |
| 3 | CAL-03 | S01 | 3 | V0-Baseline | `iso-s01-3` |
| 4 | CAL-04 | S02 | 1 | V1-Contract | `iso-s02-1` |
| 5 | CAL-05 | S02 | 2 | V2-Full | `iso-s02-2` |
| 6 | CAL-06 | S02 | 3 | V0-Baseline | `iso-s02-3` |
| 7 | CAL-07 | S03 | 1 | V1-Contract | `iso-s03-1` |
| 8 | CAL-08 | S03 | 2 | V2-Full | `iso-s03-2` |
| 9 | CAL-09 | S03 | 3 | V0-Baseline | `iso-s03-3` |
| 10 | CAL-10 | S04 | 1 | V0-Baseline | `iso-s04-1` |
| 11 | CAL-11 | S04 | 2 | V1-Contract | `iso-s04-2` |
| 12 | CAL-12 | S04 | 3 | V2-Full | `iso-s04-3` |
| 13 | CAL-13 | S05 | 1 | V0-Baseline | `iso-s05-1` |
| 14 | CAL-14 | S05 | 2 | V1-Contract | `iso-s05-2` |
| 15 | CAL-15 | S05 | 3 | V2-Full | `iso-s05-3` |
| 16 | CAL-16 | S06 | 1 | V1-Contract | `iso-s06-1` |
| 17 | CAL-17 | S06 | 2 | V2-Full | `iso-s06-2` |
| 18 | CAL-18 | S06 | 3 | V0-Baseline | `iso-s06-3` |
| 19 | CAL-19 | S07 | 1 | V0-Baseline | `iso-s07-1` |
| 20 | CAL-20 | S07 | 2 | V2-Full | `iso-s07-2` |
| 21 | CAL-21 | S07 | 3 | V1-Contract | `iso-s07-3` |
| 22 | CAL-22 | S08 | 1 | V0-Baseline | `iso-s08-1` |
| 23 | CAL-23 | S08 | 2 | V2-Full | `iso-s08-2` |
| 24 | CAL-24 | S08 | 3 | V1-Contract | `iso-s08-3` |
| 25 | CAL-25 | S09 | 1 | V1-Contract | `iso-s09-1` |
| 26 | CAL-26 | S09 | 2 | V0-Baseline | `iso-s09-2` |
| 27 | CAL-27 | S09 | 3 | V2-Full | `iso-s09-3` |
| 28 | CAL-28 | S10 | 1 | V1-Contract | `iso-s10-1` |
| 29 | CAL-29 | S10 | 2 | V0-Baseline | `iso-s10-2` |
| 30 | CAL-30 | S10 | 3 | V2-Full | `iso-s10-3` |

## Execution Freeze

- 严格按 Seq 执行；INFRA retry 紧跟原 run。
- 每个 run 新 session；同 seed Agent-visible fixture 字节级相同，仅 treatment 不同。
- resolved model 必须为 `minimax/MiniMax-M3`；fallback/其它 model → INFRA_FAILURE。
- Calibration 不对 cache/latency 做 Architecture effectiveness 结论。
- Cache carry-over 策略：record-and-randomize；不人为加入 cache-busting nonce。

## Blind Human Review Order

1. `CAL-07`
2. `CAL-14`
3. `CAL-02`
4. `CAL-01`
5. `CAL-19`
6. `CAL-26`
7. `CAL-06`
8. `CAL-28`
9. `CAL-17`
10. `CAL-10`
11. `CAL-04`
12. `CAL-24`
13. `CAL-30`
14. `CAL-22`
15. `CAL-16`
16. `CAL-08`
17. `CAL-03`
18. `CAL-20`
19. `CAL-11`
20. `CAL-12`
21. `CAL-13`
22. `CAL-23`
23. `CAL-21`
24. `CAL-29`
25. `CAL-09`
26. `CAL-18`
27. `CAL-27`
28. `CAL-05`
29. `CAL-25`
30. `CAL-15`
