# LFL 可插拔模型角色与候选池

## 目标

模型身份是 operator 配置，不是业务代码常量。角色名称是稳定接口；Provider/Model 候选按配置顺序解析到现有 `ProviderRegistry`。新增模型、替换供应商或调整优先级不要求修改业务代码。

## 配置

`LFL_MODEL_ROLES` 是可选 JSON 对象，key 为小写角色标识，value 为有序 `provider/model` 数组：

```json
{
  "planning": ["provider-a/model-x", "provider-b/model-y"],
  "execution": ["provider-b/model-y", "provider-c/model-z"],
  "reviewer": ["provider-c/reviewer-model", "provider-a/independent-reviewer"]
}
```

每个角色最多 8 个候选；全局最多 32 个角色。模型引用必须在当前 Provider Registry 中可解析，并且至少一个候选具备可用凭据。运行时按配置顺序过滤失效候选，不按模型名称、能力标签或任务复杂度重排。

`LFL_REVIEWER_MODELS` 是兼容的独立 Reviewer 配置，优先级高于 `LFL_MODEL_ROLES.reviewer`。两者都未配置时 Reviewer 保持 fail-closed，不存在内置 Reviewer 默认值。Reviewer 仍通过独立 Host 审查入口运行，不继承开发会话的模型身份、工具权限或审查结论。

`MODEL_FALLBACKS` 继续优先负责默认模型的 availability failover；未配置时，使用 `LFL_MODEL_ROLES.execution` 的有序候选，排除当前默认模型。此阶段不改变默认模型的首次调用。用户显式选择的会话模型失败时仍如实报错，不自动偏离用户选择。429、超时、网络错误等既有可恢复故障沿 operator 配置的候选链切换；非适用错误不切换。每次成功降级都保留结构化运行回执和审计事实。

## 热更新与失败语义

`refresh_config` 重读环境与 Provider Registry 后，独立更新角色映射；普通调用的 execution 备用链无需重启。受管 `.env`（`LFL_ENV_FILE` 或 `LFL_RUNTIME_ROOT/.env`）中显式设置的角色值覆盖启动环境旧值；空值或移除该键关闭受管映射，读取失败保留旧映射；非受管入口仍可使用进程环境。Reviewer 的 Host authority 仍在启动时冻结配置，独立审查配置热更新需另行实现且不得改变在途审查身份。配置解析失败、角色没有任何可用候选时，保留上一次有效映射并返回明确提示。Provider Registry 的默认 client 启动快照和现有连接生命周期语义不变。

## 约束

- 不把具体模型名写入业务分支；示例模型名仅存在于 operator 配置。
- 不把 capability tier、价格或模型品牌用作自动质量路由依据。
- 候选池只做注册表解析、凭据可用性、顺序与去重；角色调用方显式选择角色。
- 显式用户模型选择优先于任何自动故障切换策略。
- Reviewer 的候选链独立配置、独立执行、独立核验；配置缺失时拒绝审查，不静默降级到开发模型。
- 热更新不修改在途请求的 client；旧 client 仍由现有 pool 退休机制处理。
