# M1-SIM-003 DeepSeek switch — implementation receipt

**State: SOURCE READY; HOST REFRESH NOT YET APPLIED; PAIRED 0/60; HOLD.**

The operator approved changing the M1 B1/B2 experiment to
`deepseek/deepseek-v4-flash` on 2026-11-20. The previously frozen
`M1-SIM-002` GLM preregistration and all GLM evidence remain immutable.
Changing the model requires the separate `M1-SIM-003` experiment identity.

- New frozen prereg: `experiments/embodied/prereg-m1-sim-003.json`;
  SHA-256 `d77a2550b17c71630bee1bdaddaf733cc240ac3bb67c662837d4f5f3b3f163d6`.
- DeepSeek official docs state the legacy request alias `deepseek-v4-flash`
  currently serves `deepseek-flash` (V4.1-Flash-1017). The actual response
  model must be recorded and any other response identity must fail closed.
  https://api-docs.deepseek.com/quick/_start/pricing/
- Existing LFL DeepSeek credential and `https://api.deepseek.com/v1` route
  were verified without displaying or copying the secret. A real, bounded
  `deepseek-v4-flash` probe returned HTTP 200, response model
  `deepseek-flash`, 37 input + 13 output = 50 tokens, 0.59 s.
- One real M1 **model-only** policy probe (no Host actions) returned a valid
  `move_to` decision, 1,259 tokens, 1.59 s, response model
  `deepseek-flash`. This is **not** an L3 grasp/place acceptance.
- Official DeepSeek peak tariff: USD 0.30 per 1M uncached input and USD 1.20
  per 1M output tokens; off-peak rates are lower. Cache discounts are ignored
  for the conservative USD budget estimate.
  https://api-docs.deepseek.com/quick_start/pricing/
- Approved ceilings remain **USD 20 total**, **USD 0.05 per-call reservation**,
  **60 episodes / 360 Provider attempts / 480 tool actions**.
- New source supports both frozen Host experiment IDs, requires independent
  signed Oracle trial binding, and includes a root-only, manifest-pinned
  v2-bundle refresh with rollback to the old Host on failure.
- No root Host bundle refresh, new batch grant, formal B1/B2 trial, GitHub
  merge or unified deployment has been executed for M1-SIM-003.

**Next gates:** freeze and test the precise source SHA; build a clean offline
Host bundle and independently verify the manifest; obtain narrowly scoped
Host-only refresh approval; execute one M1-SIM-003 engineering L3 failure/
recovery smoke with both grasp and place `VERIFIED_BY_ORACLE`; independently
install/verify the USD grant; then request a **separate approval** to start
the 30 B1/B2 pairs. Final Reviewer → full R9 → CI → protected `main` →
unified deployment remains after the paired evidence is complete.
