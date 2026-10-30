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
