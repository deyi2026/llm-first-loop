# Browser SMC A/B v0.2 execution — INVALID

Status: **INVALID_CONTROLLER_TIMEOUT**. This execution is diagnostic evidence only and is not a formal six-row smoke result.

The first five rows completed and were durably written. The sixth row (`delayed_wait / smc`) had already made real model/tool progress when the outer MCP command reached its 600-second controller limit. The worker was terminated before it produced a terminal `worker-result.json`, so the row cannot be classified by the frozen benchmark contract.

The incomplete row is **not retried and substituted into the same smoke**. It had already consumed provider/cache state and produced Browser perception/receipt state, so treating a second attempt as the original fresh row would bias the evidence.

The complete raw execution directory, including the partial sixth-row `.lfldata` and Chrome profile, is retained outside the tracked repository. The tracked JSON companion records only privacy-safe diagnostic facts.

v0.3 changes only the execution controller: each runner invocation is bounded to a frozen number of new rows (formal execution uses one). Tasks, arms, Browser runtime, model/provider parameters, external oracles, and the smoke expansion gate are not tuned from the v0.2 observations.
