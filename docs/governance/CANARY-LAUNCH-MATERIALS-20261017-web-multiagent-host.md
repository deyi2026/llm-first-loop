# CANARY LAUNCH MATERIALS — 真实双层 Provider Canary 精确上线材料（未执行，待授权）

> 状态：材料就绪。**本文档不构成执行授权**。生产 Provider Canary、main 合并、push、发布、重启均需用户另行显式授权并核验前置条件。

## 0. 候选身份（已通过完整验证链）

- 分支：`fix/web-multiagent-host-main-current-20261016-current`（基于 main `8041dc357d0c7ed75ed92ca5d4fad816342aa46d`）
- 代码 commit：`8634db468`；patch SHA256（预提交 staged）：`0834145b2c3df15c14242a10f7383317e53abba1fd32be79386e4fb681a9597b`
- 独立 GLM-5.3 代码审查：PASS P0=0 P1=0 P2=4（`subagent_d70044fe0589`，冻结树 `962d3760…`）
- 原版 R9：exit 0，xdist 全量 9201 passed / 141 skipped / 0 failed
- 合并前提（另行授权后）：重读当时 main tip、重算交叉修改交集；若 527fe6463/fef342164 相关文件再变更，需重新冻结与复审

## 1. Canary Profile 物理事实（代码即事实源）

- Profile：`web-glm-direct-subagent-canary-v1`（配置 schema `web-task-budget-direct-subagent-canary/v1`）
- 运营者配置：0600 权限显式 JSON，字段集精确冻结（schema/profile/authorization_id[32hex]/session_id/workspace_root/model_ref/valid_from/valid_until），TTL ≤ 3600s；**无默认激活**
- root 工具面：仅 `spawn_subagent`（1 次）+ `subagent_result`（≤2 次）
- child：显式空工具集（`requires={"tools":[]}`）、不继承、不递归（depth!=0 拒绝 + 零工具双保险）、模型锁定 `glm/glm-5.3`、决策轮次上限 3
- 共享持久 ledger：物理 attempt 上限 8（父+子共享）、工具调用上限 3、180s 窗口；失败/中断/UNKNOWN 永久禁止重试；CAS 持久化，重启后磁盘相位封锁迟到 attempt
- Provider 目标冻结：openai wire / glm / glm-5.3 / `https://open.bigmodel.cn/api/*`，无代理（proxy 声明即拒）
- 取消：按 (session_id, run_generation) 精确级联；fs_isolation 轴对 canary 双层拒绝（dispatch 层 requires 字段集 + runner 层拒绝条件）

## 2. 上线前待申请授权清单（一次一申请）

1. 生产 Provider Canary 执行授权（真实双层委派，消耗真实 GLM-5.3 配额）
2. （如需）Web live release 重启授权：`service_control` 白名单路径，须核验 Web live release 当前代、执行锁、已尝试标记
3. main 合并 + push 授权（当前明确不在本任务内）

## 3. Stage A — 单独 Web 会话双层委派（验证目标：授权机制端到端真实成立）

前置：候选已合入并部署至 live（授权 2）；运营者已按 `1` 生成 0600 配置；专用 Web 会话已创建。

步骤：
1. 运营者：`scripts/task_budget_admin_once_setup.py --profile direct-subagent --output <path> --ttl-seconds 300`（生成专用会话与配置，不自动启用）
2. 运营者：将配置路径挂到 `LFL_TASK_BUDGET_WEB_CANARY_CONFIG` 并按 live 发布流程重启/加载（需授权 2）
3. 验证者（另一会话，非运营者）：在该 Web 会话发起一个单事实任务（如「Calculate 31415+27182」），观察模型应只能 `spawn_subagent` 一次产出零工具 child，并以 `subagent_result` 收口
4. 持久化真实结果断言：ledger 文件含 root+child 两成员、attempt 计数与实际物理调用一致（预期 2±0）、tool_invocations ∈ {2,3}、终态 phase 与 stop_reason 一致；事件流有 child 的 durable 终态事件
5. 反向断言：同会话再发任务应被拒（预算已结算）；伪造第二子/跨会话读/迟到 attempt 均拒

## 4. Stage B — 父→直接子取消传播（验证目标：受控取消真实成立）

前置：Stage A 通过。另起一对专用会话/授权。

步骤：
1. 发起可阻塞的 child 任务（长任务）
2. 在 child 物理调用进行中由用户 Stop 父会话
3. 断言：`cancel_parent(sid, generation)` 精确命中（错 generation/错 session 计 0）；child 终态 cancelled/failed；ledger 进入 `stop_requested`；此后父/子任何迟到物理发送均拒；其它用户会话预算不受影响（独立 ledger 目录对照）

## 5. 明确排除

三层及以上递归委派（本 profile 物理不可能：child 零工具 + depth 检查）；扩大 Host 权限；DeepSeek 或其它 provider 冒充 GLM-5.3。

## 6. 回滚

- 配置级：删除 0600 JSON + 取消 `LFL_TASK_BUDGET_WEB_CANARY_CONFIG`（profile 无默认激活，摘除即回归 `web-task-budget-admin-once/v1` 旧行为，旧 profile 未改动）
- 代码级：revert `8634db468`（独立分支单提交，无纠缠提交）
