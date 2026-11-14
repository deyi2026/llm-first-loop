---
method_id: map-guard-chain-order-before-route-level-gate-negative-tests-17d34f6e0628
name: map-guard-chain-order-before-route-level-gate-negative-tests
description: 在真实 HTTP route 上为 handler 中段的 gate（授权/预算/准入门）写负测时，先读 handler 从入口到该 gate 的守卫链并记下各层失败响应（如会话解析 404、queue 409、附件 400、gate 403）。更早的层会拦截部分负参；既有直调 gate 函数的模板测试断言不可照搬到 HTTP 层。请求要用真实注册实体（如 engine.session.create()）穿过解析层；每个负参断言其实际拦截层的真实 status/error，加零派发/零分配等无副作用不变量，不强行让所有负参都触发目标 gate。
aliases: 负测没打到 gate 就被 404, 拒绝用例被更早的检查层拦走, 先读守卫链顺序再写拒绝断言, HTTP 负测该断言哪一层的错误码, 直调模板搬到真实请求后断言失配
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:2762:469bbd8a583e3c9da6c5
evidence_refs: learning:learn:23c2d3c40047
created_at: 2026-11-14T07:23:25.222207+08:00
updated_at: 2026-11-14T07:23:25.222207+08:00
---
## Trigger
需要为位于 route handler 中段的 gate（授权/canary/预算门）补真实 HTTP 层正负测试，而既有参考模板是直接调用 gate 函数（构造 Request 直调、不走 TestClient）时。

## Discriminator
两个当时已可见的事实：模板测试是直调 gate 函数而非走 HTTP；route 源码中 gate 调用点位于 handler 深处（session 解析、queue/attachment 检查之后）。二者已足以判定 HTTP 层负测的实际拦截层不确定，必须先读入口→gate 段确定守卫顺序，不能假设负参都会到达目标 gate（否则字面 session id 会先 404，queue/attachments 会以 409/400 在 gate 之前拒绝）。

## Short path
- grep gate 函数名，定位其在 route handler 中的调用行
- 从 handler 入口读到 gate 调用点，列出守卫链及各层失败 status/error 码——排在前面的层先拦截
- 用真实注册实体（如 engine.session.create() 产生的 session id）构造请求，使其穿过解析层到达目标层
- 每个负参按实际拦截层断言真实拒绝形态（可能是 404/409/400 而非 gate 的 403），并共同断言零 runner 派发、零预算分配等无副作用不变量
- 正测走全链路（TestClient POST→runner spy 收到 gate 产物并核身份），负测组全绿即停

## Stop conditions
- 全部负参断言与实际拦截层一致，且无副作用不变量（零派发/零分配）成立
- 不为统一错误码而改造产品代码或新造测试框架——如实断言既有分层拒绝形态

## Verification
- 每个负测同时断言 (a) 实际拦截层的 status/error 码，(b) 零派发/零分配等全局不变量
- 正测验证 gate 产物（如 signed plan 身份）真实穿过 HTTP 层到达下游组件

## Counterexamples
- gate 是 handler 的第一个检查、之前无其他守卫 → 直接断言 gate 错误码，无需层序分析
- 只需 gate 函数级单元覆盖 → 沿用直调模板即可，引入 HTTP 层反而增加脆弱性
- 前置拦截层是临时实现或待迁移 → 不把它的错误码固化进断言，先确认该层是稳定契约
