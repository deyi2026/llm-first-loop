# Deepin LFL 沙盒外路径授权闭环：P0 最小实施补充

状态：设计候选，**未实现、未独立审查、未发布**。2026-11-14。继承 `DESIGN-20261107-linux-managed-upgrade-restart-sandbox-authorization.md` §6 和 `LFL_Sandbox_Escalation_Audit_Requirements_Design_2026-11-06.md`。

## 现场证据与根因

- Deepin 25 x86_64 的 bwrap 真实执行成功，系统根目录只读；LFL `EXEC_SANDBOX=auto` 解析为 bwrap。
- 现有 `escalation_request` 只接受 CatastrophicGuard 已阻断的命令；普通沙盒外路径访问无法形成待审批申请。
- `HostCapabilityGrantStore` 已在 `tools/escalation.py` 实现并有并发/重启/撤销测试，但未接到 Web 审批、文件工具或命令执行。
- `sandbox_argv(..., writable_roots=...)` 在 Linux bwrap 分支明示忽略外部根；Web UI 批准灾难命令不等于 OS bind mount 放行。Deepin 临时目录实测：工作区内写 `exit 0`，外部默认写 `exit 2`，传入 `writable_roots=[outside]` 后外部仍 `exit 2`；未触碰生产文件。
- Web 的人类审批必须具有可信身份。回环网络来源不能证明请求来自人；未配置人类登录时，新能力申请/批准必须 fail-closed。现有 `request_auth_required` 对可信 loopback 返回 false，`POST /auth/login` 因此直接返回而不签发浏览器会话；新授权必须补齐**回环下显式人类登录**，不能只设置 `WEB_AUTH_REQUIRE=1` 就宣称已认证。

## P0 目标（只解决可复现阻断，不重造权限平台）

1. 新增 `host_access_request`（独立于灾难命令的工具入口）并复用现有 Web 右侧提权列表、详情和审批事件。申请内容由服务端冻结：`session_id/run_id/tool/cwd/operation/canonical_path/command_or_file_effect_sha256/ttl/max_uses/justification`。默认单次、最长 10 分钟；外部路径绝不靠模型自报获得权限。
2. 审批仅接受可验证的**人类浏览器登录会话**；Bearer-only、无登录的 loopback、子代理、自动化客户端不能批准。必须支持 loopback 下显式登录并签发 HttpOnly 会话 cookie（现有普通浏览免认证行为不得冒充登录）。缺少浏览器登录配置时返回明确 `human_auth_required`，而不是放宽到回环免认证。任何令牌不返回给 Web 列表或模型日志。
3. 人类审批后复用 `HostCapabilityGrantStore` 持久签发/核验/消费/撤销；使用前复核操作、工具、会话、精确路径、有效期、版本/签名、父会话 write-scope、CatastrophicGuard 和运行时隔离策略。不得跨会话复用或扩大子代理权限。
4. 首批仅支持**当前用户权限内的单个既存文件或明确指定目录**的 read/write。write 必须额外绑定预期文件版本或可审阅变更；create/delete、递归目录、网络、system admin 留待单独设计和验收，不以通用 shell 绕过。
5. 对 bwrap 生成精确 `--ro-bind`（read）或 `--bind`（write），目标不存在、symlink/`..`/glob、路径替换、不可安全创建挂载点时拒绝；不把整个 `$HOME`、`.ssh`、凭据目录或 `/` 作为可写根。不得使用 `EXEC_SANDBOX=none` 解决授权问题。
6. 执行与授权分开：获批后仅为该操作新建受控子进程/确定性 FileService 事务，记录执行终态与输出校验。申请/批准/消费/执行/失败/撤销均可追溯；UNKNOWN 不自动重试危险写入。

## 关键安全边界

- 用户级 systemd 管理不需 sudo；修改 `/etc`、安装系统包或系统网络规则不能由 host grant 提权。此类请求需独立受信 polkit helper，默认不实现。
- 不修改现有灾难命令审批语义，不用其令牌冒充文件授权。
- `HostCapabilityGrantStore` 是唯一持久 grant 真值源；不引入第二授权账本。
- 不允许“批准了路径”绕过 parent write-scope；如果父 Run 范围不包含目标，需同一可信人工审批事务明确授予**精确子范围**，否则拒绝。不可通过静默扩工作区完成。
- 未启用人类身份认证时，功能可发现、可解释，但不能自批准或执行。

## 最小验收矩阵

- 正向：Deepin 两个专用临时目录，默认工作区内写成功、外部写拒绝；申请出现在 Web、人工批准后只对指定文件的一次写成功，核对字节/SHA/审计；重启后未过期授权仍可验证。
- 负向：无认证 loopback/Bearer 自批准、未批准、过期、撤销、重复消费、跨 session/tool/cwd/command/path、目录扩大、symlink 替换、路径竞态、父 write-scope 拒绝、bwrap 不可用、OS ACL 拒绝均不得执行。
- 稳定性：审批后取消、进程崩溃、UNKNOWN、持久 grant CAS 并发与审计链断裂 fail-closed；Web 显示真正阻断层及原任务恢复入口。
- 门禁：先 P0 专项/前端 E2E，独立 GLM-5.3 Reviewer `PASS P0=P1=0`，再原版完整 R9 exit 0；受审查分支和远端 CI 通过后合入 main。Deepin 仅用新的不可变 wheel 受管发布并核验 live identity，不覆盖旧 release。

## 实施路径

优先复用：`src/llm_loop/tools/escalation.py`、`tools/builtin/escalation.py`、`tools/builtin/execute_command.py`、`tools/sandbox.py`、`web/routes.py`、`webui/src/components/sidebar/EscalationCenter.tsx`、`factory.py`。先做端到端 P0 单文件授权，随后根据真实失败决定是否扩到 FileService/目录/创建删除；不得在首批一并重写升级器或系统管理员权限。

---

## §7 P0 实现决议（fix/deepin-host-grant-p0-20261114，候选冻结）

> 本节由实现会话在隔离工作树追加，记录 §1-§5 到代码的精确映射与偏差说明。
> 设计正本（设计 worktree HEAD 9f30b8a42）未被修改。

### 7.1 组件映射

| 设计决议 | 实现 |
| --- | --- |
| 新工具 host_access_request（服务端冻结申请） | `src/llm_loop/tools/builtin/host_access.py`；冻结字段写入 EscalationStore 记录 `request_kind="host_grant"` + `host_request` 嵌套 dict（operation/canonical_path(realpath)/file_sha256/command_sha256/cwd/session_id/ttl_s/command_text） |
| Web 右侧列表/详情/审批事件复用 | EscalationStore 记录直接进入既有 `/api/v1/escalation/list|detail|review`；command 字段承载人类可读摘要 `[host-grant:op] path …`，展示-审批绑定（expected_sha256==command_sha256）复用 |
| 审批仅人类浏览器登录会话；loopback 不能自批 | `routes.py` review 端点：`request_kind=="host_grant" && channel!="web_session"` → 403 `human_auth_required`（loopback 未登录与 Bearer 均拒）；灾难命令类审批语义**不变**（回归测试保护） |
| loopback 下显式登录签发 HttpOnly cookie | `auth_routes.py`：GET /login 在 loopback+无有效会话时显示表单（原为 303）；POST /auth/login loopback 下浏览器表单提交（非 JSON）走完整验证+签发；JSON 带密码 → 400 `explicit_login_browser_only`（防自动化通道铺路）；JSON 无密码维持零打扰短路（零回归） |
| 复用 HostCapabilityGrantStore 持久签发/核验/消费/撤销 | `issue()` 增 `request_binding`（command_sha256/cwd/file_sha256/request_id → `policy_hash`）；新增 `peek()` 只读快照（消费方先取路径再消费）；`consume()` CAS 单次语义不变 |
| 审批→签发原子性 | web 端点顺序：`issue()`（先签发，可审计可撤销）→ `decide(host_grant_id=…)`（原子落决定+绑定 grant_id，**不铸**灾难令牌）；decide 冲突 → 立即 `revoke()` 孤儿 grant；崩溃窗口内孤儿 grant 无记录引用、AI 拿不到 grant_id，按 ttl 自然过期（审计有 issue 记录） |
| bwrap 精确 --ro-bind/--bind + 拒绝 symlink/glob/不存在 | `sandbox.py` `sandbox_argv(..., extra_file_binds=[(host, sandbox, ro|rw)])`：bwrap → `--dir` 祖链逐级创建挂载点 + 精确 bind（位于系统 ro-bind 后、workdir bind 前）；sandbox-exec → rw 追加 writable_roots（ro 读侧 profile 本不限制）；docker → RuntimeError fail-closed；symlink/目录/相对路径/非法 access 在 `validate_file_binds` 拒绝 |
| 不挂 HOME/.ssh//、不得 EXEC_SANDBOX=none | execute_command `_resolve_host_grant`：`_sandbox_mode==none/docker` → 拒；bwrap 缺失 → 提前拒（不浪费审批）；绑定**仅**授权单文件（argv 构造级验证：无其它 bind 追加） |
| 父 write-scope 不可绕过 | `command_scope_guard.check_command_scope(..., extra_write_allowed=frozenset)`：豁免仅作用于扫描器对**绝对路径精确匹配**的授权单文件（root 边界/allow 匹配跳过）；deny 清单优先（含对绝对路径的显式 fnmatch 兜底 `_extra_path_denied`）——deny 命中仍拒（`write_target_denied_by_deny_list`） |
| 灾难命令守卫不可绕过 | CatastrophicGuard 流程不变（grant 不豁免灾难命令）；`host_grant_id` 与 `escalation_id/escalation_token` 互斥（参数级拒绝） |
| 授权与执行分开、单次 | execute_command：resolve（peek 全维度预检）→ guards → write-scope gate → sandbox argv 构造 → **consume（CAS 单次，执行尝试即消耗）** → Popen；回执含 `[host-grant] op path grant=… 已消费（单次）` |
| 版本绑定（write 防竞态替换） | 申请时 file_sha256 冻结；消费预检时目标当前 sha 与绑定不一致 → 拒（`目标文件内容已变化`）；read 同样绑定（读到批准的版本） |
| cwd/会话/命令逐项绑定 | request_binding.command_sha256 == sha256(实际 command 逐字) ；cwd==realpath(workdir or workspace_base())；session_id==current_session_id；任何一项不符拒绝 |

### 7.2 有意的最小化偏差

1. **audit 目录**（P0-1 修订）：grant home 由 `host_grant_store_home()` 推导为**独立安全状态目录**（`LFL_HOST_GRANT_HOME` env > `$XDG_STATE_HOME/lfl-host-grants` > `~/.local/state/lfl-host-grants`；与 web 审批端点、execute_command 同源），并经 `ensure_grant_home_isolated()` fail-closed 校验（realpath 双向不与沙盒可写根重叠——工作区/LFL_DATA_DIR//tmp/缓存目录/EXEC_SANDBOX_MACOS_WRITABLE、祖先属主/权限/symlink）。此前取 `LFL_DATA_DIR` env > 代码根/data 的推导在生产使账本落入 workspace 内（`--bind workdir` 可写面），系独立 Reviewer P0 的根源，已闭合。**不用** `settings.DATA_DIR`（两 env 名分歧的路径漂移问题同前）。
2. **审批 UI（P0）**：EscalationCenter 不改（command 摘要文本承载审批信息；detail 端点新增 `request_kind`/`host_request` 字段）；grant 徽标 UI 留给后续。
3. **create/delete/目录/递归**：P0 一律拒绝（`_validate_request`）；无扩大面。
4. **执行失败不退 grant**：单次语义=执行尝试（无论退出码/沙箱启动失败于 consume 后）即消耗；重新申请需人工再批。fail-closed 方向。
5. **跨进程部署**（P0-1 修订）：web 审批端点与 AI 会话同进程假设沿用既有 escalation 架构（EscalationStore 进程签名密钥）；HostCapabilityGrantStore 现同样持有**进程内随机 HMAC 密钥**（`_GRANT_SIGNING_KEY`，独立 domain，不落盘/env/日志/子进程）：签发即 MAC（grant 落盘带 `key_id`+`mac`），peek 附 `_sig_unverified` 只读标记，consume/revoke/变更前必验签（含锁内 fresh 重读），CAS 写回后重签——伪造/篡改/他进程签发/服务重启旧记录一律拒绝（不假装仍有效，需重新人工审批）；审计链 HMAC 化并按 key epoch 分段（旧 epoch 链归档 `audit.<key_id>.<n>.jsonl` 保留证据、新链以 epoch_start 重开；同 epoch 篡改即 `audit_chain_broken` 停止签发；legacy 无 MAC 链 fail-closed 需人工清理）。跨进程签发的 grant 在消费端验签失败并明确拒绝（同进程部署契约与 escalation 一致）。

### 7.2.1 P0-1 双防线（2026-11-14 增补，独立 Reviewer P0 闭合）

- **防线 A（MAC）**：见 §7.2(5)。核心不变量——**不可信内容绝不重签洗白**（锁内 fresh 验签失败即拒，revoke 拒绝改写不可信记录）；MAC 覆盖含 `key_id` 的全部字段（防换绑）。
- **防线 B（home 隔离）**：见 §7.2(1)。另加 execute_command **workdir 账本禁区**（workdir 与账本候选——生效 env home+平台默认 home——双向重叠即拒执行，防 `--bind workdir` 圈住账本）；web 审批端点账本构造移入 fail-closed try（不可用即 503、决定不落盘）。
- **旧数据**：旧不可信 grants/audit **不自动迁移**——重启后旧 grant 验签失败拒绝消费；legacy 审计链 `audit_chain_broken`，恢复动作=人工移走旧 `grants/` 目录（生产当前无存量依赖）。
- **恢复语义**：服务重启→密钥轮换→旧 grant 失效（需重新人工审批）；审计链自动按 epoch 归档重开，审批流不断。
- **攻击面收口**：`LFL_HOST_GRANT_*`/XDG env 污染、symlink 重定向、workdir 圈账本、伪造/篡改/重放/跨进程签发，全部负例回归（§7.3 新增行）。

### 7.3 测试映射（专项）

| 验收项 | 测试 |
| --- | --- |
| 默认拒绝/申请校验矩阵 | `tests/unit/test_host_grant_closure.py::test_request_rejects_*`（相对/glob/../symlink/不存在/目录/operation/justification/ttl） |
| 冻结字段/幂等 | `test_request_freezes_binding_fields` |
| 批准后一次成功（逻辑闭环）+ 审计 | `test_decide_binds_grant_and_mints_no_token`、e2e `test_grant_consumed_once_with_audit` |
| 重放拒绝 | `test_concurrent_consume_single_winner`（4 线程 1 赢家+重放 None）、e2e r2 |
| 跨 session/path/command/cwd | `test_resolve_rejects_cross_session`、`test_resolve_ok_and_bindings_enforced`（命令篡改/cwd 不匹配） |
| expiry/revoke | `test_expired_and_revoked_grant_rejected` |
| symlink 替换/文件消失 | `test_resolve_rejects_symlink_replacement`、`test_resolve_rejects_deleted_target`；TOCTOU 版本漂移在 `test_resolve_ok_and_bindings_enforced` |
| 竞态 | `test_concurrent_consume_single_winner`（barrier 4 线程） |
| 无登录/loopback 自批/Bearer 拒绝 | `test_loopback_unauthenticated_cannot_approve_host_grant`、`test_bearer_channel_cannot_approve_host_grant`（记录保持 pending、无 grant 文件） |
| 登录会话批准 → 持久 grant+审计 | `test_logged_in_session_approval_issues_persistent_grant`（grant 文件+binding+policy_hash+review log） |
| 审批冲突→孤儿撤销 | `test_stale_review_revokes_orphan_grant` |
| denied → 无 grant | `test_denied_issues_no_grant` |
| 灾难类 loopback 语义不变（回归） | `test_catastrophic_class_loopback_semantics_unchanged` |
| loopback 显式登录 | `test_loopback_form_login_with_password_sets_cookie` / `…_json_explicit_login_rejected` / `…_json_probe_zero_regression` / `…_without_config_fails_closed` |
| bwrap 不可用 fail-closed | `test_resolve_bwrap_missing_fail_closed`（提前拒、不消费） |
| none/docker 模式拒绝 | `test_resolve_rejects_unsafe_backends` |
| write-scope allow 豁免/deny 不可绕 | `test_gate_allows_grant_path_under_allow_scope`、`test_gate_never_bypasses_deny_scope` |
| bwrap argv 精确 bind/未授权无 bind | `test_bwrap_argv_precise_file_bind_with_dir_ancestors`、e2e `test_bwrap_argv_bind_shape_for_write` |
| 真 bwrap 默认拒绝 | e2e `test_real_bwrap_default_deny_and_grant_write`（skipif 无 bwrap；Deepin/CI Linux 跑） |
| grant 与灾难令牌互斥 | e2e `test_grant_mutually_exclusive_with_catastrophic_token` |
| **P0-1** 伪造（无 mac / 伪造 mac+key_id / 字段全自洽+request_id 不存在）拒 | `test_host_grant_store_auth.py::test_forged_approved_grant_without_mac_rejected`、`…_with_fake_mac_and_key_id_rejected`、`…_fully_selfconsistent_binding_rejected` |
| **P0-1** 篡改已签发文件（保留原 mac）拒 | `…::test_tampered_issued_grant_rejected` |
| **P0-1** 审计链篡改 → 停止签发 | `…::test_audit_tamper_stops_issuance` |
| **P0-1** 服务重启（密钥轮换）旧 grant 拒 + 旧链 epoch 归档 + 审批流可用 | `…::test_service_restart_rotates_key_and_invalidates_grants` |
| **P0-1** 不可信记录拒绝改写（防洗白） | `…::test_revoke_refuses_untrusted_record` |
| **P0-1** 同进程跨 store 对象签发-消费 + 单次重放拒 | `…::test_same_process_cross_store_object_consume` |
| **P0-1** unsafe home（workspace/LFL_DATA_DIR//tmp/缓存/EXEC_SANDBOX_MACOS_WRITABLE/XDG/symlink）fail-closed | `…::test_unsafe_home_env_rejected`、`…_via_lfl_data_dir_rejected`、`…_xdg_state_home_into_workspace_rejected`、`…_symlink_redirect_into_workspace_rejected`；默认分离 `…::test_default_home_outside_writable_roots` |
| **P0-1** execute_command 拒伪造 grant / workdir 账本禁区 | `…::test_execute_command_rejects_forged_grant`、`…::test_execute_command_workdir_grant_home_guard`；e2e `test_workdir_overlapping_grant_home_rejected`（父侧验收 2026-11-14 修正后新增：真实链路签发→workdir 圈账本→拒且不消耗；e2e ctx 改为账本兄弟目录，使正例不再依赖 basetemp 位置） |
| **P0-1** 真实 bwrap：workdir bind 内不可写账本 | `…::test_bwrap_cannot_write_grant_home`（skipif 无 bwrap；Deepin/Linux 跑） |

回归：tests/unit/test_escalation.py、test_sandbox*.py、test_execute_*.py、tests/test_escalation_*、test_write_scope_*、test_command_scope_guard.py、test_web_auth_csrf.py 全绿（839 passed / 2 skipped，含专项）。

### 7.4 阻断项（冻结候选边界，待用户协调）

- 独立 Reviewer PASS（P0/P1=0）未取得——按 RULE-AI-28 由用户后续发起。
- 完整 R9 exit0 未跑（全量测试需先过独立审查闸）。
- main/push/部署禁止；Deepin 真机复现（真 bwrap 集成分支 + 浏览器人工审批走查）未执行，需用户在 Deepin 主机安排。
- bwrap `--bind` 对不存在 dest 文件的自动创建行为在 macOS 无法实测：实现以显式 `--dir` 祖链 + bind 挂载点兜底，真机验收时确认（若 bwrap 版本不支持自动创建文件挂载点，Deepin 集成测试将显式失败，不会静默）。
