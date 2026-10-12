---
method_id: version-field-inert-until-a-consumer-enforces-it-aa27e025967b
name: version-field-inert-until-a-consumer-enforces-it
description: 新增 version/cohort 字段并声称完成数据分代（'不再混算'）时，分代只有在至少一个消费方按该字段过滤时才真实存在。用字段/常量名做一次全引用面搜索即可判定：命中仅限生产模块的定义+写点、消费/聚合模块 0 读取点 ⇒ 分代只是纸面完成。补最小消费侧隔离：按当前版本常量整行纳入/排除、暴露 cohort 计数 diagnostics、当前代次样本不足时如实 N/A；并把文档/changelog 声称收敛到已实现范围。实现前查一次 import 方向，无环则直接 import 常量，不为抽象而抽象。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:393:fa32bd75e5f430f3cd31
evidence_refs: learning:learn:25974b208fe6
created_at: 2026-09-30T09:56:39.741258+08:00
updated_at: 2026-09-30T09:56:39.741258+08:00
---
## Trigger
刚在写入侧（审计/日志/schema record）新增 version/cohort/provenance 字段，或复查这类分代合同是否真实生效；尤其是 changelog/文档已出现'不再混算/已隔离'类表述时。

## Discriminator
字段/常量名全引用面搜索的结果形态：命中只有生产模块内常量定义与写点（episode 中 VALIDATOR_VERSION 仅 validator.py:90 定义 + :563 审计写入 2 条），消费侧 0 读取点 ⇒ 写侧字段惰性，隔离未被执行；出现 ≥1 个消费方按字段过滤则合同完整。

## Short path
- 定位字段写点（生产模块的定义与落盘处）
- 用字段/常量名做一次全引用面搜索，区分'写点'与'读取点'
- 若 0 读取点：先做一次 import 方向检查（无环则消费方直接 import 当前版本常量，否则注入），在聚合入口按字段整行分桶——当前代次进指标，legacy/他代次整行排除
- 补 cohort 计数 diagnostics（窗口行/当前代次行/排除行/来源版本分布），当前代次样本不足时返回 N/A 而非用混合样本填充
- 把文档/changelog 声称改到与已实现一致；focused tests 全绿后才进入被该修复门控的下一步（重启/上线）

## Stop conditions
- 引用面搜索显示已有消费方按该字段过滤且 diagnostics 暴露 cohort 构成 ⇒ 分代已生效，停止
- 字段是设计上的 telemetry-only 且文档如实标注'不改变决策' ⇒ 无需消费方，停止
- 核查后声称与实现一致 ⇒ 只需保持，无需改动

## Verification
- 重跑字段名引用面搜索：读取点现在出现在消费/聚合代码路径中，而非仅写点
- 存在 focused test 证明携带旧版本（或缺字段）的行即使含有效声明也不进当前 cohort 聚合
- 文档中不存在超出已实现行为的分代/隔离表述

## Counterexamples
- 字段本就是纯观测 telemetry（如 cross_round_eligible / session_untracked 计数），设计上明确不改变决策——强行造消费方是过度工程
- 消费方在搜索树之外（外部 BI/离线脚本）——仓内 0 读取点不等于字段惰性，先确认预期消费方清单再下结论
- 指标对 cohort 混合天然不敏感（纯计数、无率值/归因）——此时隔离是可选项，文档如实写'未隔离'即可
