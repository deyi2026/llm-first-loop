---
method_id: contract-misreading-repair-align-official-evidence-protect-frozen-surfac-9071ef2074eb
name: contract-misreading-repair-align-official-evidence-protect-frozen-surfaces
description: 修复'实现误读外部协议字段、而 Mock/fixture 与实现同源误读导致测试全绿'的一类 bug：以独立于实现的官方契约证据为唯一真值；用错误字面量全仓 grep 枚举完整耦合面（含包外 runner/mock/测试助手）；TDD 先红后绿；被冻结的判定面（cases/labels）必须逐字节不变并用 manifest 重冻哈希证明零漂移；单次外发失败路径补 raw/answers 摘录持久化，使协议失败离线可诊断、无需再消耗外发预算。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d1e343a5-0eb5-4b62-b607-a8cd333ed256:733:9618c59ff22503e4b831
evidence_refs: learning:learn:13d5c295754f
created_at: 2026-10-15T13:24:39.726631+08:00
updated_at: 2026-10-15T13:24:39.726631+08:00
---
## Trigger
修复一个外部协议契约误读（如响应字段名），且历史记录显示测试/Mock/fixture 因与实现共享同一误读而曾全绿；典型发生在首次真实外发批量 contract_invalid 之后。

## Discriminator
修复开始时已存在的判别事实：设计/治理文档已记录（a）官方字段名的独立证据来源，（b）实现自某版本起误读，（c）Mock/fixture 共享误读故测试全绿，（d）raw 未留档致失败不可恢复。这四条各映射一个必需修复动作，把'重新发现契约'缩成'对齐已知官方事实 + grep 错误字面量全部出现点 + 哈希保护冻结面 + 失败留档'，无需宽泛探索。

## Short path
- 读当前验证器代码，确认误读字面量（如 raw.get("answer")）真实存在于判定路径
- 以该错误字面量做全仓 grep（src/tests/fixtures/包外脚本/mock 构造处），得到完整耦合面清单，而不是逐文件试探
- 核对契约真值来自独立官方证据（文档引用的官方 wire 事实），而非实现派生物；文档正确则修实现回文档
- TDD：测试助手与 fixture 先改官方字段名得 RED，再改三处验证器至 GREEN
- 重冻 manifest：变更的支撑样本（wire_examples）换新哈希；被判定面（cases/labels）哈希必须不变，证明判定口径零变更
- 为单次外发的失败路径补 answers 原文摘录持久化（cap 限长），消除'raw 丢弃即不可诊断'
- 过代码闸并在任何真实外发前完成新一轮预注册冻结，随后执行与对账

## Stop conditions
- 错误字面量全仓 grep 归零，定向测试全绿
- manifest 校验通过且被判定面哈希逐字节不变
- 官方契约事实与实现一致，失败路径留档机制有测试钉住

## Verification
- 重跑 fixture 冻结校验：变更文件得新哈希、cases/labels 保持旧哈希
- Mock dry-run 与真实外发响应均 schema-valid，resolved 落在预注册合法集
- 构造一条无效响应单测，确认事件中可查到 answers 摘录（失败可离线诊断）

## Counterexamples
- fixture 源自真实抓取的官方响应（独立来源）——此时 fixture 即真值，应改实现迁就 fixture，而非把 fixture 同步到实现
- 内部自有 schema 无外部对手方——不存在更高权威的'官方证据'，设计文档本身即契约，且无外发预算约束
- 无冻结判定面/无盲评资产的普通 bugfix——manifest 重冻与判定面哈希保护步骤不适用，直接修测即可
