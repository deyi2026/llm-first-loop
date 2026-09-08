---
name: method-candidate-ab-validity-trigger-confound
description: A/B qualification candidate distilled verbatim by Qwen3.8-27B from the working-set receipts teacher episode; experimental candidate only, not promoted.
status: candidate
source_model: qwen3.8-27b-mlx-8bit
---
# Qwen-authored candidate (verbatim)

FRICTION
- 首个 OFF 因环境缺 providers.json 走 unknown provider，属 invalid arm，不能参与 A/B 结论。
- ON 的 fold 到第 15 个大 read_file 才真实触发，前段与 OFF 行为近似，机制未早触发。
- elapsed/cache-hit 的 ON 是第二个 run，同物理模型且无安全 cache clear，存在 warm/order confound。

DISCRIMINATOR
- 有效 arm 判据：同 model/prompt SHA/tools/reasoning settings + 独立 session/data dir + 环境可解析 provider。
- 机制触发判据：必须观测到 fold 实际发生（folded_results 非空/达到阈值），而非仅配置开启。
- 收益判据：任务正确性（4/4、15/15）与收敛轮次/token 分开看；elapsed/cache 在 warm/order 未控时只作 observation。

SHORTEST_PATH
- 先做 arm 有效性预检（provider 可解析、配置 SHA 一致、独立目录），失败即标 invalid 不进入对比。
- 在 ON 侧埋点确认机制真实触发点（第几次 read 触发 fold、folded 数量），未触发则该 run 对机制无效。
- 对 elapsed/cache 类指标，要么做 cache clear/顺序平衡，要么降级为 observation，不用于 promotion 决策。

GENERAL_RULE
- A/B 结论前，先排除 invalid arm（环境/配置不可解析）与未触发机制的 run，再谈收益。
- 机制收益需“触发证据 + 任务正确性 + 收敛/成本”三者齐备；任一缺失则 mixed/不足 promotion。
- 时序相关指标（elapsed、cache-hit）在 warm/order 未受控时不得作为因果或 promotion 依据。

COUNTEREXAMPLE
- 若把首个 unknown-provider 的 OFF 当作有效基线，会高估 ON 的相对收益。
- 若只看 ON 配置开启就断言 fold 生效，会忽略前 14 次 read 未触发的空窗。
- 若把第二个 run 的 elapsed/cache 优势归因于 ON，会混入 warm/order confound。

METHOD CARD
- 名称：working-set receipts A/B 蒸馏
- 适用：验证某机制（如 fold）是否带来真实收益的 A/B
- 步骤：1) arm 预检（provider/SHA/独立目录）2) 埋点确认机制触发 3) 分维度判收益
- 判据：机制 PASS=触发证据；任务 PASS=正确性+可恢复性；收益=收敛/成本且无 confound
- 降级：elapsed/cache 未控 warm/order 时仅 observation
- 反例：invalid arm 入对比、未触发即断言、warm run 归因
- 产出：PASS/mixed/不足 promotion 三态结论，附触发点与 confound 说明
