# PLAYBOOK: worktree 生命周期治理 v1（EVO-20260920-47e815f1）

来源：两轮审计（20260919-20）发现 121→28 个 worktree 中 55+31 个为"零价值残留"
（dirty=0 且补丁已等价落地/HEAD 已含于 main），大量产生于 `.tmp-ci/`、`/private/tmp/`
临时路径（r9probe×7、tmp-ci 复验×4、/tmp 部署副本×3），且存在"等时副本"模式
（分支哈希未合并但补丁已在 main）——临时 worktree 无退出回收机制。

工具：`scripts/worktree_lifecycle.py`（零 LLM/零网络；测试
`tests/scripts/test_worktree_lifecycle.py`）。

## 分类口径

| 类 | 判定 | 处置 |
|---|---|---|
| A | HEAD ∈ main（`merge-base --is-ancestor`） | 可删（连同分支） |
| B | `git cherry main <head>` 全 `-`（补丁全等价） | 可删（连同分支） |
| C | 有 `+` 提交（真未合并内容） | 保留/转 rescue |

## T1（低成本）：closeout 固化步骤

任务收尾清单新增机械步骤（每轮收尾必跑）：

```bash
python3 scripts/worktree_lifecycle.py audit                # 只看
python3 scripts/worktree_lifecycle.py audit --delete-ab    # A/B 连分支回收
```

- 仅回收 `dirty=0` 的 A/B；dirty>0 输出 `SKIP_DIRTY` 交人工决策。
- 已验证可单轮大规模回收（20260920 实测：55 删 + 31 清 + 12 注销）。

## T2（中成本）：临时路径 worktree TTL 登记

凡创建于 `.tmp-ci/`、`/private/tmp/`、`/tmp/` 等临时路径的 worktree，创建后立即：

```bash
python3 scripts/worktree_lifecycle.py register <path> [--ttl-hours 72] [--note ...]
```

sidecar：`data/state/worktree_ttl.jsonl`。超期 triage（closeout 或定期维护时）：

```bash
python3 scripts/worktree_lifecycle.py triage              # 列出超期
python3 scripts/worktree_lifecycle.py triage --prune      # 清理已注销条目
python3 scripts/worktree_lifecycle.py triage --expire-delete
```

`--expire-delete` 语义：**内容先保底**——C/detach 建 `rescue/<name>-<ts>` 分支
（或沿用既有分支），再注销 worktree；dirty>0 只报 `REQUIRES_MANUAL` 不强删。

## T3（结构性）：PR 合并后等价落地提示

`gh pr merge` 之后（closeout 步骤 2 附近）：

```bash
python3 scripts/worktree_lifecycle.py merge-hint          # 列出可删源分支
python3 scripts/worktree_lifecycle.py merge-hint --delete # 执行删除
```

对 patch-id 已全在 main 的本地分支（等时副本源头）输出 `deletable` 并可删除；
在岗分支（被任一 worktree 检出）自动排除。

## 安全边界

- 永不触碰主仓 worktree、`main` 分支、任何在岗分支。
- 删除前置条件：分类 ∈ {A,B} ∧ dirty=0 ∧ remove 成功；失败即跳过并如实输出。
- rescue 分支命名带时间戳防冲突；一切动作可从 stderr/stdout 回执复盘。
