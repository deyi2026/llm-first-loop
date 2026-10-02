---
method_id: no-identical-retry-after-deterministic-target-failure-b0198a230707
name: no-identical-retry-after-deterministic-target-failure
description: 当工具回执给出确定性、目标相关的失败（目录/文件/资源不存在、404、no-such-record），该回执本身就是权威证据：同参数重试的信息增益为零，必然复现同一失败。此时禁止原样重发调用；应先从失败目标中提取可搜索符号（文件名/类名/导入行），用一次窄搜索定位真实目标路径，再以修正后的参数重试。只有 transient 失败（timeout、限流、连接抖动）才允许有界的同参数重试。本集内同一缺失路径被原样读取两次后才转向 search_files，属于可完全避免的确定性浪费。
status: candidate
source_model: chatgpt-web/web-gpt
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:83:ba45570666756770f8f3
evidence_refs: learning:learn:5450556a9b47
created_at: 2026-10-01T22:58:36.315383+08:00
updated_at: 2026-10-01T22:58:36.315383+08:00
---
## Trigger
一次工具调用返回确定性、目标相关的失败回执（如『目录不存在 <path>』、404、no-such-record），失败归因于目标/参数本身而非临时状态，且后续仍需获取该目标内容。

## Discriminator
失败回执的类别在当时就已可见：回执明确写『目录不存在 src/llm_loop/factory.py』，是 deterministic not-exist 而非 transient timeout/限流。deterministic 类意味着同参数重发必然得到相同回执，下一跳必须改变至少一个变量——先用搜索定位真实目标，而不是复述已证伪的假设。

## Short path
- 失败回执到达后先分类：deterministic（not-exist / invalid-target / invalid-argument）还是 transient（timeout / 限流 / 连接抖动）。
- deterministic → 视为该假设已被证伪：不再重发同一调用；从回执中的目标字符串提取可搜索符号（文件名、类名、模块导入行）。
- 用一次内容/文件名窄搜索定位真实目标（例如从测试文件的 import 行直接得到定义模块路径），每次重试前明确它要解决哪个未知量。
- 以修正后的目标重试一次原读取；若再失败，回到分类步骤，并记录已排除的假设，禁止参数完全相同的第二次尝试。
- 取得目标内容并完成原任务后立即停止，不为『再确认』重复读取已完整展示过的内容区间。

## Stop conditions
- 同参数的 deterministic 失败绝不超过一次；紧随其后的调用必须至少改变一个参数或更换工具。
- 已通过权威来源（搜索命中的真实路径 + 成功读取回执）获得目标事实，转入下一步任务。
- 搜索无命中且无其他线索时，停止重试，向下游明确报告『目标不存在/未定位』，而不是继续枚举。

## Verification
- 检查 trace：任何 deterministic 失败回执之后，紧随的同工具调用参数必须与失败那次不同。
- 最终读取的文件路径必须可追溯到搜索命中或导入/引用边等证据，而不是未经验证的猜测路径。
- 确认没有对同一文件已完整展示过的行区间重复发起读取（利用回执中的 coverage/complete 字段）。

## Counterexamples
- 失败回执是 transient（timeout、rate limit、连接重置）：一次有界的同参数重试是合理的，本方法不适用。
- 写/创建类操作（mkdir、touch、create）：『目标不存在』正是操作的前置条件，不是被证伪的假设。
- 有意的参数枚举探针：每次尝试都在改变候选路径/参数——本方法只禁止参数完全相同的盲目重试，不禁止系统性枚举。
