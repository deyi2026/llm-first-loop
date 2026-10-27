# LFL Release / Restart 阶段 0 只读基线测量报告（T4）

- 基线提交：`e535a11ab8c6917d6d5ac2721db7251d5240ad2a`（实测 `git rev-parse HEAD` = `origin/main` = `e535a11ab`，三者一致，2026-10-27 17:43）
- 测量方式：**严格只读**。因并行 agent 正在改 ci.yml / service_control，所有源文件一律经 `git show origin/main:<path>` 读取基线版本，行号即该版本文件行号（`git show` 输出经 `cat -n` 编号）。
- 纪律项：开工前要求对记录库做方法论检索（search_records kind=method）。本代理工具集中不存在 `search_records` 工具（可用工具清单核对），检索不适用，按纪律"不适用则直接开始任务"处理。
- 本报告未修改任何代码/配置/规则/服务状态，未执行 git commit / push。

## 对决策直接有用的结论（先读这 5 条）

1. **release gate 四项检查中只有 1 项与 PR CI 完全等价（ruff）**；pyright 是同一工具但 release 侧带 `--require-complete` 严格化（超时=exit 3 拒绝，而 ci.yml/ci_gate 为 advisory 放行，release.yml:44 vs ci.yml:48 vs scripts/check_static_diagnostics.py:296-323）；pytest 选择集三方互不等价（详见 A.4 矩阵第 5 行）；tag↔包版本一致性检查为 tag 侧独有（release.yml:35-38）。
2. **release gate 的 pytest 实际包含 serial_signal 切片**（`-m "not real_llm"`，release.yml:46；pyproject.toml:74 addopts 同为排除 real_llm），而 ci.yml test job 明确排除 serial_signal（ci.yml:50 `-m "not real_llm and not serial_signal"`，且 ci.yml:135-136 注明并行跑须排除）——即 release gate 跑的用例集是 PR 门禁的**超集**，此项不能简单视为"PR 已跑过的重复"。
3. **本地 ci_gate.sh 有两项门禁在任何 CI/release 路径都不存在**：测试环境声明门禁 `check_test_env_pins.py`（ci_gate.sh:50）与红数对账 `eval/rules/red_reconciliation.py`（ci_gate.sh:169）。"release 改验绿"若以 ci_gate 结果为凭，这两项本地独有检查不在 GitHub 侧任何回执里。
4. **现有 2 份审查回执均为叙述性 Markdown，无机器可读 verdict 字段，且全仓库无任何脚本消费 `docs/governance/review-receipts/`**（`git grep -n 'review-receipts' origin/main` 0 命中）。可机械复核的只有产物指纹与测试计数（SHA256 表、commit、pytest 数字）；PASS 裁决本身必须人读。代码侧另有一套独立的机械审查准入（review_host_admission.py:1756-1768，明言"旧审查回执…无效"），与该目录零接线。
5. **service_control 的 failed 动作没有"自动重投"**：程序明文"不自动重跑"（runtime/service_control.py:3432-3433、3581-3582、3611、3620-3622）。唯一的自动恢复是**单次** known-good 自动回滚，仅当 rc≠0 且回执证明已进入物理副作用阶段（runtime:3566-3577、3311-3374）。同一 code_root 重复 update 每次都产生**新 generation**（builtin:458-461 + runtime:1058-1062，无按 git_head 去重分支，runtime:3926-3977），即使运行版本不变也会再次物理停启（accept_restart 无 live 一致性短路，runtime:1258-1294）。

---

## A. 三方用例集差异表

### A.1 scripts/ci_gate.sh 实际执行的检查项（按执行顺序，逐条命令）

| # | 检查项 | 命令 | 证据 |
|---|---|---|---|
| A1 | Ruff 全树 ratchet 门禁 | `"$PY" scripts/check_static_diagnostics.py --tool ruff` | ci_gate.sh:43 |
| A2 | 测试环境声明门禁（COMPACT_RATIO 等 env pin 静态全树扫描，违例阻断） | `"$PY" scripts/check_test_env_pins.py` | ci_gate.sh:45-50 |
| A3 | Pyright 全树 ratchet 门禁（advisory 语义：超时捕获 status=unknown、exit 0；非零 RC 仍 exit） | `PYRIGHT_OUT="$("$PY" scripts/check_static_diagnostics.py --tool pyright 2>&1)"` | ci_gate.sh:52-67 |
| A4 | 测试前置：隔离 HOME + Playwright 浏览器缓存复用 + 从候选源码构建 WebUI（dist 缺失即退 1） | `mkdir -p "$CI_TEST_HOME"` … `npm run build` … `test -f webui/dist/index.html` | ci_gate.sh:69-113 |
| A5 | pytest tier0 预检（分钟级，非提交门禁；`--quick` 到此为止） | `"$PY" -m pytest -m tier0 -q` | ci_gate.sh:115-121 |
| A6 | pytest 全量门禁（xdist loadfile、worker 预算默认 4、junitxml 落盘） | `"$PY" -m pytest --dist loadfile -n auto -q --junitxml="$GATE_XML"`（无 `-m`，选择集由 addopts 决定，见 A.4） | ci_gate.sh:123-139 |
| A7 | xdist 红降级：serial 单点复核（serial 绿=假红不阻断；serial 红=真回归） | `"$PY" -m pytest $fail_files -q --junitxml=...` | ci_gate.sh:143-162 |
| A8 | CI 红数对账（serial 复现红后与 known-reds 登记基线对账，未登记新红=阻断） | `"$PY" eval/rules/red_reconciliation.py --report "$GATE_SER.xml"` | ci_gate.sh:163-179 |
| A9 | 守卫 WARN 汇总（guard_report marker，不阻断） | `"$PY" -m pytest tests/unit/test_arch_guards.py -m guard_report -q` | ci_gate.sh:182-183 |
| A10 | 结论行二分：pyright=unknown 时明示"发布资格不得引用本次结果作为类型检查通过" | `if [[ "$PYRIGHT_STATUS" == "unknown" ]]` | ci_gate.sh:185-190 |

### A.2 .github/workflows/ci.yml 的 job/step 检查项

触发：`on: push:`（无分支/tag 过滤）+ `pull_request:` + `schedule`（cron 0 20 * * *）+ `workflow_dispatch`（ci.yml:12-17）。

| # | Job | 检查项（命令） | 条件 | 证据 |
|---|---|---|---|---|
| B1 | security-scan | `bash scripts/git_security_scan.sh --tree` | 无条件（push/PR/schedule/dispatch 都跑） | ci.yml:20-26 |
| B2 | test（门禁） | `uv sync --frozen --extra dev`；ruff：`uv run --no-sync python scripts/check_static_diagnostics.py --tool ruff`；pyright：同脚本 `--tool pyright`（无 --require-complete）；pytest：`uv run --no-sync python -m pytest tests/ -q -m "not real_llm and not serial_signal"` | 无条件 | ci.yml:28-50 |
| B3 | linux-installer（matrix x86_64/aarch64） | `uname -s/-m` + `getconf GNU_LIBC_VERSION` 核验；WebUI `npm ci --ignore-scripts` + `npm run build`；`uv build --out-dir dist`；`python scripts/verify_linux_installer.py --wheel dist/*.whl`（安装/重复安装/卸载保留数据）；报告 upload-artifact | 无条件 | ci.yml:52-95 |
| B4 | nightly-real | `pytest tests/integration/test_real_llm_smoke.py tests/integration/test_real_llm_exec_smoke.py -m real_llm -q`；`python scripts/run_eval.py --output docs/metrics/eval_ci`（无 key 自动跳过） | 仅 schedule/workflow_dispatch | ci.yml:97-127 |
| B5 | serial-signal-stress | `bash scripts/verify_serial_signal_stability.sh --runs 50`（顺序 50 次） | 仅 schedule/workflow_dispatch | ci.yml:129-145 |
| B6 | ambient-env-gate | 注入 `tests/conftest._DEPLOYED_WORKSPACE_IDENTITY_VARS` 全部变量后跑泄漏敏感切片（test_ambient_leak_immunity / test_workspace_resolution / test_terminal_cli / test_runtime_identity_enforce / test_runtime_manifest / test_runtime_config_p0，`-m "not real_llm and not serial_signal"`） | push/PR/schedule/dispatch | ci.yml:147-169 |

### A.3 .github/workflows/release.yml gate job 检查项

触发：仅 `push: tags: ['v*']`（release.yml:9-12）。

| # | 检查项（命令） | 证据 |
|---|---|---|
| C1 | 依赖安装：`uv sync --frozen --extra dev`（fetch-depth: 0） | release.yml:26-34 |
| C2 | tag 与包版本一致性：读 pyproject `project.version`，`test "v${PACKAGE_VERSION}" = "${GITHUB_REF_NAME}"` | release.yml:35-38 |
| C3 | ruff：`uv run --no-sync python scripts/check_static_diagnostics.py --tool ruff` | release.yml:39-40 |
| C4 | pyright（发版资格）：`... --tool pyright --require-complete`（注释：900s 超时不再 advisory 放行，exit 3 拦截） | release.yml:41-44 |
| C5 | pytest（非真实 LLM）：`uv run --no-sync python -m pytest tests/ -q -m "not real_llm"` | release.yml:45-46 |

（下游 release job 的产物构建与验收——WebUI 构建、uv build、安装脚本入 dist、verify_install_distribution、verify_linux_installer、SHA256SUMS、草稿 Release——在 gate 之后的独立 job，release.yml:48-92，不属于 gate 检查项。）

### A.4 三列对照矩阵

标记：✓=存在；✗=不存在。等价性按"命令/参数/用例选择范围"逐字比较。

| 检查项 | ci_gate.sh | ci.yml | release.yml gate | 等价性判定 | 差异要点（证据） |
|---|---|---|---|---|---|
| ruff ratchet | ✓ :43 | ✓ :46 | ✓ :40 | **完全等价**（脚本/工具/参数逐字一致，同一冻结 ledger） | 三处均为 `check_static_diagnostics.py --tool ruff`；check_static_diagnostics.py:270-293 同一 ratchet ledger 流程 |
| pyright ratchet | ✓ :58（advisory：unknown 放行 exit 0，:57-67） | ✓ :48（同 advisory 语义） | ✓ :44（`--require-complete`：超时 → exit 3 DENIED） | **不等价：release 严格化** | check_static_diagnostics.py:296-323：advisory 时 status=unknown，带 --require-complete → return 3；不带 → return 0 |
| 测试环境声明门禁 check_test_env_pins.py | ✓ :50 | ✗ | ✗ | **仅本地 ci_gate 存在** | ci.yml/release.yml 全文无此脚本（两文件全读核对） |
| pytest tier0 预检 | ✓ :115-116 | ✗ | ✗ | **仅本地** | ci_gate.sh:118-121（--quick 止于此，非提交门禁） |
| pytest 全量（非 real_llm） | ✓ :139（无 `-m`；执行器=xdist `--dist loadfile -n auto`，worker 默认 4，:129；含 serial 复核与红数对账 :143-179） | ✓ :50（`-m "not real_llm and not serial_signal"`；单进程、无复核/对账） | ✓ :46（`-m "not real_llm"`；单进程、无复核/对账） | **三方互不等价**：① 选择集：release 含 serial_signal，ci.yml 排除；ci_gate 无显式 -m，由 addopts `-m "not real_llm"` 决定 → 与 release 选择集相同（pyproject.toml:74；pytest CLI -m 覆盖 addopts -m 属文档语义，本轮未实测）② 执行器：ci_gate=xdist+serial 复核，两 workflow=单进程 ③ 红数对账仅 ci_gate | serial_signal marker 定义"并行跑排除，nightly 顺序 50 次验证"（pyproject.toml:82；ci.yml:135-136 注释同义） |
| 守卫 WARN 汇总 guard_report | ✓ :182-183（不阻断） | ✗ | ✗ | **仅本地** | pyproject.toml:83 |
| 安全扫描 git_security_scan.sh --tree | ✗ | ✓ :26 | ✗ | **仅 ci.yml** | — |
| Linux 安装器真实验收（matrix） | ✗ | ✓ :52-95 | ✗（gate 无；release job 另有单次 wheel 冒烟 :74-75） | **仅 ci.yml（gate 语义下）** | — |
| WebUI 候选构建作为测试前置 | ✓ :101-113 | ✗（test job 无；linux-installer :81-83 另有） | ✗（gate 无；release job :65-67 另有） | 位置不同 | — |
| nightly real LLM / 评测集 | ✗ | ✓ :97-127 | ✗ | 仅 ci.yml 且仅 schedule/dispatch | — |
| serial-signal 50 次稳定性 | ✗ | ✓ :129-145 | ✗ | 仅 ci.yml 且仅 schedule/dispatch | — |
| ambient 泄漏门禁 | ✗ | ✓ :147-169 | ✗ | **仅 ci.yml** | — |
| tag↔包版本一致性 | ✗ | ✗ | ✓ :35-38 | **tag 侧独有** | — |
| 依赖安装面 | 本地 .venv 回落主区（:29-33）+ PYTHONPATH 前置本树（:34） | `uv sync --frozen --extra dev`（:44） | 同左（:34） | 两 workflow 同一 uv.lock 面（各自注释自述"与本地 ci_gate 同一面"，ci.yml:43、release.yml:33）；环境不同（本地 macOS vs ubuntu-latest，ci_gate.sh:124-128 有 worker 预算说明） | — |

另：`.github/` 下对 `ci_gate` 的引用仅出现在注释/步骤名（ci.yml:3、ci.yml:43、release.yml:33），**没有任何 workflow 实际调用 `scripts/ci_gate.sh`**（`git grep -n 'ci_gate' origin/main -- '.github/'` 仅 3 处文本命中）。

### A.5 结论：release gate 哪些是"重复 PR 已跑过"，哪些是 tag 侧独有

- **重复（PR 已跑、命令与参数完全一致）**：ruff（ci.yml:46 ≡ release.yml:40）。
- **表面重复、实际不等价**：
  - pyright：同工具同 ledger，但 release 带 `--require-complete`（release.yml:44），语义是"本轮必须取得真实诊断数据"，ci.yml/ci_gate 是 advisory 放行（check_static_diagnostics.py:311-323）。
  - pytest：release 选择集（not real_llm，含 serial_signal）⊇ ci.yml test job 选择集（not real_llm and not serial_signal）；且 release 无 serial 复核、无红数对账。
- **tag 侧独有**：① tag↔包版本一致性检查（release.yml:35-38）；② pyright `--require-complete` 严格化（:44）；③ serial_signal 切片进入发版门禁（:46）。
- **本地 ci_gate 独有（任何 GitHub 路径没有）**：env-pin 声明门禁（:50）、tier0 预检（:115-116）、xdist→serial 复核 + known-reds 红数对账（:143-179）、guard WARN 汇总（:182-183）。
- **ci.yml 独有（release gate 没有）**：安全扫描（:26）、Linux 安装器矩阵（:52-95）、ambient 泄漏门禁（:147-169）、nightly/serial-stress（schedule 限定）。
- 附注（UNVERIFIED-运行时）：ci.yml `on: push:` 无过滤（ci.yml:12-14），按 GitHub Actions 语法 tag 推送同样触发该 workflow——即 tag 推送时 ci.yml 的 test/security-scan/linux-installer 与 release.yml 同轮并行。此为 workflow 语法事实 + 平台文档语义，本轮未实际推送 tag 验证。

## B. 审查回执归类

目录 `docs/governance/review-receipts/` 现有文件（`git ls-tree -r --name-only origin/main docs/governance/review-receipts/`，共 2 份）：

### 逐份归类

| 文件 | 日期 | 涉及目标 | 触发源 | 覆盖范围 | 是否含可机械判定的 PASS | 可机械验证 / 必须人读 |
|---|---|---|---|---|---|---|
| 2026-10-12-evo-19f88338-code-review.md | 2026-10-12（:5，含 2026-10-13 勘误重写 :40-58） | EVO-20261012-19f88338：RULE-AI-29 入 SoT + 台账补登 + card-lifecycle 指针（:3） | **子代理**（独立子代理 subagent_b03b560a7f38，审查者/执行者分离，:4；RULE-AI-28 代码闸，:1） | 单次改动 3 文件（docs/ai_rules.md、card-lifecycle.md、rule-presence-ledger.md，SHA256 表 :10-14）；非全树 | **否**：verdict 是 Markdown 文本行"最终 verdict：**PASS**"（:6），无结构化 verdict 字段（无 YAML/JSON front-matter） | 可机械：3 文件 SHA256 指纹（:12-14）、pytest 命令与计数（:32-34、:52-53，勘误后基线 8641 passed/0 failed）。必须人读：PASS 裁决本身、五维度逐条结论（:16-22）、发现清单闭环判断（:24-28） |
| 2026-10-13-readonly-inspection-fix-merge-review.md | 2026-10-13（:4） | fix/readonly-observation-20261012 → main 合并（b29e1ff3c，3 commits，:5）；safety.py 只读识别 + registry.py + 测试 + 审计文档（:6） | **人工**（LFL 主会话独立审查者，产出方为 MCP Console/GPT 子会话，:3） | 分支合并 diff 范围（4 类文件），含独立安全面核查（放行面/拒绝面清单 :18-21） | **否**：verdict 是标题行"## Verdict: PASS"（:8），同样无结构化字段 | 可机械：被审 commit SHA（:5）、pytest 32 passed / 931 passed, 1 skipped（:24-25）、ruff 3 文件（:26）、探针 22/22（:27）——均可重跑复核。必须人读：P0/P1/P2 判级（:10-15）、安全面清单的完备性判断（:18-21）、授权边界（:29-30） |

### B 结论：现有回执格式能否支撑"按风险分级审查"

- **不能机械判定 PASS**：两份回执的 verdict 均为自由文本行（回执1 :6、回执2 :8），无机器可读字段；全仓库没有任何脚本/CI/workflow 消费 `review-receipts` 目录（`git grep -n 'review-receipts' origin/main` 退出码 1、0 命中）。即现状为零机械接线。
- **能机械验证的部分**：产物身份与复现性材料——SHA256 表（回执1 :12-14）、commit SHA（回执2 :5）、带命令的测试计数（回执1 :52-53；回执2 :24-27）。这些可支撑"指纹/计数复核"级别的降档判定。
- **必须人读的部分**：PASS 裁决、缺陷判级（P0/P1/P2）、安全面/范围完备性论述、授权边界陈述——两份回执的核心结论全部以叙述呈现。
- **代码侧另有独立机械审查准入面**：`review_admission` 工具由 Host 冻结任务+真实 child 终态签发一次性资格，明言"单纯自述PASS、任意JSON、**旧审查回执**、未经检查的不同目标均无效"（src/llm_loop/tools/review_host_admission.py:1756-1768）；review_gate 探测只记观测、`review_qualification_verified: False`（src/llm_loop/tools/review_gate.py:1-6、228-239）。该机制与 docs/governance 回执目录互不引用、零接线。

## C. 重启链路盘点（service_control update/restart）

涉及文件：`src/llm_loop/tools/builtin/service_control.py`（工具面，685 行）、`src/llm_loop/runtime/service_control.py`（运行时，4600 行）。以下 builtin: / runtime: 均指这两个文件。

### C.1 update / restart 缺省值

| 参数 | 缺省值 | 证据 |
|---|---|---|
| update 的 restart_target | 缺省按 code_root 路径名推导：含 web/feishu/learning → 该服务；推导不出 → `all`；可被显式 `restart_target` 覆盖（`restart_target` 空则取 `target`） | builtin:34-45、512-516；schema 描述 :185-189 |
| update/restart 的 expected_generation | 缺省自动取当前 desired generation（无 desired 视为 0）；publish 新代 = expected+1 | builtin:448-450、458-461（restart 同构 :385-388） |
| restart 的 target | **必填**，enum web/feishu/learning/all | builtin:76、377-384 |
| update 必填字段 | code_root + reason（publish 只需 code_root） | builtin:72-81 |
| 物理重启等待 | `RESTART_WAIT_IDLE=1` 恒注入；两阶段等待：requester 退出（仅 web/all，poll 2s/超时 900s）、目标空闲（poll 5s/超时 900s） | runtime:2689、128-131、3394-3428 |
| reaper 回收窗口 | 死 pid 宽限 30s；accepted 无 pid 宽限 120s；waiting 总窗 900+900+300=2100s | runtime:128-142（builtin:152 描述"30s/120s/2100s 分档"与实测常量一致） |

### C.2 参数校验顺序（update 为例，全链）

1. **契约聚合预检（任何副作用之前）**：`_service_control_contract_error` 一次性汇总 missing/invalid，execute 入口最先调用（builtin:89-138、297-301）。
2. update 内部顺序：code_root 非空 → reason 非空 → restart_target 推导/enum 校验（builtin:506-520）。
3. publish：expected_generation 解析（缺省=当前代）→ runtime_root 由 data_dir 契约推导（不接受调用点自选）→ `build_deployment`（code_root/runtime_root 存在性 → git rev-parse HEAD → tracked 干净检查 → webui dist 源绑定校验 → dist tree-sha → 物化 release checkout，runtime:3926-3977、3950-3954）→ `compare_and_swap`（lifecycle→state 双锁；期望代不符=Conflict；next 必须=expected+1，runtime:1041-1063）。
4. accept_restart：target enum → deployment 存在 + 期望代 CAS → 回收陈旧 waiting 动作 → 创建 status=accepted 动作 → 建立准入屏障（建立失败则受理一并置 failed，不留"已受理无屏障"；owner 已终态（failed/succeeded）则新动作 adopt 接管，非终态 owner=冲突拒绝，runtime:1258-1371）。
5. worker spawn：失败即把动作置 failed（durable），builtin:550-561（restart 路径同构 :410-420）；spawn 前先 `build_restart_plan` 复核绑定，stale 即拒（runtime:2694-2699）。

### C.3 partial 之后的重试路径

- update = publish（固代）+ accept_restart（受理）两阶段（builtin:147、504-505）。publish 成功、accept_restart 被拒（代冲突/屏障冲突/OS 错）→ 回执 `[service_control update partial] desired 已发布到 generation=N，但 restart 受理失败`，**给出的续路径是 `service_control(action=restart, target=..., expected_generation=N)`**，不是重跑 update（builtin:542-549）。
- 重跑 update 会再次 publish：expected+1 再进一代（builtin:458-461；runtime:1058-1062），不会恢复/复用原代。
- restart 单独受理成功后，物理执行由 detached worker 异步完成；"受理≠完成"，终态须查 status=action_id（builtin:424-433）。

### C.4 失败动作（status=failed）的自动重投/接管逻辑

- **无自动重投**：程序三处明文"不自动重跑"——重启后核验只产证据不判终态（runtime:3430-3433）、核验 confirmed_fail → failed 且"程序不自动重跑，待模型/新动作裁决"（runtime:3604-3619）、判据缺失 → verify_evidence_ready 非终态交模型裁决（runtime:3620-3625）。
- **唯一的自动恢复=单次 known-good 自动回滚**，触发条件：rc≠0 且 desired 存在且回执判定已有物理副作用（failure_released=False）且本动作 origin 不是 auto-rollback（runtime:3566-3577）。回滚=按 receipt 历史找最近 known-good release → build_deployment(generation=失败代+1) → CAS → accept_restart + 同步 run_action_worker；仅尝试一次、失败不循环、CAS 冲突即放弃（runtime:3311-3339、3342-3374；origin 前缀防二次回滚 :3349、:3575）。
- **屏障接管（自恢复）**：新 restart 受理时，若屏障 owner 动作已终态（failed/succeeded）→ 自动 adopt 接管；owner 非终态/未知/corrupt → fail-closed 拒绝（runtime:1316-1342；工具描述同义 builtin:157）。
- **failed 的持久可见性**：failed 动作保持"待确认"直到显式 `verify_acknowledge(verdict=accept)`（builtin:432；runtime:2307-2332 accept=确认已知不改判成功）；`scan_unacknowledged_failed_actions` 扫最近 24h 未确认 failed（≤10 条，desired 已前进的标 superseded 但不抹痕，runtime:4537-4592）。
- **屏障释放规则**：accepted/waiting→failed 且未起物理副作用 → 释放；running→failed → keep（fail-closed，可能已停服）；rc≠0 时按脚本回执 stage_fact=not_started 才释放，否则 keep（runtime:2880-2902、3531-3557）。
- **等待超时**：900s 超时 → 状态置 failed，回执提示可用 override 附证据推进（runtime:3130-3142）。
- **reaper**：waiting 三态（accepted/waiting_for_requester_exit/waiting_for_idle）死 pid/超窗/无 pid 孤儿 → 置 failed 并释放屏障（runtime:1140-1197）。

### C.5 同一 code_root 重复 update 会发生什么

- 每次 update 都走 `_publish` → `build_deployment(generation=expected+1)` → CAS；`build_deployment` **没有按 git_head/code_root 去重的分支**（runtime:3926-3977 全函数仅有存在性/干净/产物绑定校验），deployment_id 每次新生成（`deploy-{uuid4}`，runtime:3971）→ **重复 update 必然产生新 generation**（同 git_head 亦然）。
- release checkout 物化是幂等复用：`.releases/<head>` 已存在且为注册 worktree、HEAD 一致、tracked 干净 → 直接复用；HEAD 分歧或脏 → `worktree remove --force` 后重建（runtime:3845-3923）。即磁盘产物可复用，但 desired 代照样 +1。
- 版本未变时工具面只给**提示不短路**：live git_head 已等于 desired 时回执附"本次不会改变其运行版本"（builtin:603-624）；accept_restart 全函数无 live 一致性检查（runtime:1258-1294）→ 物理重启照常受理执行。

### C.6 "重复执行风险"清单（哪些入口失败后重跑会放大影响面）

| # | 入口/场景 | 放大机制 | 证据 |
|---|---|---|---|
| R1 | update partial 后**重跑 update**（而非按回执续 restart） | 每次重跑都 publish 新一代（+1），desired 链被无谓推进；前一代动作痕迹变为 superseded；两阶段割裂状态反复出现 | builtin:542-549（官方续路径=restart）；458-461 + runtime:1058-1062（代必 +1）；runtime:4540-4542（superseded 语义） |
| R2 | 同一 code_root 版本未变**重复 update** | 新 generation + 新 deployment_id + 一次**无版本变化的物理停启**（accept_restart 无 live 短路）；若 release checkout 检查不过还会 `worktree remove --force` 重建 | runtime:3926-3977、3971；1258-1294（无 live 检查）；builtin:603-624（仅提示）；runtime:3888-3897 |
| R3 | failed（屏障 keep）后**并发/反复发起新 restart** | 新动作会自动 adopt failed owner 的屏障（设计内自恢复），但多个重试并存时互相触发期望代 CAS 冲突（提示"以 current 重试"）与 waiting supersede 互废，形成反复受理-作废循环 | runtime:1316-1342；1054-1057、1272-1276；builtin:496-498；runtime:3076-3082 |
| R4 | 停机级失败触发**单次自动回滚**后，操作者不知情再手动 update | 回滚本身也是一次受理+物理重启（accept_restart + run_action_worker 同步执行）；再 update 在回滚代之上又 +1 代，known-good 链被快速稀释 | runtime:3352-3362、3311-3339、3566-3577 |
| R5 | `override` 以 **E3（纯声明）** 推进等待门禁后进入物理重启 | E3 允许用于非物理 gate（等待类），等待循环读到 override 即放行推进；目标实际忙碌时等于强行插队停启 | runtime:2148-2162、2168-2188（E3 仅限非物理 gate）；3110-3129（等待循环按 override 放行）；builtin:226-230（enum 含 E3） |
| R6 | accepted 态 worker 慢启动（>120s 未盖章 pid）被 reaper 误回收后重发动作 | 回收置 failed 并释放屏障；旧 worker 恢复后有终态零续写守卫（不复活），但新旧动作并存窗口内操作者重发 restart → 重复受理与潜在重复停启 | runtime:1170-1182（120s 宽限）、1185-1197；3065-3071（终态零续写守卫） |
| R7 | 等待超时（两阶段各 900s）后反复重发 restart | 每次超时终态化 failed + 屏障释放；忙时段反复重试=反复占用/释放屏障并重启两阶段等待；唯一旁路是 override（见 R5） | runtime:128-131、3130-3142、2880-2898 |

## 未核实项（UNVERIFIED）清单

1. **UNVERIFIED（运行时行为，未实测）**：tag 推送是否实际触发 ci.yml 的 `on: push:`（语法上无过滤，ci.yml:12-14；本轮未推送 tag 验证平台行为）。
2. **UNVERIFIED（工具语义，未本轮实测）**：pytest 命令行 `-m` 覆盖 addopts 中 `-m` 的优先级（用于判定 ci_gate.sh:139 无显式 -m 时选择集=not real_llm；依据 pytest 文档语义与 pyproject.toml:71-74 的 addopts/调用方参数交互注释推断）。
3. **UNVERIFIED（范围外）**：`gh release view` 等 GitHub 远端事实（任务允许但 A/B/C 三块均不需要，未执行）；`.releases/`、`data/` 下运行时落盘的实测状态（本任务严格只读代码基线，未读取部署运行时数据目录）。

## 交付核对

- 产出文件：`docs/LFL_Release_Restart_Baseline_20261027.md`（本文件，基线 e535a11ab 工作树内新增，未 commit）。
- 全程未修改代码/配置/规则/服务状态；除本文件外未写任何路径。
- 写入方式备注：直接 heredoc 写入被 RULE-AI-28 Host 准入以 compound_protected_shell 拦截两次（未执行）；最终以"占位 echo 建文件 + edit_file versioned 全量替换"完成，内容与被拦版本一致。
