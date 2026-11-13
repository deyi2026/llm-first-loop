# M1 T1 真实执行预算与写入策略冻结 v2

状态：**准入冻结 / 待能力验收**。本文件不是开发或发布资格，也不是自动打开预算授权。

## 范围、身份与继承

- 父 Goal：`cc85f7c4-7e19-49fb-ade3-91186ace3799`；LFL Goal：`GOAL-20261113-b6d17fa0`。
- 首批只做一个 **FX05 合成资料文稿修订** 纵切：已有文件快照、精确 CAS 定点修改、结果 SHA / 段落不变性、停止后拒绝写入、断点恢复需重授权。
- 开发者：唯一 LFL `glm/glm-5.3`；最多三名独立只读调查员，独立 Reviewer 不参与实现。禁止真实外发、公开发表、跨仓写入与生产故障注入。
- 干净工作树：本工作树从 `origin/main` `93d009878412db15495aecaf19db9970eb850fad` 精确创建。旧原型 `m1-t1-writer-20261113`、其两次提交、失败尝试、预算补偿及 `bgt-t1-m1-002` 的持久 `stop_requested` revision 27 **只读保留**，严禁解锁、reset、删除或计入新成功率。
- 目标主机：本次连接的 Mac；仅发布审核通过的 Web、Feishu、Learning、WeCom（service_control all 物理仅覆盖前三个，WeCom 必须独立重启）。生产现状 gen 407 / 55e9e810c，未发生本项目发布。

## 新预算根的独立上限

- 每个**全新持久预算根 / exact Session / exact Run generation**：物理 Provider attempts ≤3，实际 Tool invocations ≤200（当前 FX05 原型进一步收紧至 ≤8），payload bytes ≤2 MiB，运行窗口 ≤30 分钟，GLM 单模型，不允许递归子代理、wake、shell 写入与跨工作树写入。
- 总输入+输出 token ≤400,000，**包含缓存命中的输入**，不能减去 cache-hit 再声称未超限。费用未知时费用判定为 unknown。
- 真实 Token 口径以 Provider 返回用量和 Host `request.usage` 的可验证物理请求回执为准。必须证明完整性和去重；缺用量或对不上时，立即 `stop_requested`，标记 unknown，不允许估计值 `usage_complete=true`。
- Provider 发送之前必须使用有期限、单用户/单 Run 绑定的 `TaskBudgetExecution` 做原子 reserve + dispatch，真实工具 Registry 在**副作用发生前**完成工具 allowlist/额度检测。离线 `t1_budget_gate.py`、提示词、聊天消息、Web 旁路代理或仅事后统计都不构成真门禁。
- 单次请求的 token 尚未从 Provider 回来，必须在发送前使用**保守可证明的请求上界**（例如 JSON payload UTF-8 bytes + 允许输出 tokens + 协议余量）预占完整上界，使任何一次回复后不能超出冻结额度；前置字节额度和 Provider max_tokens 均须有生效证据。无法证明则该请求拒绝，不回退到无预算通道。当前试验脚本采用 (2×canonical JSON bytes+8000) 的输入 token-equivalent 预占，**尚未证明与智谱 tokenizer 的严格上界关系**，因此这只能作为保守代理上界，不能宣传为经证明的全量 token 硬限。
- 新预算授权不可继承旧根；停止、超限、Session/进程中断后旧预算不可重新激活。重新执行需要独立新 Root 和明确准入。保留真实物理未知负债，不能用 `stop_requested` 当作远端取消/结算证明。

## 写入与证据准入

- 只准在该隔离树内使用 `read_file(snapshot=true)` → `edit_file(expected_snapshot_ref=...)` 对已存在目标进行原子 CAS。新文件需要经过工具 schema 确认的 create-only 路径；不存在则本批先使用 Git 已跟踪的固定 FX05 初稿，不能以 `/tmp/*.py` + `execute_command`、here-doc 或隐蔽替代姿势规避。
- 写前核 `Goal/Task claim`、权限、当前预算 phase/余额、Run/Session 绑定、快照 hash、目标目录；写后读真实字节、验证段落内容、SHA、一次性标注 attempt 身份。人工独立复核而不是执行者自称 PASS。
- 禁止将可变预算 ledger（运行态状态文件）混在受审 Git tree 中；另存于持久运行数据目录，候选只引用固定 receipt/hash/snapshot，避免预算 `request_stop` 导致候选 SHA 漂移。审查前冻结完整补丁集和 evidence；候选变化必须重新审查。
- 新样本默认 1 个 FX05 attempt，不沿用旧 8 fixture + 2 repeats 的成果为合规证据。M1 单例通过后再决定扩到 N/F/R，不用追加样本美化成功率。

## 闸门与部署

1. **先证实真门禁已接到实际 GLM Provider/Registry dispatch 并完成超额/撤销 fail-closed 演练**。若当前 Web canary 默认 OFF 或固定 profile 不支持允许写入的真实预算，不得靠改预算文件或把开发会话的无限流量标为预算受控；要么在隔离服务实现并验证最小桥接，要么停在 HOLD。
2. LFL GLM-5.3 单一 writer 只修改隔离树；独立 Reviewer completed/PASS/P0=P1=0，候选 SHA/审查范围一致。
3. 原版完整 `bash scripts/ci_gate.sh --release` 真实 exit 0；再受审查 push 候选 branch，核远端精确 commit CI；保护本地 main 脏修改，按仓库流程隔离集成 main 并核最终 tree。
4. Mac 以现有 source_checkout 受管发布合同为准，wheel 仅在切换至 wheel_release 被独立批准时才是硬约束；需核 WebUI artifact / source SHA / 配置指纹 / desired-live-stable / PID / health / idle / barriers。`all` 之后 WeCom 单独受管 restart，确认四服务实际加载身份，失败按受管 rollback 并产生新 generation。

**根本裁决：保证实际能力，不为完成流程指标新增第二套框架。不能机械证明的预算维度标 unknown，且严格拒绝把不合格候选发布为合格生产版本。**

## 2026-11-13 真实执行的结果与仍缺资格

- Mac 现有权威 Provider registry 的 GLM 配置在生产 data 目录，不在隔离目录。首次隔离引擎仅继承旧 DeepSeek 合成注册表，但显示模型标签 glm/glm-5.3；已在进程内先加载 Mac 真实注册表并重新绑定模型路由，验证 provider=glm / model=glm-5.3 / HTTPS host=open.bigmodel.cn。不能把错误标签路由当 GLM 真值。
- 新预算根首次实测产生 1 个真实 Provider physical dispatch reservation，input_token-equivalent 预占 28,098、output_token 预占 6,000、payload 10,049 bytes；Provider ReadTimeout 120 秒，无有效 usage、工具 0，最终根 stop_requested、未知负债不退费。
- 第二个**独立新根**使用 GLM-5.3 的 low reasoning_effort，仍在 180 秒 ReadTimeout，无有效 usage、工具 0，预算根 stop_requested。两次 FX05 源文件 SHA 均保持 ad44484566051fad39f12ba070dfe95738677cc1118a31d7f4dfdb9b12a2a1ab；**未完成真实文稿修改**，不得将试验计为通过样本。
- 无密钥 GET/HEAD 连通性检查对 open.bigmodel.cn 返回 HTTP 401（说明 DNS/TLS/HTTP 通路可达，不证明模型推理可用）。出现两次真实 GLM 超时后不无限重试；后续须先取得有效 GLM 回应和可信 usage，再申请 M1 开发验收。
- 原代码相关 TaskBudget 契约定向回归 55 passed；新 M1 预算 reserve/stop/allowlist 四项测试 4 passed，ruff/pyright 通过。这些只证明本地模型尝试前的 CAS 和工具拒绝面，不是 T1 内容完成、F18 端到端或正式 R9 的证据。
