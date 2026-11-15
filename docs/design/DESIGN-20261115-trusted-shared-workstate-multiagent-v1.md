# LFL 可信共享工作状态与多 Agent 协同执行：差距审查、P0 最小补修与拷问设计 v1

- **日期**：2026-11-15
- **状态**：隔离候选 / **P0-3 受管 execute_command 沙盒补修已实现并完成 Mac/Deepin 临时数据真实负向验证**；仍为 **NO-GO**（none 不隔离、Docker 未真运行、其他文件写入口未统一核验；独立 GLM-5.3 Reviewer、完整 R9、远端 CI、main 集成与受管发布均未完成）
- **上游设计**：`docs/design/DESIGN-20261112-task-intelligence-execution-v2.md`；`docs/design/DESIGN-20261101-cross-session-coordination-v1.md`
- **开发安全基线**：`AGENTS.md`、`docs/DEVELOPMENT_REPAIR_SAFETY.md`；模型做语义判断，程序只守身份/授权/协议/预算/不可重复副作用
- **代码基线**：本地 main `9483fd8975412f8330f62e70fca5ac508164a5fa`，隔离工作树 `/private/tmp/lfl-trusted-shared-context-p0-20261115`，分支 `fix/trusted-shared-context-p0-20261115`
- **远端对账**：观察时 origin/main `55d269897`；本地 ahead 7 / behind 3。两者不能互认，更不能用本地测试替代远端精确 SHA CI
- **生产声明**：仅通过 SSH 在 Deepin 的 /tmp 自动清理假账本执行 bwrap 探针，未修改 Deepin 生产源码/配置/服务/账本；未核 live SHA，不宣称生产已修复；未发 Provider 调用、合并、push、重启

## 0. 一页裁决

**方向**：不是建设一个“Agent 群聊/Topic 数据库”，而是把已有 Goal/Task/TaskClaim、Evidence、Journal、TaskBudget、Method/Experience 接成**按需、最小权限、可精确恢复**的共享工作视图。共享视图是派生物，不能变成新的权威账本，也不能靠 prompt 代替授权。

**本次唯一代码问题族**：跨会话 Goal 写入授权边界。它属于灾难性安全/数据完整性硬边界，不能交给模型自我判断。

**已核 P0-1**：`goal_coordination._override_authorized` 仅检查 `cross_session=true`、非空 `reason`、非空 `evidence_refs`，将模型自报理由当成授权。已有测试用 `evidence://v1/deadbeef` 并期望越权 checkpoint 成功。

**拷问新增 P0-2**：`run_create_goal` 原先优先采用模型提供的 `session_id`，即使无运行时 session binding 也可创建指定归属的 Goal。这是同一身份信任边界的第二个漏洞。

**拷问新增 P0-3（本轮已在隔离临时目录物理复现）**：`execute_command` 的 macOS `sandbox-exec` 策略默认允许写整个工作区；若 Goal 审计账本位于该工作区下，模型可通过 shell 直接修改账本，绕过 `checkpoint_goal` 的归属门。实验仅创建并修改 `.worktrees` 下自动清理的假 `data/audit/goals.jsonl`：`sandbox_exit=0`、`audit_file_changed=true`，**未触碰生产账本**。此漏洞使本次工具层修复只能称为**防误用改进**，尚不足以宣称跨会话数据隔离 P0 收口。

**P0-3 二轮拷问与修订**：仅追加 Seatbelt `deny subpath(audit)` **不够**：真实 Mac 临时实验中 `mv data data_renamed && append data_renamed/audit/goals.jsonl` exit 0 且修改成功；预先存在的 hardlink 别名也 exit 0 并修改原 inode。修订为 **deny audit subtree + 所有祖先 literal 写操作**，普通 sibling 写入仍通过；spawn 前对受管审计树逐项 lstat，发现硬链接 `st_nlink != 1` 或关键账本 symlink 即拒绝。Mac 真实 `ExecuteCommandTool` 假账本写入 failure，正常文件写入 success。

**Deepin 实机验证**：在 `Deepin 验收主机` 的 /tmp 自动清理临时工作区中，bwrap 的 **仅 audit 只读覆盖层也不够**：`mv data data_renamed` 可以成功，造成原审计路径消失；但挂载仍只读。修订为 **workspace rw bind → 祖先目录 rw 自绑定（固定 mountpoint）→ audit ro-bind**。Deepin 原生命令实测：直接写、符号链接、父目录重命名、硬链接新建、umount 均拒绝；`data/sibling.txt` 写入成功。随后把**本隔离候选的实际 `sandbox.py` 源文件**仅复制到 Deepin /tmp，动态生成 bwrap argv 再真跑，得到 `EXACT_CODE_DEEPIN_BWRAP_PASS`（direct/symlink/parent_rename/hardlink_create 全拒、normal 成功）；临时目录已清理。测试仅涉及假账本，无生产写入。

**Docker 与 none 边界**：Docker 使用相同祖先 mountpoint 固定 + audit readonly bind，已有 argv 结构测试，但 Deepin 没有本地镜像，因此**未做真实 Docker 容器验证**；`none` / `auto→none` 明确回执“审计账本未受沙箱写隔离”，仍不具备强制 ACL，严禁用其声明 P0 闭环。其他文件工具、宿主身份与跨入口读写仍需独立核验。

**拷问新增 P1-1**：`session_unverified` 与 `owner_unknown` 的写侧放行不能证明归属。当前 `data/audit/goals.jsonl` 只读统计为 296 条、77 active、ownerless 0 条（观察时快照，非长期不变量），因此本轮改为只读 HOLD，历史迁移另设人工通道。

**拷问新增 P1-2（并发完整性）**：`GoalStore._file_lock` 在 `fcntl.flock` 抛 `OSError` 时明确 fail-open，继续执行写入。隔离临时账本通过 mock 锁获取异常复现：`lock_acquire=forced OSError`、`write_succeeded=true`；这尚未证明实际并发丢更新，但证明了并发锁失败时没有硬停止。后续单独补 fail-closed 与多进程负向测试，不与本次跨会话身份补修混成一个大提交。

**工具层最小修订**：同 owner + 可信运行时绑定才允许 Goal 写入；其它情况拒绝、原因码明确、给可执行的 owner 会话出口；不引入新存储、不添加审批 token、不改变任务图或完整证据源。模型提供的证据仍可供人工判断，但不自动变成权限。

## 1. 事实与未核范围

| 需求 | 已有权威源/机制 | 本轮处理 |
|---|---|---|
| 共享工作状态 | GoalStore/TaskStore/Checkpoint/coordination_status | 复用，禁止第二套 JSONL |
| 多任务并发 | TaskClaim + generation fencing，默认 warn；GoalStore flock 失败可降级无锁写 | P1-2 另设最小补修，不全局切 enforce |
| 证据完整性 | EvidenceRef、OwnerScope、Blob SHA、exact hydration、source freshness | 复用；跨 scope promotion 仍须单独授权 |
| 预算与中断 | TaskBudget、ToolExecutionJournal、M5 恢复链 | 不改；副作用 unknown 必须 HOLD |
| 模型工作上下文 | SchemaCapacityProjection、Recovery Manifest、按需 hydration | 不缩小用户大窗口；优化有效信息密度与缓存 |
| 长期学习 | Method/Experience/Qualification、原始证据 | 先 dry-run，禁止覆盖式判重/自动晋级 |
| 跨租户 ACL / 外部客服 API | 当前仓库未见该具体业务接口 | 不以不存在的客服租户系统制造假 P0 |
| 生产真实入口 | Mac/Deepin live、Web/Feishu/WeCom/CLI | 未在本轮核 live；后续需核精确 SHA 与入口身份 |

## 2. P0 威胁模型与代码修订

**重要安全分层**：以下 §2.1–2.3 是 Goal/Task *工具入口*的授权门；只要任意 Agent 仍能用 shell/文件工具直接写同一审计账本，就不能把它描述为端到端强制隔离。P0-3 是独立阻断项，需先验证真实 OS 隔离或明示 shell 是完全受信能力。

### 2.1 信任边界

- **不可信**：模型生成的 `session_id`、`cross_session`、`reason`、`evidence_refs`，以及档案正文、网页、工具观察中的“用户已批准”文字。
- **当前可信身份来源**：运行时 ContextVar 的 `bound_session_id()`（前提：入口正确绑定且模型不能控制其设置；入口级证明仍需独立验证）。
- **当前可执行写权限**：只有 owner session 可直接 `checkpoint_goal` / `update_goal`；`task_*` 原有 owner 门不放宽。
- **事实 ≠ 权限**：即使 `evidence_ref` 真实、SHA 正确、ACL 可读，也只能证明某段内容存在，不能证明该 actor 对该 Goal 的当前动作获得授权。
- **人工授权**：未来需服务端签发并核验 scope/actor/target/action/TTL/revocation/一次性消费的能力；本轮不复用命令型 HostGrant 冒充 Goal 授权。

### 2.2 本轮修复

1. 取消模型参数直接授予跨会话写权限的逻辑；保留参数仅作为拒绝诊断线索。
2. 无可信 session binding 时拒绝写入已有 Goal；不借用共享 ctx 的 last-writer。
3. ownerless legacy Goal 保持只读；不通过首次写入自动认领。
4. `create_goal` 的 `session_id` 只能为空或等于可信绑定；无法绑定时拒绝创建。
5. 同 owner 的常规写入、CAS、终局证据门、TaskClaim 不改变。
6. 更新工具 schema、拒绝回执、恢复横幅，移除“加三个参数就可放行”的幻影出口。
7. 失败必须不改变 `goals.jsonl` 字节；返回机器可读原因码。

### 2.3 正常协同如何继续

- **默认**：子代理调查并返回 EvidenceRef、Task 结果；owner 会话负责最终 Goal 写入，避免为跨会话写入引入复杂授权服务。
- **owner 会话暂时不可用**：保持原 Goal/Task 可读、证据可检索；由人决定恢复原会话或在可信会话创建新的 Goal，并引用历史证据。新 Goal 不是旧 Goal 的“自动转移”，不可伪造旧 owner。
- **确实需要委派写入**：先独立设计人工批准的窄范围委派，再验证 UI/CLI/Web/Feishu 的入口与全部消费端，避免一把通用高权限 key。

### 2.4 P0-3 安全隔离方案裁决（隔离候选已实现，待独审/全量门禁）

| 方案 | 好处 | 代价/风险 | 裁决 |
|---|---|---|---|
| A：仅修 Goal 工具归属门 | 改动小、兼容好 | shell/直接文件写可旁路；**不满足安全闭环** | 仅作当前候选，NO-GO |
| B：执行沙箱对 audit/授权/账本根强制只读，服务进程受管写 | 保留 Agent 正常修改业务代码，防任意 shell 篡改账本 | Mac/Deepin 已真测；Docker 仅构造；none 不隔离；其他文件工具未统一验证 | **已实施隔离候选，未获生产准入** |
| C：将状态存储迁到隔离服务进程/独立 OS 身份 | 物理边界更强、跨租户扩展好 | 重构大、迁移/回滚复杂 | 当前不做，只有 B 无法证明时再评估 |

B 的最小验收：Mac sandbox-exec 和 Deepin bwrap 的假账本写入均拒绝、业务 sibling 写入成功（已真测）；Docker 未验证不得宣称已验收；none 不得宣称隔离；硬链接预检、符号链接、祖先重命名、工作区外根和 host-grant 绑定有对应负例。当前仅覆盖受管 execute_command 的 shell/argv/后台共同沙盒接线，其他文件写工具仍是端到端安全评估缺口。禁止通过字符串黑名单拦 shell 命令冒充隔离。

## 3. 14 轮拷问：反方质疑 → 裁决 → 必须补的验收

| # | 反方拷问 | 裁决及边界 |
|---|---|---|
| Q1 | 这是真漏洞还是仅理论风险？ | 单测可复现真实工具写入；未证明外部未认证攻击可达。按可触发的权限边界缺陷修，不虚报外部入侵 |
| Q2 | 校验 `evidence://` 是否存在就够了吗？ | 不够。证据的存在、可读、当前有效和授权批准是四个不同事实 |
| Q3 | 直接加“请遵守 owner”提示能解决吗？ | 不能。授权必须在工具写入前由程序检查 |
| Q4 | ownerless/无 binding 一律拒绝会不会让旧任务无法续接？ | 有兼容成本。当前账本 ownerless=0；历史未知保留只读，人工迁移而非静默写 |
| Q5 | 能否复用 EscalationStore/HostGrant？ | 不能直接把命令授权令牌当 Goal 权限；其请求类型、绑定域、跨进程验证和消费端必须逐一核验 |
| Q6 | owner 会话失联时，是否自动接管？ | 不自动。可恢复原会话；若无法恢复，用户明确批准新 Goal 承接，原证据不覆盖 |
| Q7 | Goal CAS 与 TaskClaim 是否重复？ | 不重复：CAS 防状态覆盖，TaskClaim 防同一任务执行权冲突；跨 Task 并行不应被 Goal 全局锁堵死 |
| Q8 | Topic 隔离是否可用 prompt 实现？ | 不可。只检索授权作用域；派生摘要的 ACL 不得高于来源 |
| Q9 | 过期事实是不是都应该丢弃？ | 不是。保留历史供审计；高风险执行前回读权威源，普通研究显式标注时效 |
| Q10 | 相似 Method 是否应自动合并？ | 不应覆盖原文。只读候选、版本化 supersede、可逆引用关系，先证明假阳性可恢复 |
| Q11 | 是否默认压缩所有上下文、缩小窗口？ | 不。原始证据先保存，模型按需精确水合；保留大窗口和稳定缓存前缀 |
| Q12 | 为安全增加很多全局闸会不会让 LFL 失去主动性？ | 只对身份、授权、预算、不可重复副作用硬执行；任务语义、检索、委派和策略仍由模型决定 |
| Q13 | shell 能写账本时，工具归属门还有什么安全意义？ | 只能防误用，不能作为强制 ACL。已用临时假账本物理复现；下一批必须修 OS/进程边界 |
| Q14 | 只在 macOS Seatbelt 加 deny 就算完成了吗？ | 不算。bwrap/docker/none、额外可写根和别名攻击仍需独立负向验证 |

### 3.1 第二轮反方追问（尚未解决的设计风险）

1. **审批粒度**：未来委派是否允许 `update_goal(status=complete)`？建议初版只允许 checkpoint，完成声明仍由 owner 或人工收口；需核是否导致真实协作死锁。
2. **审批跨进程**：若授权在 Web 签发而 Feishu/CLI 消费，如何保证密钥/撤销一致？不得复用仅进程内签名的临时审批记录冒充跨进程能力。
3. **消费原子性**：批准一次、两 Agent 同时提交，是否可能两次成功？需在同一受管事务/锁边界内验证一次性消费与目标版本。
4. **身份边界**：ContextVar 是否在全部 Web/CLI/Feishu/WeCom/SubAgent 入口绑定并清理？当前只证明工具内判定，不证明所有入口无污染。
5. **旧 Goal 可用性**：如果生产出现 ownerless 记录，如何只读恢复并让用户选择受控迁移？不能因安全补丁丢掉任务成果。
6. **最小权限**：授权是否能只覆盖一个 Goal、一类操作、一次版本及短 TTL？拒绝“全 workspace 通用”。
7. **审计真实性**：授权申请/批准/拒绝/消费是否与模型写入权限隔离，且异常时 fail-closed？
8. **高风险动作**：即使 Goal 写入被批准，也不能自动授予文件、命令、浏览器或发布权限；各物理执行边界仍需单独授权。
9. **执行沙箱**：审计根是否真正只读？在无沙箱/自动降级、Deepin bwrap、macOS Seatbelt、Docker 和额外 writable_roots 下如何保持一致？
10. **别名攻击**：符号链接、硬链接、目录重命名或 bind 覆盖能否把受保护账本暴露到可写路径？

## 4. 共享状态方案：只增派生视图，不增权威账本

### 4.1 最小投影契约（设计，未实现）

```text
goal_id, goal_version, owner_session_id, generated_at
task_frontier: [task_id, status, claim_generation, dependencies]
facts: [{evidence_ref, kind: observed|inferred|decision,
         source_version, acquired_at, freshness, scope}]
actions: [{tool_call_id, outcome: confirmed|unknown|failed, effect_ref}]
capacity: {projected_tokens, schema_tokens, remaining_budget}
truncated: boolean, next_cursor
```

- 由现有存储**按需查询**派生，默认最小；不得每轮强制注入、不得复制完整会话。
- 所有 `facts` 仅引用真实 Evidence，摘要必须标来源和覆盖范围，不能升格为原始事实。
- `unknown` 是副作用未知而不是失败；中断后不得盲目重放。
- 共享投影应保留稳定、可水合的 ref；分页 `next_cursor` 单调推进。
- 作用域过滤在**取数据前**发生；派生视图不得扩权。多租户若未来接入，tenant 从可信认证上下文注入，不从 ID 字符串推断。
- 不承诺所有 Provider/Tool/Agent 当前都已实现这一投影；先在一条真实多 Agent 任务上验证需求缺口。

### 4.2 学习和判重

只读列出高频使用且证据过期、冲突或重复的 Method/Experience；原文 append-only，索引/推荐可版本化 supersede。优先测假阳性：相似文字但不同适用条件不能静默合并。模型做语义判断，程序保存 provenance、版本和可逆关系。不得全库重写、默认自动推广或用 record_use 冒充效果。

### 4.3 上下文与速度

保留用户选择的大窗口；优化“有效信息密度”，而非强制裁剪。复用 SchemaCapacityProjection 与 Evidence Recovery Manifest；记录 provider-visible request/token、首 token P50/P95、LCP/cache、无效工具调用和精确恢复率。未获得真实同模型同配置 A/B 之前，不宣称 StateBraid、自动摘要或新路由带来净收益。

## 5. 证据、回归与验收

| 项 | 本轮证据 | 判定 |
|---|---|---|
| 代码级 RED | 新增 `test_goal_write_authority_p0.py`，基线 7 failed / 1 passed | 已复现 |
| P0 修复 | Goal 归属判定、创建绑定、工具契约、拒绝回执 | 已写隔离候选 |
| 定向 GREEN | `test_goal_write_authority_p0.py` + `test_goal_coordination_l1.py` + `test_cross_session_acceptance.py` + `test_missing_context_authority.py` | 38 passed |
| sandbox-exec 假账本写入 | 原始允许；仅 deny 子树仍可通过父目录重命名/预置硬链接绕过；修订祖先 literal deny + hardlink 预检后真实工具写账本失败、业务文件成功 | **隔离候选通过** |
| Deepin bwrap 假账本 | 真实 Linux bwrap：只读 audit overlay 可被父目录 rename 移走；补祖先 rw self-bind 后 direct/symlink/rename/hardlink/umount 拒绝，sibling 可写；候选源文件生成的 argv 再验 `EXACT_CODE_DEEPIN_BWRAP_PASS` | **临时目录真测通过** |
| Docker / none | Docker argv 有审计 readonly overlay 与祖先 mountpoint；无本地镜像，未真测。none/auto-none 只给明确不隔离警告 | **Docker 待真测；none 不具强制隔离** |
| GoalStore 锁故障 | 模拟 flock OSError 时写入仍成功（临时账本） | **P1-2 已证 fail-open，真实并发损坏未证** |
| 相关 Goal/Task 回归 | 初轮 602 passed；扩大至 Goal/Task/Sandbox/HostGrant/Factory/跨会话联测：初轮 **735 passed、4 skipped、exit 0**；P1 补修后 **738 passed、4 skipped、exit 0** | PASS |
| Ruff / Pyright | 修改范围 Ruff PASS，目标模块 Pyright 0 errors、0 warnings，git diff --check PASS | PASS |
| 原版完整 R9 | 需独审后运行，未执行 | **未执行** |
| GLM-5.3 独立 Reviewer | 冻结候选后，审查代码/测试/设计完整变更 | **未执行** |
| GitHub 精确 SHA CI | 审查通过并推送隔离 PR 后核验 | **未执行** |
| Mac/Deepin 生产 | 另行受管发布授权与 live SHA/PID 验收 | **未执行** |

### 必须补的负向测试（正式审查前）

- 伪造/真实但无授权的 EvidenceRef 均不能越权；checkpoint 和 blocked/complete 路径都必须拒绝。
- `create_goal(session_id=other)` 和无绑定时自报 session 均拒绝；匹配绑定的旧调用不退化。
- ownerless Goal 不能通过任意 session 的首次写入认领；原账本字节不变。
- 旧任务的同 owner checkpoint、CAS、TaskClaim 与只读视图不退化。
- 无权限时拒绝文案不指向不存在的 `transfer_goal` 或“补三个参数再试”。

## 6. 阶段退出与停机线

**S0 本轮**：只处理跨会话授权与创建身份的 P0，隔离 RED/GREEN，完成拷问设计与变更登记；不碰其它并行问题族。

**S0.5 沙盒补修**：方案 B 已在隔离工作树实现，Mac/Deepin 临时账本真测通过，Docker 仅 argv，none 明示不隔离。进入 Reviewer 前须明确审查范围：只允许宣称受管 execute_command 在有效沙盒后端下受保护，不能宣称所有物理写入口均已保护。

**S1 独立审查**：冻结候选 SHA、精确 diff；GLM-5.3 只读 Reviewer，P0/P1=0，P2 有明确处置；若发现权限回归，先最小补修、重新冻结。

**S2 完整门禁**：原版完整 R9 exit 0，不改 baseline/豁免掩盖失败；随后 GitHub PR 精确 SHA CI，再考虑 main 集成。主线目前 ahead/behind 分叉，必须重新核实其它并行提交与冲突。

**S3 功能试验**：选一条真实长任务多 Agent 协同样本，B/B′ 同配置噪声地板 + 按需共享视图候选；没有可复现净收益就不继续扩架构。

**S4 生产**：仅在明确受管发布授权后按精确 SHA/服务代际发布并验证，不因本报告或本地测试自动重启 Mac/Deepin。

**停止线**：P0-3 未关闭不得声称跨会话安全闭环；不得把“模型给出的证据”当权限；不得以新的共享状态覆盖原始证据；不得因安全修复静默丢旧 Goal；不得把本地 GREEN 说成生产已生效。

## 7. 独立 GLM-5.3 审查（第一次 REVISE）与收敛记录

- **冻结输入**：候选 `52ddc7e8b1112c415ae57e89162ec326b1c54b8f`，完整 16 文件补丁 SHA-256 `a69da1736c2915fdf52c0197d06e0099dfc6d68588d21e45a8c5d235126eed60`。
- **Reviewer**：真实 `glm-5.3`、独立只读无工具 HTTP 请求；首次请求 `finish_reason=length` 且最终正文 0 字，**不算审查**。第二次显式 `reasoning_effort=low`，`finish_reason=stop`，获得 `VERDICT: REVISE / P0=0 P1=3 P2=4`。不借旧 SHA 的任何 PASS。
- **P1-1（审计目录非关键 symlink）**：Reviewer 提议“一律拒绝任意 symlink”，但本机真实审计树只读统计有 10 个历史 Provider 配置文件 symlink（两个去重目标），直接拒绝会让所有正常命令失败。最小兼容修订：关键账本 symlink 拒绝；其它 symlink 若指向**审计根外常规文件**，把解析后的目标也加入只读保护集合（Mac final deny、Linux/Docker 文件 ro-bind）；目录/悬空目标拒绝，目标硬链接拒绝。Mac 实测目标经审计 symlink 与直接路径均写失败；Deepin 候选源文件真实 bwrap 运行 `DEEPIN_SYMLINK_TARGET_E2E_PASS`，普通业务文件仍可写。
- **P1-2（TOCTOU）**：Reviewer 指出 preflight 到 spawn 的可信宿主并发修改窗口。不能用多线程进程中的 `preexec_fn` 或“spawn 后再 kill”冒充原子隔离。现阶段明确边界：**不可信子进程自身**不能在沙盒生效后 rename 受保护父目录/新增硬链接；**可信同 UID 宿主进程**可在 preflight 与 spawn 之间修改 inode/路径，此竞争不在本次物理隔离承诺内。每次沙盒回执增加机器可读 `audit_toctou=trusted_host_race_not_closed`；不宣称绝对 TOCTOU-free。未来若要求跨受信宿主进程的强隔离，应使用独立 OS 身份/服务进程与 fd/事务绑定，非本次最小批次。
- **P1-3（Linux 真实 e2e 的 CI skip）**：Mac 运行 Linux bwrap 用例会显式 skip，不能计为 Linux PASS；新增 `LFL_REQUIRE_REAL_BWRAP_AUDIT=1` 资格开关，启用后缺少 bwrap/内核 userns 即测试失败。Deepin 已在真实 bwrap 中用本候选 `sandbox.py` 构造 argv 做临时目录物理验证，但不冒充“GitHub CI 已在 Linux 真跑”。
- **P2 处置**：audit preflight 是 O(n) 元数据扫描（本机约 1.6 万目录项，热缓存观测约 0.13–0.52s/次）；为保证已有 hardlink 的 fail-closed 不引入不安全缓存，先接受该成本并纳入后续性能 A/B。Docker `--mount` 保护路径额外拒绝逗号/冒号，尚无现成镜像，仍不宣称 Docker 真测；CLI/WeCom 等身份绑定需独立入口验收；Mac 祖先 literal deny 的作用域按现有真实测试限定，不夸大。
- **再审门槛**：上述改动必须形成新的冻结 SHA，重新由独立 Reviewer 审查，取得 `PASS/P0=P1=0` 后才可运行原版完整 R9。**第一次 REVISE 仍是历史事实，不得擦除或改记 PASS。**
