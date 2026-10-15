# Learning f7c isolated integration: independent GLM-5.3 and native Full R9
Sampled 2026-10-16T07:26:27+08:00
- Fixed main base: f7c0812825807d6dec2a2ad6e835899766229c40
- Behavior source: 672c1e3b6437f589b51b249fcc78c6c0f4753929
- Isolated branch: fix/learning-source-deleted-f7c-integration-20261016
- Two-file Git binary patch 5550 bytes, SHA256 925e453fd5baf1632eaa305134a47b2b198762dc26af8b0d222d1bec50981e89

## Provider-free targeted / quick
- 16 targeted files: 221 passed, zero failed, one warning; raw SHA256 9f39b904ad6d4b053cd38054696ba662fa6c57c3068382cc8adc9674314a67af
- Native unmodified Quick exit0; 319 passed, 8895 deselected, 3 warnings; raw SHA256 c367dea73dc0f37d90542e385b85a4a33a535c7a5b6fd66363ae56a59d18cdbb
- Ruff/EnvPin867/Pyright/WebUI build PASS; Quick alone is not full qualification.

## One real independent GLM-5.3 Reviewer
- Child subagent_81ac3cf3a6de real live terminal event 144d6b16-2844-4ae1-9574-ae191c3402b4 (exactly one); reviewer had zero tools and one round, no retry.
- PASS P0=0 P1=0 P2=2. Nonblocking P2: manual outer-failure handler simulation and missing direct foreground/deletion-race test.
- Original reviewer JSON SHA256 a50e91aaac808edc9c72ceffb38b542953c62c8174bdf64e3edb4b658731f736, runner log SHA256 5d0008e3788a2c0dd0386070e4f91439216124421d97e92ee68f383a4fde2d0e.

## Original unchanged complete R9
- Native bash scripts/ci_gate.sh physical exit0; original script SHA256 174a541d40e5d1fcb32849bffd178bf63a8c08b0c535caa898f452059683e17e
- Ruff/EnvPin/Pyright/WebUI build PASS; tier0 319passed/8895deselected.
- First xdist all green: 9057 passed, 141 skipped, zero failed, 13 warnings, 4 workers, 189.01 seconds. No D-B2-09 serial fallback was needed.
- Final architecture guard 1 passed, 29 deselected.
- Original raw full log 91839 bytes SHA256 e9e7b05f355b9cb163c589d04a82ba802b777cb598866faf4abbc3c50c8a4f74.
- Provider variables unset; Python-only offline network guard SHA256 a66fd43421b2f3232bbd5b7960339ea3e988c6c47aa8a442283a9ae110866961.
- Exactly 18 self-owned test-generated tracked reports saved as ignored binary patch SHA256 9c20ace1187584b8d335d1bde0c1bf5eebbc7e5768b59ecc291dc8128a76aac5, and restored only in this independent worktree. Exact source SHA remains unchanged.

Formal receipts: docs/governance/receipts/RECEIPT-20261016-learning-source-deleted-f7c-independent-glm53.json and docs/governance/receipts/RECEIPT-20261016-learning-source-deleted-f7c-full-r9.json.
Source, formal receipts and this summary live only on independent branch. Raw logs remain in private ignored worktree data.
This PASS is bound to f7c base and 672c behavior source. Before a local main merge, recheck latest main SHA/cleanliness/concurrency/three-way delta and seek explicit separate merge approval. No merge, push, release or restart.
