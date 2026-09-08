---
name: method-candidate-relative-clock-never-state
method_id: method-candidate-relative-clock-never-state
description: Root Cause candidate distilled verbatim by Qwen3.8-27B from the fresh-process relative-clock sentinel teacher episode; experimental candidate only, not promoted.
status: candidate
source_model: qwen3.8-27b-mlx-8bit
---
# Qwen-authored candidate (verbatim)

FRICTION
- 症状间歇且与环境相关（fresh CI / fresh process 的第一次事件），最初把怀疑引向 transport / 消息发现层。
- transport 与发现均验证正常，失败仍复现——真正的摩擦点是一个"看起来无害"的默认值：状态用 numeric zero 初始化，且只在进程时钟读数小于 interval 时才出错。
- 初始值 0.0 是"自然默认"，不显眼，因此被排除在嫌疑之外。

DISCRIMINATOR
- 同一代码路径在长运行进程正常、在 fresh 进程首次事件失败 → 变量是进程年龄/时钟读数，而非消息内容、transport 或 CI 环境本身。
- gate 形式为 now - last >= interval，时钟是相对 monotonic（进程内从 0 附近起算），而 last 初始化为该时钟域内的合法值 0.0 → "从未 wake" 与 "t=0 刚 wake" 不可区分。
- 这一条把根因与 transport/发现/环境类假设干净分开。

SHORTEST_PATH
1. 先排除症状指向的层：确认 transport/发现健康，把失败定位到抑制事件的 gate。
2. 读 gate 的两件事：时钟基准（相对 vs 绝对）+ 状态初始化值。
3. 问：初始状态是否是时钟域内的合法值？相对时钟从 0 附近起算且哨兵为 0 时，首次事件会被当成"刚发生过"。
4. 用边界验证：fresh now < interval → 被抑制；长运行 now > interval → 通过。与观察完全吻合即收口。

GENERAL_RULE
- 任何基于相对时钟（monotonic / 进程 uptime）的"每 interval 至多一次"gate，"从未发生"必须用域外显式哨兵（如 None）编码，不能用 numeric zero。
- 形如 now - last >= interval 且 last := 0 的 gate，必然在 now < interval 时抑制首次事件。
- 时间戳只应在真实事件通过 gate 之后记录。

COUNTEREXAMPLE
- 若时钟是绝对时钟（epoch / wall clock），0 远在過去，首次事件不会被抑制——规则不适用，"修复"是多余的。
- 若首次事件本就该被抑制（设计上的 warmup / 宽限期），则观察到的行为是正确语义，问题是对意图的误读，不是状态编码错误。
- 用 -1 或极大数当哨兵仍是域内数值，可能再次误判——哨兵必须是类型层面的"缺席"，不是另一个数。

METHOD CARD
- 名称：relative-clock zero-sentinel（根因模式）
- 触发：事件只在 fresh process / fresh 环境的首次出现被限流或抑制，之后正常。
- 步骤：
  1. 验证症状指向的传输/发现层健康，把失败收敛到 gate。
  2. 读 gate：时钟基准 + 状态初始化。
  3. 检验"never"状态是否可被表示为该时钟域内的真实时间戳。
  4. 修复：显式 never 哨兵（None）；首次放行；真实通过后才记录时间戳。
- 不变量："从未发生"在时钟域内不可表示。
- 陷阱：规则绑定的是"时钟域 + 哨兵编码"，不是任何具体 limiter、标识符或数值；绝对时钟与"首次本应抑制"两种情形下不得套用。
