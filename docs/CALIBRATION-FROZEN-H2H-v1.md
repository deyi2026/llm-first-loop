# Calibration Frozen H2h v1

> Status: **FROZEN / READY FOR H2H REAL EXECUTION**
> Measurement: v2.1 narrow semantic judge + deterministic trace
> H1h: 48/48 judge rows all-exact PASS
> Real H2h generation requests at freeze: 0

## SHA-256
| Artifact | SHA-256 |
|---|---|
| `scripts/calib/semantic_judge_v21.py` | `a52ade5b9cc9bed5797e66995ee00b4de71b98568af5d806f5af661bfd868ffd` |
| `scripts/calib/run_h1h.py` | `6bbc44f316e7e067ef7c68bfe8d9adc04ec506e45d1f2d0306d9c7a5d442aa2c` |
| `data/calib/h1h_control_bank.json` | `30be4e70b705c562cc6369d3b67fc8738a119e1c8c09cda90db0d0d7ba12cbeb` |
| `data/calib/h1h_report.json` | `1291314168abb0fdb4857cde771c2271cdfd2076703dabfab79acbb6d3613708` |
| `docs/CALIBRATION-H1H-v1.md` | `5999ae1521679feb2d7f571b3557957b4fd6f8cdd2cdc858c810acc7fb2112ba` |
| `scripts/calib/fixtures_h2h.py` | `409468c79ac754718457892f1d8c3fbb957bae20a884d8080e56e499448cb9a8` |
| `scripts/calib/run_h2h.py` | `668a187224296bda48111c09887020105d4d7b78f4b4da9ebcc6aabebf080f16` |
| `scripts/calib/judge_h2h.py` | `7d83389b252de246772f3b98f7d5d023d4021e532c182bf256fcb5699b43361c` |
| `data/calib/h2h_matrix_v1.json` | `ea155e38c22e670f2eead736e44fe3b8003d46191af4c2a8e54d3d7eb436985f` |
| `data/calib/h2h_provider_manifest.json` | `edf3e68b282290d42976fcd88ec1e4792e5eeabb9d1017a3ff7a0d66ae56d803` |
| `docs/CALIBRATION-H2H-v1.md` | `51da09d34d6e29eb33b2001421149d986ecef17ec1e4d2a7e1d4cf22f59f5602` |
| `tests/unit/test_semantic_judge_v21.py` | `e8a4b7f2355df95f122c60d7719be826040e1900fe6c0f814278d0f38749f205` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `scripts/calib/runner.py` | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |

## Holdout Discipline
Any measurement bug discovered after H2H-001 invalidates H2h. No prompt/rule/fixture/matrix repair followed by reusing M01-M04 as confirmatory evidence.
