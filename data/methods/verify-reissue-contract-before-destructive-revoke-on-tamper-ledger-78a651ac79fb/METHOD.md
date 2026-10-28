---
method_id: verify-reissue-contract-before-destructive-revoke-on-tamper-ledger-78a651ac79fb
name: verify-reissue-contract-before-destructive-revoke-on-tamper-ledger
description: 防篡改账本上的『撤销再重签』不是 undo 循环：当记录载荷在签发后被改过，同 id 重签常被反篡改规则禁止，revoke 因此成为单向门，会把『坏但 fail-closed』状态进一步降级为『已撤销』。正确顺序：先定点读账本/授权模块的 revoke 与 reauthorize 契约（错误字面量+docstring），判定就地修复可行性；不可行则不动状态，核对失效态是否在 claim 阶段即被拒（无静默错执行），再如实上报并给出新 id 合规重建（含真人签发通道）选项。
status: active
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:1635:c342667f8d00f2e3c5e5
evidence_refs: learning:learn:6094280dd956
created_at: 2026-10-19T11:15:46.873595+08:00
updated_at: 2026-10-19T12:27:57.719923+08:00
---
## Trigger
对受签名/防篡改授权账本保护的持久化记录（schedule 授权、凭证、票据类）执行『先撤销再就地重签』式修复，且已知失败签名同时包含：账本侧仍登记授权（如 already has a grant 类字面量）与记录载荷在签发后被改（authority/signature invalid、新 schema 字段被剥离）

## Discriminator
执行 revoke 前即可获得的两条事实：(a) 失败字面量 already has a wake grant + authority_state=invalid 表明『账本有授权但载荷与签名不符』——正是防篡改设计要拒绝的状态；(b) 仓库内授权模块（含 Pre-upgrade services rewrite… 注释与 altered wake cannot be reauthorized 类规则）可一次定点读取，直接回答『此状态下同 id 重签是否被允许』。未读该契约就先撤销，等于在未验证后半步可行的前提下踩下单向门。

## Short path
- 1. 从守护日志与权威文件确认失败签名：账本侧已有授权 + 磁盘载荷签发后被改（新字段被剥离、authority invalid）。未知量：就地修复是否可能？
- 2. 定点读取授权/账本模块的 revoke 与 reauthorize 契约（错误字面量、payload-hash 绑定规则）。未知量：撤销后半步（同 id 重签）是否被契约允许？
- 3. 若契约禁止 altered 后重签：判定 revoke 是单向门、就地修复不可行；不发出任何撤销/重签调用，状态保持原样。
- 4. 核对当前失效态是否 fail-closed（claim/consume 阶段抛错即拒）——是则无『本该跑却没跑』的静默错执行，修复紧迫度降级为合规重建问题。
- 5. 如实上报现状与两条路径（真人签发新 id 重建 / 显式例外授权），停止等待用户决策。

## Stop conditions
- 已读到再授权契约并据此明确判定就地修复可行或不可行
- 确认未对记录发出任何未通过契约验证的不可逆调用
- 用户所需决策（合规重建 vs 例外授权）已连同现状证据一并上报

## Verification
- 报告中的每个状态断言（schema 字段缺失清单、authority_state、账本 revoked/invalid）与权威文件和账本当前读数一致
- 若选择不动状态：回查调用记录确认零次 revoke/upgrade 发出
- 若后续经合规通道重建：新 sid 的签名与账本记录一致，旧条目按声明处置

## Counterexamples
- 账本未把授权绑定到载荷哈希、revoke→重签是文档支持的标准运维循环——先读契约是多余步骤，直接修复
- 修复是纯增量动作（补缺失字段、不触碰授权与签名）——无破坏性半步，不需要此检查
- 存在原子性 recreate API 在同一事务内完成撤销+新签——单向门不成立
- 契约在早前回执中已完整读过且明确允许 altered 后重签——无需重复验证
