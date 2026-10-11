# llm-first-loop-mirror 收尾报告

> 范围：从只读代码审查到本轮 6 个提交的全部工作
> 生成时间：2026-10-11 22:30 (+08:00)
> 被审查仓库：`/Users/yyj/Project/llm-first-loop-mirror`（全程只对该仓库做必要写入，从未新建无关文件）
> 本报告只写有真实证据的内容；未验证之处一律显式标注「未验证 / 无覆盖」

---

## A. 执行摘要

本轮从一次**只读代码审查**出发，最终在 `llm-first-loop-mirror` 上落地 **6 个提交**（**4 个 `fix(r9):` + 2 个 `guard(r9):`**；其中 `9ac1740e5` 为含 P0-1 的合并 `fix`），修掉了三类问题：**门禁基建阻断**（`ci_gate.sh` 因 `pipefail` + 管道早关而 SIGPIPE 自杀，导致整个仓库无法提交）、**诊断工具误报**（ruff 缓存不可写被报成 `runner crashed`）、**代码级缺陷与债务**（`chatgpt_surface` 的 `_browser` Optional 崩溃面、17 处无原因说明的静默异常、75 处 `run_context` inline import 及其失效防御层）。结果：**`main` 当前全绿** —— ruff 棘轮 `exit 0`（historical=67 → current=46）、pyright 棘轮 `exit 0`（45 → 21）、`ci_gate.sh` 五步全过、`tests/unit/test_arch_guards.py` 25 passed、定向回归 195 passed、全量 pytest 一度达到 **8592 passed / 0 failed**。`main` 现处于**本地领先远端 205 个提交、未 push** 的状态，工作区已跟踪改动为 0。**尚未做**：Q1-Q5 五项口径/结构决策、残留 11 个 PROBE worktree 与 1 个 2026-09-25 旧 stash 的处置、13 个 >1500 行文件拆分、剩余 inline import 的 (c) 类清理。

---

## B. 提交清单（时间正序）

> 通道分布核对：`fix(r9):` × **4**（`9ac1740e5`、`42886bb30`、`4f12265cc`、`f5799c467`）+ `guard(r9):` × **2**（`a48094102`、`0d2574d66`）。

| # | hash | 标题 | 文件（数） | 行数 | 通道 | 门禁 |
|---|---|---|---|---|---|---|
| 1 | `9ac1740e5` | `fix(r9): 修复 ci_gate 管道早关导致的门禁基建失败，并清除 ruff BLOCK NEW` | `scripts/ci_gate.sh`、`tests/unit/test_chatgpt_page_send_collapsed.py`（2） | `2 insertions, 3 deletions` | `fix(r9):`（合并提交，方案 A） | 机检 PASS（2 files，五规则全过）→ ci_gate EXIT=0 → 安全扫描通过 → HEAD 复核 PASS |
| 2 | `42886bb30` | `fix(r9): chatgpt surface 未连接时 fail-closed 抛租赁错误` | `src/llm_loop/llm/chatgpt_surface.py`、`tests/unit/test_chatgpt_surface.py`（2） | `70 insertions, 1 deletion` | `fix(r9):` | 机检 PASS（2 files）→ ci_gate EXIT=0（PROBE=842618efb）→ 提交 |
| 3 | `4f12265cc` | `fix(r9): 诊断棘轮不再把缓存不可写误报为 runner crashed` | `scripts/check_static_diagnostics.py`、`tests/unit/test_static_diagnostic_gate.py`（2） | `72 insertions, 3 deletions` | `fix(r9):` | 机检 PASS（2 files）→ ci_gate EXIT=0（PROBE=1f9049458）→ 提交 |
| 4 | `f5799c467` | `fix(r9): 为静默异常吞没补原因说明（P1-4 A 类）` | 14 文件（src 7 + tests 1 + scripts 6） | `24 insertions, 5 deletions` | `fix(r9):` | 机检 PASS（14 files）→ ci_gate EXIT=0（PROBE=2aa6dfcac）→ 提交 |
| 5 | `a48094102` | `guard(r9): 新增静默异常吞没守卫（except+单条 pass 必须带原因说明）` | `tests/unit/test_arch_guards.py`（1） | `150 insertions` | `guard(r9):`（规则④） | 机检 PASS（1 file）→ ci_gate EXIT=0（PROBE=d7f33846f）→ 提交 |
| 6 | `0d2574d66` | `guard(r9): run_context inline import 提升为模块级 + 静默吞没常量随动（混合提交）` | 35 文件（34 源文件 + `tests/unit/test_arch_guards.py`） | `86 insertions, 120 deletions` | `guard(r9):`（规则④；混合提交经用户裁决） | 机检 PASS（35 files，五规则全过）→ ci_gate EXIT=0（PROBE=d42de2228）→ 提交 |

**注**：提交 1 的通道虽是 `fix(r9):`，但它按用户裁决做过一次**合并**（原计划「①门禁修复 ②P0-1」两个提交，因棘轮是全树判定 + P0-1 未入树会在 `[1/5]` 被 `BLOCK NEW` 拦下，改为合并）。提交 6 同理为混合提交。

---

## C. 修复项与验收证据

### C-1　P0-1：ruff `BLOCK NEW`（唯一 lint 硬阻断）

- **问题**：`tests/unit/test_chatgpt_page_send_collapsed.py:1` `I001 Import block is un-sorted or un-formatted`。棘轮判定 `new=1` 并 `BLOCK NEW`。
- **根因**：该文件在本地 HEAD（`2059e84d4`）但不存在于 `origin/main`，历史债基线里没有它；实际违规是 import 块后**多了一个空行**（双空行 → 单空行），import 顺序本身是对的。
- **改动**：`ruff check --fix` 该文件 → 删除 1 个空行（纯格式，零行为变化）。
- **验收证据**：
  ```
  RUFF_CACHE_DIR=/tmp/lfl-ruff .venv/bin/python scripts/check_static_diagnostics.py --tool ruff
  → R9 ruff: historical=67, current=49, new=0, resolved=18, changed_file_diagnostics=0
  → R9 ruff: PASS ...   [exit=0]
  ```
  修复前同一命令：`new=1` + `BLOCK NEW x1: tests/unit/test_chatgpt_page_send_collapsed.py I001`，`exit=1`。

### C-2　P0-2：`chatgpt_surface` 未连接时 fail-closed

- **问题**：pyright 报 2 处 `reportOptionalMemberAccess: "contexts" is not a known attribute of "None"`（`src/llm_loop/llm/chatgpt_surface.py:733:39` 与 `:745:38`）；该文件属「近期改动文件」，棘轮按规则 **BLOCK CHANGED FILE**。
- **根因**：`__init__` 设 `self._browser = None`（`:706`），`close()` 又置回 None（`:1057`），只有 `open()` 内 `:839` 赋真实值；`_owned_context()`（`:733`）与 `_find_target()`（`:745`）裸解引用。
- **改动（3 处 + 2 用例）**：
  - `_owned_context()`、`_find_target()` 各加 `if self._browser is None: raise BrowserSurfaceLeaseError("ChatGPT browser is not connected")`
  - `open()` C-1 加强：`connect_over_cdp` 结果先接局部变量，`None` 则抛 `BrowserSurfaceLeaseError("CDP connect_over_cdp returned no browser")`，再赋 `self._browser`
  - 新增用例：`test_stale_lease_with_no_connected_browser_fails_closed`、`test_cdp_connect_returning_no_browser_fails_closed`
- **验收证据**：
  ```
  .venv/bin/pyright src/llm_loop/llm/chatgpt_surface.py
  → 0 errors, 0 warnings, 0 informations            （修复前 = 2 errors）

  scripts/check_static_diagnostics.py --tool pyright
  → R9 pyright: historical=45, current=22, new=0, resolved=23, changed_file_diagnostics=0
  → R9 pyright: PASS ...   [exit=0]

  pytest tests/unit/test_chatgpt_surface.py tests/unit/test_chatgpt_web_model_client.py -q
  → 54 passed in 0.16s
  ```
- **叙事更正（重要）**：见 D-1。

### C-3　`ci_gate.sh` 门禁基建 SIGPIPE（本轮最有价值的一项）

- **问题**：`bash scripts/ci_gate.sh` 在 PROBE 里**一个字节都不产出**就退出，`r9_commit.sh` 因此报
  `❌ ci_gate 非零退出且未达 [5/5] 测试步——基建失败（非测试红），中止`。**整个仓库此前无法提交**。
- **根因**：`scripts/ci_gate.sh:31`（与 `:88` 同型）
  ```bash
  MAIN_WT="$(git worktree list --porcelain | head -1 | cut -d' ' -f2)"
  ```
  脚本头部 `set -euo pipefail`；`head -1` 读完首行即关闭管道 → `git` 写端收 **SIGPIPE**（exit 141）→ `pipefail` 判失败 → `set -e` 在打印 `═══ [1/5]` 之前**杀掉整个脚本**（这解释了日志 0 字节）。本仓 `git worktree list --porcelain` 现输出 102 个 worktree / 18299 字节，必然触发。
  **注意**：这不是「输出超 64KB 缓冲」——真实机制是**读端提前关闭**。对照实验：`awk 'NR==1{...;exit}'` 同样 141，`sed` 读完整管道则 0。
- **改动（两行）**：
  ```diff
  -  MAIN_WT="$(git worktree list --porcelain | head -1 | cut -d' ' -f2)"
  +  MAIN_WT="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
  ```
  改动后全脚本已无任何 `head` 调用（`grep -n "head " scripts/ci_gate.sh` → 无）。
- **验收证据**：
  ```
  对照实验（均带 set -euo pipefail）：
    原写法 head|cut            -> exit=141
    新写法 sed -n '1s/...'     -> exit=0
    awk + exit（对照）         -> exit=141

  bash scripts/ci_gate.sh
  → ═══ [1/5] Ruff …  ═══ [2/5] … ═══ [3/5] … ═══ [4/5] … ═══ [5/5] …
  → （xdist 全量绿）
  → ✅ ci_gate 全链路通过   [exit=0]
  ```
- **附带产出**：修复后 `r9_commit.sh` 能正常走完「机检 → 门禁 → commit」三步，本轮后续 5 个提交全部通过。

### C-4　P1-1：诊断棘轮把「缓存不可写」误报为工具崩溃

- **问题**：`scripts/check_static_diagnostics.py` 在缓存目录不可写时输出
  `R9 static diagnostic ratchet FAIL-CLOSED: ruff runner crashed (exit=2): error: Failed to initialize cache at /proc/nonexistent: Read-only file system (os error 30)`，`exit=2` —— 环境问题被当成工具崩溃，掩盖真实诊断。
- **根因**：`run_analyzer()`（原 `:77`）用 `os.environ.copy()` 起子进程，**从不设置缓存变量**，完全继承父环境；`returncode not in (0,1)` 分支（原 `:94-95`）把它抛成 `RuntimeError`，顶层 `:245-247` 包成 `FAIL-CLOSED`。另外 ruff 在缓存不可写时直接 exit 2（实测）。
- **改动（最小）**：
  - 新增 `analyzer_cache_dir()` 上下文管理器：`tempfile.mkdtemp()` 建**必然可写**的私有临时缓存，`finally` 清理；若连平台临时区都不可写，抛**显式可操作**错误（提示设 `TMPDIR`/`RUFF_CACHE_DIR`），不静默吞。
  - `run_analyzer(..., cache_dir=None)` 新增可选参数：非 None 时注入 `RUFF_CACHE_DIR` 与 `PYRIGHT_PYTHON_CACHE_DIR`；`main()` 用 `with` 包裹调用。
  - 工具版本漂移报错补 `uv sync --frozen --extra dev` 提示与「不要改基线」说明。
  - **未动**棘轮判定规则、未动 `tests/guards/*.json` 数值。
- **验收证据（正反两向）**：
  ```
  正向（正常环境）：
    --tool ruff    → historical=67, current=49, new=0, resolved=18 → PASS, exit=0
    --tool pyright → historical=45, current=22, new=0, resolved=23 → PASS, exit=0

  反向（故意不可写缓存）：
    RUFF_CACHE_DIR=/proc/nonexistent         --tool ruff    → PASS, exit=0（修复前 exit=2 runner crashed）
    PYRIGHT_PYTHON_CACHE_DIR=/proc/nonexistent --tool pyright → PASS, exit=0
  ```
  新增用例 2 条（`tests/unit/test_static_diagnostic_gate.py`）：不可写缓存下 `main()` 仍返回 0；版本漂移报错含 `uv sync` 提示。**负例自验**：临时去掉 cache_dir 注入后，第 1 条用例精确复现
  `RuntimeError: ruff runner crashed (exit=2): … Failed to initialize cache …`。
- **附带事实**：实测 pyright 侧「缓存不可写」**不会**崩溃（`PYRIGHT_PYTHON_CACHE_DIR=/proc/nonexistent` 直接跑 pyright 仍 `exit=0`，因它用自带 `dist/`）；给 pyright 注入缓存属**预防性**，不是已证实的缺陷。

### C-5　P1-4：静默异常吞没护栏

- **问题**：`except (Exception|BaseException): pass` 全仓（src/tests/scripts）共 **54 处**，其中 **16 处无原因说明**（初查报的是 src 内 39 处 / 7 处弱，扩面后数字更大）。
- **根因**：仓库 README 明文「错误完整透传，不静默降级」，但**只靠评审纪律**，无静态约束；且实测即使删掉 `# noqa: BLE001` 这些处照报 BLE001（因为 ruff `select` 里**没有** BLE）→ `noqa` 是前瞻性写法，真实护栏只能自建。
- **改动**：
  - **A 类（17 处注释）**：为无理由的处补原因注释（写「为什么必须 fail-open」，非复述代码）。含 `s0_browser_attestation_probe.py` 的 2 处**既有** ruff 债务（`SIM115` 加 noqa + 说明；`SIM105` 改 `contextlib.suppress`）——因棘轮要求「改动文件零诊断」必须一并清偿。
  - **B 类（0 处收窄）**：判定**两处都不该收窄**（见下）。
  - **守卫**：`tests/unit/test_arch_guards.py` 新增 4 条用例（含合成树 4 样本语义断言 + 显式负例），规则 = 「`except(Exception|BaseException)` 且 body 仅一条 `pass` 时，handler 源码段内必须有注释，去掉 `noqa` 代号后仍 ≥3 字符」；扫描面 `src/tests/scripts`；**零容忍、不设新基线文件**，存量下限由 `SILENT_SWALLOW_MIN_SITES` 承载。
- **B 类 0 收窄的判定与理由**（用户要求「无法证明上层能处理就不收窄」）：
  - 两处候选：`tools/builtin/codearts_dispatch.py:121`、`tools/builtin/workflow.py:425`。
  - 决定性事实：`run_context.py:19-21` 的 `current_session_id` 是 **`ContextVar(default="")`**，`.get()` **永不抛 `LookupError`** → 上次建议的 `except LookupError` **永远捕不到任何东西**。
  - 真实异常来自 **inline import**；两文件的模块级**从未**导入 `run_context` → 收窄为 `LookupError` 会让 `ImportError` 冒泡，把「session_id 退化为空」升级成「远端派发整体失败」，而**上层处理能力未验证**。
  - 故两处保留宽捕获并补注释。（该结论在后续 inline import 批次中随「提升 + 删 except」一并解决。）
- **验收证据**：
  ```
  # A 类提交前自检
  ruff 棘轮 → historical=67, current=47, new=0, resolved=20, changed_file_diagnostics=0 → PASS
  pytest tests/unit/test_arch_guards.py → 25 passed

  # 守卫真实树负例自验（必须暂存，否则 D-07 读源口径回退 HEAD 看不见）
  注入违规到 src/llm_loop/timekeeping.py + git add →
  AssertionError: 静默异常吞没（except Exception: pass 无原因说明）：src/llm_loop/timekeeping.py:35
  git reset + git checkout 还原 → 2 passed
  ```
  当前实测：全仓静默吞没 **51 处、无理由 0 处**。

### C-6　inline import 批次（`run_context` 提升）

- **问题**：`run_context` 相关 inline import 共 **75 处 / 35 文件**，其中 22 处在 try 内；其中 2 处（`codearts_dispatch`、`workflow`）的 `try/except: pass` 是**已被证明永不可能失败**的防御层。
- **根因**：历史遗留——`run_context` 是**叶子模块**（模块级只 `import contextvars`，无任何 `llm_loop` 反向依赖），inline import 并非为破环而设。
- **改动**：34 文件、75 处 inline import → 模块级（同符号同来源、别名保留）；消除 2 处失效 try/except + `path_registry.py` 除外；顺带清偿 `status.py` 既有 pyright 债务（`_normalize_dimensions(known: set[str])` → `collections.abc.Set[str]`，函数内只做 `in`/迭代）。
- **无环论证（可复核）**：AST 构建**模块级** import 依赖图（447 模块 / 1329 边）→ Tarjan SCC：现有环 **3 个**（`core.session`+`event_log.*`；`core.loop.engine`+engine_services 族；`web.preview_routes`+`web.routes`），**`run_context` 不在任何环内**；再对 35 个目标模块**逐个模拟加边后重算 SCC** → **0 个**产生含 `run_context` 的环。
- **导入期副作用**：`run_context` 模块级**零副作用**（不读环境变量、不建连接、不注册全局、不读文件）。
- **验收证据**：
  ```
  # 导入实证
  35 个改动模块 + cli/web/web.routes/factory/tools.registry/core.loop.engine/subagent.runner/feishu.bridge/codearts.scheduler 全量 import → 0 失败

  # 棘轮
  ruff   → historical=67, current=46, new=0, resolved=21, changed_file_diagnostics=0 → exit=0
  pyright → historical=45, current=21, new=0, resolved=24, changed_file_diagnostics=0 → exit=0

  # 门禁
  bash scripts/ci_gate.sh → 五步全过，exit=0（xdist 全量绿）

  # 定向回归
  pytest tests/unit/test_wire_fixtures.py tests/unit/test_arch_guards.py tests/unit/test_introspection_status.py tests/unit/test_fleet_effect_fence.py tests/unit/test_workflow.py tests/codearts/ -q → 195 passed
  ```
- **未纳入：`tools/path_registry.py` 整文件退出本批**。原因：其 inline import 被 `tests/unit/test_path_registry_isolation.py` 当**隔离契约**钉住——3 个用例用 `monkeypatch.setattr(rc, "workspace_base", …)` 注入故障，**依赖函数内 import 的运行时查找**；提升后调用点绑死模块级符号，patch 失效 → 门禁报 `DID NOT RAISE <class 'RuntimeError'>`。全仓扫描确认**只有 `workspace_base` 有此依赖**（10 个 ContextVar 被 patch 次数均为 **0**）。

---

## D. 关键更正与教训

### D-1　我把「崩溃窗口」讲重了（P0-2 叙事的更正）

设计阶段我断言 `chatgpt_surface` 存在「connect 失败 + 陈旧 lease → `_find_target` 解引用 None → `AttributeError`」的真实崩溃窗口，并据此写了用例 `test_open_with_unreachable_cdp_and_stale_lease_fails_closed`。**实测把该用例跑红**：`RuntimeError: cdp endpoint unreachable` 直接冒泡。
**真相**：`open()` 的 `except Exception`（`:909-911`）只 `self.close(); raise`，**不吞不换** → `connect_over_cdp` 一旦抛错，异常在 `:843` 就离开 `open()`，`_load_recoverable_lease()` / `_find_target()` 那两行**永不执行**。即「抛错型失败」**不可达**该窗口。已改用两条**真正可达**的用例（守卫本身；C-1 的 `return None` 型失败）。
**结论**：pyright 诊断与守卫修复都仍然正确，但**原设计的「错误掩盖」叙事只对 `return None` 型失败成立**，对 `raise` 型失败不成立。

### D-2　我对「自我指涉死锁」的漏判

我曾判断提交一的失败是「`ci_gate.sh` 自我指涉死锁」。**错**。真因是**棘轮是全树判定、与暂存面无关**：`ci_gate` 的 PROBE 树只含**本次暂存文件**，因此只要 P0-1 的修复还没 commit，**任何不含它的提交**都会在 `[1/5]` 被 `BLOCK NEW` 拦下。实测反证：同一时刻在主仓库（P0-1 在工作区）跑同一棘轮 → `new=0 → PASS`，即「把 P0-1 放进树就绿」。
**教训**：判定提交失败原因前，先确认判定面的**输入集合**（暂存树 vs 工作区 vs 提交态），不要假设。

### D-3　`git stash pop` 误弹旧 stash 事故

- **经过**：为对照「修复前 pyright 行为」，我执行 `git stash push -- scripts/check_static_diagnostics.py`。该文件**已 commit、无未暂存改动** → `git stash` **什么都没存**；紧接着的 `git stash pop` 于是弹出了**栈顶旧 stash**（`stash@{0}`，2026-09-25，38 文件「annotation-only 注释审阅」改动）→ 工作区被灌入 27 个 staged `M` + 11 个 `UU` 冲突。
- **根因**：本仓 stash 栈是**共享的历史栈**（当时 11 条），`pop` 永远取栈顶，不会分辨「你刚 push 的那条」。
- **恢复**：取证（`git stash show --name-only` 与脏文件清单 diff **完全一致 38=38**，且该 stash **仍在列表、hash `02a4c25a` 未变**——pop 因冲突未 drop）→ `git reset` 清索引 → `git checkout -- <那 38 个文件>` 从 HEAD 取回。复核：已跟踪改动 0、`stash@{0}` = `02a4c25a` 原值、38 文件内容完整、无 `<<<<<<<` 残留、HEAD 未变。
- **结论（已写入长期记忆）**：**该仓库禁止使用 `git stash push/pop`**；需要旧版本对照一律 `git show <rev>:<path>` 取到 /tmp 再运行。**无数据丢失**。

### D-4　常量 `SILENT_SWALLOW_MIN_SITES` 由我（守卫作者）自己下调（治理点）

`SILENT_SWALLOW_MIN_SITES` 是我在 `a48094102` 刚加的守卫常量；`0d2574d66` 又由我把 53 → 51。形式上属**「作者自证本次防护调整」**，与该仓库防篡改精神（守卫文件修改走 `guard(r9)` + 独立复核）存在张力。本批因**tier0 暂存树自洽 与 规则④ 正面相撞**（下调常量的提交必须同时含把 count 降下来的源码改动，故必修成混合提交），经用户显式裁决接受。**此点应由后续复核者独立检查**：确认 51 与实际 count 一致、且下调是「消除失效防御」而非「放宽基线」。

### D-5　依赖图脚本第一版 bug（误报 35 文件已模块级导入）

我的首版 import 图脚本在汇总时（`for node in tree.body: for n in ast.walk(node)` + 只保留「最后一个 llm_loop 导入」）把 `codearts_dispatch.py`、`workflow.py` 等**误判为已模块级导入 `run_context`**，并据此输出「35/35 已导入、需要新增边 = 0」。**实测 grep 当场证伪**（两文件模块级只有 `codearts.models`/`core.message`）。
**修正**：改用**逐文件精确 AST 比对**（模块级符号集合 vs inline 符号集合），正确结果 = **74 处需新增 + 1 处纯冗余**。
**教训**：图/统计脚本的结论必须与至少一个**独立手段**（grep/直接读文件）交叉验证后再采信。

### D-6　提升 inline import 的系统性反面约束：monkeypatch 运行时查找

`tests/unit/test_path_registry_isolation.py` 依赖「函数内 import 的运行时查找」来 monkeypatch `rc.workspace_base`。**任何批量提升 inline import 的后续批次，都必须先扫 `monkeypatch.setattr(<target module>, "<symbol>", …)`**，否则会静默破坏隔离测试（本次是 3 个用例直接 FAIL 才暴露）。本仓只有这一处命中，但它是一条**通用约束**：可 patch 性是某些测试契约的一部分，与「结构整洁」冲突。

---

## E. 未做 / 待决策

| # | 事项 | 现状与需要谁定 |
|---|---|---|
| Q1 | **棘轮基线以谁为准**：本地 `main` vs `origin/main` | 本地领先远端 205 提交；基线记 `origin_head=500ee8f3eff0`（既非 HEAD 也非当前远端）。决定 `historical/current/new/resolved` 是否可解释 |
| Q2 | **是否复核 `external_red_registry.json` 的 90 条豁免** | 首次审查的 24F/13E 涉及 12 个测试文件，**全部不在**该豁免清单内；仓库规则要求「逐批销号、非永久遮罩」 |
| Q3 | **是否拆分 13 个 >1500 行文件、优先哪 1-2 个** | 见下表；热文件拆分与在飞演进线冲突风险高 |
| Q4 | **`assurance/` 接入还是退役、deadline** | 约 2948 行、全 src 引用数 **0**（自述「not connected to production runtime」），其 7 个测试在 `testpaths=["tests"]` 内**每次全量都在跑** |
| Q5 | ~~P0-2 A/B~~ | **已裁决 A 并落地**（`42886bb30`），不再挂起 |
| R1 | **残留 11 个 `/tmp/r9probe.*` worktree** | **更正此前报告**：不是 4 个，是 **11 个**（每次门禁运行新建、失败/成功路径未清）。它们在 `git worktree list` 中注册着，且**本身贡献了 `git worktree list` 的输出体量**（与 C-3 的 SIGPIPE 触发面相关）。处置需用户决定 |
| R2 | **2026-09-25 旧 stash `02a4c25a`（38 文件）** | 仍原样保留在 `stash@{0}`（栈内共 11 条）。内容为「pre-web-restart: comment-review edits（annotation-only）」。处置需用户决定（本人不是其作者） |
| R3 | **剩余 inline import** | 普查 760 处中，(c) 类（可选依赖/延迟加载等）与其它 llm_loop 模块的 inline import **未纳入**本批；后续批次必须先做 D-6 的 monkeypatch 扫描 |
| R4 | **13 个 >1500 行文件** | 见下表，需定拆分批次 |
| R5 | **`.env.example` 权限与体积** | 已 tracked、`chmod 600`、19388 字节（与 `.env` 的 18983 字节同量级）。**全程未读其内容**。建议人工确认只含占位符 |
| R6 | **未 push（本地领先 205 提交）** | 是否 push、由谁决定、是否先同步 `origin/main`（远端仍停在 `74ea92522`，2026-10-09） |

**13 个 >1500 行 `.py`（当前实测，含本轮增幅）**

| 文件 | 行数 |
|---|---|
| `src/llm_loop/runtime/service_control.py` | 4446 |
| `src/llm_loop/web/routes.py` | 4194 |
| `src/llm_loop/llm/client.py` | 3204 |
| `src/llm_loop/browser/perception.py` | 3060 |
| `src/llm_loop/factory.py` | 2840 |
| `src/llm_loop/core/loop/engine.py` | 2637 |
| `src/llm_loop/subagent/runner.py` | 2413 |
| `src/llm_loop/core/session.py` | 2302 |
| `src/llm_loop/semantic_logic/rules.py` | 2223 |
| `src/llm_loop/core/history.py` | 2022 |
| `src/llm_loop/tools/registry.py` | 1955 |
| `src/llm_loop/core/episode_history.py` | 1872 |
| `tests/unit/test_llm_client.py` | 1844 |

---

## F. 环境伪红清单

首次只读审查时，在**受限沙箱**（仓库不可写、`sandbox-exec` 不可用）下跑全量 pytest：
```
24 failed, 8553 passed, 132 skipped, 13 errors in 62.42s
```
**逐一归因（全部为环境产物，非项目缺陷）**：
- 13 ERROR：`test_tool_result_factualization.py`(4) + `test_browser_semantic_guard_e2e.py`/`test_browser_dispatch_settle_e2e.py`(9) —— `PermissionError: [Errno 1] Operation not permitted`（写 fixture 被拒）
- 8 FAILED：`test_assurance_p1_process_reviewer.py` —— `Failed: sandbox-exec: sandbox_apply: Operation not permitted`
- 2 FAILED：`tests/scripts/test_restart_preflight_source.py` —— `git worktree add … → exit 128`
- 9 FAILED：`test_evidence_r{7,7v2,8,10}_runner.py` + `test_evidence_r{11,13}_stress.py` —— 写 `data/audit/evidence_*/` 被拒
- 4 FAILED：`test_task_budget_operator_mailbox.py`
- 沙箱拒绝的直接实证：`touch data/audit/...` → `Operation not permitted`；`Path.write_text()` 写仓库内文件 → 同样被拒（但 shell 可读）
- 这些 test id **均不在** `external_red_registry.json`（90 条豁免）内 → 若在正常环境真红会直接阻断提交

**反证（最关键的证据）**：沙箱放开为 `danger-full-access` 后，**同一份代码**跑全量：
```
8592 passed, 132 skipped, 25 warnings in 60.95s     [exit=0]
```
—— 上述 **24F/13E 全部消失、零红**，反向证实它们确为环境伪红。

---

## G. 当前状态快照

```
仓库:        /Users/yyj/Project/llm-first-loop-mirror
HEAD:        0d2574d66  guard(r9): run_context inline import 提升为模块级 + 静默吞没常量随动（混合提交）
已跟踪改动:  0（工作区干净）
未跟踪:      262（全部为后台演进资产：data/methods/**、docs/promotion/**、experiences/**）
             ⚠️ 该数字持续变动（后台学习平面不断落盘；本轮观察 231 → 262），只能同一时刻内比较
stash@{0}:   02a4c25a145b484942c5e0d6e4236b54bf74ea49（2026-09-25 旧条目，未动）
stash 总数:  11
remote:      lfl  https://github.com/deyi2026/llm-first-loop.git（未改动）
origin/main: 74ea92522（2026-10-09，未刷新）
未 push:     205 个提交（origin/main..HEAD）
残留 probe:  11 个 /tmp/r9probe.*（已注册在 git worktree list）

质量门禁（提交后复验）:
  ruff 棘轮    → historical=67, current=46, new=0, resolved=21, changed_file_diagnostics=0 → exit=0
  pyright 棘轮 → historical=45, current=21, new=0, resolved=24, changed_file_diagnostics=0 → exit=0
  arch 守卫    → tests/unit/test_arch_guards.py 25 passed
  ci_gate      → 五步全过，exit=0（xdist 全量绿）
```

---

## H. 证据边界声明（未验证之处）

- **全量 pytest 在本地当前树的最新数字**：最后一次全量运行是沙箱放开后（`8592 passed`）与 CI gate PROBE 内的 `（xdist 全量绿）`。**未**在 `0d2574d66` 上单独再跑一次完整全量并记录数字——但 `ci_gate` 的全量步骤已在该提交的 PROBE 树内全绿。
- **`path_registry` 那条隔离契约分支**：3 个用例覆盖「`workspace_base` 抛错 → `_registry_file` 抛 `RuntimeError`」，**有测试覆盖**。反例是 P1-4 的 B 类两处 —— 它们的 `except` 分支**无任何测试覆盖**（声明为无覆盖，不是「验证过了」）。
- **`assurance/` 是否真的无人依赖**：证据是 `grep` 全 src 引用数为 0 + 其自述。**未**做运行期动态验证（如运行时模块加载追踪）。
- **`.env.example` 与凭据清单报告**：**全程未读内容**，只核对文件名与权限位。
- 本报告中所有「机检 PASS / ci_gate EXIT=0 / 棘轮 exit 0」均来自各步骤真实输出；未做任何推测性陈述。
