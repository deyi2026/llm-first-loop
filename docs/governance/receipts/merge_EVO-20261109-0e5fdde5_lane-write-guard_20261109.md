# MERGE 回执 — EVO-20261109-0e5fdde5（lane 主写机械门：push 判据拆分 + stale lane 回收）

- 日期：2026-11-09
- Lane：`lane-e8e9c97c` / 分支 `feat/lane-stale-reclaim-20261109`
- 审查过的 head：`142e6d08c`（7 files，+1123/−56）
- 合并基线：main `3171f1278`（origin/main `75ed7eb3a` 已在本地 main 内；lane 基线 = main head → 可 ff-only）
- 关联：GOAL-20261109-ba6e6629；EVO-20261109-0e5fdde5（人工批准 executing，见 web 面板 11:44 回执）

## 交付物

| 文件 | 作用 |
|---|---|
| `src/llm_loop/core/lane_main_write_guard.py` | commit / push 判据拆分：commit 只按"当前分支是否 main"；push 按 refspec 目标归一（`HEAD`/`@`/`+`/通配/`--all`/`--mirror`），仅 `verifying`/`merging` 阻塞，`open`/`active` 不再阻塞；stale lane 4h TTL 自动回收；`git -C` 链式目标仓解析；`ls-remote` 快进校验；`--repo` 形式不建模 → fail-closed |
| `src/llm_loop/introspection/lane_gate.py` | S1-08 只统计**本 lane 范围内**的 `need=block`，别人的阻塞项不再误伤本 lane |
| `src/llm_loop/introspection/tools_help.py` | `lane_*` 帮助文案与判据对齐 |
| `docs/ai_rules.md` | RULE-AI-37（lane 并行与写闸）措辞对齐实现 |
| `docs/design/DESIGN-20261105-main-lane-parallel-delivery-v1.md` | 设计稿与实现对齐（判据拆分、stale 回收、S1-08 范围） |
| `tests/unit/test_lane_main_write_guard.py` | 41 测试（含应拦输入） |
| `tests/unit/test_lane_gate.py` | 45 测试（含 S1-08 范围） |

## 独立审查轮次（RULE-AI-28）

| 轮 | 审查者 | 范围 | 结论 | 处置 |
|---|---|---|---|---|
| R1 | `subagent_9b91f6e58100` | 初版 guard | REVISE P1×3（push 快进校验用错 workdir / 浅克隆误拒 / env nan 放大回收） | 全修 |
| R2–R5 | 逐轮窄审 | 增量 | REVISE→修→窄复审 | 修 |
| R6 | 合并闸审查 | 全切片 | PASS P0=0 P1=0 P2=2 | 记录 |
| R7 | 窄审 | `-o`/`HEAD`/通配修复 | PASS，维持 2 P2 | 记录 |
| R8 | **模型自查探针（非审查轮）** | `--repo` 远端位 | 发现 fail-open（`--repo origin main` 把 main 当 remote） | 加测试并修 |
| R9 | `subagent_77c946111bd2` | `86dc0e770` 全树（scope=patch） | **REVISE P0=0 P1=1 P2=4**：P1=`--repo` 值原样喂 `ls-remote`（可注入 git 选项）；P2-1=`origin --repo other` 漏判 | 撤销 `--repo` 建模改 fail-closed；远端名以 `-` 开头不喂 git；补 6 测试 → `142e6d08c` |
| R10 | `subagent_184cee719201` | `142e6d08c`（previous=R9 逐条回应） | **PASS**（candidate `78378c07`） | 放行 |

诚实记录：R8 不是独立审查，是我自己的探针；`--repo` 支持是我 14:03 自行加进去的，40 分钟后被 R9 判为 P1 并撤销。这条弯路保留在账上，不粉饰。

## 全量门禁（RULE-AI-28）

- 命令：`bash scripts/ci_gate.sh`（lane worktree，R10 PASS 之后执行）
- 结果：**exit 0**；ruff ratchet PASS（new=0，改动文件零红）、env-pin PASS、pyright ratchet PASS（new=0）、tier0 341 passed、**全量 14329 passed / 158 skipped / 3 xfailed（263.36s）**
- 首轮门禁（`bc5ece44b`）此前亦 PASS，但被 R9 修复作废；以 `142e6d08c` 这次为准。

## 目标测试

`test_lane_main_write_guard.py` 41 + `test_lane_gate.py` 45 + `test_help_s1_integration.py` 2 = **88 passed**；ruff / pyright 干净。

## RULE-AI-35「应拦输入实测」

| 应拦输入 | 断言 |
|---|---|
| `git commit` 在 main 且有他人 active lane | `main_commit_other_lane` |
| `git push` 目标 main 且有他人 `verifying`/`merging` | `main_push_closing_lane` |
| `git push --all` / `--mirror` / 通配 dst | `main_push_all_other_lane`（open lane 也拦） |
| `git push --repo origin main`（含 `--repo=`） | `main_push_repo_option_unmodeled`（fail-closed） |
| 非快进（远端 main 有本地未含提交） | `main_push_not_fast_forward` |
| 远端名以 `-` 开头 | 不喂 `ls-remote`，按非快进拒 |
| 他人 lane 全 stale（>4h） | 不阻塞 + 回收 |

真机旁证：14:08 我在 main 根目录用 `cd <worktree> && git commit --amend` 被本闸**实际拦截**（`main 直写拒绝`，因执行器 workdir=main 根）；改用 `workdir` 参数后通过。这是"应拦输入被拦"的真机证据，不是单测自证。

## 残留（P2，不阻塞合并；后续 lane）

1. **删除 refspec**：`git push origin :main` 的 src 为空，快进校验可能通过 → 删远端 main 不被拦。建议：delete refspec 落 main 时，只要有他人 live lane 就拒。
2. `_push_is_non_ff` 比对 `refs/heads/<branch>` 而非被推 src → `git push origin feat:main` 可能误拒（方向安全，仅多拦）。
3. `_idle_seconds` 把 naive 时间戳按宿主本地时区解释；若写入方发 naive UTC，4h TTL 会被放大 8h（写入侧格式未核）。
4. `--git-dir`/`--work-tree`/`GIT_DIR` 重定向不跟随（代码内已披露的 accepted residual，与间接 shell 同级）；闸内新增网络 I/O（`ls-remote`，≤10s 超时）。

## 后置 docs-only 提交披露

本回执在门禁通过后以独立 docs-only 提交落盘（不触碰 `src/` 与 `tests/`）。因此门禁覆盖的树与本回执提交后的树差这一次文档提交；**源码与测试与门禁树完全一致**。

## 合并与部署

- 合并：`git merge --ff-only`（基线 = main head，零冲突）
- 部署：`service_control publish(web)` + `restart` → 新护栏在服务进程生效
- **远端推送不在本 lane 范围**：origin/main 停在 `75ed7eb3a`（00:07），本地 main 领先 42 个提交（多会话累积）。远端发布是独立的批次动作，本 lane 不代他人推送；此处显式记录，不假装已推。

