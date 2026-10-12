---
name: method-self-distill-root-cause
description: Root Cause Method teacher exemplar。用于任务完成后，教模型怎样从真实根因事故中找“最早可区分事实”并压成可迁移诊断方法；样板来自 fresh CI 首次 wake 被 relative monotonic clock + 0.0 sentinel 错误限流的真实 LFL 事故。仅用于 Method 蒸馏实验，不是生产规则。
status: teacher
---
# Root Cause teacher: fresh-only throttle bug

学习目标不是记住 `_last_wakeup`，而是学会从“只在 fresh process 失败”这种差异事实迅速缩小根因空间。

## Real episode facts

- 长时间运行的开发机上 coordinate wakeup 正常。
- fresh CI / fresh process 中，第一次 coordinate wakeup 会被 rate limit；进程运行足够久后又正常。
- rate limit 使用 `time.monotonic()`。
- 初始化是 `_last_wakeup = 0.0`。
- gate 是 `now - _last_wakeup >= min_interval`。
- fresh process 的 monotonic uptime 可能小于 `min_interval`，因此 `now - 0 < interval`。
- 真实语义却是“从未 wake 过”的第一次应该允许。
- 修复语义：用显式 never-state（如 `None`），第一次无条件允许；只有真实 wake 后才记录 monotonic timestamp。

## Teacher distillation

**FRICTION**：如果先把它归咎于 CI 慢、线程调度、文件事件偶发或网络，搜索空间会变得很大；这些假设解释不了“只在 fresh process 的第一次失败、运行久了自动正常”。

**DISCRIMINATOR**：`fresh-only + age-dependent + relative monotonic clock` 是最早的高区分度事实。看到这个组合，应优先检查 throttle/debounce 的初始化状态，而不是先调重试。

**COUNTERFACTUAL**：
1. 固定现象：fresh first event blocked，old process works。
2. 找所有与 process age 相关的状态/clock。
3. 看到 relative clock + numeric zero sentinel，代入一个 fresh `now < interval` 的具体值。
4. 若“never happened”被计算成“刚发生在 t=0”，根因成立。
5. 用显式 never-state 做最小修复并加 low-monotonic regression。

**GENERALIZE**：当 throttle/debounce/cooldown 的行为只在 fresh process 初次事件异常时，优先检查是否把“从未发生”错误编码成 relative-clock 的数值时间点。把生命周期状态与时间值分开表示。

**FALSIFY**：若使用 `time.time()` wall-clock 且 `last=0` 的业务语义就是“1970 年发生过”，当前时间与 0 差值巨大，第一次不会被误限流；又或者产品明确要求“进程启动后先静默一个 interval”，则 fresh-first block 是预期，不应套用此方法。

## 小模型输出要求

只输出：
`FRICTION / DISCRIMINATOR / SHORTEST_PATH / GENERAL_RULE / COUNTEREXAMPLE`，然后一个紧凑 Method Card。
必须遵守 knowledge-at-time，不得使用后续才知道的修复作为早期证据。
