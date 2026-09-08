---
name: method-self-distill-ab
description: A/B qualification Method teacher exemplar。教模型从真实 working-set receipts Qwen A/B 中提炼实验纪律：先确认 arm 有效与机制真实触发，再分层裁决 mechanism/task benefit/promotion，并把 warm/order confound 从因果结论中剥离。仅用于 Method 蒸馏实验。
status: teacher
---
# A/B teacher: mechanism, benefit, promotion are different claims

## Real episode facts

- 目标：同一 Qwen3.8-27B、同 prompt/task/tool surface，比较 working-set receipts OFF vs ON。
- 第一次 OFF 隔离运行因为新的 DATA_DIR 没有 `providers.json`，在 `load_settings/build` 后走 unknown provider/不可用路径；该 run 被明确判 invalid 并排除，不与 ON 比较。
- 修正后两 arm 使用相同 provider registry、模型、prompt SHA、reasoning 设置；独立 session/data dir。
- ON 直到第 15 个大 `read_file` 后才真正触发 fold；这证明被测 mechanism 确实发生。
- OFF/ON 最终答案都 4/4 正确，Evidence exact recovery 都 15/15。
- ON 把 tool-result representation 大幅压缩，但模型随后主动发起 13 次 `read_evidence` 恢复；ON 比 OFF 多 1 round、13 个 recovery calls。
- tokens_in 有下降，但 elapsed/cache-hit 的 ON run 是第二个运行，物理模型/cache 没有安全清空，因此 warm/order effect 不能当强因果性能证据。

## Teacher distillation

**FRICTION**：如果只看“ON 更快/输入 token 更少”，会把顺序 warm cache 当成 feature 收益；如果只看“feature flag 开了”，又会把未触发的路径当成机制验证。

**DISCRIMINATOR**：实验首先要回答两个机械问题：arm 是否有效？被测 mechanism 是否真的触发？这两项不过，后续 performance/quality 比较没有归因意义。

**COUNTERFACTUAL**：
1. 冻结唯一自变量及 model/prompt/tools/runtime。
2. 验证每个 arm 没走 fallback/unknown-provider/配置缺失。
3. 用机制 telemetry 证明 candidate 路径真实触发。
4. 再看 correctness + structural behavior（rounds/tools/recovery/context）。
5. 对受运行顺序/warm state 影响的 elapsed/cache-hit 只记 observation。
6. 分开给出 Mechanism / Task Benefit / Promotion 三层 verdict。

**GENERALIZE**：A/B 的顺序是 `valid arm -> mechanism triggered -> task outcome/structure -> performance limitations -> promotion`。不要从“flag=ON”直接跳到“机制有效”，也不要从单次更快直接跳到 promotion。

**FALSIFY**：若是纯确定性单元测试，没有 warm/cache/模型方差，且测试直接覆盖目标分支，就不需要套完整的 real-model A/B 隔离流程；用更便宜的 deterministic gate 即可。

## 小模型输出要求

只输出：`FRICTION / DISCRIMINATOR / SHORTEST_PATH / GENERAL_RULE / COUNTEREXAMPLE` + Method Card。必须保留三层裁决：mechanism / task benefit / promotion。
