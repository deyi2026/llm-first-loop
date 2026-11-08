---
method_id: guard-effectiveness-acceptance-live-replay-receipts-then-full-suite-91b68d5958fd
name: guard-effectiveness-acceptance-live-replay-receipts-then-full-suite
description: 当验收措辞要求证明闸/护栏『真的拦住』（应拦输入实测、护栏存在≠生效）且规格已枚举对抗输入矩阵时，唯一合格证据是逐行真实拒绝回执：起真实进程面（真实 server 子进程/端口/签名）重放每行输入并比对期望回执，而非凭进程内测试绿灯结项；同时把全量套件纳入验收谓词——首轮红名单正是产出（时区序列化、登记账本、长度上限等宿主约定只在全量暴露）。不可构造的行如实 N/A+理由。本集真实请求暴露 8 个 137 条进程内测试看不见的缺陷，全量首轮 exit=1 再暴露 4 类违规，全部修复后结项。
aliases: 拦没拦住要打真请求验证, 门禁生效别拿测试绿糊弄, 真服务起进程重放攻击样例, 子系统测试绿不等于护栏生效, 全量首红是收获不是事故
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:877:89ce45cbb8c30fef015a
evidence_refs: learning:learn:e8534a5ebd16
created_at: 2026-11-08T01:53:36.702661+08:00
updated_at: 2026-11-08T01:53:36.702661+08:00
---
## Trigger
验收/结项措辞要求证明闸、护栏或门禁『真的拦住/已生效』（如『应拦输入实测』、RULE-AI-35 式『护栏存在≠护栏生效』），且权威规格已枚举逐行对抗输入→期望拒绝回执→反例矩阵；现成交接只有进程内（mock/TestClient 级）测试绿灯。

## Discriminator
任务标题或规格小节已把验收谓词枚举成 N 行可判定条目，并明文要求真实构造的应拦输入跑过且拿到拒绝回执；同时既有测试回执（如 137 passed）全部是进程内级别。二者并置即排除『重跑子系统测试全绿即结项』，并预示宿主级违规只会在全量套件出现。

## Short path
- 从权威设计文档的验收矩阵（§9.x 表）提取逐行谓词：应拦输入→期望回执→反例，作为唯一结项合同
- 显式丢弃『只重跑 tests/<子系统> 全绿』捷径：进程内绿灯不在谓词覆盖内
- 起真实进程面（真实 server 子进程+真实端口+真实 HMAC/签名），逐行重放对抗输入并比对真实拒绝回执；只修真实请求暴露的问题
- 跑全量套件而非仅子系统目录：首轮红名单即产出（时区序列化/单元登记/持久化写入面/长度上限类宿主约定），修复后复跑到 exit 0 且 CI 门禁过
- 独立审查过闸；不可构造的矩阵行如实标 NOT_APPLICABLE 并写具体前提缺失理由，不用替身输入凑 PASS

## Stop conditions
- 矩阵每行均有真实拒绝回执，或带具体理由的 NOT_APPLICABLE
- 全量套件 exit 0 且 CI 门禁（lint/类型/测试/环境钉）通过
- 独立审查通过；未覆盖事项已在验收文档逐条写明理由

## Verification
- 每条『已生效』宣称能回指 harness 输出中的一对真实 request/response 回执
- NOT_APPLICABLE 行各有不可构造前提的具名说明（如无 blocked 生产者、TLS 未实现）

## Counterexamples
- 纯 happy-path 功能验收、无对抗输入枚举 → 子系统测试+定向集成足够，不必为仪式感起真进程 harness
- 某行前置在本环境不可构造 → 记 N/A+理由即可；伪造替身输入强凑 PASS 会使验收失真
- 纯库改动无进程/网络面 → 『真实面』退化为真实接线下的真实入口函数与真实鉴权栈，判据是真实调用链而非必须 spawn server
