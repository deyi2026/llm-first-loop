# 失败与坑：记录 → 优化 → 复查 循环 Playbook

版本 v1 · 2026-10-07 · 依据当日 exception_log / event_stream / 记忆库核实结果编写

## 0. 目的

把「出现不成功或有坑 → 及时留档 → 对既有设定升级对策」固化为标准动作。
反面教材：evolution_complete 状态前置坑跨 13 天复发 4 次才建档——本 playbook 要消灭的就是这种"踩了不记、记了不用"的滞后。

## 1. 触发条件

任一工具回执出现：fail / timeout / 拒绝 / 空命中 / 状态与预期不符 / "不报错但结果错"的验收假象。

## 2. 第一步永远是分层判定（不是所有失败都该重试）

| 层级 | 判定特征 | 首选动作 |
|---|---|---|
| A 模型误用 | 回执文本明确指出参数契约/状态前置（如"仅 executing 状态需登记"） | 同参数禁止重试；修参数或流程后重发 |
| B 环境层 | 超时 / 网络 / 沙箱 EPERM / 资源竞争 | 三向排除法定位（readonly 池阻塞案例，2026-09-22）；换通道，不原样重试 |
| C 程序层 | 确定性状态机缺陷（如 grant_lost_owner_dead） | 不重试；按 sid 查全局生命周期事件；模型侧兜底 + submit_evolution |

依据：method:policy-block-receipt-no-same-param-retry-branch-or-stoploss-945f1a981801（确定性拒绝，同参重试必复现）。

## 3. 高频坑速查（本次已核实 stable refs）

| 坑 | 卡 | 一句话对策 |
|---|---|---|
| 同文件并行 edit_file | experience:EXPERIENCE-20260917-edit-file | 必须串行，首个成功即失效其余快照 |
| 双仓工作区写错仓 | experience:EXPERIENCE-20260911-edit-file | 先确认会话工作区根 vs 目标仓库 |
| search_files 参数混用 | experience:EXPERIENCE-20260820-search-files-pattern | pattern=文件名/glob，content=内容，root=目录根 |
| search_files 漏检深层文件 | experience:EXPERIENCE-20260930-search-files-find | find 兜底定位 |
| HTTP 验收 303→200 假绿 | experience:EXPERIENCE-20260917-http-303-200 | 禁用自动重定向再断言 |
| 配置读取猜默认值 | experience:EXPERIENCE-20260917-manifest-port-8787-8903 | 无键不兜底，去 resolver 权威源 |
| browser 大页 capture 失败 | experience:EXPERIENCE-20260918-cdp-timeout-vs-frame-too-large-vs | 根因多为帧超限非超时，加时无效 |
| restart 只换 PID 不换代码 | experience:EXPERIENCE-20260917-mirror-service-control | 上代码走 publish + 代次推进 |
| publish 后忘重启其余服务 | experience:EXPERIENCE-20260924-publish-restart-action-publish | publish 不派发 restart，逐服务显式发起 |
| 异步回执"受理≠完成" | method:deferred-wakeup-verify-async-action-terminal-states-e9c597e4c1e4 | 查到 succeeded/failed 才算数 |
| wake 授权丢失全链 | experience:EXPERIENCE-20261007-schedule-wake-grant-lost-owner-dead-6-30 | 确定性终态：全局事件定位 + 非 wake 兜底，勿重挂 |
| wake 跨 restart 边界失效 | experience:EXPERIENCE-20261006-schedule-wake-restart | 终态核验不托付 wake |
| evolution_complete 状态前置 | experience:EXPERIENCE-20261007-evolution-complete-accepted-executed-4 | 先查建议状态，仅 executing 才登记 |
| 失败尝试冒充经验 | experience:EXPERIENCE-20260911-4 | 失败尝试只入 lesson（用户 2026-09-11 明确要求） |

注：restart 活跃会话空闲门自锁（2026-09-18 记录）本次未复核到 stable ref，使用前先检索确认。

## 4. 记录纪律

1. **先查重**：search_records（experience/lesson/method）确认无同类卡再建档；命中旧卡则把本次证据声明为"验证/细化"关系（如 20261007 wake 卡串联 0919/1006 两张旧卡）。
2. **分型**：失败尝试 → lesson；被证据核验的解法 → experience(verified) + evidence ref；可复用操作序列 → method 候选。
3. **evidence 必须可回溯**：event_stream 时间戳/sid、exception_log 条目、文件/commit——不接受转述。
4. **程序侧根因**（模型侧无法根治）→ submit_evolution，写明 evidence 与 impact_scope，并跟踪审阅状态。
5. **卡龄超龄降权**的旧卡：重验证后再信任；适用性永远由当前任务事实判断。

## 5. 本日已落地（2026-10-07）

- 新卡 ×2：
  - experience:EXPERIENCE-20261007-evolution-complete-accepted-executed-4（lesson / verified）
  - experience:EXPERIENCE-20261007-schedule-wake-grant-lost-owner-dead-6-30（experience / verified）
- 演进建议：EVO-20261007-8057c39a（21:23 已批准，同日执行完毕）——① owner_dead 确定性失败立即降级（不再 6 轮退避）；② 降级通知携带 `wake_degraded_payload`（可再锚定）；③ 锚定评估完成：维持 session 锚定（docs/EVAL-20261007-wake-authorization-anchoring.md）。
- method 使用登记：deferred-action-failure-layer-scoped-lifecycle-trace（applied）。

## 6. 复查节奏

- **机会主义**（每次踩坑）：§2 分层 → §3 速查 → 新坑解决后立即按 §4 入库。
- **周期性**（人工触发或会话间隙）：exception_log 高频 tool_failure 词扫描 → 对照 §3 找未建档项 → 补档；已建卡的用新证据 annotate_freshness / 重验证。
- **周期 wake 限制解除**（EVO-20261007-8057c39a 执行后）：owner 死亡的 wake 现在立即降级为通知并携带再锚定 payload（不再空烧 30 分钟），注册周期性复查 wake 不再与可靠性目标自相矛盾。
