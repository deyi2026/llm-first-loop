# llm-first-loop-mirror 整改计划

> 来源：2026-10-11 只读代码审查（HEAD `35da887ea`，工作区 231 项未提交改动，全部未跟踪；审查过程零改动仓库）
> 本文件仅为整改计划，不含任何代码改动。落地时**每一步都必须走仓库自己的提交通道**（见第 5 节）。

---

## 1. 一句话现状总结

这是一个工程门禁体系相当成熟（棘轮式静态检查 + 架构守卫 + 已知红登记 + `uv.lock --frozen`）的 LLM 优先 Agent 运行时，**真正卡住提交的只有 2 个具体诊断**（1 个 ruff `I001`、1 组 pyright `reportOptionalMemberAccess`），其余是**口径分叉**（本地领先远端 199 提交，棘轮基线挂在旧 ref 上）与**历史债**（39 处静默异常、13 个 >1500 行文件、约 2900 行未接入生产的 `assurance/`）。

### 支撑证据速览

| 检查 | 结果 |
|---|---|
| `ruff check src tests scripts`（裸跑） | 50 errors（historical=67 → resolved=18） |
| `check_static_diagnostics.py --tool ruff` | **DENIED，new=1**：`tests/unit/test_chatgpt_page_send_collapsed.py:1 I001` |
| `check_static_diagnostics.py --tool pyright` | **DENIED，new=0**，但 `changed_file_diagnostics=2` → `src/llm_loop/llm/chatgpt_surface.py` 的 `"contexts" ... None` |
| `check_test_env_pins.py` | PASS（827 文件，0 违例） |
| `pytest --collect-only` | 8722/8738（16 deselected），13.6s |
| `pytest -n 8 --dist loadfile` | 24F / 8553 passed / 132 skipped / 13E，62s（**全部为本次审查环境沙箱产物**，见第 6 节） |
| `src/llm_loop/assurance/` | 全 src 引用数 **0**（自述「未接入生产运行时」），其 7 个测试文件在 CI `testpaths=["tests"]` 内 |
| `except (Exception\|BaseException): pass` | **39 处**：32 处有说明注释，**7 处只有 `# noqa: BLE001` 无说明** |
| >1500 行 `.py` | **13 个**（12 个在 src），30 天内最高变更 101 次 |

---

## 2. 整改项清单

### P0 — 立即（都是「门禁红」，成本极低）

---

#### P0-1　ruff 新诊断阻断提交（唯一 `BLOCK NEW`）

- **问题**：`tests/unit/test_chatgpt_page_send_collapsed.py:1` — `I001 Import block is un-sorted or un-formatted`。棘轮判定 `new=1` 并 `BLOCK NEW`，这是当前 lint 面的唯一硬阻断。该文件在本地 HEAD（commit `2059e84d4`）但不存在于 `origin/main`，所以历史债基线里没有它。
- **为什么现在做**：一行自动修复，非改不可（否则任何提交都过不了 ruff 棘轮），零行为影响。
- **具体动作**：
  1. `cd /Users/<user>/Project/llm-first-loop-mirror`
  2. `RUFF_CACHE_DIR=/tmp/lfl-ruff .venv/bin/ruff check --fix tests/unit/test_chatgpt_page_send_collapsed.py`
  3. `RUFF_CACHE_DIR=/tmp/lfl-ruff .venv/bin/ruff check tests/unit/test_chatgpt_page_send_collapsed.py` 确认单文件 0 错
  4. `git add tests/unit/test_chatgpt_page_send_collapsed.py`
  5. `bash scripts/r9_commit.sh "fix(r9): 修复 chatgpt-page-send-collapsed 测试 import 排序（棘轮 BLOCK NEW）"`
- **验收标准**：`bash scripts/check_static_diagnostics.py --tool ruff` **exit 0**（`new=0`）；`ruff check tests/unit/test_chatgpt_page_send_collapsed.py` 输出 `All checks passed!`。
- **成本**：5 分钟。
- **风险与回归面**：只重排 import，无行为面；该文件当前因收集期错误无法运行（属环境伪红，见第 6 节），修复后建议在有写权限环境单跑一次 `pytest tests/unit/test_chatgpt_page_send_collapsed.py -q`。
- **提交通道**：`fix(r9):`（标准修复前缀，无附加机检）。

---

#### P0-2　pyright 对「改动文件」的阻断：`_browser` 无 None 守卫

- **问题**：`src/llm_loop/llm/chatgpt_surface.py:706` 定义 `self._browser = None`，但 `:733`（`list(self._browser.contexts)`）与 `:745`（`for context in self._browser.contexts`）直接解引用，无 None 守卫。pyright 报 2 处 `reportOptionalMemberAccess: "contexts" is not a known attribute of "None"`；因这两个文件属「近期改动文件」（`changed[committed]=2`：`src/llm_loop/llm/chatgpt_surface.py`、`tests/unit/test_chatgpt_surface.py`），棘轮按「改动文件零诊断」规则 **BLOCK CHANGED FILE**。
- **为什么现在做**：这是**唯一同时具备「阻断门禁」+「真实崩溃面」**的项。`_browser` 只有在 `:839 connect_over_cdp` 之后才非 None，`:1057` 又置回 None；在 lease 恢复/清理竞态路径上调用 `_owned_context()` / `_find_target()` 会抛 `AttributeError`，而该模块的既有错误类型是 `BrowserSurfaceLeaseError`。
- **具体动作**（二选一，需提交人裁决语义）：
  - **方案 A（推荐，语义更诚实）**：在 `_owned_context()` 与 `_find_target()` 开头加显式守卫
    `if self._browser is None: raise BrowserSurfaceLeaseError("ChatGPT browser is not connected")`。
  - **方案 B（零运行时行为变化）**：只做类型收窄，不加新分支——在解引用前加 `assert self._browser is not None`，并补注释说明「调用方契约保证已连接」。
  - 无论 A/B：改完跑 `PYTHONPYCACHEPREFIX=/tmp/lfl-pycache .venv/bin/python scripts/check_static_diagnostics.py --tool pyright`，并定向跑 `pytest tests/unit/test_chatgpt_surface.py -q`。
- **验收标准**：`check_static_diagnostics.py --tool pyright` **exit 0**（`changed_file_diagnostics=0`）；`pytest tests/unit/test_chatgpt_surface.py` 全绿。
- **成本**：30 分钟（含定向回归）。
- **风险与回归面**：方案 A 会把 `AttributeError` 变成 `BrowserSurfaceLeaseError`——**属可观测行为变化**，必须确认上层有对应 except/恢复分支（该模块下文正是 lease 恢复逻辑）；方案 B 零行为变化但保留潜在 AttributeError。两者都要回归 `chatgpt_surface` 测试面。**建议交回最近两次 `fix(chatgpt-web)` 提交人处理**，因为涉及 lease 恢复语义。
- **提交通道**：`fix(r9):`（若最终改了错误类型/控制流）。若改动仅限类型注解与注释、且不触碰守卫文件，仍可 `fix(r9):`；**不要**用 `refactor(r9):`——该前缀不得触碰行为面文件，且必须附 `wire-fixtures: PASS` 等价性回执。

---

### P1 — 本周（阻断面 + 口径决议）

---

#### P1-1　门禁在「缓存不可写」时以假崩溃收场

- **问题**：`scripts/check_static_diagnostics.py` 调用 ruff/pyright 时未指定缓存目录，受限环境/只读挂载下会以
  `R9 static diagnostic ratchet FAIL-CLOSED: ruff runner crashed (exit=2): Failed to create temporary file ... .ruff_cache/0.16.5/.tmpXXXX` 收场（本次审查实测复现）。这是**把环境问题误报成「分析器崩溃」**，会掩盖真实诊断，也让人误判为代码问题。
- **为什么现在做**：成本小、收益是「门禁输出可信」。且任何 CI/沙箱/容器的只读层都会踩到。
- **具体动作**：
  1. 在 `scripts/check_static_diagnostics.py` 里给子进程显式注入缓存目录（优先 `tempfile.mkdtemp()` 或环境变量 `RUFF_CACHE_DIR`），并在版本不匹配时输出明确提示「请执行 `uv sync --frozen --extra dev`」而非笼统 crash；
  2. 保留「诊断失败即 FAIL-CLOSED」语义不变（不得为了过门禁放宽任何诊断）。
- **验收标准**：把仓库根设为不可写（或 `RUFF_CACHE_DIR` 指向不存在目录）后重跑 `check_static_diagnostics.py --tool ruff`，输出应为**与本次相同的 DENIED/BLOCK 结论**，而**不是** `runner crashed`；正常环境下 exit 码与当前一致。
- **成本**：1–2 小时。
- **风险与回归面**：触碰门禁脚本本身 → **改动这门脚本要格外小心**，必须正反两向自验（正常环境结论不变 + 受限环境不再假崩溃）。属于「测试基建」而非产品行为，无产品回归面。
- **提交通道**：`chore(r9):`（工程/基建变更）。**若同时修改 `tests/guards/*.json` 基线，则必须改走 `guard(r9):`**（规则④防篡改，非 guard 前缀触碰守卫文件一律拒收）。

---

#### P1-2　`assurance/` 约 2900 行未接入生产的代码，需要退役或接入的死线

- **问题**：`src/llm_loop/assurance/`（14 文件、约 2948 行）自述 `Provider-free P0 assurance contracts; not connected to production runtime.`，实测**全 src 引用数 = 0**（`grep -rn "llm_loop.assurance|from \.assurance" src` 排除自身后为 0）；而它的 7 个测试文件（`tests/unit/test_assurance_p1_process_reviewer.py` 等）在 `pyproject.toml` 的 `testpaths=["tests"]` 内，**每次 CI 全量都在跑**，其中 `test_assurance_p1_process_reviewer.py` 还是本次跑红的来源之一。
- **为什么现在做**：不是现在删码，而是**现在定死线**。否则该包持续消耗 lint/type/门禁维护成本，且「测了但没接生产」会给人虚假的安全感。
- **具体动作**（口径类，先决议再动手）：
  1. 项目方给出二选一结论：**(a) 接入生产**（写明接入批次与负责人）或 **(b) 退役**（移出 `src/`，迁到 `evals/` 或 `docs/`，并同步摘掉其测试的 testpaths 覆盖）；
  2. 若选 (b)，执行顺序必须是「先动测试归属、后动源码目录」，避免出现「源码删了测试还在」的红灯窗口；
  3. 在 `docs/subsystem-disposition-*.md` 类文档里补一条登记（与仓库既有 disposition 治理惯例一致）。
- **验收标准**：文档中 `assurance` 条目含明确的 deadline + owner + 二选一结论；若已执行退役，`grep -rn "llm_loop.assurance" src | wc -l` 为 0 且对应测试不再被全量收集（或已迁址并有说明）。
- **成本**：决议 30 分钟；若执行退役 半天–1 天（主要成本在测试迁移与门禁复核）。
- **风险与回归面**：退役会移除一批评测覆盖——**必须先确认没有任何生产路径/未来 spec 依赖它**（引用数为 0 已强证据，但仍需项目方确认）；不碰运行时代码，产品行为零回归面。
- **提交通道**：文档部分 `docs(r9):`；测试归属调整 `test(r9):`；源码迁移 `refactor(r9):`（**注意**：`refactor(r9)` 不得含行为面文件且 body 必带 `wire-fixtures: PASS`）——因此实际执行时大概率要拆成多个单性质提交。

---

#### P1-3　基线分叉：本地领先远端 199 提交，棘轮基线挂在旧 ref

- **问题**：`HEAD=35da887ea`，`origin/main=74ea92522`（对象时间 2026-10-09 23:20），`git rev-list --count origin/main..HEAD = 199`、反向为 0。而 `tests/guards/static_diagnostic_debt.json` 记的 `origin_head=500ee8f3eff0`（提交标题 `guard(r9): backup_store T2 observe → conform`），`check_static_diagnostics.py` 打印 `ancestry_enforced=True`。也就是说：**「历史债」口径锚定在一个既非本地 HEAD、也非当前远端 ref 的提交上**，而本地与远端已分叉。
- **为什么现在做**：这是**口径类，不是写码能解决的**。它决定后面每一次门禁数字是否可解释：远端一旦刷新，`historical` 计数可能整体跳变，或被误读成「突然新增大量债务」。
- **具体动作**（决议 → 再决定是否动基线）：
  1. 项目方裁决权威基线 **(a) 以本地 main 为准** 还是 **(b) 以远端 origin/main 为准**；
  2. 若 (a)：更新基线 `origin_head` 指向本地权威提交，并重跑两个棘轮确认 `new=0`；
  3. 若 (b)：先 `git fetch` 让远端 ref 变新，再重跑棘轮，评估 `historical/current/new/resolved` 的变动是否可接受（**只允许解释，不允许放宽基线**）；
  4. 无论哪种，建议在门禁脚本输出里显式打印「基线 ref + 抓取时间」，避免下一次再靠人脑推断。
- **验收标准**：项目方书面确认基线 ref；`check_static_diagnostics.py --tool ruff|pyright` 在**未放宽任何基线**的前提下 exit 0；脚本输出能看出基线 ref 与其新鲜度。
- **成本**：决议 30 分钟；执行（若需）1–2 小时。
- **风险与回归面**：**最高风险动作 = 改基线**。仓库明文禁止「为了修红灯而放宽架构/测试基线」；任何 `tests/guards/*.json` 变更必须走 `guard(r9):` 并经受规则④防篡改约束。不要用 `LFL_R9_BASE` 之类的环境变量去重新分类已登记的历史债。
- **提交通道**：口径记录 `docs(r9):`；基线文件变更（如确需）`guard(r9):`。

---

#### P1-4　`except …: pass` 的护栏（把既有原则变成机器可查）

- **问题**：全 src 共 **39 处** `except (Exception|BaseException): pass`（AST 精确统计）。其中 **32 处有说明注释**（例：`core/loop/engine_services/interrupted_capture.py:242 → checkpoint failure must not break streaming`、`feishu/approval.py:94 → 白名单读取失败 fail-open`），**7 处只有 `# noqa: BLE001`、无任何原因说明**，无法从代码判断是「有意 fail-open」还是「顺手吞掉」：
  | 位置 | 上下文推断 |
  |---|---|
  | `src/llm_loop/cache_guard/guard.py:468` | 清理会话缓存字典，失败无影响 |
  | `src/llm_loop/core/prompt_build/stages/base_assembly.py:132` | 日志/埋点轴记录 |
  | `src/llm_loop/feishu/bridge.py:203` | 日志等级修补（keepalive） |
  | `src/llm_loop/feishu/bridge.py:716` | SDK 重连钩子挂接 |
  | `src/llm_loop/introspection/tools_goal.py:359` | TaskStore summary 行拼接 |
  | `src/llm_loop/tools/builtin/codearts_dispatch.py:124` | `current_session_id` contextvar 取值 |
  | `src/llm_loop/tools/builtin/workflow.py:428` | 同上（同一模式重复两处） |
  按目录分布：`introspection` 9、`feishu` 8、`tools/builtin` 6、`core/loop/engine_services` 2、`llm` 2、`memory` 2、`task_quality` 2、`tools` 2，`cache_guard`/`core/prompt_build/stages`/`core/trace_leak`/`experiences`/`runtime`/`web` 各 1。
- **为什么现在做**：README 的「错误完整透传，不静默降级」目前**只靠评审纪律**，没有任何静态约束；这 7 处是现成的坏样本。成本低，且能复用现有守卫基建。
- **具体动作**：
  1. 先补齐 7 处：给 5 处补一句原因注释（如 `# noqa: BLE001 — 日志等级修补失败不影响重连`）；
  2. 对 `codearts_dispatch.py:124` 与 `workflow.py:428` 这两处**建议收窄捕获类型**（`current_session_id.get()` 的正常失败面是 `LookupError`，捕获 `Exception` 会连真实 bug 一起吞）——改为 `except LookupError:` 保留原兜底行为；
  3. 在守卫层加一条静态检查：`except` + 单条 `pass` 必须带 `# noqa: BLE001` **且**同行/上一行含 ≥N 字符的原因说明，否则违规；基线可先登记这 39 处现存行（**只允许减少，不允许新增**），新增未说明的静默异常一律阻断。
- **验收标准**：新守卫对当前树 **exit 0**（现存 39 处已登记）；人为插一条 `except Exception: pass` 能被守卫拦下（负例自验）；`ruff check src tests scripts` 结果不劣于当前。
- **成本**：补注释 30 分钟；守卫实现 + 基线登记 2–4 小时；含负例自验共半天内。
- **风险与回归面**：收窄 `except Exception` → `except LookupError` **是行为面变更**（真实非 LookupError 异常将由静默变显性），必须定向跑 `tests/unit/` 中相关工具面测试；守卫新增会改变门禁口径，需按「新增约束不得仅为了变绿而放宽」原则走 guard 通道。
- **提交通道**：注释/收窄 `fix(r9):`；守卫脚本与基线登记 `guard(r9):`（涉及 `tests/guards/*.json` 即为唯一合法前缀）。

---

### P2 — 排期（结构债，需批次化）

---

#### P2-1　13 个 >1500 行 `.py`：按「改动最热」排序拆分

**完整清单（行数｜近 30 天提交数｜近 7 天提交数｜职责）**

| # | 文件 | 行数 | 30d | 7d | 职责 |
|---|---|---|---|---|---|
| 1 | `src/llm_loop/runtime/service_control.py` | 4446 | 35 | 6 | 服务生命周期：status/publish/update/restart，desired deployment + CAS |
| 2 | `src/llm_loop/web/routes.py` | 4194 | 58 | 7 | Web HTTP 路由总表（会话/工作区/文件/认证面入口） |
| 3 | `src/llm_loop/llm/client.py` | 3204 | 27 | 10 | LLM 客户端：请求编排、流式解析、重试/降级、埋点 |
| 4 | `src/llm_loop/browser/perception.py` | 3060 | 22 | 6 | 浏览器只读感知：snapshot 投影、视觉证据、diff/wait |
| 5 | `src/llm_loop/factory.py` | 2837 | **101** | **21** | 组件装配工厂（CLI 与测试共用） |
| 6 | `src/llm_loop/core/loop/engine.py` | 2641 | 38 | 6 | 核心五阶段状态机 LoopEngine |
| 7 | `src/llm_loop/subagent/runner.py` | 2421 | 12 | 1 | 递归子代理执行与反馈 |
| 8 | `src/llm_loop/core/session.py` | 2302 | 17 | 1 | 会话持久化与元数据 |
| 9 | `src/llm_loop/semantic_logic/rules.py` | 2223 | 6 | 0 | Shadow-only 语义规则（默认零行为） |
| 10 | `src/llm_loop/core/history.py` | 2022 | 14 | 0 | 历史预算/压缩/投影 |
| 11 | `src/llm_loop/tools/registry.py` | 1956 | 65 | 5 | 工具注册表与派发 |
| 12 | `src/llm_loop/core/episode_history.py` | 1872 | 7 | 0 | episode 级历史（R9 环登记相关） |
| 13 | `tests/unit/test_llm_client.py` | 1844 | 7 | 1 | LLM 客户端单测 |

- **为什么先不做大拆**：「改动最热」的前 3 名是 `factory.py`(101) / `registry.py`(65) / `routes.py`(58)，而 `factory.py` **正是 R9 架构守卫环登记（`function_size_baseline.json.known_cycles`）的常客**。对热文件做机械拆分与在飞的多条演进线（本地还有 199 个未推送提交）冲突概率极高，会制造大量 rebase 地狱。
- **具体动作**（分批，不一次性做）：
  1. 只挑**热文件中职责最内聚的一段**先拆：建议从 `factory.py` 的「Provider/模型装配」或 `routes.py` 的「工作区 API」入手；
  2. 严格遵守仓库既有 R9 提交流程：`git add <精确目标>` → `bash scripts/r9_commit.sh "refactor(r9): ..."`，body 必带 `wire-fixtures: PASS`；**不得触碰** `src/llm_loop/cache_guard/**`、`src/llm_loop/core/trace_leak/**`、`docs/r824/*.md`（规则②）；
  3. 每次拆分后跑 `pytest tests/unit/test_arch_guards.py tests/unit/test_function_size_guard.py -q`；
  4. 讨论「文件级 1500 行红线」是否加入 `tests/unit/test_function_size_guard.py`——**注意**：该文件变更必须 `guard(r9):`，且新增红线通常要 `refactor(r9)`+ratchet-tighten 例外（`_MIXIN_CAP` 只降不升）。
- **验收标准**：选定文件行数下降且 `test_arch_guards.py` / `test_function_size_guard.py` 全绿；`pyright` 与 `ruff` 棘轮保持 exit 0；等价性回执 `wire-fixtures: PASS` 在 commit body 中可见。
- **成本**：单个文件半天–1 天；13 个文件全量是跨批次工作（数周），不建议列为单次整改。
- **风险与回归面**：**高风险**（纯结构迁移但涉及运行时装配、循环依赖、守卫基线）。必须有定向回归 + 等价性回执；拆环（known_cycles）有专门规则与例外，**不要自己发明拆分方式**。
- **提交通道**：`refactor(r9):`（结构迁移专用，须带等价性回执；不得含行为面文件）；触碰守卫文件/基线时 `guard(r9):`。

---

#### P2-2　遗留 mypy 与方向不清的类型检查面

- **问题**：`.venv/bin/mypy` 存在（mypy 2.3.1）且仓库根残留 `.mypy_cache/3.13`（2026-09-16），但 `pyproject.toml` **没有任何 mypy 配置**，项目既定的类型检查面是 pyright（`[tool.pyright] include=["src"]`）。这造成「工具存在但无契约」——新成员可能跑 mypy 并得到与门禁无关的结论。
- **为什么现在做**：低成本消歧，避免后续有人在错误工具上花时间。
- **具体动作**：二选一并记录：**(a)** 明确「类型检查 = pyright，不再使用 mypy」，在 `docs/DEVELOPMENT_REPAIR_SAFETY.md` 或 CONTRIBUTING 里写一句，并清理 `.mypy_cache`（本地目录，非 tracked）；**(b)** 若确实要引入 mypy，则必须像 pyright 一样进棘轮基线——但那属于新增约束，需说明为何现有 pyright 不够。
- **验收标准**：文档中一处明确声明；仓库根不再出现 `mypy` 缓存（或文档说明其用途）；`git ls-files | grep mypy` 结果与结论一致。
- **成本**：15 分钟（选 a）。
- **风险与回归面**：零（本地缓存清理不影响 git 状态；`.mypy_cache` 本身不被跟踪，已核实）。
- **提交通道**：`docs(r9):`（文档）；删除本地缓存无需提交。

---

#### P2-3　`feishu/__init__.py` 的 9 处 E402：豁免或重构，别只靠棘轮兜着

- **问题**：`src/llm_loop/feishu/__init__.py:9–19` 有 **9 处 E402**（模块级 import 不在文件顶部），是全仓单文件 ruff 诊断最密集处。仓库已有先例：`pyproject.toml` 的 `[tool.ruff.lint.per-file-ignores]` 为 `scripts/injection_r8_remote_ab.py` 显式豁免 E402 并注明原因（「sys.path 引导型独立脚本」）。`feishu/__init__.py` 却靠棘轮历史债名单兜着，**没有声明这是有意设计**。
- **为什么现在做**：属口径澄清——要么承认它是有意模式并显式豁免，要么它是导入顺序脆弱点应当修。低成本。
- **具体动作**：读该文件前 20 行确认引导意图（审查阶段未读全）；若为合法引导模式，则在 `pyproject.toml` 的 `per-file-ignores` 加 `"src/llm_loop/feishu/__init__.py" = ["E402"]` 并写注释说明；**注意**：显式豁免会减少 `current` 计数 → 属于「棘轮值变化」，需按基线流程处理（见 P1-3 口径）。
- **验收标准**：该文件 E402 或为 0、或为显式豁免且注释说明原因；`ruff` 棘轮 exit 0。
- **成本**：30 分钟。
- **风险与回归面**：改 `pyproject.toml` 不影响运行时行为；若选择「重构 import 顺序」则可能触发 feishu 桥启动面回归（需 `pytest tests/feishu tests/unit -k feishu -q`）。
- **提交通道**：`chore(r9):`（工程配置）。

---

### P3 — 观察（记录在册，暂不动手）

| 项 | 位置 | 现状与处置建议 | 成本 |
|---|---|---|---|
| P3-1 依赖下界全 `>=`，可复现性只靠 `--frozen` | `pyproject.toml` | 所有依赖 `>=`；CI 与 README 均用 `uv sync --frozen --extra dev`，`uv.lock`（55 包）保证精确复现。棘轮基线却冻结了**工具精确版本**（ruff 0.16.5 / pyright 1.1.411）→ 用普通 `uv sync` 升级工具会让棘轮因版本不匹配而崩溃。**建议**：保持 `--frozen` 为唯一入口；这条已由 P1-1 的「版本不匹配给明确提示」覆盖，无需单独动作。 | — |
| P3-2 磁盘占用 | `.worktrees/`（64 个，8.3G）、`.venv`（1.6G）、`evals/.venv-eval`（147M）、`evals/pilot/.venv-da`（141M） | 两个 evals venv 确认**未被 git 跟踪**（tracked=0），属实为本地残留。**建议**：定期 `git worktree prune` + 清理失活 evals venv。 | 30 分钟 |
| P3-3 `.env.example` 与凭据清单报告 | `.env.example`（chmod 600，**已 tracked**，19388 字节）；`docs/REPORT-20260909-env-bak-credential-inventory.md`（已 tracked） | `.env`/`.env.bak*` 已被 `.gitignore` 覆盖（第 25–27 行），扫描未发现硬编码真实密钥（唯一 `sk-…` 命中是 4 处测试占位串）。但 `.env.example` 权限 600 且体积与 `.env`（18983 字节）同量级，有「示例即快照」的气味。**审查阶段未读取这两份文件内容**。**建议**：人工确认 `.env.example` 只含占位符。 | 15 分钟 |

---

## 3. 代码修改 vs 口径/决策类：明确分界

| 事项 | 类型 | 说明 |
|---|---|---|
| P0-1 ruff I001 | **代码修改** | 一行自动修复 |
| P0-2 `_browser` None 守卫 | **代码修改**（含语义裁决） | 方案 A 改错误类型，方案 B 零行为变化——需提交人裁决 |
| P1-1 门禁缓存假崩溃 | **代码修改**（基建） | 改 `scripts/check_static_diagnostics.py` |
| P1-2 `assurance/` 退役 | **先决策、后改码** | 死线由项目方定；执行是测试迁移 + 源码搬家 |
| P1-3 基线分叉 | **纯口径/决策** | 写码解决不了；只能由项目方定权威基线，再决定是否动 `tests/guards/*.json` |
| P1-4 静默异常护栏 | **代码修改**（含 2 处行为收窄） | 注释补齐 + 守卫新增 + 基线登记 |
| P2-1 超大文件拆分 | **先决策、后改码** | 拆分批次与目标文件需与在飞演进线协调 |
| P2-2 mypy 面澄清 | **代码/文档** | 建议选「明确只用 pyright」 |
| P2-3 feishu E402 | **代码（配置）** | 显式豁免或重构，二选一 |
| P3-* 观察项 | **记录类** | 不改码 |

**关键约束（来自仓库自身治理）**：任何 `tests/guards/*.json`、`tests/unit/test_arch_guards.py`、`tests/unit/test_function_size_guard.py` 的变更，**唯一合法前缀是 `guard(r9):`**（规则④防篡改）；本计划中 **P1-3、P1-4、P2-1 若触及基线即落入此通道**。反过来，`refactor(r9):` **不允许**触碰行为面文件（`src/llm_loop/cache_guard/**`、`src/llm_loop/core/trace_leak/**`、`docs/r824/*.md`），且 body 必须含 `wire-fixtures: PASS`。

---

## 4. 等待用户/项目方决策的开放问题

| # | 开放问题 | 影响 | 建议裁决方 |
|---|---|---|---|
| Q1 | **棘轮的历史债基线以谁为准**：本地 main 还是 origin/main？（当前本地领先远端 199 提交，`origin_head=500ee8f3eff0` 两头都不沾） | 决定 `historical/current/new/resolved` 四个计数是否可解释；决定是否要动 `guard(r9)` 基线 | 项目方 + 用户 |
| Q2 | **是否复核 `external_red_registry.json` 的 90 条豁免**？（本次 24F/13E 涉及的 12 个测试文件**全部不在**该豁免清单内） | 豁免清单按仓库自己的规则有「逐批销号、非永久遮罩」条款；长期不清会让门禁形同虚设 | 项目方（B4-CLOSE-03 责任人） |
| Q3 | **是否拆分 13 个 >1500 行文件**，优先哪 1–2 个？ | 热文件（`factory.py` 101 次/30d）拆分与在飞演进线冲突风险高 | 项目方 |
| Q4 | **`assurance/` 接入还是退役**，deadline 定在第几批？ | 决定近 3000 行代码与 7 个测试文件是否继续常年维护 | 项目方 + 用户 |
| Q5 | **P0-2 采用方案 A 还是 B**（新增 `BrowserSurfaceLeaseError` 分支 vs 仅类型收窄保留 AttributeError） | 方案 A 是可观测行为变化，需确认上层恢复分支覆盖 | 最近两次 `fix(chatgpt-web)` 提交人 |

---

## 5. 本次审查的环境伪红清单

> **定性**：以下失败/错误由**本次只读审查环境的沙箱限制**造成——实测 `touch data/audit/...` 与 `Path.write_text()` 写仓库内文件均返回 `Operation not permitted`，且沙箱禁止 `sandbox-exec` 系统调用、禁止 `git worktree add` 写入。**换到可写环境或 CI 应消失**。
> **但仍建议项目方复核**：这些测试文件的 test id **不在** `tests/guards/external_red_registry.json` 的 90 条豁免内，若在正常环境真红，会直接阻断提交。

| 类别 | 测试文件 | 数量 | 沙箱证据 |
|---|---|---|---|
| 收集期 ERROR | `tests/unit/test_tool_result_factualization.py` | 4 | `PermissionError: Operation not permitted: tests/fixtures/tool_factualization/death-loop-scenario.json`（shell 可读、`write_text` 被拒，已实证） |
| 收集期 ERROR | `tests/integration/test_browser_semantic_guard_e2e.py`、`tests/integration/test_browser_dispatch_settle_e2e.py` | 9 | 同上（fixture 写/Chromium 环境） |
| FAILED | `tests/unit/test_assurance_p1_process_reviewer.py` | 8 | `Failed: sandbox-exec: sandbox_apply: Operation not permitted`；子进程 milestone flag 等待超时 |
| FAILED | `tests/scripts/test_restart_preflight_source.py` | 2 | `git worktree add --detach ... → exit 128`（沙箱禁写） |
| FAILED | `tests/unit/test_evidence_r7_runner.py`、`test_evidence_r7v2_runner.py`、`test_evidence_r8_runner.py`、`test_evidence_r10_runner.py`、`test_evidence_r11_stress.py`、`test_evidence_r13_stress.py` | 9 | `PermissionError ... data/audit/evidence_r7/runtime/dry/R7-001`（仓库不可写） |
| FAILED | `tests/unit/test_task_budget_operator_mailbox.py` | 4 | 临时目录内 mailbox 校验失败（与沙箱下 fsync/权限语义相关） |
| **合计** | 12 个文件 | **24F + 13E** | 另：8553 passed / 132 skipped |

**另注三条与代码无关、但值得记入门禁运维手册的观察**：
1. 棘轮脚本在「缓存不可写」时会以 `FAIL-CLOSED: ruff runner crashed` 收场（非代码缺陷，已立为 P1-1）。
2. 本项目**未配置 mypy**，`pyright` 才是契约工具（已立为 P2-2）。审查中**未跑 mypy**，因其属规格外工具。
3. **审查期间工作区仍在被写入（重要）**：审查开始时报 231 项未提交改动，结束时报 **232 项**——新增的是 `data/methods/reconcile-existing-install-before-mutating-342e01936595/METHOD.md`（mtime 19:42，与任何一次审查命令无关）。这说明**该仓库是活跃生产区，学习平面/会话运行在后台持续落盘 method candidate**（`data/methods/`，且该目录在 `.gitignore` 的 `data/*` 覆盖内）。对整改的直接影响：① 任何「未提交改动数」「data/ 文件清单」都只能在**同一时刻**内比较，不能跨时刻对账；② P0/P1 提交前务必先 `git add <精确文件>`（B1 模式），不要用 `git add -A`/`-u`，否则会把后台落盘的演进资产误提交；③ 全量 pytest 会在 `data/` 下产生写操作，跑门禁时应确认没有正在运行的生产会话被测试污染（仓库已有 `data/providers.local.json`、LFL_DATA_DIR 等隔离手段，整改时不要削弱）。

---

## 6. 建议执行顺序（一页速览）

| 顺序 | 事项 | 通道 | 成本 | 产出 |
|---|---|---|---|---|
| 1 | P0-1 ruff I001 | `fix(r9):` | 5 min | ruff 棘轮 exit 0 |
| 2 | P0-2 `_browser` 守卫（先定 A/B） | `fix(r9):` | 30 min | pyright 棘轮 exit 0 |
| 3 | Q1 基线口径裁决（`docs(r9):` 记录） | 决策 | 30 min | 基线 ref 明确 |
| 4 | P1-1 门禁缓存假崩溃 | `chore(r9):` | 1–2 h | 受限环境不再误报 |
| 5 | P1-4 静默异常护栏（先补注释，再上守卫） | `fix(r9):` + `guard(r9):` | 半天 | 新守卫 + 39 行基线 |
| 6 | Q4 `assurance/` 死线裁决 → 执行 | `docs/test/refactor(r9):` | 0.5–1 d | 维护面收缩 |
| 7 | Q3 拆分之首（建议 `factory.py` 或 `routes.py` 单一职责段） | `refactor(r9):` | 1 d/次 | 结构债递减 |
| 8 | P2-2 / P2-3 / P3-* | `docs/chore(r9):` | 1 h 合计 | 口径澄清 + 清理 |

> 全文结论：**先做 1、2 两项把门禁恢复绿（35 分钟内可完成），再解决口径（3）**，其余按批次推进。**任何一步都不得以「放宽基线」换取变绿**（仓库明文禁令）。
