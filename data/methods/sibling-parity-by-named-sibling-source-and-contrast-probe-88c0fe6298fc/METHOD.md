---
method_id: sibling-parity-by-named-sibling-source-and-contrast-probe-88c0fe6298fc
name: sibling-parity-by-named-sibling-source-and-contrast-probe
description: 『与 sibling X 同口径/对齐』类审查意见的真值面是被点名 X 的源码与统一挂载点，不是意见措辞、也不是另一模块的相似用法：X 若只靠 include_router 的共享 guard，本地再加内层鉴权就是双重 guard 回归。诊断面同理——同进程内兄弟端点在相同无凭据请求下 200/401 分叉，第一假设是内层重复检查，而非策略收紧或部署未生效。
aliases: 同口径意见怎么落地, 对齐兄弟路由先读谁, 一个接口401一个200, handler里又查了一遍鉴权, 实现审查意见过了头, 前端不带凭据拿401
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d0e6ba0c-dfdb-4a7e-b110-850f0ae238a6:824:b8f03615f855f28535b3
evidence_refs: learning:learn:0c44989dc5a7
created_at: 2026-11-05T12:23:30.546788+08:00
updated_at: 2026-11-05T12:23:30.546788+08:00
---
## Trigger
收到或遵循『与 sibling/兄弟模块同口径、保持一致』类审查意见要落码时；或同一进程内兄弟端点在相同无凭据请求下 auth 判定分叉（一 200 一 401）且真实前端/消费方不带凭据时

## Discriminator
指令或代码注释点名了具体 sibling，其源码可直读并一步回答『X 的口径 = handler 内自检，还是只依赖统一挂载的 guard』；同条件无凭据对照探针的状态码分叉，把候选解释从『策略收紧 / 部署未生效 / 路径不对』缩成『多出的那层 guard 在哪』

## Short path
- 直读被点名 sibling 的 router/handler 与统一挂载点（include_router 的 dependencies），回答『X 的口径是自检还是只靠外层共享 guard』
- 按最小差异实现 parity：若 X 无内层检查则不加/删除内层检查，不照搬其他模块的相似用法
- 用与真实前端同构的无凭据请求对照探测目标路由与 sibling 路由各一次
- 状态码一致即收口；仍分叉则回到第一步定位多出的那一层

## Stop conditions
- 无凭据对照探针中目标路由与 sibling 状态码一致，且挂载点 dependencies 确认覆盖目标路由
- 对照探针证明分叉是有意策略（规格/需求明确要求该路由更严），对齐指令让位于规格

## Verification
- 对目标路由与 sibling 路由各发一次相同条件的无凭据请求，比对状态码是否一致
- 直读统一挂载点确认共享 guard 存在且覆盖该 router，再判断内层检查是否冗余

## Counterexamples
- 目标路由不在统一 guard 的挂载范围内（独立挂载或不同依赖），此时同口径可能确实需要本地检查——对齐的是有效守卫总量，不是『都不写』
- 规格明确要求该路由比 sibling 更严（有意分叉），对齐意见被规格覆盖
- 前端本就携带凭据（cookie/Bearer），401 指向会话过期而非双重 guard 死码
- sibling 属不同框架/版本，鉴权惯用法不迁移，字面照抄反而制造分叉
