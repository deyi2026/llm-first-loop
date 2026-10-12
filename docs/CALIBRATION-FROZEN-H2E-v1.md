# Calibration Frozen H2e v1

> Status: **FROZEN / READY FOR H2E REAL EXECUTION**
> Scorer: `v1.8-action-commitment` + `v1.8-h2e` adapter
> H1e: PASS 48/48
> Real H2e requests at freeze time: 0

## Gates
- H1e sensitivity=specificity=1.0.
- H2e cross-judge task/fatal/constraint >=95%, novel >=90%.
- Zero adjudicated scorer bugs.
- H2E-001 onward: scorer/fixtures/matrix/treatments/runner/judge protocol zero edits.
- On any scorer bug: STOP and invalidate H2e.

## SHA-256
| Artifact | SHA-256 |
|---|---|
| `scripts/calib/scorer_v18.py` | `7a832f1be2641397aab097ab5df96ab77b66a38a0ff51a49361ccc27bd6d24c0` |
| `tests/unit/test_calib_scorer_v18.py` | `81e49fccfc59d6d845220ee20eb2938c7a683cc59741a5c702477db1b8611c81` |
| `data/calib/h1e_control_bank.json` | `49cf729c37bc4d733a511f59188d46150c5f4d91ba94bc55973c0265c3d060b7` |
| `scripts/calib/run_h1e.py` | `d7fb5c7cd0445fa70b2d6a13d9f260acf804da9dd89ef0816b4a84e72dd84307` |
| `data/calib/h1e_report.json` | `ab340e9bd1bb84cba8b0c70b91c6790703ab1cc83f7b92953e9dc70e22ef8c4e` |
| `docs/CALIBRATION-H1E-v1.md` | `ea6bf7a4bd3db6403a5aa87c6ee7f25baac7e4e758c941d524a4f82ddff28363` |
| `scripts/calib/fixtures_h2e.py` | `b27b0161fae550b7e62d306c8ce1332f8e18040c01db204981444010d5f52a8f` |
| `scripts/calib/h2e_scorer.py` | `656c211084f36f6eed15d234e1ade2febff1dcc6850a199a1a88316cc829826b` |
| `tests/unit/test_calib_h2e.py` | `31c1e6a4a1f6e00922714723f62024a582a025b4368a34b85265b66724514461` |
| `scripts/calib/run_h2e.py` | `8fe86253918ae9140caa55b3e0538c5ba95dcfbeee3709adfece33b9777e2d4c` |
| `scripts/calib/judge_h2e.py` | `900f08476ffb7260746f76f0fbbc5bb11715cfbce699f0c05cb32149cb6a36cc` |
| `data/calib/h2e_matrix_v1.json` | `adca293b84e60c5d3203e836076ebec133976510cfc0a988b1e139a76df61f95` |
| `data/calib/h2e_provider_manifest.json` | `ee35f06a137d9c2f96b4d491a1b2c51da824b11e0cd2e30af8391a34f570433b` |
| `docs/CALIBRATION-SEEDS-H2E-v1.md` | `d3e50dba720a636cabe7b667d6d99312258c1ce12e20e0a4136e960967f5598d` |
| `docs/CALIBRATION-MATRIX-H2E-v1.md` | `ba53113a21363982d7b62a975b91a168bd57adc7e807a97c154e813ebae40f5c` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `scripts/calib/runner.py` | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |
