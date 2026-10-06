# Pre-formal protocol amendment: Weak provider-qualified model ref

Time: 2026-10-06, before any formal row was reserved or executed.

The frozen physical Weak model remains exactly `cognilocal/qwen3.8-flash-next`.
The initial plan used bare `qwen3.8-flash-next` as the runtime reference. Real non-scored
preflight v3 proved that this legacy startup path attached the bare name to the DeepSeek
provider (`deepseek/qwen3.8-flash-next`) and received HTTP 400. The source contract in
`ProviderRegistry.resolve()` states that `provider/model` is the explicit cross-provider
selection form, while `build_engine()` uses registry provider parameters for a fully
qualified default model.

Therefore the runtime reference is corrected to the already-preregistered canonical model
`cognilocal/qwen3.8-flash-next`. This is a routing-identity repair, not a model substitution.
No formal efficacy row had been consumed; prior calls were preflight-only. The matrix order,
case set, treatment, statistical thresholds, safety gates, and cost gates are unchanged.
The plan/freeze hashes are regenerated before formal execution, and all four model×arm
preflights must pass in fresh v4 namespaces before row 1 may be reserved.
