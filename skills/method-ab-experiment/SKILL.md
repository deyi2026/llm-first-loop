---
name: method-ab-experiment
description: 设计或审查模型、Agent、缓存、上下文、工具策略、runtime 优化的 A/B/qualification 实验时使用。用于锁唯一自变量、隔离 cache/session/evidence/model residency 等跨 run 状态、确认机制真正触发，并把“机制生效”“任务收益”“可推广/可发布”分层裁决；特别适合本地模型和长 Agent benchmark。简单确定性单测不需要加载。
---
# A/B Experiment Qualification

目标是获得可归因结论，不是让两组“都跑一次”。任何不能隔离的状态都应成为结论限制，而不是被忽略。

## 开始前先回答

1. 唯一自变量是什么？能否用一句话写清？
2. 除它之外，模型、prompt、tool schema、任务、runtime、参数、数据是否真的相同？
3. 哪些状态可能跨 run 泄漏：prompt cache、KV/cache residency、session、Evidence、文件、provider client、进程热身？
4. 哪些指标属于正确性、哪些属于结构效率、哪些受顺序影响只能观察？
5. 样本如何证明被测机制真的发生过？

## 实验前冻结

记录至少这些事实：

- exact model/provider；
- prompt/task 的可比标识；
- reasoning/temperature/max_tokens 等关键生成参数；
- 工具面及 schema 数量/版本；
- 数据目录/session 隔离方式；
- 服务进程与模型 residency；
- 被测 feature 的精确开关和值；
- 不能清除或不能随机化的共享状态。

不要为了“公平”而同时加载两个本地大模型；若机器资源会互相干扰，应顺序测试并把顺序效应写入限制。

## 默认路径

1. 建立 OFF/baseline，并确认任务能正常运行。
2. 建立 ON/candidate，只改变目标变量。
3. 在共同分叉点之前检查两组输入与行为是否保持同构；若早已不同，先解释差异来源。
4. 确认 ON 组确实触发目标机制，而不是 feature 开着但路径从未命中。
5. 收集结构指标和最终任务结果。
6. 对不可隔离的 warm cache/顺序效应，避免把 elapsed/cache-hit 单独当因果证据。
7. 加至少一个反例或 adversarial case，检查方法没有只适配主 benchmark。

## 指标分层

### 正确性

- 最终答案/任务验收；
- exact source/evidence recovery；
- 工具副作用是否正确；
- 是否出现新错误或遗漏。

### 行为结构

- rounds；
- tool calls / unique calls / duplicates；
- 无信息增量重复动作；
- recovery/hydration 次数；
- post-sufficiency extra rounds；
- provider-visible chars / tokens_in / prefill。

### 只能谨慎观察

- wall-clock elapsed；
- cache hit ratio；
- 首轮/后轮速度；
- 受模型 warm residency、OS 调度、共享 cache 影响的性能数值。

这些指标若未做随机顺序、冷启动或独立进程控制，不应独自支持强因果结论。

## 三层裁决

实验结束必须分开回答：

1. **Mechanism**：机制是否按设计真实触发？
2. **Task benefit**：触发后是否改善任务正确性或行为效率？
3. **Promotion**：证据是否足以推广到默认路径/公开 claim？

`Mechanism PASS` 不自动推出 `Task benefit PASS`；单个任务收益也不自动推出 promotion。

## 反例设计

至少选择一种与主样本不同的情况：

- 主样本需要 heavy path，反例只需 simple path；
- 主样本事实位于 head，反例把关键事实放 middle/tail；
- 主样本机制一定触发，反例故意保持在阈值以下；
- 主样本是长 Agent，反例是短任务，检查优化是否制造额外税。

## 停止/重做条件

以下情况不要继续解释结果，应先重做实验：

- A/B 实际用了不同模型或 prompt；
- 数据目录缺配置导致一组走 fallback；
- 被测机制根本未触发；
- 同时改变了多个关键变量且无法拆分贡献；
- 一组出现与实验无关的基础设施失败；
- 比较指标的统计口径不同。

## 反模式

- “ON 更快，所以机制更好”，但 ON 是第二个 warm run；
- feature flag 打开就视为机制已验证；
- 只测一个专门为方案设计的 happy path；
- 模型、prompt、tool schema 中有一项偷偷漂移；
- 把 cache hit、elapsed 的顺序效应包装成确定因果；
- 为得到好结果临时加入 prompt-visible completion hint，导致实验测的是另一件事。

## 方法边界

本方法提供实验纪律，不替模型决定哪些指标最重要，也不预设 ON 必须胜出。负结果同样是有效结论；发现 candidate 增加恢复税、固定偏差或收敛问题时，应如实 HOLD。

## 可沉淀内容

具体 run 数据属于 Evidence；一次实验结论进入 Experience/报告；多次都稳定成立的实验设计原则才进入 Method。可重复的采样脚本可进入 benchmark/Skill，但不要把语义裁决写进脚本。

来源：`docs/local/METHOD-PLAYBOOK-v0.1.md` §7；最近 working-set receipts Qwen A/B 为主要实证样本。
