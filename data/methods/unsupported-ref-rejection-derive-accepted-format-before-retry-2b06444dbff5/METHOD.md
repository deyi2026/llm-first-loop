---
method_id: unsupported-ref-rejection-derive-accepted-format-before-retry-2b06444dbff5
name: unsupported-ref-rejection-derive-accepted-format-before-retry
description: 收口/准入闸拒绝自报引用（evidence_refs）且回执同时给出粗 reason_code（evidence_below_threshold）与细 status（unsupported_ref）时，细 status 才定位差分层：unsupported/invalid 类表示引用的字面格式/身份不在接受值域，重试前先解决『闸接受什么格式』——grep 细 status 定位仓内校验器读解析合同，或调权威实例清单工具（list_evidence）取合法样例，逐字复制重发；不要基于自拟变体（混文件路径等）盲试第二次。与『命名缺失字段→上下文取值重发』互补：本卡用于值域错误且上下文无现成合法值的场合。
aliases: 证据门引用格式不对怎么过, 收口时证据引用不被接受, 重试前先查闸接受什么格式, 证据引用混了文件路径被拒, 终局证据门卡住先读校验器
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1a7bb31d-f3da-497f-9322-336483f4435a:536:0ec405f910b20addcd21
evidence_refs: learning:learn:3aea800dbbcf
created_at: 2026-11-14T12:52:10.629056+08:00
updated_at: 2026-11-14T12:52:10.629056+08:00
---
## Trigger
带自报引用字段（如 evidence_refs）的收口/准入闸第一次拒绝，回执含指向引用本身不被支持的命名细 status（unsupported_ref/invalid_ref 类），且当前仓库可 grep 到校验器实现或环境存在权威实例清单工具

## Discriminator
细 status 是 unsupported_ref 而非 insufficient/coverage 类——差分在引用的字面格式/身份，不在证据数量或强度；此时任何自拟变体（继续混入文件路径）必然重复同类失败，合法值只能来自校验器合同或权威清单（样例形如 evidence://v1/<hash>）

## Short path
- 被拒后第一步用细 status 定位合同：grep 细 status → 读校验器解析函数（如 EvidenceRef 仅接受 evidence://），或直接调权威清单工具 list_evidence 取合法样例
- 从清单逐字复制与待证事实对应的合法引用（push 回执、ls-remote 核实、审查 PASS 各一条）
- 用纯合法格式引用重发同一名义动作；闸通过即停，不追加多余确认

## Stop conditions
- 重发后闸返回通过（如 goal → complete）
- 读合同后发现本会话确实不存在所需类型的合法引用 → 走人工 waive/升级出口，不再构造自拟引用

## Verification
- 重发载荷中每条 ref 都能在权威清单中逐字找到
- 细 status 消失；若新拒绝变为覆盖/数量类，说明格式层已解决，转入证据量问题而非继续改格式

## Counterexamples
- status 为 insufficient/coverage 类（引用解析成功但证据不足）：读格式合同无收益，应补更强证据或请人工 waive
- reason 是命名缺失字段且任务上下文已有合用取值：直接按『rejection-as-contract-diff 重发』即可，无需源码考古
- 校验器为外部闭源服务且无实例清单工具：允许一次有界变体重试后即升级，不做实现考古
