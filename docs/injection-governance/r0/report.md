# R0 基线与数据门报告（INJECTION-GOVERNANCE）

> schema: `r0-injection-baseline-v2` | R0: **PASS**
> 数据源：镜像区 `data/event_logs/*.jsonl`；本报告为确定性离线分析，不调用任何 LLM。

## 1. R0 四门

| Gate | 结果 | 机械证据 |
|---|---|---|
| R0-1 数据完整性 | **PASS** | origin coverage 100.0%；request attribution 100.0% |
| R0-2 基线可测 | **PASS** | completed turns=170；wire observed requests=707 |
| R0-3 机制复现 | **PASS** | post-user / duplicate / imperative / consecutive-user 四类脱敏 fixture 均已冻结 |
| R0-4 参数候选门 | **PASS** | 注入字符分布 p50=1463、p75=1821、p90=3627、max=11866 |

## 2. 结构基线

- 有 **user-role 程序附录** 的 completed turn：**71/170**。
- 用户真话之后仍追加程序块的 turn：**71/170 (41.76%)**。
- 参考资料帧重复：**340/666 (51.05%)**。
- 资料帧祈使污染：**23/666 (3.45%)**；按整注入块计 172/173 (99.42%)。
- wire 尾部连续 user 违规：**133/707 (18.81%)**。
- 发现无稳定 metadata 仍以 `role=user` 写回历史的 legacy program-user：`program_recovery`=7、`context_guard_notice`=1；已由内容前缀确定性识别，不再误算为 human turn。

### 按会话

| session | 角色 | turns | truth chars | injection chars | user-lane 注入占比 | 尾后注入 turn | 重复率 | 资料祈使率 | wire tail 违规 | models |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `09c44093` | duplicate-heavy-history | 11 | 141 | 55314 | 99.75% | 100.0% | 79.8% | 2.65% | 17 | glm/glm-5.3-flash |
| `68fed5f5` | weak-model-drift | 43 | 6892 | 65858 | 90.53% | 100.0% | 32.42% | 4.69% | 38 | cognilocal/qwen3.8-27b-cog, glm/glm-5.3, local/qwen3.8-27b-mlx |
| `69715765` | clean-control | 99 | 11093 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0 | deepseek/deepseek-v4-flash, minimax/MiniMax-M3 |
| `996e7e52` | compact-long-session | 17 | 417 | 24046 | 98.3% | 100.0% | 14.81% | 2.78% | 78 | cognilocal/qwen3.8-27b-cog, glm/glm-5.3 |

### 分桶口径

`baseline.jsonl` 每行同时记录 `model_id / capability_tier / compact_first / recovery`，报告聚合保存在 `baseline-manifest.json:aggregate.by_bucket`。`compact_first` 的 R0 操作定义是：该 human turn 首个 `request.meta` 之前已有 durable `context.compressed` 事件；`recovery` 只认显式 recovery/retry 事件或程序恢复注入，不凭错误码猜测。

## 3. R0-3 冻结 fixture

`fixtures/structural-fixtures.json` 只保存来源 session/turn、字符数和 SHA-256 前缀，不保存用户原文或资料全文。四类 fixture 分别证明：

1. program block 在用户真话之后追加；
2. 同一规范化资料帧在同 session 重复出现；
3. 资料帧含 command-shaped / imperative 表述；
4. provider wire 出现连续 user-role 消息。

## 4. R0-4 参数判定

- `INJECTION_BUDGET_CHARS=8000` 与 `K=3` **继续作为候选，不在 R0 擅自升级为生产常量**。
- R0 已冻结注入字符分布和分桶数据，可用于给 L3 选择候选区间。最终预算/K 必须在治理实现后用同 fixture 的任务完成率/漂移率 A/B 决定。
- 因用户此前已明确取消重复 cognilocal 基线跑，本轮没有重新启动本地模型；这不影响 R0 的确定性结构门。

## 5. 数据完整性与限制

- `message.appended` 是 origin/content 真相源；`request.meta` 提供实际模型与 history_chars；`cache.window` 提供 wire role/char 结构；`context.compressed` 与 `run.end` 提供 compact/run 归因。`injection_chars` 仅指 user-role program appendix；system notice 单列在 `all_program_injection_chars/system_program_injection_chars`，不冒充“用户尾后注入”。
- `incremental_injection_share` 是“本 human turn 新增程序块字符 / 首请求 history_chars”，不是把历史中所有已存在注入重新归因；会话级 `user-lane 注入占比` 则衡量真实 user 与程序 user-like 数据量。
- 行为漂移率/任务完成率属于 L3 A/B；R0 只保存既有历史事故作为 supporting evidence，不以随机采样结果作为硬门。

## 6. Source manifest

- `68fed5f5-3002-445b-95ad-cb2065168979` (weak-model-drift): events=6157, sha256=`b0bca0b7eb14ceca7c3371866ae5e0b1ec57b88f2931fa65925a7c1f55b5ad14`
- `09c44093-a0c4-49e4-95af-3ae2e59b210a` (duplicate-heavy-history): events=1426, sha256=`39469213ffd2d9b81f4464448c68d485562718e98570e856bf30cb159ea0dc5b`
- `996e7e52-82c3-4fc5-82ea-fff5863c2969` (compact-long-session): events=970, sha256=`b914ebc6e7f8c544f998e86ddc3b22b4419757648ab1cb82050b291f25f35b24`
- `69715765-08b3-40af-a054-8a8161543243` (clean-control): events=21216, sha256=`e8021532c72f3ecfa9f70ccc66271405f06ce4da7e55dd2c1f36a7da9aaf16be`

