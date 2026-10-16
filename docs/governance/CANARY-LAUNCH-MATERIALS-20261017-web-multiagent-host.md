# CANARY LAUNCH MATERIALS — 真实双层 Provider Canary 精确上线材料（未执行，待授权）

> 状态：材料就绪。**本文档不构成执行授权**。生产 Provider Canary、main 合并、push、发布、重启均需用户另行显式授权并核验前置条件。

> **2026-10-17 离线准备修订**：下列代码审查/R9 引用属于历史冻结候选；Web-only 离线包现单独固定于 `9101b841ce54903697e24484a5fdbbc7ec2ef586`。本地 `main` 在本轮盘点时已推进至 `b68dbc2a53c87295c7f160502795a4bd26f2f91d`，含额外 F 批变更，**不得将其自动视为同一个已审发布包**。生产 Web desired/live 仍在 `b184edf9c7ecc16014c1806fd1c0bedff7a440cb`、generation 273。详细离线核验和当前阻断见同日 offline readiness 回执。

## 0. 候选身份（已通过完整验证链）

- 历史原始候选分支：`fix/web-multiagent-host-main-current-20261016-current`（基于 `8041dc357d0c7ed75ed92ca5d4fad816342aa46d`），**不是本次准备发布的 HEAD**
- 历史代码 commit：`8634db468`；patch SHA256（预提交 staged）：`0834145b2c3df15c14242a10f7383317e53abba1fd32be79386e4fb681a9597b`
- 后续已合入 LFL 本地 `main`：代码提交 `8784c28cc`，merge-gate `a0acecbfb`，治理收口 `9101b841c`；合并执行回执 `docs/governance/receipts/RECEIPT-20261017-web-multiagent-b184-merge-execution.json`
- 本阶段单独冻结的**离线发布包**：`.worktrees/web-multiagent-release-9101-20261017`，HEAD 为 `9101b841c`，非 production release、未 publish。新 `main` 其他提交不自动并入该候选；若目标更换则重新核准准确代码 SHA 与验收
- 独立 GLM-5.3 代码审查：PASS P0=0 P1=0 P2=4（`subagent_d70044fe0589`，冻结树 `962d3760…`）
- 原版 R9：exit 0，xdist 全量 9201 passed / 141 skipped / 0 failed
- 历史审查/R9 并未证明后来所有 `main` 提交可发布；本地合并已经完成，**发布前提**改为重读 exact code root / current main / desired/live generation、检查生产任务空闲/回滚候选/Host 配置、取得单独 Web-only 发布授权

## 1. Canary Profile 物理事实（代码即事实源）

- Profile：`web-glm-direct-subagent-canary-v1`（配置 schema `web-task-budget-direct-subagent-canary/v1`）
- 运营者配置：0600 权限显式 JSON，字段集精确冻结（schema/profile/authorization_id[32hex]/session_id/workspace_root/model_ref/valid_from/valid_until），TTL ≤ 3600s；**无默认激活**
- root 工具面：仅 `spawn_subagent`（1 次）+ `subagent_result`（≤2 次）
- child：显式空工具集（`requires={"tools":[]}`）、不继承、不递归（depth!=0 拒绝 + 零工具双保险）、模型锁定 `glm/glm-5.3`、决策轮次上限 3
- 共享持久 ledger：物理 attempt 上限 8（父+子共享）、工具调用上限 3、180s 窗口；失败/中断/UNKNOWN 永久禁止重试；CAS 持久化，重启后磁盘相位封锁迟到 attempt
- Provider 目标冻结：openai wire / glm / glm-5.3 / `https://open.bigmodel.cn/api/*`，无代理（proxy 声明即拒）
- 取消：按 (session_id, run_generation) 精确级联；fs_isolation 轴对 canary 双层拒绝（dispatch 层 requires 字段集 + runner 层拒绝条件）

## 2. 上线前待申请授权清单（一次一申请）

1. **Web-only 发布及必要重启的明确授权**（仅一次，必须先看到无在跑 Web 任务、无服务屏障、目标 release/前端来源有效；只使用 `service_control publish` CAS + `restart web`，Feishu/Learning 不动）
2. **真实生产 GLM-5.3 Provider Canary 的单独授权**（Stage A：一条专用 Web 会话、固定限额；Stage B 在 A PASS 后另建独立会话与专用授权；不把普通对话授权当作物理 Host 资格）
3. 如另行计划 push，需精确 remote/ref 的 push 审查与单独授权；本阶段没有 push 需求，不能默认 `origin` 等于正式公开远端 `lfl`

## 3. Stage A — 单独 Web 会话双层委派（验证目标：授权机制端到端真实成立）

前置：准确目标代码已受控部署至 Web live（发布授权 1）；运营者已生成有效的 0600 配置并将其绑定到**已存在、专用、与 workspace_root 一致**的会话；真实 Provider 调用另需授权 2。

步骤：
1. 运营者：`scripts/task_budget_admin_once_setup.py --profile direct-subagent --output <path> --ttl-seconds 300`（生成专用会话与配置，不自动启用）
2. 运营者：在 Web 启动的权威业务配置中明确挂载 `LFL_TASK_BUDGET_WEB_CANARY_CONFIG`，完成配置/TTL/会话身份核对后，经单独批准的受控 Web-only 重启加载（不是热切换、不得带动 Feishu/Learning）；若配置缺失则 Canary 默认 OFF
3. 验证者（另一会话，非运营者）：在该 Web 会话发起一个单事实任务（如「Calculate 31415+27182」），观察模型应只能 `spawn_subagent` 一次产出零工具 child，并以 `subagent_result` 收口
4. 持久化真实结果断言：ledger 文件含 root+child 两成员、attempt 计数与**实际物理调用逐笔一致且总数 ≤ 8**；不预设必然等于 2（轮询与回合可能产生不同合法次数）；tool_invocations ≤ 3、工具名称受 profile 限制；终态 phase 与 stop_reason 一致，事件流有 child 的 durable 终态事件
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

- **配置级（仅 Canary 退出，不是代码回退）**：先在受控的 Web 启动配置中撤销 `LFL_TASK_BUDGET_WEB_CANARY_CONFIG`，验证下一代 Web 配置不再引用该授权，再通过已批准的 Web-only 重启生效；此时 Canary 为 **OFF**，**不是自动回到 `web-task-budget-admin-once/v1`**。仅在不再被任何正在运行的配置引用后，按保密/审计策略处理原 0600 JSON，禁止先删除仍被引用的授权文件。
- **代码级（Web-only 回滚）**：保留已验证的稳定 release `.releases/b184edf9c7ecc16014c1806fd1c0bedff7a440cb`（generation 273 原绑定有效，实际回滚时必须重新核时）；确认禁用本次 Canary 新 schema 配置，使用 `service_control publish`（新 generation、当前 desired generation 的 CAS）重新绑定这份 known-good release，然后仅 `service_control restart web`，回读 live SHA/PID/generation、HTTP、消息/工具；不能用 `git reset --hard` 改写有并行工作的共享 `main`，也不能直接重启旧 desired 伪称回滚完成。

## 7. 发布资格与隔离保证（2026-10-17）

- 离线 `9101b841c` 只是**待审批包**；已验证前端 Git 跟踪输入树（104 文件）与旧稳定版本逐字节同源，复用的 66 个 dist 文件通过 `.lfl-webui-source.json` 校验及精确产物树 SHA-256 比对。不能由此推断已通过线上功能 Canary。
- 对发布时刻重新执行安全四锁：候选 HEAD+tracked clean+WebUI 指纹；独立代码审查及 R9 范围；`service_control show` 与现行 Web/Feishu/Learning live manifests、活动 Web whole-run locks 与其它 in-flight；旧 release 本体和 rollback CAS 路径可用。
- Web 忙碌（`confirmed_busy`）、授权失效或仍使用旧 startup schema 时保持 NO-GO；等待自然空闲而非 FORCE 打断。若选择更新后的 `main`（含 F 批代码），先另做适用于该精确整合树的独立验收，不能引用 `9101b841c` 的完整资格代替。
- Stage A/B 只在上述发布、资格和人类授权真正生效后分别执行；成功须有 Host ledger、持久化父子事件、物理 provider settlement 及跨会话负向断言证据，绝不把配置文件存在当作真实 Canary PASS。
