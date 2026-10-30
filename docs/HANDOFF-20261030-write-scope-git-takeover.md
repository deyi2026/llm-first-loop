# HANDOFF-20261030 · write_scope P0 收口与 git 接管（并发写者线）

> 用途：write_scope 实现会话的 git 操作已由本会话接管并提交。**该会话先读本文件 → 核 §2 活事实 → 再动。**
> 生成：2026-10-30 14:30（+08:00）｜生成者：LFL 主会话（应用户授权接管 git 操作）
> 复用原则：进度以**已持久化状态**为准（git commit / 落盘产物），不重扫历史日志。

## 0. 一句话现状

write_scope P0 实现已在 `main` 落三笔提交（锚点闭合 / P0 实现收口 / 知识资产入库），工作树 tracked 改动 = 0。**原会话无需再 rebase**（其 `4abd81bd7` 是悬空提交，修订内容已在 main）；**push 由本会话走 review_admission 流程，未完成前请勿 `git push`**。

## 1. 已提交的 commit（push 前 origin/main = `fc1c2d0d6`）

| commit | 内容 |
|:---|:---|
| `408c2cb1e` | 锚点就地闭合（治理文档 `card-lifecycle.md` + 1 张方法卡 + annotations 账本）——属另一条线，见 §4 |
| `ab86dde5b` | write_scope P0 实现收口（34 文件：core/tools/workspace/runner + 4 个测试文件 + 设计文档 + phase3-6 验收产物） |
| `ee4564e5f` | Round 4/5 知识资产入库：30 张方法卡 + 8 张经验卡 + `reports/qualification-r4/`（manifest 已拆分，见 §3.2） |

## 2. 接手前必须先核的活事实（易变，勿照抄本文件的数字）

1. **`4abd81bd7` 是悬空提交**：不在 `origin/main`，`git branch -a --contains 4abd81bd7` 为空；其 `card-lifecycle.md` 修订内容已在 main（main 另多 2 行）。⇒ **不需要 rebase**，直接基于 `main` 继续。
2. **push 由本会话在走**：本会话正按 RULE-AI-28 执行 `review_admission`（full_test → git_push）。**在回执给出前请勿 `git push`**，避免双推/非快进冲突。
3. **工作树状态**：tracked 改动 = 0；残留 untracked 14 项 = 13 个 `.tmp-*.py` / `.tmp-r4-*.json` 临时脚本 + `reports/qualification-r4/mech-all-sample.json`（1.28MB）。**本会话未替任何一方删除文件**——这些是原会话的过程物，由其自行处置。
4. **原会话在本文件生成时仍处于活跃写入**（`src/llm_loop/tools/builtin/spawn_subagent.py` 于 14:20 被修改）。若其在本会话 push 之前提交并推送，两边会推同一 `main`；本会话的 push 以 `origin/main` 为 base 重新计算，推送将是非快进而被拒——**遇到这种情况以本会话的交接回执为准，不要重复推**。

## 3. 本会话对这批 WIP 做的四处改动（均为提交前的必要修正，非语义改动）

1. **设计文档第 56 行 F13**：本机工作区绝对路径（形如 `/Users/<user>/...`） → 「当前工作区根」。**原因**：pre-commit 安全扫描的绝对路径闸拦截（仓库卫生规则）。后续若确需写绝对路径，先查 `scripts/git_security_scan.sh` 的 `_ALLOWLIST` 机制。
2. **`reports/qualification-r4/mech-all-sample.md` 按小节边界拆为两份**（`mech-all-sample.md` + `mech-all-sample.part2.md`，各约 339 KB）：**原因**：review_admission 的单次 git 输出上限 400 KB，而该文件整份 676,921 B ⇒ 整份**可提交但推不进**（该闸的运行期输出投影发生在 400 KB 上限之后，属 Host 侧次序漏洞，见 §7）。**拆分按 `### method:<id>` 小节边界、对齐字节中点，两侧各以完整小节收尾；内容零删减已按重建逐字节校验一致**（rebuilt == original，676,921 B）。
3. **`reports/qualification-r4/mech-all-sample.json`（1.28MB）未入库**：超仓库 1MB 文件闸。同目录 `.md`（已拆分）、`mech-findings.json`、`url-samples.json` 已入库；**生成命令与 `ran_at` 记录在 `.md` 头部，可原样重生成**，不丢信息。
4. **新卡入库前做了不变量校验**：全部卡 frontmatter 的 `method_id` == 目录名（0 mismatch）、`status` 齐备（0 缺失）；**未做任何生命周期流转**（全部保持 candidate / lesson）。

## 4. 另一条线的改动（与 write_scope 无关，但会撞同一批文件）

锚点就地闭合（`408c2cb1e`）：卡 `method:subagent-three-layer-diagnose-and-spawn-playbook-87273b2b3118` 的悬空指针（`docs/SUBAGENT-PLAYBOOK-20261025.md`，实测**从未存在**——`git log --all` 为空且无删除记录）改指 `docs/PLAYBOOK-20261014-subagent-capability.md`；治理文档 R3-bis 新增「**锚点失效的三分支处置**」规则（曾被删⇒恢复 / 从未存在⇒重指或事实轴 invalidate / 改名移位⇒内容指纹重指）。**若你要改 `card-lifecycle.md` 或该卡，请基于 `408c2cb1e` 之后的内容。**

## 5. 下一期的入口（设计文档已定，尚未做）

> **2026-10-30 15:4x 就地更正（本轮 P1-b / EVO 落地后）**：下列 P1 条目中的 **P1-b 能力面剔除已落地**——提交 `90fad9ab6`，受限 child 启动时工具面剔除 `execute_command`，异步 `start()` 与同步 `run()` 两条路径同款，测试 T17–T23（设计文档 §15 / §15.7；状态见本文件 §9 表）。**仍未做**的是 C8 的 P0 段：命令串绝对路径字面量 scope 校验 + `scope_unverified` 审计事件。本节保留原始表述作为历史记录，不删改。

- **P1**：能力面剔除（受限 child 直接不给 `execute_command`，设计 §4.2 Q2 / §5.6 P1-b）与命令族判定二选一；**两条 spawn 路径都要改**——异步 `start()` 与同步 `run()` 各自算 scope（设计 §4.3 盲点 4），测试须覆盖 T15 / T16。
- **诚实边界**：P0/P1 运行期**无法完全阻断** `cp` / 裸 shell 通道（不经 `FileService`），只能事后检出并归因（设计 §4.2 Q3 / §9）；`execute_command` 的语义盲区需靠 P1-b 消除。

## 6. 验证状态（以回执为准，本文件不预先宣称结果）

- write_scope 四个测试文件：2026-10-30 14:13 实测 **141 passed / 1 skipped**。
- Ruff 静态诊断：2026-10-30 14:19 实测 **PASS**（new=0、触及文件零诊断；historical=67 / current=29 / resolved=38）。
- 全量回归与 push 走 `review_admission`（full_test → git_push），结论以工具回执为准。
- **跑测环境注意**：`.venv` 的 editable 安装指向 `.releases/8c114428…` 的旧发布快照；`pyproject.toml` 的 pytest 配置自带 `pythonpath = ["src"]`，因此**在仓库根用 `.venv/bin/python -m pytest` 才会打到工作树源码**（`scripts/ci_gate.sh` 亦自带 PYTHONPATH 前置）。在仓库根之外直接 `python -m pytest` 会测旧代码（假绿）。

## 7. 给 Host 的一个待办（本会话已记录，未自行改动代码）

`review_host_admission` 的运行期输出投影（`_project_committed_runtime_diff`）应用在 `_path_diffs` **之后**，而 `_git` 的 400 KB 单次输出上限在 `_path_diffs` **之内**先抛 `git_state_too_large` ⇒ **400 KB–1 MB 之间的 `reports/**` 文件可提交却永远推不进**。修法方向：把投影下沉到 `_git` 之前（按路径先投影再取 diff），或对运行期输出路径改用分段取 diff。属 Host 安全边界，**须走人工审批的演进流程，本会话未自行放宽**。

## 8. 推送已完成（2026-10-30 14:45）

- `main` 已推到 origin：**fc1c2d0d6 → 038a0821e**（5 笔，含并发写者会话的抽减收尾与 §13 返修记录 `038a0821e`）。
- 准入记录：`review_admission` full_test（候选 `60c8ed2f…`）PASS；git_push 首轮（候选 `077801fb…`）**REVISE**（P0=0 / **P1=1** / P2=3，P1 = 文档快照相对已提交测试过期：§12.4 仍写 109 passed、§13 未入库）→ 修复（§12.4 改实测 141 passed/1 skipped + §13 入库 + 新增 §13.7 记录本轮处置）→ git_push 第二轮（候选 `349640fc…`）**PASS** → 推送成功。
- **§2.2 的「勿 push」约束已解除**：并发写者会话的工作已在 main（`038a0821e`），其后续提交是 `038a0821e` 的后代，快进推送即可；只有当它的提交与 `038a0821e` 并列时才需先 `git pull --rebase`。

## 9. 后续状态（2026-10-30 15:40 起，接管会话补记）

本文件 §1/§2/§6 的部分数字已被后续提交取代；以下为补记，**不改写上文任何历史陈述**。

| 项 | 后续事实 | 依据 |
|---|---|---|
| 远端锚点 | `origin/main` 已推进到 `566e5b09f`（本文件 §8 记录的 `038a0821e` 之后）；其后接管会话新增 `bfeacf003`（修回既有守卫）与最终交付提交 | `git log --oneline -3`、`git rev-list --count origin/main..HEAD` |
| §6「全量回归以 review_admission 回执为准」 | **已兑现**：`review_admission` kind=full_test（候选 `7ba48414…`，child `subagent_b728459b392d`）结论 **PASS（P0=0 / P1=0 / P2=3）** | 工具回执 |
| 新发现 | 接管会话在 `566e5b09f` 上独立复跑全量回归，发现**一个既有守卫回归**：`tests/unit/test_inspect_code.py::test_factory_registered`（根因 `ab86dde5b` 抽 `_register_basic_tools` helper）。已修（字面量断言 → 行为级断言 + AST 接线判定），详见设计文档 §13.8 / §14 | 设计文档 §13.8 |
| §5 的 P1 入口 | **P1-b 已落地**（2026-10-30 15:4x，提交 `90fad9ab6`）：受限 child 启动时工具面剔除 `execute_command`，异步 `start()` 与同步 `run()` 两条路径同款，测试 T17–T23（设计文档 §15）；**C8 的 P0 段（命令串绝对路径字面量校验 + `scope_unverified` 审计）仍未做**——不得声称「写侧路径授权已全量生效」 **（2026-10-30 16:3x 更新：P1-b 口径已回退为 P1-a，C8 的 P0 段已随之落地——现行口径见本文件 §10 与设计 §16）** | 设计文档 §9 / §12.5 / §15 / §16 |
| 未跟踪 scratch | 仓库根仍有 `.tmp-*` 过程脚本与 `reports/qualification-r4/mech-all-sample.json`（1.28MB）**未入库**；含本机绝对路径，接管会话**未删除他人过程物**，也未提交 | `git status --porcelain` |

## 10. 本会话：P1-a 命令族闸落地（2026-10-30 16:3x，P1-b 口径回退）

> **给接管会话的第一句话**：写侧约束的现行口径已从 **P1-b（剔除 `execute_command`）** 改为
> **P1-a（保留命令能力 + 命令族闸）**。你若按 §9 表最后一行（"P1-b 已落地"）继续做，会做出
> **与现行代码相反**的动作。**以本节与设计文档 §16 为准。**

### 10.1 口径变更（产品决定）

| 项 | P1-b（§15，作废） | P1-a（§16，现行） |
|---|---|---|
| 受限 child 的命令能力 | **无**（工具面剔除 `execute_command`） | **保留**（能 `ls`/`git log`/跑测试） |
| 写侧约束落点 | 工具面不可用 | **命令族判定**：写盘命令的写目标必须静态可定位且落在 scope 内 |
| 强度 | 强（无歧义） | 中（命令语义层；残余见 §16.6） |
| 判定代码 | 无（靠工具面） | `src/llm_loop/core/command_scope_guard.py`（新增） |
| 强制点 | runner 工具面 | `execute_command` 工具层（越界 → `error_type="write_scope_violation"`，命令不执行） |

**连带结论**：C8 的 P0 段（命令串绝对路径字面量 scope 校验 + `scope_unverified` 审计）不再是
"下一轮可选项"，而是 **P1-a 的前置配套**——P1-a 的判定层用的就是那三件事，本轮已一并落地。

### 10.2 改动清单（本会话）

| 文件 | 改动 |
|---|---|
| `src/llm_loop/core/command_scope_guard.py` | **新增**：判定层（shell 词法切分 → 写盘命令族识别 → 写目标 scope 校验；fail-closed 原因码）。**首版经独立审查 REVISE 后重写**：不可静态判定的 shell 构造一律 fail-closed 拒绝（见 §10.5） |
| `src/llm_loop/core/write_scope.py` | 新增 `write_scope_audit_record_unverified()` + 快照字段 `scope_unverified` / `scope_unverified_count` |
| `src/llm_loop/tools/builtin/execute_command.py` | 新增 `_write_scope_command_gate()` + 接线（`execute()` 内、任何执行之前）；受限写域下拒绝 worktree 隔离 |
| `src/llm_loop/tools/builtin/verify_path_scope.py` | 观测面新增「未验证路径(scope_unverified)」段 |
| `src/llm_loop/subagent/runner.py` | 判定函数更名 `_apply_write_scope_tool_surface_policy`，**不再剔除任何工具**；回执新增 `write_scope_command_guard="p1a_write_family"`（**仅受限 child 才有**——未受限 child 不再声称闸生效） |
| `tests/test_command_scope_guard.py` | **新增** 74 例（判定层 40 组参数化「应拦输入」+ 12 组放行 + 强制层 + 审计层 + 残余显式化 + 门禁自证伪） |
| `tests/test_write_scope_spawn.py` | `TestP1bToolSurface` → `TestP1aToolSurface`；T17–T23 断言由「剔除」改为「不收窄」 |
| `docs/DESIGN-20261030-…md` | 新增 §16；§14.6 第 1/2 条与 §15 标题加**口径已作废**就地标注 |

### 10.3 残余逃逸口（P1-a 相对 P1-b 放宽，**未闭环**）

1. **解释器任意代码**（`python -c '…'` 可写任意路径）——判定层不判解释器为写盘族；测试
   `test_interpreter_payload_is_documented_residual` 把它显式钉住。
2. **读侧越界只审计不阻断**（scope 是写侧授权；读侧封禁会阻断解释器与测试）。
3. `cp -r` 的**读**越界、`ln -s` 造符号链接后的写入链路，可绕开字面量判定。
4. `git` 写子命令一律按隐式写目标拒绝——语义偏保守。
5. **shell 脚本文件执行被拒**（`sh s.sh` / `bash s.sh` ⇒ `implicit_write_target`）——fail-closed 的
   代价：受限 child 不能跑仓库脚本（如 `scripts/ci_gate.sh`），只能跑只读命令与 in-scope 写命令。
6. **写族名单是封闭清单**：名单外的命令（如 `sponge`）默认按只读放行，只审计读侧字面量。
7. `cd` 位移后的相对写目标一律拒（cwd 位移不可静态定位）。

### 10.4 与并发写者会话的关系

本轮工作树里仍有另一活跃会话（`cbda67c5-…`）的在途 WIP（`review_host_admission.py` 与其测试、
`docs/EVO-20261030-109d7068-…md`）。本会话**只提交自己那 8 个文件**，不纳入、不删除他人过程物。

### 10.5 独立审查 REVISE 轮（2026-10-30 16:4x）：首版闸被 shell 语法整体绕过 → 已重写

首版 P1-a 闸（提交 `28aea305d`）经 RULE-AI-28 独立审查（child `subagent_5c30c04b42ba`）
判 **REVISE：P0=1 / P1=3 / P2=3**（候选 SHA256 `545c6858…`）。P0 是**闸可被普通 shell 语法
整体绕过**：`FOO=1 rm /x`、`if…then rm…`、`(rm …)`、`{ rm …; }`、`echo $(rm …)`、
`eval rm …`、`&>`/`>&`/`>|` 重定向等 16 类全部放行。本会话逐条自行复现（16/16），确认非误报。

**修法（口径翻转）**：判定从「识别写命令」翻成「**不可静态判定就拒**」——命令替换/分组/
控制流/heredoc 一律 fail-closed；载体链（`env`/`sudo`/`eval`/`sh -c`）完整解析；
`git` 子命令判定穿过全局选项；`cp -t DIR` 取目标目录；`find -delete`/`-fprint`/`-exec`
按写目标校验；重定向形式补齐（`>&` 仅在目标是路径时算写）。详见设计文档 §16.8。

**连带修复**：P2-2 回执不再超额声明（未受限 child 不带 `write_scope_command_guard`）；
P2-3 审计卫生（`scope_unverified` 条目自带原因字段；被拒命令不落审计）。

**证据**：40 组参数化「应拦输入」用例（逐条钉住审查指出的绕过类）；门禁自证伪——
把闸打成空实现后 40/40 应拦用例仍放行 ⇒ 用例确实在测拦截而非空转。
