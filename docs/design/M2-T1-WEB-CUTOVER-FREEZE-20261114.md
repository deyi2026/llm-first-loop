# M2 · T1 预算化写入 Web 入口接线 — 设计冻结（2026-11-14，候选未提交）

> 状态：**M2 内容冻结待独立审查**（冻结前 M2 增量为 unstaged/untracked；M1 staged index 原样保留，
> `git write-tree = 59d73bfb2b4ef60c6c07c93dd772df226704e42f`）。零生产部署、零真实 GLM、
> 零 git commit/push/Reviewer/R9/重启。独立执行回执见
> `docs/receipts/M2-T1-WEB-CUTOVER-20261114.json`。

## 1. 目标与范围

把 M1 已真实验证的预算门禁（Provider/Tool 双预留、CAS 结清、EventStore 唯一用量
事实源）接到**受控 Web 会话入口**：operator 显式授权的单个 session/workspace/
run_generation、固定 `glm/glm-5.3`、固定工具集 `read_file/edit_file`、单目标文件
写入。不是 CLI 演示、不是仅改 config：普通 Web 会话路径零行为变化（无授权配置时
`load_operator_web_canary` 返回 None，全部既有路由行为不变）。

## 2. 复用与新增（最小面）

| 层 | 复用（零改动） | M2 增量 |
| --- | --- | --- |
| 预算核心 | `TaskBudgetStore` CAS（reservation schema 白名单未扩）、`TaskBudgetExecution` reserve/dispatch/settle | `T1WebBudgetExecution`：M1 v3.3/v3.4 语义——EventStore `provider.transport.opened`+`settled` 按真实 `pattempt:<32hex>` 一对一 join、opened.prepared 重建 reserved 三元组（input≡2·payload+8000 恒等校验、output=per-request max_tokens 非全局常量）、`m1fx05ev:<event_id>:<digest16>` receipt_ref、CAS 唯一结算提交点、UNKNOWN 永不冒充 settled |
| Web 入口 | `/api/v1/chat/stream` → `BackgroundRunner.start(signed_web_canary=...)` 既有管线；`choose_signed_web_canary` gate（未认证/错 model/queued/attachments → 403 `budget_canary_not_qualified`）；sync 路由 409 `budget_canary_requires_stream` | T1 plan 作为 `WebTaskBudgetCanary.plan` 挂 `app.state.task_budget_web_canary`；`load_operator_web_canary` 读取 operator config（schema `web-task-budget-t1/v1`）构造 plan；`bind_web_canary` T1 分支绑定 isolated transport + 单目标 write scope + 工具发现收敛 |
| 工具链 | `read_file` 物理快照、`edit_file` CAS | registry.py `note_t1_read_result`：武装 gate 的 snapshot_ref 权威取自 `ToolResult.artifact_facts[0].artifact_ref`（非文本正则）；2MiB 编辑预检与 `FileService.edit` 完全同构（CRLF/replace_all/LF 注入恢复膨胀精确覆盖，父侧反例 3,300,000B 预写拒绝） |
| 中断恢复 | durable stop（`request_stop` CAS） | F18 跨实例守卫 `_t1_assert_no_open_liability`：重绑 root 首笔 reserve 前扫描非终态预留，UNKNOWN 负债拒绝 `t1_root_has_unsettled_liability` |

改动文件（M2，全部 unstaged/untracked）：
- `src/llm_loop/resources/task_budget_t1_web_profile.py`（新）
- `tests/unit/test_task_budget_t1_web_profile.py`（新）
- `src/llm_loop/web/task_budget_canary.py`、`src/llm_loop/web/__init__.py`（T1 arm + config 加载）
- `src/llm_loop/core/loop/lifecycle.py`、`src/llm_loop/llm/client.py`、`src/llm_loop/resources/task_budget_dispatch.py`（canary run 生命周期/传输钩子最小接线）
- `src/llm_loop/tools/registry.py`（note_t1_read_result 快照权威化）
- `docs/design/M1-T1-LIVE-BUDGET-FREEZE-20261113.md`（M2 增量段落，staged 版本之上）

## 3. 测试口径（07:11 父侧复核后明确）

1. **engine-scope e2e**（`test_t1_engine_scope_e2e_synthetic_provider_stream`，
   原 `..._web_route_e2e_...` 改名+docstring 修正）：生产 `bind_web_canary(T1)` →
   真实 `engine.run_stream` → 真实 `LLMClient` 流解析 → EventStore 三事件 → 预算
   CAS → read→arm→edit→CAS 工具链 → 终轮自然语言。**不含** HTTP 路由层/
   BackgroundRunner 派发（显式披露，由下一项覆盖）。
2. **真实 HTTP route 正测**（`test_t1_real_web_stream_passes_pinned_plan_to_background_runner`）：
   真实 FastAPI app（`build_app(engine=...)`）+ `TestClient` POST
   `/api/v1/chat/stream` → `BackgroundRunner.start` spy 断言收到
   `signed_web_canary`（T1 plan 身份核验）+ sync 路由 409。
3. **真实 HTTP route 负测**（`test_t1_web_stream_route_denies_unqualified_requests`，
   4 参数组）：未认证→403 canary gate；错 model→403 canary gate；queue_id→409
   queue-claim（早于 canary gate 的 fail-closed 层）；attachments→400
   attachment-ownership（同前）。共同断言：零 `runner.start` 派发、零预算分配
   （ledger 目录无文件）。
4. 全部合成：FakeLLM/合成 SSE/TestClient/runner spy，零真实 GLM。

## 4. 验证矩阵（终值 2026-11-14 08:2x 独立复测，全 `.venv` 3.13，真实 exit code）

| 命令 | 结果 | exit |
| --- | --- | --- |
| `py_compile`（profile+测试） | OK | 0 |
| `ruff check`（M2 全部改动文件） | All checks passed | 0 |
| `pyright`（M2 全部改动文件） | 0 errors, 0 warnings | 0 |
| `pytest tests/unit/test_task_budget_t1_web_profile.py` | 59 passed（43→47→48→56→58→59：+4 单飞负测、+1 父侧全栈流验收、+8 F18 撤销/跨 kind 负测、+2 operator 身份复检、+1 build_app fail-closed 启动负测） | 0 |
| `pytest tests/unit/test_m1_fx05_budgeted_run.py` | 36 passed | 0 |
| `pytest tests/unit -k "canary or t1 or budget"` | 745 passed, 4 skipped（729→733→737→742→744→745） | 0 |

4 skips = 既有 RED-12~15 平台限制（非本轮引入，与本改动无关）。

## 5. 明确未做（如实）

- 未部署生产 Web、未开 canary、未重启任何服务——接线仅存在于本隔离工作树候选。
- 真实 HTTP 进程级 e2e（真实鉴权栈/queue 存储/worker 进程）未建；`load_operator_web_canary`
  的文件路径加载在装配级 e2e 未测（单测以 app.state 直塞等价覆盖 gate 与派发）。
- 非流式/错误帧/SSE 中断的 route 层 e2e 未建（engine 层对应失败路径已有单测）。

## 2026-11-14 07:21 父侧负测补强：T1 single-flight 硬门落在 store.reserve 原子 CAS

父侧同树零网络实测四项缺陷：① 第一个 provider send scope 未退出时嵌套第二个，两者均进入（physical reservations=2）；② reserve 后模拟崩溃（root ACTIVE、旧 reservation DISPATCHED），fresh T1WebBudgetExecution 同 store/member 可再进入；③ request_stop 内部 CAS 失败时同实例 local latch 语义确认（非缺陷）；④ 两个嵌套 read_file(snapshot) tool scopes 均进入（tool reservations=2）。

修复（最小面）：`TaskBudgetStore.reserve` 的 apply 内、既有 subagent-canary 门之后，对 `grant.profile == web-glm-t1-budgeted-write-v1` 增加 per-kind single-flight 硬门——任一同 kind reservation 处于 open 相位（reserved/dispatched/unknown）即拒绝新 reserve（`t1_single_flight_provider_denied` / `t1_single_flight_tool_denied`）；settled / aborted_before_dispatch 释放。门在 reserve CAS 本身：崩溃债务、fresh 实例、嵌套 scope 全部命中同一持久拒绝；无新账本、无新锁、execution 层 F18 首查保留。串行合法流不受影响（settled 后可继续；真实引擎成功工具在 registry.py 置 `outcome_fact["complete"]=True` 落 settled）。

夹具修正：既有两个测试的 4 处正向工具块此前模拟"成功执行却未上报 complete"（落 unknown），在新门下正确拦截第二笔——门行为正确、夹具失真；已补 `outcome["complete"] = True` 与真实引擎一致。

负测 +4（43→47）：嵌套 provider 拒（reservations==1）、崩溃 DISPATCHED 债务下 raw store.reserve 与 fresh T1 实例均拒（store 门独立于 execution 层证明）、CAS 失败 local latch 同实例阻断（root 仍 ACTIVE 如实断言）、嵌套 tool 拒。串行正向由既有 `test_consecutive_attempts_each_bind_both_events`（3 连发全 settled）覆盖。

验证（全 `.venv`）：ruff（含 SIM117×2 修复后 All checks passed）；pyright 两文件 0 errors；T1 专项 47 passed；`-k "canary or t1 or budget"` **733 passed, 4 skipped**（729→733）。父侧报的 Ruff SIM105×1 / Pyright×8 出现在父侧实测草稿副本，本候选树全绿（如实记录差异）。`task_budget_store.py` 为本批次新增 M2 unstaged 修改文件；M1 staged 六文件与 index tree 不动；零真实 GLM/Reviewer/R9/commit/push/main/restart/deploy。

## 2026-11-14 07:44→08:05 父侧验收闭合：F18 权威撤销 + 全局跨 kind 单飞

**并发写入披露（诚实记录）**：父侧 07:45:28 指令要求"排队处理、禁止并行写"，但 `tests/unit/test_task_budget_t1_web_profile.py` 的 mtime 在 07:50、07:55 两次外部变化（2441→2448 行；2406 行 `assert "event: run_started"` 断言被替换为解析 `data:` JSON 帧的 frame_types 断言并扩充全栈验收深度）。本人（唯一 writer）未做这些写入；本轮在父侧停手（mtime 稳定 20s+）后基于其最终版本继续。此前本人首跑 47P+1F 中的 1F 即父侧测试旧断言（SSE 线格式）问题，父侧自行修正后本树 48 passed。

**P1-A（F18 operator 授权撤销，权威动作落地）**：
- 裁决：权威撤销入口 = operator 0600 配置文件本身（宿主属主），**删除/不可读/任一字节变化（轮换）= 撤销**；不建第二状态库、不建审批服务；授权事实在启动时以 sha256 钉住（`_read_operator_config` 捕获被校验的原始字节）。
- 三层 fail-closed：① `choose_signed_web_canary` 每个 Web 请求重验（删除/轮换 → 新 Run 直接 deny；duck-typed 无 plan 的遗留夹具不受影响）；② `prepare_t1_web_event_budget` 发新 root 前重验；③ `T1WebBudgetExecution.reserve` 开头（每次 Provider/Tool 动作前）重验，命中撤销 → `request_stop("t1_operator_canary_revoked")` 持久 stop（幂等：root 已因其它 reason 停止时 CAS 冲突被抑制、动作仍拒、首个 stop reason 保留）+ `TaskBudgetDeniedError`。
- 重启语义：新进程 `load_operator_web_canary` 在配置路径已配但文件消失（OSError）时返回 None——无 canary、普通 Web 不受影响、T1 路径天然拒绝；已 stop 的 root 经持久 phase 对一切新动作拒绝。
- 负测 +5：删除后新 Run 拒（choose+prepare 双层、无新 root）、read 与 edit 之间撤销（首 read settled 后 unlink，edit reserve 拒 + root stop_requested + 同实例后续拒）、进程重启后拒绝（loader None + 轮换字节永不恢复授权 + 停止 root 拒 provider）、配置轮换=撤销（sha 逐字节钉住）、已停止 root 上撤销 stop 的 CAS 幂等（suppress 后仍拒、首 reason 保留）。

**P1-B（并发口径，全局单飞）**：父侧实测 provider scope 未退出时嵌套 tool dispatch 两者均进入——per-kind 门不满足"实际并发≤1"的全动作语义。修复：单飞门从 same-kind 放宽为 **跨 kind 全局**（`_T1_ACTION_KINDS`：任一 action-kind OPEN reservation 存在即拒新 action reserve，同一 reserve CAS 内）；错误码按"请求进入的 kind"区分保留。合法串行流证明：provider settled → tool（armed read+bound edit）→ 全部 settled 的混合序列通过（负测 `test_t1_serial_mixed_provider_tool_flow_passes_global_gate`：3P+2T 全 settled）；父侧全栈流验收（真实 runner+真实 LLMClient+合成 SSE：3 provider/2 tool 全 settled、webt1ev: join、observed allocations 逐项）在 48 基线中。嵌套负测 +2（provider OPEN 内 tool 拒且 tool reservation 从未存在 / tool OPEN 内 provider 拒）。

**P2（回执口径统一）**：主验证表更新为最终冻结快照（56 / 36 / 742·4S，命令+exit 与父侧 07:44 实测同式）；receipt 追加 `m2_f18_global_gate_20261114_0744` 块记录最终口径与新 sha256。

验证（全 `.venv` 3.13，真实 exit）：py_compile 0；ruff All checks passed（I001×7 由 `--fix` 仅 import 块修复）；pyright 四文件 **0 errors, 0 warnings**；T1 专项 **56 passed**（48→56：+8 本批负测）；M1 专项 36 passed（未回归）；`-k "canary or t1 or budget"` **742 passed, 4 skipped**（737→742：+5 F18、+3 跨 kind/串行；另修复 7 个既有 canary API auth 测试因 `selected.plan` 过早访问 SimpleNamespace 假 canary 的 AttributeError——改为防御式 getattr，语义顺序不变）。M1 staged index tree=59d73bfb… 未动；M2 增量全部 unstaged；零真实 GLM/Reviewer/R9/commit/push/main/restart/deploy。

## 2026-11-14 07:50 父侧补充 P1 闭合：operator 配置安全身份重验（08:0x 实施）

**父侧 TemporaryDirectory 实测三漏洞**（07:50 指令）：在途 `operator_revoked()` 只做 `Path.read_bytes()` 字节 SHA 比对——①原路径 chmod 0644（权限放松）→ revoked=False；②原路径 unlink 后 symlink 指向另一份**字节完全相同**的 0600 文件 → revoked=False；③FIFO/超大文件可阻塞/无界读取。均与"同一个受保护 operator 文件为持续权威"的安全契约矛盾。

**最小补修（task_budget_t1_web_profile.py）**：新增模块级 `_operator_config_intact(path, expected_sha256)`，复用 `_read_operator_config` 等价契约——`O_NOFOLLOW|O_NONBLOCK` 打开（symlink→ELOOP 即撤销；FIFO 打开立即返回不等待 writer）、`fstat` 身份五查（S_ISREG、owner∈{root, geteuid}、`mode & 0o077 == 0`、`st_nlink == 1`、`st_size ≤ 16384` 先于任何读）、一次有界 `os.read(16385)`、SHA-256 与启动指纹比对；任一失败 → revoked。`operator_revoked()` 改为调用该函数；零新状态库；choose/prepare/reserve 三层 fail-closed 调用点不变（同一入口收紧）。

**负测 +6（`test_t1_operator_config_identity_relaxation_is_revocation`，单测试五探针 + fence 断言）**：chmod 0644（撤销）→ chmod 回 0600（**恢复即再授权**，同一 inode）；unlink+symlink 同字节 0600 twin（O_NOFOLLOW 撤销）；hardlink bump nlink=2（撤销）→ unlink 恢复；mkfifo（S_ISREG 撤销，不阻塞）；16,385 字节 oversized（fstat 先拒，零读取）。每探针同时断言 `plan.operator_revoked()` 与 `choose_signed_web_canary` fence 拒绝。

**loader→fence 全链新测（`test_t1_build_app_autowires_real_operator_config_loader_to_fence`）**：区别于既有 route 测试的手工 `app.state` 注入，本测试经**真实 0600 config + `build_app(engine)` 生产装配链**（`web/__init__` 调 `load_operator_web_canary`：身份校验→指纹钉住→T1 plan 挂载），断言 plan 自动装配（session/config 绝对路径/sha 指纹/operator_revoked=False）→ HTTP `/api/v1/chat/stream` 经 per-request fence 放行并把 canary 注入 runner.start → **同一 app 实例**上 chmod 0644 后第二请求被拒（runner 收到的调用数保持 1）。既有删除（deletion）与字节轮换（rotation）负测继续覆盖删除/替换两态。

验证（全 `.venv` 3.13，真实 exit）：py_compile 0；ruff All checks passed；pyright 两文件 0 errors, 0 warnings；T1 专项 **58 passed**（56→58）；M1 专项 36 passed（未回归）；`-k "canary or t1 or budget"` **744 passed, 4 skipped**（742→744）。M1 staged index tree=`59d73bfb2b4ef60c6c07c93dd772df226704e42f` 未动；M2 增量全部 unstaged；零真实 GLM/Reviewer/R9/commit/push/main/restart/deploy。
## 2026-11-14 08:01 父侧裁决落地：F18 夹具修复 + typed fail-closed 启动

父侧在未冻结树实跑 `-k 'operator_config_deletion or revocation_ or provider_open_rejects_nested_tool or tool_open_rejects_nested_provider or serial_mixed'`：真实 exit 1（5 failed/2 passed/49 deselected），判定 5 项为夹具错误（非已证生产回归），但第③项是真实 fail-OPEN 语义洞，并给出明确安全裁决。

**当前树同款过滤 8 passed / 51 deselected**（父侧 7 项 + 新增 build_app 传播测试）。逐项处置：

| # | 父侧发现 | 处置 |
| --- | --- | --- |
| ① | deletion 测试缺 Bearer，choose 先报 unqualified | 07:44-07:50 批次已修（`_request_for` 带 `Bearer unit-key`，sanity `chosen is canary` 证明到达） |
| ② | read 仅 pass 未真实成功，edit 参数层先死 | 已修：真实 `checked_tool_dispatch("read_file", complete=True)` + 生产 `note_t1_read_result` 通道 arm `artifact://v1/revoked-mid-run`，edit 携带该 armed ref 在授权层被拒 |
| ③ | 配置丢失 `load_operator_web_canary` 返回 None → 受限 session 回退无预算默认路径（fail-OPEN） | **本批生产代码修复**：新增 `TaskBudgetCanaryConfigMissingError(RuntimeError)`，configured-but-missing → typed 异常，经 `build_app`（无 try/except，直接赋值）传播 → Web 拒绝启动。未配置路径仍 default OFF（cutover 套件 9 passed 证明普通 Web 不受影响）。运行中删除仍走 07:50 `_operator_config_intact` 身份重验 |
| ④ | stop 幂等测试调不存在的 `list_ids` | 已修：直接断言 durable row 的 phase/stop_reason |
| ⑤ | serial 沿用已 stop root | 已修：`_setup`+`_open` 新 root，3 provider settle → read(complete) → note_t1_read_result → edit(complete)，断言 3 physical + 2 tools 全 settled |

**新增测试**：`test_t1_configured_but_missing_config_fails_build_app_closed`（真实 `build_test_engine` + monkeypatch `business_config_snapshot` 指向不存在文件 → 断言真实 `build_app` 调用本身抛 typed 异常）；`test_t1_revocation_survives_process_restart` 更新为断言 typed 异常 + 旧 root durable 拒绝持续。

**验证（全 `.venv` 3.13）**：py_compile 0｜Ruff All checks passed｜Pyright 0 err/0 warn（两文件）｜T1 专项 **59 passed**｜M1 专项 36 passed｜cutover 9 passed｜canary 家族 55 passed｜`-k "canary or t1 or budget"` **745 passed, 4 skipped**。

**Git**：M1 staged index 未动；本批仅 unstaged M2 增量。零 commit/push/main/R9/restart/deploy/Reviewer/真实 GLM。P1 元数据 chmod0644/symlink 同字节已在 07:50 批次闭合（身份松弛探针+loader→fence 全链），待父侧复核。

## 2026-11-14 预冻结安全卫生与父侧验收

提交前原版 git_security_scan.sh --staged 阻断了两份执行回执中 7 处本机用户绝对路径。只对回执中的解释器和事件日志目录做相对路径脱敏，保留真实预算、事件、产物 SHA、执行统计与负测事实，不修改运行源码或测试逻辑；未增加扫描豁免。另将两处不触网的测试夹具假 API key 从 14 字符缩短为单字符 k，以满足原版敏感内容扫描，测试逻辑不变。父侧独立实测 M1+M2 专项 95 passed、F18/跨 kind 定向 10 passed、相关回归 749 passed / 10546 deselected / 7 warnings（无 cacheprovider 插件），Ruff All checks passed、Pyright 0 errors/0 warnings。协作代理先前在其沙盒通道记录的 745 passed / 4 skipped 属不同执行环境，两者选中总数均为 749，分别保留，不合并冒充同一次测试。冻结 tree SHA、Reviewer、R9 与后续集成/发布资格由 Goal checkpoint 和 Git 回执单独核验。
