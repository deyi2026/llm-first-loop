# DELIVERY-20261030 · write_scope 写侧约束（P1-a 命令族闸）上线交付说明

- 作者会话：`cbda67c5-6cd8-421e-b4df-f59d74b4f2cc`（统筹协调 / 独立验收 / 上线执行）
- 代码作者会话：`cab051cc-c0ca-4a09-b848-6d4a00ec0ffe`（并发写者，负责闸的实现与逐轮独立审查修订）
- 本文只记录**本会话亲自取证**的事实；标注「未核验」的段落一律按未核验处理。

## 1. 现行口径

写侧约束现行口径 = **P1-a**：受限 child **保留** `execute_command` 能力，写侧约束下沉到**命令族闸**
（`src/llm_loop/core/command_scope_guard.py`，强制点 `src/llm_loop/tools/builtin/execute_command.py`）。
**P1-b（受限 child 剔除 `execute_command` 的工具面口径）已作废**，不得按其上线。
上游依据：并发会话 2026-10-30 16:40 口径变更通知 + 设计文档 §16 顶部口径变更框 + HANDOFF §10.1。

## 2. 上线结果（已核实）

| 项 | 值 | 来源 |
|---|---|---|
| deployment_id | `deploy-968d4c69dcec4b0698cbcfe3c5cae3d6` | publish 回执 |
| desired generation | `344` | publish 回执 |
| git_head | `4ae2d8f7d91b2489abede4fdc340908e4b5d614a` | publish 回执 |
| 代码快照 | `.releases/4ae2d8f7d91b2489abede4fdc340908e4b5d614a/`（含 `core/command_scope_guard.py` 30528B、`core/write_scope.py` 24602B、`webui/dist/`） | 本会话 `ls` + `git -C .releases/... log` |
| webui_artifact_sha256 | `072bbd6471cbbf2e59b871ef64a370286f20c4db4babd5e92aea08e7ade8a6dd`（source binding `431b0d33ad6ef67c`） | publish 回执 + `dist/.lfl-webui-source.json` |
| code_root（发布用） | `.worktrees/p1a-release`（tracked 干净、HEAD=4ae2d8f7d、webui/dist 本次构建） | 本会话自建并核对 |

**上线前 live 实况（对比基线）**：web live=`8c114428f`（10-29 14:11 启动），其 `.releases` 快照里
**既无 `write_scope.py` 也无 `command_scope_guard.py`** ⇒ 上线前写侧约束**零生效**；desired 当时为
`5002688c3`（含 P0 write_scope + **已作废的 P1-b**），feishu/learning live=5002688c3。

**为什么必须走 publish 而不能只 restart**：运行时代码从 `.releases/<sha>/src/` 快照加载，不从工作区 `src/` 加载
（本会话实测：本会话 `import llm_loop` 命中 `.releases/8c114428f…/src/llm_loop/__init__.py`）；
且「直接 restart 到 5002688c3」会把**已作废的 P1-b 口径**上线，故先 publish 新代 344 再重启。

## 3. 独立验收（本会话亲自跑，非采信任何自述）

工作副本 `.worktrees/p1a-verify`（独立 git worktree，不碰主工作树），解释器 `../../.venv/bin/python` +
`PYTHONPATH=src`（避免 `.venv` 的 editable 安装指向旧 release 快照）。

| 验收项 | 结果 | 备注 |
|---|---|---|
| 聚焦用例 `tests/test_command_scope_guard.py` + `tests/test_write_scope_spawn.py` | **121 passed** | 4ae2d8f7d |
| 扩大口径 `-k "write_scope or execute_command or command_scope or tool_surface"` | **267 passed / 6 skipped** | 同代 |
| 设计 §16.8 列出的 12 类 shell 绕过（`FOO=1 rm` / `if…then` / `for` / `case` / `(rm)` / `{ rm; }` / `$( )` / 反引号 / `eval` / `&>` / `>&` / `>|`） | **逐条实测全拦，0 漏** | 自行写判定层直调脚本，非只跑测试 |
| 设计 §16.9 第二轮 7 类 P0 向量（命令位 `$X`/`${X}`/花括号、`` `cmd` ``、`timeout 10 rm`、`su -c`、`su` 无 `-c`、`env -S`、`watch -x`、`find … -exec true {} \; -delete`、`. x.sh`/`source x.sh`/`bash < x.sh`） | **逐条实测全拦，0 漏** | 原因码分别为 `command_identity_not_literal` / `unmodeled_shell_construct` / `write_target_outside_scope` / `implicit_write_target` |
| 第二轮 3 类 P1（`rsync -t`、`gzip -d`、`wget` 无输出、`patch` 无目标、`git -c`、`git config`、`git diff -o`） | **逐条实测全拦，0 漏** | — |
| 自造 42 组文档/用例未覆盖的 shell 构造 | 42 组中 **40 组被拦**；2 组放行＝**解释器任意代码**（§16.6 已声明残余：`python -c "open('/out/x','w')"`、`perl -e 'open(F,">/out/x")'`） | 残余非新缺陷 |
| 放行方向（scope 内写入不被误杀） | `echo x > sub/ok.txt` / `rm sub/tmp.txt` / `mkdir -p sub/dir` **均放行** | 否定面回归，避免闸把受限 child 的正常写全堵死 |
| 门禁自证伪 | 用例 `test_self_falsification_disabled_gate_actually_executes_write` **通过**：闸置空后目标文件确实被删 ⇒ 用例测的是真实拦截而非空转 | 另见设计 §16.9 记录的 57 组参数化「应拦输入」 |

## 4. 未闭环 / 残余（上线即知，不掩盖）

**闸本身的结构性残余（设计 §16.6 + §16.9「教训·第三层」）**：

1. 解释器任意代码可写任意路径（实测 2 例放行）——**最强残余**。
2. 读侧越界只审计不阻断（scope 是写侧授权）。
3. 符号链接绕道（`ln -s` 造链后经链写入）。
4. `git` 写子命令一律按隐式写目标拒绝——语义偏保守（可用性代价）。
5. shell 脚本文件执行被拒（`sh s.sh` / `bash s.sh`）——fail-closed 的代价：受限 child 不能跑仓库脚本。
6. 写族名单是封闭清单：名单外命令默认按只读放行。
7. `cd` 位移后的相对写目标一律拒。
8. **判定是命令语义层的列举式清单**：本轮两轮独立审查各找出 7 类新绕过，说明「靠列举堵洞」本身有上限，
   不能把「本轮全拦」等同于「无绕过」。

**本交付未做的事（如实标注）**：

- **未执行全量测试**。原因：host 准入要求候选相对当前分支存在 delta，而本次发布候选就是分支 tip
  （`full_test_no_delta`），本会话无法再发起独立审查资格；权威全量门禁属并发会话的第三轮
  `review_admission(kind=full_test)`，本会话**未核验**其结论。
- **三服务重启终态已核对（2026-10-30 19:4x 补记）**：feishu / learning 两条 restart **已 succeeded 且 confirmed_ok**（live head＝`4ae2d8f7d91b…`）⇒ 这两个服务**已物理生效**；
  web 两条 restart 均 **failed**（busy / requester active），现役仍是旧代 `8c114428f` ⇒ **web 侧闸零生效**。逐条回执见 §5。

## 5. 上线后验收清单（2026-10-30 19:4x 本会话逐条回执核对）

**结论先行：feishu / learning 已物理生效；web 未生效，仍是旧代 ⇒ 三服务未全部上线，本清单未整体通过。**

| # | 验收项 | 本会话实测结果 | 证据 |
|---|---|---|---|
| 1 | 三条 restart 终态 | feishu `svc-f28ad1c788a748e2ae31bf3fff7088a5` = **succeeded**（`verify=confirmed_ok feishu[ok pid=31975 head=4ae2d8f7d91b…]`）；learning `svc-a7d7d4f4f1c047ff90ec32d87a853ea3` = **succeeded**（`confirmed_ok learning[ok pid=32366 head=4ae2d8f7d91b…]`）；web `svc-49974f93551242d5adcf3e5c60d0b1af` = **failed**（`target still busy after 900s: confirmed_busy: active run locks: 1`）；web 第二次 `svc-ccda2ee7fc434da197960b3b09713fe3` = **failed**（`requester run still active after 900s`） | `service_control(action=status)` 三次观测 + `data/runtime/service-control-actions/*.json` 逐条读出 |
| 2 | 三服务 `live git_head == 4ae2d8f7d91b2489abede4fdc340908e4b5d614a` | **feishu ✅ / learning ✅**（runtime manifest live head 均等于新代）；**web ❌ = `8c114428f3edbd44f3064dfc4412df574aebf127`**（2026-10-29 14:11 起未变）。旁证：旧代快照 `.releases/8c114428f…/src/llm_loop/core/` 内 `write_scope*` / `command_scope_guard*` 文件数 = **0**，新代快照同名文件 **齐全**（另含 4 个 write_scope 测试文件） | runtime manifest + `.releases/` 目录清点 |
| 3 | live 端到端实测（受限 child 越界写被拦、in-scope 写放行） | **未能在 live web 进程内完成**——web 现役进程跑的是旧代 `8c114428f`，旧代根本不含闸，测了也没有闸。改为**在已发布代快照（PROD）上取证**，三项互补证据：<br>① **产物自带用例**：`cd .releases/4ae2d8f7d…` 内 `PYTHONPATH=$PWD/src pytest tests/test_write_scope_spawn.py tests/test_command_scope_guard.py -q` ⇒ **121 passed**（快照根目录 `tests/` 确实存在；独立子代理误查 `src/tests` 子路径而误判「快照不含 tests」，以其为准不采信）<br>② **判定层直调**：`PYTHONPATH=PROD` ⇒ 越界 `rm -rf`/`echo >` **allowed=False**（`write_target_not_in_allow_list`）、scope 内 `rm`/`echo >` **allowed=True**、读侧越界放行但记 `unverified`、shell 构造拒（`unmodeled_shell_construct`）<br>③ **接线静态核验**：PROD `execute_command.py:25/1132` 调 `check_command_scope`；runner 侧 `_compute_child_write_scope`（求交 fail-closed）、`_apply_write_scope_tool_surface_policy`、`current_write_scope.set(...)` 下发、回执 `write_scope_command_guard=p1a_write_family`；**OLD 快照同路径 grep 计数＝0**（旧代零闸）<br>**这是产物级证据，不等同于 live 进程级证据**（工具调用路径的运行时拦截回执未取），live 端到端仍待 web 切代后补做 | PROD 快照内 pytest 输出 + PYTHONPATH 直调输出 + `grep -rn` 接线行号；OLD 快照 grep 计数 0 |
| 4 | 并发会话后续写侧修订是否需再次 publish + 重启 | **需要**。并发会话 HEAD 已到 `d94b6ce39`，闸提交链为 `4ae2d8f7d → 9d11af003 → ae8158530 → f979b9564 → d94b6ce39`；其中 `f979b9564`（第三轮审查 9 个绕过向量 + 2 P1 + 4 P2）与 `d94b6ce39`（第四轮修复）**尚未发布、尚未上线** | `git log` + `service_control(status)` 的 desired/live 差异 |

**必须一并记住的诚实结论（勿据「已上线」宣称「闸有效」）**：已发布代 `4ae2d8f7d` **正是第三轮独立审查判 `REVISE` 的那个候选**（P0=1 / P1=2 / P2=4，P0 含 `env -S` 尾操作数、`watch -b` 吞命令名、进程替换 `<(` `>(`、`tar -C`、`sed -i.bak`、`sed w FILE`、`patch -o`、`zstd -o` 等向量，见设计 §16.10）。因此 **feishu / learning 现役代码仍带这些已知绕过向量**，修复只在未发布提交里 ⇒ 上线 ≠ 闸有效；须待 `f979b9564` / `d94b6ce39` 经审查后**再次 publish + 重启**才物理生效。

**web 未切换的机制原因（非本会话可自行绕过）**：web restart 走两段 fail-closed 门——先等请求方 run 退出（`waiting_for_requester_exit`），再等 `data/sessions` 下**零前台 run lock**（`waiting_for_idle`，判据为 `active_run_locks()` 对每个 `*.run.lock` 取共享 flock）。`src/llm_loop/runtime/service_control.py` 明写「Both waits fail closed; there is no model-side force-through path.」；本轮在飞动作 `svc-3fbc389196c94123a2ef709d943668f4`（请求方为另一 web 会话 `25e48ad9`，worker pid 14218）已过第一段、正等第二段，持 admission barrier ⇒ 本会话**不重放 publish/restart**，也**不宣告失败**。

## 6. web 未切换的根因与可执行恢复路径（2026-10-30 19:5x 追加）

**根因不是闸、不是产物、不是 publish，而是 run lock 竞态（run-lock contention）。**

三次 web restart 失败的回执都是同一形状，与闸无关：
- `svc-49974f93`（17:29）`failed`：`target still busy after 900s: confirmed_busy: active run locks: 1`
- `svc-ccda2ee7`（19:14）`failed`：`requester run still active after 900s`
- `svc-3fbc3891`（19:22→19:51）`failed`：`active run locks: 3`（当时持锁者：并发 writer `cab051cc`、本会话 `cbda67c5`、子代理 `subagent_2396b6ff6ffc`）

源码权威（`src/llm_loop/runtime/service_control.py`）：
- Phase 1 `waiting_for_requester_exit`：只等**请求方自己**的 run 退出（`_requester_run_active`，按 `<session_id>.run.lock` 取 flock）；
- Phase 2 `waiting_for_idle`：web 判据＝**`data/sessions` 下无任何前台 run lock**（`_target_idle_state` → `confirmed_busy: active run locks: N`）；
- 两段等待**均 fail-closed，源码明写 "there is no model-side force-through path"** ⇒ 模型无法绕过，只能等锁自然释放。

已验证经验（`experience:EXPERIENCE-20261021-排队重启与定时验证互相饿死…`，verified）：`run.lock` 是**按 run 的排他 flock，由 web 进程自身持有，run 结束即释放**；文件本身是**墓碑**（existence ≠ activity，须用 `active_run_locks()` 实测而非看文件是否存在）。同一经验指出关键陷阱：**为验证重启而注册的定时唤醒会话本身会持锁，形成自我饿死** ⇒ 排程形态必须避开。

**可执行恢复路径（供下一会话/真人按序执行，本会话按「严禁重放 publish/restart」未发起）**：
1. 等并发 writer 会话 `cab051cc` 结束本轮提交、**释放其 run lock**（这是当前唯一的真实阻塞项；它每提交一轮就可能重新占锁）。
2. 由一个**即将结束自己 run** 的会话发起 `service_control(action=restart, target=web, expected_generation=344)`：Phase 1 只等它自己退出 ⇒ 它一退出即过；Phase 2 随即要求 web 侧零 run lock ⇒ 此刻必须无第三个会话（含定时唤醒会话）在跑。
3. **不要为等待验收注册定时唤醒会话**（会持锁饿死 Phase 2）；如需登记，只用纯通知型 `task_mode=remind`（无 run lock），或等本轮 run 自然结束后由真人再发起一次。
4. 判据：web live `git_head == 4ae2d8f7d91b2489abede4fdc340908e4b5d614a` **且** 该 restart 动作终态 `succeeded` ⇒ 再补做 live 端到端受限 child 越界写实测（期望 `error_type="write_scope_violation"` 且目标文件未产生），随后关闭 Goal `GOAL-20261030-376a8de4` 的 T5/T6。

**发布代的一个必须记住的事实**：本轮 desired 代为 generation **344**（`deploy-968d4c69…`，git_head `4ae2d8f7d91b…`），feishu / learning 已按此代生效；但 `4ae2d8f7d` **正是第三轮独立审查判 `REVISE` 的候选**（见设计 §16.10：P0=1，含 `env -S` 尾操作数、`watch -b` 吞命令名、进程替换 `<(` `>(`、`tar -C`、`sed -i.bak`、`sed w FILE`、`patch -o`、`zstd -o`），修复在**尚未发布**的 `f979b9564` / `d94b6ce39`。⇒ **web 切到 344 只能得到「带已知绕过向量的闸」**，不是最终形态；并发会话发布新代后仍需再次 restart。要把「上线」升级为「闸有效」，须待新代发布后**再 restart 一次**（同样避开 run lock 竞态）。

## 7. 配套记录

- 目标与任务图：Goal `GOAL-20261030-376a8de4`（T1 独立验收 / T2 门禁语义 / T3 交付说明 / T4 publish / T5 重启与 live 实测 / T6 验收收口）。
- 上游文档：设计 `docs/DESIGN-20261030-write-scope-and-concurrent-writer-ownership.md` §16、§16.8、§16.9、§16.10；
  交接 `docs/HANDOFF-20261030-write-scope-git-takeover.md` §10、§10.5、§10.6。
- 本会话独立复核脚本（隔离 worktree 内，未入库）：`.worktrees/p1a-verify/verify_matrix.py`、`.worktrees/p1a-verify/verify_r2.py`。
- 本轮（19:4x–19:5x）追加证据：PROD 快照自带用例 `121 passed`、判定层直调 6 断言、闸文件计数（OLD=0 / PROD=齐全）、`active_run_locks` 实测、三条 restart 动作 detail 原文、`_target_idle_state` / `_requester_run_active` 源码。
- 续跑安排：纯通知型提醒 `sched-6d9f468d`（**无 run lock**，不参与 idle 门判定）；一次性 wake 续跑在本 delegated run 内**无法签发**（`delegate_ingress` 要求未委派真实 human ingress，运行时按设计拒绝），故不构成自动执行入口。
- 本轮新增知识：`experience:EXPERIENCE-20261030-上线后验收遇到-restart-全-failed-且回执形状一致-时的判别顺序-先查-run-loc`（lesson, verified）。
- 任务状态：T5 标 **blocked**（附当前事实依据，解除条件见 §6 步骤 1-4）；T6 保持 waiting（依赖 T5）；Goal 未标 complete。
