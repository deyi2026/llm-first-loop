# D3 立项说明：用独立 worktree 根治"推送要先搬空工作树"

- 立项日期：2026-11-01
- 状态：**论证中（P2）**，本文件只确立问题、目标与实测约束，不含实现
- 关联：`DESIGN-20261101-efficiency-hardening-v1.md` §10 D3、§4.1（E1 消费端）

## 1. 要根治什么

现行推送流程要求**工作树干净**。为满足这个前提，管线把 tracked 改动 stash、把 untracked 产物搬到 `/tmp/lfl-prebackup*`，推完再靠"人记得"恢复。今天一天内搬了 3 次：

| 备份目录 | 时间 | tracked patch | untracked 文件 |
|---|---|---|---|
| `/tmp/lfl-prebackup-20261101-101655` | 10:16 | 有 | 有 |
| `/tmp/lfl-prebackup2-20261101-103119` | 10:31 | 有 | 有 |
| `/tmp/lfl-prebackup3-20261101-104015` | 10:40 | 有 | 有 |

每一次搬迁都产生一份"只有人才知道要不要恢复"的负债；且备份落在 `/tmp`，本身不满足"可恢复"。

**根治思路**：不在工作树上做清场，而是新建一棵临时 worktree，只在那棵树上提交与推送。工作树零接触，负债归零。

## 2. 目标形态（不做半成品）

1. 管线在 `<repo>/../.lfl-push-worktrees/<ts>` 或系统临时目录建 worktree，固定指向待推 commit。
2. 推送期间开发者可继续编辑主工作树，管线不清场、不搬 untracked、不写 `LATEST.json`。
3. 管线退出即回收 worktree（`worktree remove --force`），失败时保留并打印路径（可诊断优先于干净）。
4. 消费端（E1）保留，用于"历史遗留备份"的恢复，不再作为常规路径。

## 3. 实测约束（2026-11-01，`/tmp/lfl-wt-probe`，HEAD=2f538f58b）

| # | 探针 | 实测结果 | 对方案的影响 |
|---|---|---|---|
| W1 | 新建 worktree 后的目录内容 | 只有 tracked 文件；**没有 `.venv`** | 不能假设 worktree 自带解释器；要么共用主区 `.venv`（绝对路径），要么显式拒绝在 worktree 跑测试 |
| W2 | `.git` 形态 | worktree 根的 `.git` 是**文件**（`gitdir: …`），不是目录 | 任何"写 `<repo>/.git/...`"的脚本在 worktree 里会失败或写错位置；E1 的围栏根不能依赖 `.git/` 是目录 |
| W3 | hook 是否生效 | `core.hooksPath=.githooks`（**被跟踪**，worktree 里存在同名目录） | hook 在 worktree 中可用，提交门禁不因换树而失效 |
| W4 | 同 `.venv` 跑 pytest 测的是哪棵树 | `pyproject.toml` 里 `pythonpath=["src"]` 相对 rootdir 解析 → 从 worktree 跑 pytest 测的是 **worktree 的 src** | 这是 worktree 方案的可行性前提，成立 |
| W5 | 裸解释器执行 `import llm_loop` | 解析到 `.releases/ce205a4da…/src`（本机 `PYTHONPATH` 钉在 release 快照） | **新增风险**：同一环境里"pytest 测工作树、裸脚本读旧快照"。任何"用裸脚本验证"的结论都可能是假绿 |

W5 是立项顺带发现的独立隐患：它不是 worktree 特有的，而是**本机环境共性**——环境指纹若只记解释器路径与版本、不记"模块实际来源"，就无法区分"测的是哪棵树"。建议修 E4 时把 `source=<origin>` 纳入指纹（已反馈给 E4 实施）。

## 4. 未验证项（不要当成已解决）

- [ ] worktree 中跑**全量**测试的耗时与磁盘占用（本次只跑了 1 个测试文件）
- [ ] 推送管线自身的其余假设（是否读 `./.venv/bin/python`、是否要求 `.git` 为目录、是否读取主区 untracked 产物）——**管线代码不在本仓库**，本文件无法覆盖
- [ ] 多个 worktree 并存时的锁竞争与 `index.lock`
- [ ] `webui` 构建产物是否需要进入推送（若需要，worktree 无产物 → 必须先构建）

## 5. 验收（实现阶段）

1. 推送一次 dirty 工作树的仓库后：主工作树的未提交改动集合与推送前逐字节一致（含 untracked）。
2. 全程无 `/tmp/lfl-prebackup*` 新增目录。
3. 管线失败时保留 worktree 并输出路径与当前 worktree 清单片段。
4. 并发两个推送不互相破坏（第二次等待或拒绝，二者之一，且可预期）。

## 6. 回滚

worktree 方案是**旁路**：删掉管线里的 worktree 分支即回到"清场 + 搬迁"，主仓库无结构性改动。因此可以先灰度（仅对 dirty 工作树启用），保留旧路径到验收通过。
