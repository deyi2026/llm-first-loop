# Calibration Frozen H2f v1

> Status: **FROZEN / READY FOR H2F REAL EXECUTION**
> Core: v1.9-measurement-core (Action v1.8 + Novel Integration v1.9)
> H1f: 56/56 exact PASS
> Real H2f requests at freeze: 0

## SHA-256
| Artifact | SHA-256 |
|---|---|
| `scripts/calib/scorer_v18.py` | `7a832f1be2641397aab097ab5df96ab77b66a38a0ff51a49361ccc27bd6d24c0` |
| `scripts/calib/scorer_v19.py` | `bf6f977e29fd37902e3d653df71739856e38c7947dcf2b607acae5e644d0d8d6` |
| `tests/unit/test_calib_scorer_v19.py` | `de4db90b6ac02e8ad899f2757e11e4f99419559c9cda6e4ee2c8e9c89b745d1b` |
| `data/calib/h1f_control_bank.json` | `598e76821637258c1dd627a621a3ec434efb9691f79b92b74a21fa0abd216671` |
| `scripts/calib/run_h1f.py` | `4b85183fda5e634244d590e331f34e54734d8d070c69167d73966bce424c3ec1` |
| `data/calib/h1f_report.json` | `0aeae18b3c46fce245d267f05bb5a359c7e6d3ed79b3108d5ebe9867c9d0789a` |
| `docs/CALIBRATION-H1F-v1.md` | `548717cc47f40b6a27e32d02af832c3f1f0f585b681ff7e2e78588be1be60012` |
| `scripts/calib/fixtures_h2f.py` | `b41c765aaa75161a2a12f9f99e1c9587b53b5d1ce3894475df7672f9e46300b0` |
| `scripts/calib/h2f_scorer.py` | `9879e777a1e7e951b07a2c63a80463f16da7fc30135d1fc8e7201cef3a0ba0e0` |
| `tests/unit/test_calib_h2f.py` | `3b83b4e3f58eed6ff4197ac5ebd9ff89f1f9f1841b0f39fd93802ebd04b83098` |
| `scripts/calib/run_h2f.py` | `4866530fdbac0b56916c2ca369f72dd3b4c662c425e7a02850f97817968faf35` |
| `scripts/calib/judge_h2f.py` | `e960be9e0dff3916740e4ff3869f00a8a959d3197f0a8b032a1c49c8298e551c` |
| `data/calib/h2f_matrix_v1.json` | `5cd1b576f31ac1d8e108bcfb67caad29d6ff2b658dfa8198f915d5e04c3996f1` |
| `data/calib/h2f_provider_manifest.json` | `76962330aece82619fd9684944a253530b6bfa5a33ee28b48b80428bff2b664a` |
| `docs/CALIBRATION-SEEDS-H2F-v1.md` | `ed07477cd06e1bd5ed65745479012311ba353b8de3e73cdcb0e599a4510de0ce` |
| `docs/CALIBRATION-MATRIX-H2F-v1.md` | `92e7a19577c1ca85c2e492113a94b71ba4fe254ca4b4cee7e33f46cbaa250b35` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `scripts/calib/runner.py` | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |

Gate: cross-judge task/fatal/constraint >=95%, novel>=90%, zero adjudicated scorer bugs. Any bug => STOP/FAIL.
