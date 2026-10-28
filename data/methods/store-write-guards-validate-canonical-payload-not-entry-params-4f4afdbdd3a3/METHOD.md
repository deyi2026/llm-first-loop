---
method_id: store-write-guards-validate-canonical-payload-not-entry-params-4f4afdbdd3a3
name: store-write-guards-validate-canonical-payload-not-entry-params
description: 给持久化 store 实现 fail-closed 内容禁写门（防 task_id/题面/secret 落盘）时，校验点必须放在序列化后的 canonical 载荷与最终返回行，而不是各写入口的主参数：每个最终落盘的自由文本字段（aliases/note/refs/recent_issue 类）都是等价写通道，逐 API 设门必然漏旁路。配套纪律：先枚举全部持久化字符串字段确定『写入通道全集』，用真实禁写 token 做定向注入自测；读侧检索通道单独 fail-open+计数，不与写侧共用 fail-closed。
aliases: 防泄漏门该校验哪里, 禁写token自由文本旁路, 知识库写入门全字段枚举, heldout题面泄漏方法库, 写门漏字段返工
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:c5f52ba4-0dd0-440d-ab8e-d4b02bb2ed41:102:9e989d3b529a251ce0be
evidence_refs: learning:learn:6ab2fc255a9a
created_at: 2026-10-25T12:04:39.356612+08:00
updated_at: 2026-10-25T12:04:39.356612+08:00
---
## Trigger
需要给持久化知识/数据 store 实现『特定 token 禁止经任何路径落盘』的写侧门（held-out 隔离、防题面泄漏、secret/PII 拦截），或写门已按写入口逐个设校验、需评估旁路覆盖面时

## Discriminator
store 的序列化 schema 中除主字段外还存在多条最终落盘且可被检索的自由文本字段（本集：aliases、freshness_refs、record_use.note、recent_issue 四条）——store 源码本身（alias 参与检索判定的代码）在当时就已表明这些字段会进入持久化载荷；按写 API 主参数设门时它们不经过校验，对抗审核用真实 task_id 即可复现泄漏

## Short path
- 实现前先枚举最终落盘 schema 的全部字符串/数组字段（含 metadata 与自由文本），把『写入通道全集』当作第一未知量
- 把校验点放在序列化后的 canonical 载荷与最终返回行上：命中禁写 token 即抛错、零落盘
- 用真实禁写 token 对每条自由文本字段做定向注入自测，复现即修，直到全部字段拦截
- 读侧/检索命中污染行单独处理：fail-open + 丢弃计数 + 无正文日志，不与写侧共用 fail-closed
- 后续审核轮只问『还有哪些字段会落盘』，不再重复验证已收敛的写入口

## Stop conditions
- 真实禁写 token 注入全部持久化字段均被拦截且落盘文件零变更
- canonical 载荷与最终返回行经过同一校验器，无中间表示直通

## Verification
- 定向注入测试：对每条自由文本字段写入真实禁写 token，断言抛错且文件内容不变
- 对既有库存量做误报扫描：正常内容 blocked=0，门不阻塞合法写入

## Counterexamples
- store 字段全为枚举/结构化、无自由文本时，主字段校验即已覆盖，无需全字段扫描
- 校验请求参数或中间表示而非最终载荷：写入 hook、字段合并、并发旧写者会在校验之后改写落盘内容
- 读侧检索通道不能照搬写侧 fail-closed：单行污染会摧毁整个检索可用性，应丢弃+计数+可见日志
