# LFL 可插拔模型角色与候选池

## 目标

模型身份是 operator 配置，不是业务代码常量。角色名称是稳定接口；Provider/Model 候选按配置顺序解析到现有 `ProviderRegistry`。新增模型、替换供应商或调整优先级不要求修改业务代码。

## 配置

`LFL_MODEL_ROLES` 是可选 JSON 对象，key 为小写角色标识，value 为有序 `provider/model` 数组：

```json
{
  "planning": ["provider-a/model-x", "provider-b/model-y"],
  "router": ["provider-b/model-y", "provider-c/model-z"],
  "execution": ["provider-b/model-y", "provider-c/model-z"],
  "reviewer": ["provider-c/reviewer-model", "provider-a/independent-reviewer"]
}
```

每个角色最多 8 个候选；全局最多 32 个角色。模型引用必须在当前 Provider Registry 中可解析，并且至少一个候选具备可用凭据。运行时按配置顺序过滤失效候选，不按模型名称、能力标签或任务复杂度重排。

`LFL_REVIEWER_MODELS` 是兼容的独立 Reviewer 配置，优先级高于 `LFL_MODEL_ROLES.reviewer`。两者都未配置时 Reviewer 保持 fail-closed，不存在内置 Reviewer 默认值。Reviewer 仍通过独立 Host 审查入口运行，不继承开发会话的模型身份、工具权限或审查结论。

`MODEL_FALLBACKS` 继续优先负责默认模型的 availability failover；未配置时，使用 `LFL_MODEL_ROLES.execution` 的有序候选，排除当前默认模型。此阶段不改变默认模型的首次调用。用户显式选择的会话模型失败时仍如实报错，不自动偏离用户选择。429、超时、网络错误等既有可恢复故障沿 operator 配置的候选链切换；非适用错误不切换。每次成功降级都保留结构化运行回执和审计事实。

## 热更新与失败语义

`refresh_config` 重读环境与 Provider Registry 后，独立更新角色映射；普通调用的 execution 备用链无需重启。受管 `.env`（`LFL_ENV_FILE` 或 `LFL_RUNTIME_ROOT/.env`）中显式设置的角色值覆盖启动环境旧值；空值或移除该键关闭受管映射，读取失败保留旧映射；非受管入口仍可使用进程环境。Reviewer 的 Host authority 经既有 refresh_config 热更新；已接纳审查冻结候选与策略快照（PR #143），不改变在途审查身份。配置解析失败、角色没有任何可用候选时，保留上一次有效映射并返回明确提示。Provider Registry 的默认 client 启动快照和现有连接生命周期语义不变。

## 约束

- 不把具体模型名写入业务分支；示例模型名仅存在于 operator 配置。
- 不把 capability tier、价格或模型品牌用作自动质量路由依据。
- 候选池只做注册表解析、凭据可用性、顺序与去重；角色调用方显式选择角色。
- 显式用户模型选择优先于任何自动故障切换策略。
- Reviewer 的候选链独立配置、独立执行、独立核验；配置缺失时拒绝审查，不静默降级到开发模型。
- 热更新不修改在途请求的 client；旧 client 仍由现有 pool 退休机制处理。

## Planning / Router 实际调用（2026-11-27）

复用 `spawn_subagent` 的异步子任务入口：调用方可显式指定 `model_role=planning` 或 `model_role=router`，通过 `task` 和 `context` 提供完整研判材料。角色模式只返回研判文本，不调用工具、不继承父上下文 artifact、不创建 worktree、不续话、不接受在途 steer。角色不是权限、身份或 Reviewer 资格；派工/审批仍由现有确定性入口完成。已知目标直接派发的路径不新增模型调用。

- 省略 `model_role` 时保持既有子代理行为；同时提供 `model` 时仅尝试显式模型，不使用角色备用链。角色未配置或无可用候选时明确拒绝，不继承父模型。
- 启动时从同一 ProviderRegistry 与角色映射冻结有序 client 引用。热更新影响下一次研判，不替换在途候选身份。每个候选最多一次 runner 逻辑尝试（底层 client 的既有有界传输重试不变），并受 `max_rounds` 限制。
- 复用统一错误语义，429/1305、超时、网络等可用性错误才允许进入下一个候选；已计费空响应、确定性拒绝、工具调用、截断等不重放。所有候选失败如实返回失败。
- 复用 ProviderCallCoordinator 的调用结算和子任务持久结果；结果附角色、尝试顺序、请求模型、Provider 自报模型（缺失为空）、错误分类/业务码、耗时及已报告 token。实际费用仍以既有结算事实为准，不推算未报告用量。
- 本次只接通显式角色短研判入口，不增加自动复杂度判断器或自动派工系统；生产 15 秒目标、4–8 并行 Run 及 Mac/Deepin 实测需部署后验收。
