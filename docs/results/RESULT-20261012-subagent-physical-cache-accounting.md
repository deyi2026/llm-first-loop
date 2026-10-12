# 子 Agent 物理 Provider 缓存/成本独立统计

**状态：隔离候选；未修改缓存或 Provider 请求，待正式 R9/受管发布验收。**

## 真实缺口

主循环会为普通请求写 request.usage 事件，旧 Web SessionStats 优先读取
该事件；但 SubAgentRunner 的物理调用走 ProviderCallCoordinator，
其子会话并不一定写 request.usage。D07 保存的 child Assistant 消息
tokens_cache_hit 也全部为 0，原 stats 误显示 0% 命中。

**原始权威仍在**：每次 Provider 真实 transport 返回的
provider.transport.settled.usage.cached_input_tokens、input_tokens、
output_tokens 以及 started_at、settled_at。子代理可能有 Provider
隐藏的 transport retry，不能仅统计模型回复次数或仅统计
SubAgentResult.tokens_in。

## 实施：纯只读，不建立第二套缓存

- 新增 core/provider_transport_usage_stats.py：按实际
  attempt_id 去重；同 id 不同回执标记 conflict、不据此计费；
  聚合已结算物理 Provider 输入、输出、已缓存、未缓存输入，
  真实 transport 时间总和和 per-provider/model 分桶。
- 记录 opened-but-not-settled 数量；缺 usage、缺缓存字段、异常
  缓存数（cache > input）或结算冲突均不能假称 0% 命中；
  全局 cache_hit_rate、uncached_input_tokens 可为 null。
- 不推断美元支出：模型/Provider 计费价不同；这里的「实际消耗」
  是 Provider 回执可证明的**物理 Tokens**，不是发票或账单金额。
  transport_duration_ms 是逐物理调用耗时之和，不等于端到端墙钟。
- Web 已有 GET /api/v1/sessions/{id}/stats 在 child_session
  (Session.parent_id 且 subagent_ 前缀) 优先使用这些物理事件，
  不与 parent 逻辑计量叠加；普通会话统计保持原逻辑。
- 父会话 GET /api/v1/sessions/{parent}/stats?child_id={exact_child}
  可在 agent_comparison 中并列提供 parent / child 指标；
  必须验证同一真实 parent_id，拒绝无关 child。没有可信
  Reviewer role 元数据时返回 reviewer_role=unverified，
  不能仅凭子任务文字给子代理贴 Reviewer 标签。
- Web SessionStats 在缓存缺失时显示「未上报」，不把 null
  normalization 成 0%。切换到子会话时明确标出「子代理」，
  提示该物理口径包含隐藏重试。
- 不修改 Provider 请求参数、缓存策略、tool schema、SubAgentRunner
  的 prompt、物理重试或模型选择。**没有新增模型/Provider 调用**。

## D07 真实历史数据复算

只读打开生产保存的
data/event_logs/subagent_c0488e1c1d83.jsonl，按真实 attempt_id
逐行统计：

| 指标 | 真实物理回执 |
|---|---:|
| Provider / 模型 | minimax / MiniMax-M3.1-Flash-Preview |
| 独立逻辑 Provider 调用 | 23 |
| 已结算物理 transport 尝试 | 31 |
| 未结算 opened | 0 |
| 输入 Tokens | 1,132,294 |
| 输出 Tokens | 25,312 |
| 缓存输入 Tokens | 1,069,021 |
| 未缓存输入 Tokens | 63,273 |
| Provider 缓存命中率 | 94.41% |
| 物理 transport 耗时合计 | 262,930.4 ms |

此前 D07 审稿 PASS 属于语义审查证据，与缓存成本归因不同。
以上统计只证明这个 MiniMax 子代理真实调用的缓存表现，
**不能外推 GLM-5.3、其他 Reviewer 或全部子代理的命中率**。

## 负例与验收

- 相同 logical call 下多物理 attempt：全部正确入账；
  完全相同 attempt 重复结算不重复加账。
- 对抗不同 Provider/模型：独立分桶。
- 缺 cache usage、冲突 settlement、无已结算数据、
  opened 未结算：不会冒称 0% 缓存命中或 100% 完整。
- 父子关系不匹配拒绝对照；父会话既有统计未受影响。
- Web UI 对未知值展示「未上报」，保留旧数值显示。
- 真实 Provider 调用没有发生，回放 D07 历史文件只读。

**发布原则**：只有最终提交候选的 R9、WebUI 以及整树安全扫描
通过，且 managed service 的 Web-only 新 generation 与 HTTP
健康现场核对一致，才可宣称统计功能已经上线；不涉及
Feishu、Learning 或生产双 Agent 的 Reviewer/Witness 门禁。
