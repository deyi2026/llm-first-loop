# RULE-AI-28 窄复审回执：Release Restart 效率线 rebase 至 lfl/main（feat/release-restart-eff-main）

- 审查者 id：独立窄复审子代理（父代理委派任务派生；委派上下文未随附具名 subagent id，以本回执所在 run 为身份留痕，UNVERIFIED 见文末）
- 时间：2026-10-27 晚（UTC+8）
- 被审基线：`lfl/main = feb52b5b1c1b102cb9f2a0f9b0a8ed07036897e6`
- 被审 HEAD：`1a7412eba8ce7b59aee21edf1ad357863b48e0a6`（分支 feat/release-restart-eff-main；`git rev-list --left-right --count lfl/main...HEAD` = `0  5`，ahead=5/behind=0 不倒退，已核；工作树 clean）
- 审查范围：`git log --oneline lfl/main..HEAD` 的 5 个 commit + `git diff lfl/main..HEAD`（15 文件 +1668/-72）。旧基线 e535a11ab 上的初审/窄复审结论不重审，仅按委派 E 项做同源性核对。
- 方法论检索：本 run 工具集无 search_records（逐项核对可用工具清单），按纪律"不适用则直接开始"处理。

## verdict: **PASS**（无 P0、无 P1；2×P2 留痕，不阻断合并）

## 产物 SHA 核对（11/11 MATCH，无 P0）

清单 `~/lfl-workspace/work/lfl-eff-20261027/artifact-sha256-main.txt`，逐条 `shasum -a 256` 工作树实测比对：

| MATCH | 文件 |
|---|---|
| d1d5e662…fad | .github/workflows/ci.yml |
| 41ee7f6f…14c | .github/workflows/release.yml |
| beec9f12…93f | .github/workflows/finalize-release.yml |
| 304f9112…86d | scripts/release_finalize.py |
| 6310961b…27b | src/llm_loop/runtime/service_control.py |
| a57c545c…b7e | src/llm_loop/runtime/service_control_derivation.py |
| 363e9f3f…d30 | src/llm_loop/tools/builtin/service_control.py |
| 6ceab2f5…34b | tests/unit/test_lifecycle_update_single_action.py |
| ee4a110d…831 | tests/unit/test_service_control_argument_contract.py |
| e13b5bf1…33b | tests/unit/test_svc_deploy_next_step.py |
| 9d880f3b…478 | tests/guards/function_size_baseline.json |

核对先于一切复跑执行；复跑结束后 `git status --short` 仍为空（被审产物零触碰）。

## 逐 commit 结论

| # | commit | 结论 | 要点 |
|---|---|---|---|
| 1 | 3757e8ef4 ci: push 只在 main 触发，并发按事件隔离 | PASS | 仅 +10 行（branches 过滤 + 顶层 concurrency），其余零改动 |
| 2 | e9cbcf45f fix(service_control): update 缺省 restart_target 收紧为 token 精确推导 | PASS | 6 文件；两处旧本地推导实现删净，收敛到单源 derivation 模块 |
| 3 | 75870c4ec feat(release): draft-first 发布语义 + 平台 manifest + 机械转正 | PASS（P2-1 留痕） | release.yml +29/-2、finalize-release.yml +51、release_finalize.py +917 新增 |
| 4 | 0e646f90c guard(r9): 重登记函数规模基线 measured | PASS（P2-2 留痕） | 仅 3 行 _meta + 1 条数值 528→562 |
| 5 | 1a7412eba docs: 阶段0 只读基线测量 + 审查回执 | PASS | 旧回执基线标注明确（见 F） |

## 重点 A–F 逐项结论

### A. release.yml 移植正确性：PASS（P2-1 关联）

1. **顶层 concurrency 唯一**：safe_load + 显式重复键检测（自定义 constructor 对重复 mapping key 抛错）通过；顶层键 `[name, on, concurrency, env, jobs, permissions]`，无重复键覆盖。main 侧原有块 `group: release-${{ github.event_name == 'workflow_dispatch' && inputs.recovery_tag || github.ref_name }}` / `cancel-in-progress: false` **原样保留**——`git diff lfl/main..HEAD -- release.yml` 中 concurrency/env/RELEASE_TAG 区零改动（grep 证实 +/- 行只出现在新增步骤内）。
2. **manifest 步骤位置**：`生成平台工件 manifest 与 draft 正文状态块`（:133-144）位于 `分发成品校验和`（`cd dist && sha256sum * > SHA256SUMS && sha256sum --check`，:131-132）**之后**；其前序链 uv build → cp 安装脚本 → verify_install_distribution → verify_linux_installer 已全部定型 dist，其后至上传无任何再改 dist 内容的步骤。CLI 参数与 `release_finalize.py` argparse（:843-853）逐一匹配（--from-dir/--tag/--commit-sha/--out/--body-out）。SHA256SUMS 不含 manifest 自身（生成在其后）属预期的自指排除，manifest 即逐资产 sha256 权威记录，finalize 侧以其实测比对（self-check S3/S4 覆盖）。
3. **files 列表含 manifest**：softprops `files:` 末行 `dist/release-artifacts-manifest.json`（:160）；`release-body-status.md` 不作为资产上传（仅用于正文），语义正确。
4. **正文块步骤**：位于 softprops 之后（:161-170），`release_finalize.py body --tag "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" --block-file dist/release-body-status.md` 与 body 子命令 argparse（:861-864）匹配；RELEASE_TAG（:25-26 顶层 env）tag push 时=ref_name=vX、dispatch 时=recovery_tag，两路径一致正确。
5. **recovery（dispatch v0.6.37）路径**：gate/release 两 job 的 `if:`（gate: `!=workflow_dispatch || ref==refs/heads/main`；release: 加 `&& inputs.recovery_tag == 'v0.6.37'`）与 `ref:` checkout（`dispatch && recovery_tag || ref`）、v0.6.37 身份四重校验步骤**全部未被本次 diff 触碰**，仍生效。但见 P2-1：新增 manifest/body 步骤无 `if:` 排除 dispatch，再次 dispatch recovery 会 fail-closed 失败（详见 P2 表）。

### B. finalize-release.yml group 对齐：PASS

- release.yml（tag push v0.6.38）：`push != workflow_dispatch` → `false && recovery_tag || ref_name` → GitHub 表达式短路求值 = `ref_name` = `v0.6.38` → group = **`release-v0.6.38`**（tag push 时 ref_name 即裸 tag 名）。
- release.yml（dispatch recovery_tag=v0.6.37）：`true && v0.6.37 || …` → **`release-v0.6.37`**。
- finalize-release.yml（dispatch tag=v0.6.38）：`release-${{ inputs.tag }}` → **`release-v0.6.38`**。
- 三种形态均为字面前缀 `release-` + 裸 tag 原文，**逐字相等**，互斥在组名层面成立。与旧分支形态（`github.ref` / `format('refs/tags/{0}',…)` 含 refs/ 前缀）不同——本分支已随 main 侧 group 表达式变化正确适配，若沿用旧形态反而会与 main 侧新表达式错位成两个组。
- 全 ref 输入（`refs/tags/vX`）时 finalize 组名错位仍被 `_TAG_RE`（:114，`validate_tag_or_die` :437-440 fullmatch 拒斜杠）在任何 gh 调用前 EXIT_GUARD 零写拦截——旧回执"留痕不修"状态在 rebase 后维持不变。

### C. guard 基线重登记最小且合规：PASS（P2-2 关联）

- `git diff lfl/main..HEAD -- tests/guards/function_size_baseline.json` 恰为 3 处 `_meta`（head_commit `b1f593fd0→e9cbcf45f`、生成时间 `2026-10-26→2026-10-27`）+ **仅 1 条**数值 `src/llm_loop/runtime/service_control.py::main: 528→562`，无其他键变化。
- `scripts/regen_function_size_baseline.py --check` 独立复跑两次：均输出 `OK: function_lines=133 条、legacy=13 条与守卫实测一致（幂等）`，EXIT=0——幂等成立。
- 登记值与实测一致性的旁证：e9cbcf45f 之后（75870c4ec、0e646f90c、1a7412eba）对 src/llm_loop/runtime/service_control.py 零改动（`git log e9cbcf45f..HEAD -- <file>` 为空），562 在 HEAD 仍为实测值。
- P2-2：`_meta.head_commit = e9cbcf45f` 是 guard 提交 0e646f90c 的**祖父**（直接父为 75870c4ec），与 _meta 自述"即本提交的父提交"字面不严格；因 75870c4ec 对 src/ 与 tests/guards/ 零 diff（已实测），e9cbcf45f 与 75870c4ec 源树相同、实测值不受影响，且 --check 只校验数值与 head_commit 形态不重算父提交——功能无损，纯元数据语义留痕。

### D. ci.yml：PASS

- YAML 合法：safe_load + 顶层重复键检测通过；顶层键 `[name, on, concurrency, jobs]`。
- 触发面回显：`on = {push: {branches: [main]}, pull_request: None, schedule: [{cron: '0 20 * * *'}], workflow_dispatch: None}`——PR/nightly/dispatch 全保留。
- concurrency：`group: ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}`，`cancel-in-progress: ${{ github.event_name == 'pull_request' }}`（表达式字符串由平台求值为布尔）。按事件推演：PR（ref=refs/pull/N/merge）同 PR 取消旧跑；push main（ci-CI-push-refs/heads/main）不互相取消；schedule 组名含 event_name=schedule 与 push 组字符串不同，nightly 不被 push 打断。
- **不误伤 tag push 的 release**：tag push 后不再触发 ci.yml（push 限 branches=main），但 release.yml `on: push: tags: ['v*']` 独立触发且未被触碰；tag 的门禁由 release.yml gate job 承担（pytest/ruff/pyright 且 pyright 带 `--require-complete`，严于 ci.yml）——门禁覆盖无缺口。

### E. 零副作用/单源/回执性质未被 rebase 稀释：PASS

- **同源性硬证据**：`diff <(git diff e535a11ab 34f1e5dae -- src/) <(git diff feb52b5b1 HEAD -- src/)` 输出**完全一致**（SRC DIFF IDENTICAL）；`tests/unit/` 同法比对亦 IDENTICAL。即新旧分支对各自基线的 src 与单测改动逐字节同源，rebase 仅在 guard 基线（新基线 528→需重登记）与 group 表达式适配（B 项）上有预期的差异。
- 注意：直接 `git diff 34f1e5dae HEAD -- src/` 会出现 task_budget/spawn_subagent/web/auth/routes 等**差异属预期**——那是 lfl/main 在 e535a11ab..feb52b5b1 间自身演进的 src 变化（本分支不承载），非本分支稀释；本项结论以上述"各对其基线"比对为准。
- 零副作用亲读（HEAD diff 全文）：CLI 面 `main` update 分支——`ManagedServiceDeploymentStore.__init__` 仅算路径（惰性），derive 失败打印 NEEDS_TARGET JSON（ok=false、basename、targets、example、"本次未产生任何 publish/CAS 写入"）到 stderr 后 `return 2`，位于 build_deployment/compare_and_swap 之前；工具面 `_update`——显式 target 优先，derive 失败 `_failure("[service_control update rejected] NEEDS_TARGET: …")` 于校验段返回，先于 `_publish` 内 CAS。
- 单源：`grep -rn "derive_restart_target|_derive_restart" src/ scripts/`——实现仅 service_control_derivation.py:47 一处，import 仅 runtime:54 与 builtin:33，调用仅 runtime:4323 与 builtin:518；旧的两处本地实现（runtime `_derive_restart_target_from_code_root`、builtin `_derive_restart_target`）在 diff 中均为纯删除。
- derived_from 仅推导时标注（CLI accepted/工具 updated 两处均 `if derivation is not None`），显式传参不出现。

### F. docs 旧回执不会误用：PASS

`docs/governance/review-receipts/2026-10-27-release-restart-eff.md`（commit 1a7412eba 引入）明确写有：被审基线 commit `e535a11ab8c6917d6d5ac2721db7251d5240ad2a`（回执 :5、:88）与产物清单 `artifact-sha256.txt`/`artifact-sha256-v2.txt` 的 11 个 SHA 前缀（:16、:95-97，如 ci=a41760e0、release=691371b1、release_finalize=2914310b）。本次新基线 HEAD=1a7412eba、新清单 artifact-sha256-main.txt 的 SHA 全部不同（ci=d1d5e662、release=41ee7f6f、release_finalize=304f9112），回执与产物的对应关系可机械区分，不会被误当本次窄复审的 PASS 凭证。

## P0/P1/P2 表

| 级别 | 位置 | 问题 | 影响/建议 |
|---|---|---|---|
| P0 | — | 无 | — |
| P1 | — | 无 | — |
| P2-1 | .github/workflows/release.yml:133-144,161-170 | 新增 manifest/body 步骤未以 `if:` 排除 workflow_dispatch；若再次 dispatch recovery（recovery_tag=v0.6.37），release job checkout v0.6.37 树后 `scripts/release_finalize.py` 不存在（该文件首次新增于 75870c4ec，v0.6.37 早于它），manifest 步骤必然失败 | **fail-closed**：失败点先于 softprops，无任何 Release 写副作用；且 v0.6.37 one-time recovery 已由 main 侧 PR #10（feb52b5b1）完成，入口使命已履行、正常 tag push / finalize 路径均不受影响。建议后续收尾：给两个新步骤加 `if: ${{ github.event_name != 'workflow_dispatch' }}` 或注释声明 recovery 入口已退役 |
| P2-2 | tests/guards/function_size_baseline.json `_meta.head_commit` | 登记值 e9cbcf45f 为 guard 提交的祖父而非字面"父提交"（父=75870c4ec，其 src 与 e9cbcf45f 零差异） | 实测值与登记值一致（regen --check 幂等通过），功能无损；纯 _meta 语义留痕，建议下次重登记时以直接父提交为准 |

## 独立复跑真实输出（原样摘录，本 run 独立执行）

1. **pyright**（重点：上一轮 P1 位置 builtin/service_control.py:593；后台落盘规避 60s 工具超时，`.smx/pyright-main-recheck.log`）：
   `ratchet HEAD=1a7412eba8ce ledger_sha256=b7ed6806d661 (frozen b7ed6806d661)` / `ratchet analyzer pyright: actual=pyright 1.1.411 frozen=pyright 1.1.411` / `changed[committed]=0 changed[uncommitted]=0 changed[untracked]=0` / `R9 pyright: historical=45, current=11, new=0, resolved=34, changed_file_diagnostics=0, changed_python_files=0` / `R9 pyright: PASS (historical debt visible; no new errors; touched files clean)` / `R9 pyright status=complete`（真实完成，非超时降级）/ `PYRIGHT_EXIT=0`。上一轮 P1（reportIndexIssue 净新增）未复现，current=11 与旧窄复审关闭后水位一致。
2. **ruff**：`R9 ruff: historical=67, current=30, new=0, resolved=37, changed_file_diagnostics=0, changed_python_files=0` / `R9 ruff: PASS (historical debt visible; no new errors; touched files clean)` / `R9 ruff status=complete`，EXIT=0。
3. **pytest 六文件**：`148 passed in 10.98s`（test_arch_guards / test_lifecycle_update_single_action / test_svc_deploy_next_step / test_service_control_argument_contract / test_svc_deploy_cli_update / test_restart_cli_recovery_regression，exit 0）。
4. **release_finalize.py --self-check**：S1 全绿转正 / S2 缺 macos 保持 draft / S3 sha256 不符拒绝 / S4 manifest 缺失拒绝 / S5 幂等重放零写 / S6 latest 检测正负样本 / S7 双状态块收敛 / S8 published 只读 guard，`self-check 汇总: 8/8 场景通过`，EXIT=0。
5. **YAML 三文件**（safe_load + 顶层重复键显式检测）：全部 OK。顶层键 ci=`[True(on), concurrency, jobs, name]`、release=`[True(on), concurrency, env, jobs, name, permissions]`、finalize=`[True(on), concurrency, jobs, name, permissions]`；concurrency 回显 release=`release-${{ github.event_name == 'workflow_dispatch' && inputs.recovery_tag || github.ref_name }}`（cancel=false）、finalize=`release-${{ inputs.tag }}`（cancel=false）、ci=`ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}`；on/push 回显 ci=`{'branches': ['main']}`、release=`{'tags': ['v*']}`、finalize=workflow_dispatch(tag)。

## UNVERIFIED（未验证项）

- GitHub Actions 平台运行时行为：concurrency 组互斥的实际平台效果、GitHub 表达式平台端求值、tag push 实际触发链——本审查仅达语法解析/字符串逐字等价/脚本单测级，未推送、未触网（符合只读纪律）。
- v0.6.37 tag 对象不在本地镜像（`git cat-file -e v0.6.37:…` 报 invalid object name）；"v0.6.37 树无 release_finalize.py"由该文件首次新增于 75870c4ec（`git log --diff-filter=A` 单命中）推得，未对 tag 树直接验证。
- gh CLI 真实网络路径（self-check 的 FakeGh 内存模型覆盖接口语义，未实测 GitHub API）。
- 本审查者 id：父代理委派上下文未随附具名 subagent id，无法独立核验登记库；以此 run + 本回执落盘为身份留痕。
- 旧基线 e535a11ab 上初审的 A–J 全量结论未重审（同源性已按 E 项硬证据覆盖 src 与 tests/unit）。

## 审查纪律声明

- 未修改任何被审产物：SHA 11/11 核对先于复跑；复跑全部结束后 `git status --short` 为空。未 commit、未 push。
- 唯一写入 = 本回执文件；临时产物仅 `.smx/pyright-main-recheck.log`（gitignore 路径，不入 git status）。
- 护栏交互如实记录：heredoc 直传解释器两次被 E6 硬阻断（python heredoc、含 python heredoc 的复合命令），全部改 `python -c` / 常规 shell 等价执行，不影响结论。
- RULE-AI-28 独立性：pyright/ruff/pytest/self-check/YAML/regen --check 全部在本 run 重新执行，未采信执行方自述。
