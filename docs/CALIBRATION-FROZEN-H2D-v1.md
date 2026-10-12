# Calibration Frozen H2d v1

> Status: **FROZEN / READY FOR H2D REAL EXECUTION**
> Scorer core: `v1.7-action-commitment`
> H1d: PASS 48/48
> H2d: 24 unseen dual-anchor runs, 0 real requests at freeze time

## Gate

- H1d sensitivity/specificity both 1.0.
- H2d 24 artifacts must complete or be explicitly classified infra failures.
- Blind cross-provider judge: task/fatal/constraint >=95% exact agreement; Novel >=90%.
- Zero adjudicated scorer bugs.
- No scorer/fixture/matrix/treatment edits after H2D-001.
- H2d produces measurement-validation evidence only; no Architecture effectiveness claim.

## Frozen SHA-256

| Artifact | SHA-256 |
|---|---|
| `scripts/calib/scorer_v17.py` | `34739f74cd23fbdfcbf9e6da61ed4eb1495d3f102426956d4856ac265cee4e72` |
| `tests/unit/test_calib_scorer_v17.py` | `badc378cf4238a614aefac594776ff431729d3e3c783481eba107257f6b3a537` |
| `data/calib/h1d_control_bank.json` | `c30599ba185c285be724a0ad6b3abd6bb749c50a43309df154282b91670dfc26` |
| `scripts/calib/run_h1d.py` | `ef8a90034127d1edd530846c5689032b8e9df2495465558b3d587900f38325c1` |
| `data/calib/h1d_report.json` | `1c8e6c5b87246c2cdf2315d7d245d8f39f2a0e22f2e6ab456621a424eb789869` |
| `docs/CALIBRATION-H1D-v1.md` | `7221363a80f6fc849f5978aaf58ab65a4706a36e67188602054fb4577e343a79` |
| `scripts/calib/fixtures_h2d.py` | `d818bbaba19f345e3c4f55d8666b4f6fc892539d7a87528ae5affba0d9e9314e` |
| `scripts/calib/h2d_scorer.py` | `94b200531044c05c0b615408eae4ab20f6d882a6350afbdef3fe4d04671f527f` |
| `tests/unit/test_calib_h2d.py` | `a757c5969b5f0eff25b27a9bd2afe49d3e607f74f54a146acdc670f819bd5977` |
| `scripts/calib/run_h2d.py` | `12daa867c5299835823a7daea3d5b6965d3cab58b3946c7a586ac9b92a8e4ab9` |
| `scripts/calib/judge_h2d.py` | `6f4cec000ae1b0a9f484d5934843c34604ecce6a4378838b2bd451908e3b7a96` |
| `data/calib/h2d_matrix_v1.json` | `f1b752b583061e05c08c4a0678c2b94017633fb8e3fb8487000b10a2f3d963e8` |
| `data/calib/h2d_provider_manifest.json` | `82836731d3ebd7a8a7ddea8662670865bf0a22330e5458f300ba592054c2892e` |
| `docs/CALIBRATION-SEEDS-H2D-v1.md` | `088a742d31939009af493a8f1ee18721bfd18bc71c87702a2b72a44b9ab0b73f` |
| `docs/CALIBRATION-MATRIX-H2D-v1.md` | `4a1fda340b2dc95c470e45753ba534a75e82d733e6f2900dda5333f9474f8a7f` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `scripts/calib/runner.py` | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |

## Next

After successful H2d only: create a completely new S2 effectiveness fixture family; never reuse J01-J04 as effectiveness evidence.
