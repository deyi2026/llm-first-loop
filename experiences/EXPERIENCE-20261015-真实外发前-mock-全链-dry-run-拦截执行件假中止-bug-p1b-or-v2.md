---
title: 真实外发前 mock 全链 dry-run 拦截执行件假中止 bug（P1b-OR-V2）
scenario: 预注册评估轮的组合式包外 runner（新 runner 复用多个冻结件）在首次真实外发前，用 mock 传输跑全链 dry-run（含对账与中止路径），清掉 mock 事件后再真实执行。
root_cause: ""
solution: 冻结 runner 与 dry-run 同版落盘；mock 全链通过（批全 recorded、题全 schema-valid、分母/中止判定正确）是真实外发的机械前置；mock 事件文件删除后再跑 real。本案拦截 dict/getattr 假中止 bug 于真实请求之前。
evidence: "mock 首跑回执 aborted=schema_invalid_stop: case-101 ×4（事件中逐题 status 实为 valid，证 getattr-on-dict 假中止）；修正 diff（artifact://v1/04379e39195e40d2a817e3ca5b344572）；mock 复跑 13/13 recorded、44/44 schema-valid；真实跑回执 outputs/jev-p1l-expand-20261015/p1l_or_expand_report.json（mode=real_or_systemone, aborted=None, 13/13）；附录 C v0.9.1 第 4 条记录时序。"
tags: [jev, pre-registration, dry-run, mock-transport, outbound-budget]
source:
  artifact: "artifact://v1/04379e39195e40d2a817e3ca5b344572"
  report: outputs/jev-p1l-expand-20261015/p1l_or_expand_report.json
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T13:50:18.269397+08:00"
updated_at: "2026-10-15T13:50:18.269397+08:00"
---

场景：预注册制的外发评估（Jev P1b-OR-V2）需要新写包外 runner 组合既有冻结件（任务集装载/传输/对账）。真实外发预算有限且中止条件严格，执行件自身的 bug 会在真实请求后才暴露，浪费配额并污染"无中止"事实。做法：同版冻结 runner 后，先用 MockJevTransport 跑一遍全链（冻结校验→打包→守卫→事件→对账→中止判定），确认 13/13 批 recorded、44/44 schema-valid、分母正确，清掉 mock 事件文件再切 real_or。本轮拦截实例：中止检查 `getattr(qf,"status")` 对 dict 逐题对象恒返 None，会导致真实外发在批 1 后假中止（schema_invalid_stop）——mock 全链一次即暴露，修正于任何真实请求之前，真实跑 13/13 无中止。反例边界：mock 只验 plumbing（打包/校验/记账/中止路径），不验证远端行为；mock 结果本身无语义，必须清除其事件产物避免混入真实对账。适用条件：任何"先冻结后执行"的评估轮、有 Mock 传输层的 runner。