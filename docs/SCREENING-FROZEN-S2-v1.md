# Screening Frozen S2 v1

> Status: **FROZEN / READY FOR REAL ANCHOR-ONLY S2**
> Measurement: frozen v2.1
> Real S2 generations at freeze: 0

## SHA-256
| Artifact | SHA-256 |
|---|---|
| `docs/MEASUREMENT-FROZEN-v2.1.md` | `f6b12b650ffd93afc73eb2732c9b3969020b05b98678b229e1c6c908bfc83ce3` |
| `scripts/calib/semantic_judge_v21.py` | `a52ade5b9cc9bed5797e66995ee00b4de71b98568af5d806f5af661bfd868ffd` |
| `scripts/calib/fixtures_s2.py` | `c17317c7635025ac3978f39977d1f59007e3ff406459b5ddd7dc0de956a5182c` |
| `scripts/calib/run_s2.py` | `9b009a8650761a091bc61585a109753ac3c75f6e7f6f36634ce77def9973c306` |
| `scripts/calib/judge_s2.py` | `b9e2691a8197d704e2aebf2119115d2a0d944fac0ff08a08c624aa268464138c` |
| `scripts/calib/analyze_s2.py` | `612a0acc5b337997201c744759047dee1ba51b62e039e4c77209b5700ed74463` |
| `data/calib/s2_matrix_v1.json` | `4b3fc16d1e1332d65f306c179d2cd3862cd11020bbff0db1f1874a563cd3728c` |
| `data/calib/s2_provider_manifest.json` | `d42df432e13de88650b1430084be845cd45afa87db9373e62150796f61aae782` |
| `docs/SCREENING-S2-SEEDS-v1.md` | `545fc002a14805f2cf15af752ae38cfd91d627d295266af8b7462b0f309bf6a5` |
| `docs/SCREENING-S2-MATRIX-v1.md` | `3487936be673c9972c7bf6ff9bbfd4c8cbbe19eee8356a649921a86c7bfbb49c` |
| `tests/unit/test_s2_fixture.py` | `e4e8016940407167df75c18c47a95a9e1299b952302690c0348bdb6cc4e004d4` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `scripts/calib/runner.py` | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |

After S2-001: zero edits to Measurement v2.1, fixtures, matrix, treatment prompts, generation runner, judging protocol, analysis/classification rule. Measurement bug => invalidate S2; Architecture result must not drive scorer changes.
