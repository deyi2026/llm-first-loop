---
method_id: managed-restart-target-config-preflight-and-rollback-binding-356473240ac6
name: managed-restart-target-config-preflight-and-rollback-binding
description: 受管 Web/Feishu/Learning 发布或重启前，先确认当前 desired 与目标版本配置可解析，release 的 Git 公共目录/代码 SHA/前端构建产物完整绑定；Web 特别校验 .env 登录哈希下一配置行、权限和 /ui/v2 产物。含代码/产物变更时，独立审查与原版 R9 在正确 Git 权限及默认 umask 下通过后再 CAS 发布；纯重启已发布目标跳过这两项，只核绑定与启动配置，按 action_id 跟踪 succeeded 与 live SHA/健康；Canary 检查仅在目标真实使用时执行。
status: candidate
source_model: ChatGPT
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:344:e72cd2d12679550c2c52
evidence_refs: data/service-control-restart-logs/svc-4b332a1f7c7d4ec3b857062f3d8c93d9.log,data/service-control-restart-logs/svc-f8d50045ddd64644bc3b63dd7ee6a99c.log,data/runtime/service-control-actions/svc-4b0595ab7a0a4ebf9979588a1688cb7e.json,data/restart-audit/canary-startup-recovery-20261009T192506+0800.json
freshness_refs: src/llm_loop/runtime/resolver.py,src/llm_loop/web/task_budget_canary.py,src/llm_loop/runtime/service_control.py,scripts/restart_mirror.sh
parent_ref: method:binding-drift-preflight-before-gated-service-mutation-e6f2166d36f7
created_at: 2026-10-09T19:39:35.996776+08:00
updated_at: 2026-10-26T06:56:06+08:00
---
## Trigger
用户要求对受管 Web/Feishu/Learning 发布、重启、恢复，或报告“重启后服务起不来、自动回滚也失败”。尤其适用于启动时读取认证或 operator/Canary 配置、共享 runtime.toml、Git worktree 与不可变 release 并存的场景。检索关键词：受管重启、启动配置预检、Canary 绝对路径、代码配置联合回滚、restart rollback preflight。

## Discriminator
停服务前必须区分两种检查：TOML schema 校验只证明字段可解析；目标版本的实际启动加载器才能发现相对路径、文件权限、JSON 字段、会话/workspace 绑定等问题。自动回滚若只换代码、沿用坏配置，两次启动都可能失败。新配置还可能包含旧回滚版本不认识的字段。
2026-10-09 的确证事实：gen213 与 gen214 均在 _read_operator_config 的绝对路径检查退出；关闭过期 Canary 配置后，受管重启成功。旧版本不接受 provider_proxy 是源码核对出的额外兼容风险，不是本次回滚日志显示的首个失败点。

## Short path
1. 先读取当前 service_control status/show：desired generation、不可变 release SHA、code_root/runtime_root、上次成功回执、live PID/启动时间、待执行动作及目标服务。当前用户已授权的范围可继续执行；方法卡不提供发布、重启或新模型额度的授权。普通 restart 以已发布目标为准，不因工作区 HEAD 与 release SHA 不同就自动阻断。
2. 按目标源码核对 CLI/schema 与 resolver/配置来源；检查相对生产的**完整差异**，不夹带其他分支功能。**闸域分流**：纯重启已发布目标（代码/产物未变）跳过审查与完整 R9，直接进步骤 3 的绑定与启动配置预检；只有本次要让新代码或新 webui 产物上线时，才冻结候选 SHA、走独立 Host Review PASS/P0/P1=0，并在具备主仓 Git `.git/worktrees` 写权限、默认 umask（通常 0022）的可验证执行环境运行**原版完整 R9**，真实 exit 0 且新红=0；不能以 Web 受限 sandbox 的 `Operation not permitted` 或手动 `umask 077` 导致的 0700/0755 权限假红改测试或豁免门禁。
3. **停服务前**先验证 release Git SHA 与 `desired.git_head` 严格绑定、`git rev-parse --path-format=absolute --git-common-dir` 与正式 runtime root 同一仓库，工作树 tracked-clean；Web 必须在这个目标 release 工作树执行 `npm run build`，校验 `webui/dist/index.html` 非空、资源文件数、`.lfl-webui-source.json` 来源 SHA/产物指纹，禁止只复用另一代码版本的空 `dist`。随后用目标版本实际加载器执行启动配置预检：先 resolver --check-toml，再走其确实使用的认证或 operator/Canary 读取校验。Web 登录哈希写回还须独立重新读盘，核对 `WEB_LOGIN_PASSWORD_HASH` 格式、`WEB_SESSION_TTL_SECONDS` 独立下一行、其他配置未被吞并、`.env` 权限 0600；只验证哈希形状不披露密文。文件须符合该版本的绝对路径、存在性、非符号链接/普通文件、owner/mode/nlink/大小要求；JSON 字段、模型、session/workspace、runner/EventStore 及代理格式均按目标版本契约核对。只用只读验证，不签发额度、不发 provider 请求、不用“假 loader 返回成功”代替真实检查。路径需要绝对形式时，从权威 runtime_root 解析并验证，不照抄历史本机路径。
4. 新代码与新 Canary 字段分两阶段启用：先保持 Canary OFF，让新 release 启动并取得 succeeded + identity receipt，成为可验证的 known-good；随后再验证和启用该版本支持的完整 Canary 配置。共享配置还须与仍运行的 Feishu/Learning 解析器兼容；本次只授权 Web，就不因 convergence 的 lagging 派发其他服务重启。
5. 准备可恢复的“代码 + 配置”组合：保留原配置的安全备份、SHA、owner/mode 与目标版本；验证目标和回滚版本各自能读取将使用的配置。当前自动 rollback 若只回退代码，不宣称它已恢复配置。首次部署新字段时可使用双方兼容的 OFF 配置；若失败后要还原配置，使用备份及当前 SHA 校验，避免覆盖并行修改。过期或已消费的授权不延期、不换 ID 重发，也不借普通无预算会话绕过。
6. 用现有受管 service_control update/restart 接口或当前源码确认过的官方 CLI 执行，固定 target、根路径和 CAS expected-generation（接口支持时）。保留 action_id 与 desired identity。外部控制器使用现有 detached worker；在被重启的 Web 自身会话中，提交动作后结束该 run，交接到外部观察者按 action_id 轮询。waiting_for_requester_exit/accepted 不等于成功；不要靠旧 Web 会话里挂一个 wake 就承诺一定会恢复续跑。
7. 只观察同一 action 到终态。succeeded/confirmed_ok 后核对 actual live SHA、generation、PID、启动时间、身份/健康回执，Web 还必须检查 `/auth/status`、`/health`、`/ui/v2/` 与实际浏览器入口（单个 HTTP 200 不证明目标功能生效）；以部署身份切窗读取日志，同时确认未授权相邻服务的 PID/manifest 未变。HTTP 303/308 可能是正常重定向，应核对预期目标；单个 HTTP 200 不证明候选已生效。
8. 失败时先读取该 action 指向的完整日志和启动异常，记录 stage_fact、实际解析配置及 source binding，再修已证实缺口。若程序已自动回滚，先核对其 recovery_action，避免再派发重叠重启。坏配置导致稳定版本也无法启动时，保存备份后关闭/还原对应配置，再通过受管流程恢复，禁止裸改 release 或循环重启试运气。
9. 记录使用是可选项（RULE-AI-29 已撤销强制 record_use）：确有复用价值时再用 method_manage(action=record_use) 记下实际选择与 action/receipt 证据；只读接收方法不能冒充 applied。多次复用时继续检查 freshness 与当前代码契约，不自动 qualified/active，也不把重启成功推论为知识消费或任务收益已通过。

## Stop conditions
- 目标启动配置或回滚组合不合格：停在停服务之前，修正配置后复验；不要为了继续而放宽安全校验。
- 动作仍 accepted/waiting/running：继续观察同一 action；达到事先约定的观察期限后交付 action_id、现状与缺口，不再承诺“20–40 秒必成功”。
- 到达 failed/cancelled：读取精确失败回执，停止无诊断重试。遇到 CAS/配置并行变更，重新读取当前事实。
- 没有新物理额度授权，或现有授权过期/耗尽：停止 Canary 调用，服务恢复与额度重新授权分别处理。
- succeeded 且 identity、健康、目标入口与相邻服务核验通过：本次重启任务收口；不自动扩大到 Feishu/Learning 或后续模型实验。

## Verification
每次使用前重读当前目标版本的 runtime/resolver.py、web/task_budget_canary.py、runtime/service_control.py 与 scripts/restart_mirror.sh 中适用契约，执行只读完整配置检查；它们可能随版本改变。记录当前 snapshot SHA 与变更集合。
旧事故的证据：gen213 action svc-4b332a1f7c7d4ec3b857062f3d8c93d9 failed；gen214 recovery_action svc-f8d50045ddd64644bc3b63dd7ee6a99c failed；配置恢复 action svc-4b0595ab7a0a4ebf9979588a1688cb7e succeeded/confirmed_ok，gen214@14352cc6f，PID 85960，2026-10-09 19:25:30 +08:00 启动，Feishu/Learning manifest 未变。
2026-10-26 修复后独立 Host 审查 PASS/P0/P1=0、原版 R9 exit 0（已知红数对账通过）；Gen 322 两次失败分别为不同 Git 公共目录 `dual_root_rejected` 和 WebUI `dist` 为空；最终本地 main `2cf3ada5ed0040f543eced0a742eabfe00ff38b8`，发行产物 66 文件、official verify ok:true Gen 323，Web-only action `svc-2fee46dc41e04067b8a1c29dc807c753` 真正 succeeded/confirmed_ok，/auth/status 与 /ui/v2 返回 200，Feishu/Learning 原 PID 未变。
这是一条真实事故恢复证据；对“完整预检能在停服务前拦住所有启动错误”的全面覆盖仍需后续独立验证，不能把方法候选直接提升为普遍有效结论。

## Counterexamples
- 单机开发进程，没有受管 release/Canary/共享配置：不套用整套发布流程；按该进程实际契约检查并重启。
- 只读询问服务状态：先返回权威 status，不因此触发重启。
- 目标是纯重启已发布代码、配置未变且实际加载校验已有新鲜回执：复核回执身份与当前性即可，不重复全量 CI/重新发布代码。
- 目标配置没有 Canary：只检查它实际使用的启动依赖，不凭空添加代理或授权文件。新 release 的 WebUI 产物校验只对需要启动 Web 的范围强制，不能对 Feishu/Learning 的纯查看无关加门禁。
- 已证实故障为进程崩溃、端口冲突或资源问题：按该 action 的证据诊断；不把每次失败都归因于相对路径或代理。
- 发布与新额度已获当前用户明确授权：按权限继续执行；不要把历史 operator-only 描述变成额外逐步审批。
