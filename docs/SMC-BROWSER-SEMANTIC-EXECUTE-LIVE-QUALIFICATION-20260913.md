# SMC Browser `browser_semantic_execute` Live Qualification — 2026-09-13

## 结论

**PASS。** 新增的 model-facing `browser_semantic_execute` 已在真实、隔离的 Chrome/CDP 环境中完成机械资格化：**12/12 behavior + 7/7 safety** 全通过。

本轮只资格化新增的薄工具层，不重写、放宽或重新定义已封盘的 Browser Phase 1 mutation runtime。模型面只需要提交：

`verb + target_ref + args`

工具内部从模型已经选择的 **exact GroundingRef** 机械编译既有 `SemanticAction v0.1` 所需的 `target_id / scope_ref / expected_version / version_scope / action_id` 等字段，再交给既有 `BrowserActionAdapter` 执行 stale/version/single-dispatch/receipt 硬边界。

## 冻结身份

- 实现 commit：`b313f9bb5e689aa935cdc081d83f5dca7d7af3a7`
- qualification harness commit：`fd812123a8ad0fe5e844a2fc7f0d2e17ceccd3be`
- harness SHA256：`c169cde81f94c6f819e81d1d808656bafd2d5dec08e1a0bebdfc56d4d459a532`
- formal result SHA256：`87c2faed2567babda572bfd1d145be2e61047fe2c19003e9c2becd7a8cbdf816`

正式 run 在 exact `fd812123` committed state 上执行；run 前后 tracked working tree 均为 clean。隔离 Chrome 使用 `--use-mock-keychain --password-store=basic`，未产生新的 macOS SecurityAgent。

## 机械行为 12/12

| Gate | 结果 | 含义 |
|---|---|---|
| snapshot exposes exact resource ref | PASS | model-facing snapshot result 提供 exact page `resource_ref` |
| resource ref hydrates scope/version | PASS | resource ref 可 session-scoped exact hydrate 到 page scope + observed version |
| object ref click dispatches once | PASS | object GroundingRef 经工具编译后真实点击一次 |
| same exact request dedups | PASS | 同一 `verb+ref+args` 复用确定性 action identity，第二次 rejected，未二次点击 |
| thin fill reaches page | PASS | `fill` 的业务参数经薄工具真实到达页面 |
| stale old ref rejected | PASS | observation 后对象状态改变，旧 exact ref 未被 blind dispatch |
| same-name replacement no rebind | PASS | 同名新物理节点不会被旧 semantic identity 自动重绑 |
| wrong projection rejected | PASS | object ref 用于 navigate 时在工具编译阶段拒绝，未发生导航 |
| resource ref navigate | PASS | page resource ref 被编译为 resource-scoped navigate 并真实到达 exact loopback URL |
| receipt append-only | PASS | running → ok → duplicate rejected 序列保持 append-only |
| no automatic retry | PASS | 全部已落盘 action receipts 均为 `automatic_retry_performed=false` |
| receipt ok != task completion | PASS | receipt 不产生 task-completion 语义字段 |

## 安全 7/7

- isolated Chrome 使用 mock keychain：PASS
- basic password store：PASS
- 无新增 SecurityAgent：PASS
- read host exact target 绑定：PASS
- mutation actuator exact target 绑定：PASS
- model-facing schema 仅 `verb / target_ref / args`：PASS
- fill 明文不进入 action receipt store：PASS

## LLM-First 边界

本工具**不是 Semantic Controller**，也不拥有策略权。模型仍负责：

- 根据用户任务与当前 observation 选择哪个对象；
- 选择 verb 与业务 args；
- 读 ActionReceipt 后决定是否需要重新观察；
- 根据最新世界事实判断用户任务是否完成。

程序只负责 exact ref 水合、机械字段派生、权限/版本/identity/single-dispatch/receipt 等硬事实和硬边界。不存在自动目标选择、自动 retry、自动 latest、自动 rebind 或程序侧任务完成判断。

## 本报告不声称

这次机械 live PASS **不等于模型可用性已经通过**。它没有调用本地或云端模型，也不证明 Ornith/Qwen/GLM/MiniMax/DeepSeek 已经能稳定选择正确 GroundingRef。下一门必须独立做真实模型 A/B：旧 full `browser_action` model-facing surface 对比新的 `browser_semantic_execute` surface。
