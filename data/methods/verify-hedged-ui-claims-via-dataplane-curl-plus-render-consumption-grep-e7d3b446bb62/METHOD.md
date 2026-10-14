---
method_id: verify-hedged-ui-claims-via-dataplane-curl-plus-render-consumption-grep-e7d3b446bb62
name: verify-hedged-ui-claims-via-dataplane-curl-plus-render-consumption-grep
description: 当收到的部署/状态报告用推测性措辞（『应显示』『应该是』）断言预期 UI 显示或归属归因时，不要绕道浏览器枚举或全仓内容搜索：把断言拆成数据面（API JSON 是否下发该字段——对运行端口一次 curl）与渲染面（前端代码是否消费该字段——对 static/ 源码一次 grep）。前端全入口零消费即证明不渲染，无需浏览器；归属断言则直接枚举持有者（锁文件+owner pid）。零消费结论是范围缺口（API-only 契约），不是运行故障，需分层上报。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:0:e4d23cc663d341f8dd64
evidence_refs: learning:learn:29207bbb48ca
created_at: 2026-10-14T14:18:11.997479+08:00
updated_at: 2026-10-14T14:18:11.997479+08:00
---
## Trigger
上游报告（用户或上游摘要）以『应显示/应该是』类推测措辞断言部署后某个 web 面板将显示某命名字段，或断言某资源（如 run locks）的持有归属，且仓库内同时存在该面板的 API 源码与前端 static 源码。

## Discriminator
断言对象是否为『被服务 web 面板显示的命名字段』：此类断言必可分解为两个单探针可判定命题——运行端口上 API 是否下发该字段（读 .env/config 得端口后 curl），以及前端源码是否消费该字段（grep static/ 全部入口）。字段名在前端全部入口零命中 = 渲染不存在的决定性证据，此判据在动手当时即可从仓库结构（routes.py+static/ 并存）得出，不依赖浏览器状态。

## Short path
- 把推测措辞转成两个谓词：数据面是否下发字段、渲染面是否消费字段
- 从服务自身配置取端口/端点（如 grep .env 的 WEB_PORT），不做全仓 metric 名搜索、不枚举浏览器页面
- curl 运行中的端点，在运行面确认字段与取值（结构零=True+reason 即实证）
- grep 前端全部入口（app.js、modules/*、index.html、templates）中该字段名；零命中即证明面板不会渲染
- 数据面✓/渲染面✗ → 上报范围缺口（API-only 契约）并与运行故障区分；归属断言改为直接枚举实际持有者（锁文件数、owner pid、最近写入）后停止

## Stop conditions
- 两面各自得到证实，或任一面被决定性证伪（字段名在前端全部入口零命中）→ 停止探测，带分层归因上报
- 归属类断言在枚举出实际持有者清单（数量、owner、活跃写入）后即收口，不再靠会话身份推断

## Verification
- curl 必须打到运行端口取运行面 JSON，而非止步于『源码存在该代码路径』
- 宣告前端零消费前，确认 grep 覆盖全部前端入口（app.js、modules/*、index.html、templates），排除漏检
- 锁/持有者归因：列出实际锁文件+持有进程+最近写时间，与断言中的『应该是 X』逐项对照

## Counterexamples
- 前端用通用表格/反射式遍历渲染任意 JSON 键：源码中无字面字段名不代表不渲染，必须改用浏览器实测
- 面板是第三方/远端 UI、源码不在本仓库：渲染面 grep 不可用，回退浏览器或询问维护者
- 断言只关数据面（『API 应包含 X』）：单次 curl 即裁决，无需再 grep 前端
- 断言是纯视觉/交互表现（徽标样式、交互）：消费存在≠渲染正确，仍需浏览器验证
