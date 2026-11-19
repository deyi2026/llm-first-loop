# M1-SIM-003 — Frozen DeepSeek B1/B2 paired experiment audit

- Source SHA: `d779f382ad64edd3f56f931764d2c10fa6f44193`
- Prereg SHA-256: `d77a2550b17c71630bee1bdaddaf733cc240ac3bb67c662837d4f5f3b3f163d6`
- Grant SHA-256: `0c8ad17cdd302cd1867e096fec3a923a068cd403aeb3f7763cf3e25ae5163f6a`
- **Evidence: 60/60, 30 matched pairs, 60 distinct UID463 Host runs.**
- **Provider calls:** 319/360; **tool actions:** 308/480.
- **Conservative estimated USD:** 0.39625350/20.00 (not an invoice).

| Metric | B1 | B2 |
|---|---:|---:|
| Independent Oracle verified placements /30 | 27 | 23 |
| Success rate | 0.9 | 0.7666666666666667 |
| Provider attempts | 160 | 159 |
| Tool actions | 153 | 155 |
| Managed recovery releases | 0 | 0 |
| Replans | 7 | 3 |
| Estimated USD | 0.19899840 | 0.19725510 |
| Estimated USD per verified task | 0.007370311111111111111111111111 | 0.008576308695652173913043478261 |
| Latency p50 seconds | 25.648 | 23.108 |
| Latency p95 seconds | 44.472 | 48.083 |

**Paired success-rate delta (B2−B1):** -0.1333. 95% paired bootstrap CI (1000 resamples, seed 20261117): [-0.3008, +0.0333].

**Cost per verified task ratio B2/B1:** 1.1636291285890172. Frozen acceptance threshold <=1.5: True.

**Effectiveness verdict: NO DEMONSTRATED B2 BENEFIT.** B2 placed 23/30
versus B1 27/30, a -13.3 percentage-point paired difference. The
95% paired bootstrap interval crosses zero. The B2 managed recovery branch
was exercised **zero** times across the 30 paired episodes; the earlier
successful injected-fault L3 smoke remains engineering evidence only, not a
paired treatment effect. **Do not enable B2 by default or claim it improves
success.** This is a valid negative/inconclusive experimental outcome, not
a reason to discard or silently rerun frozen seeds.

**Operational finding:** root Host batch authorization was installed with
`umask 077`, leaving both `/usr/local/var` and its budget child root
`0700`. The operator-owned ledger could not be traversed. The local Mac
was repaired using a narrowly scoped `yyj allow search` ACL on those
two directories, preserving root ownership and no directory-listing grant.
This is a reproducibility note for future installers, not a change to the
frozen experiment or a reason to widen all-user permissions.

**Interpretation constraints:** This is the preregistered 30-pair simulator comparison. The engineering smoke was excluded. No physical robot was used. Model identity was checked on each HTTP response. Costs are peak-tariff estimates and must not be represented as invoice totals. All signed Oracle claims were verified at execution time; this audit reconciles their persisted verdicts and evidence SHA-256.

**Next gates:** fix isolated test fixture after freeze, independent Host Reviewer PASS P0/P1=0, original full R9 exit 0, exact-SHA remote CI, protected main merge, unified managed deployment. No bypass.
