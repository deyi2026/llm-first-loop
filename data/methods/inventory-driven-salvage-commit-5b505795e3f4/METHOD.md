---
method_id: inventory-driven-salvage-commit-5b505795e3f4
name: inventory-driven-salvage-commit
description: 把在途工作保护/收编进提交时，范围必须由 git status --porcelain 的完整清单驱动，而不是由 tracked diff 驱动：M 类（未提交 tracked 修改）会被 reset --hard 抹掉；?? 类（untracked）reset 不碰但 clean 会抹、且不出现在任何 diff、不进任何提交——只按 M 划范围的收编结构性遗漏 ?? 资产。本集初始保护性提交只收了 tracked 修改，漏掉 untracked 的 316 行规格测试文件，直到隔离 worktree 测试报 file-not-found 才事后对账，多花约 5 步（status 清扫、双文件 diff 辨析、拷贝、解释器排障）补收。规则：清点 M+?? 全集→按工作流归属划入同一保护性提交（tag/backup ref 加固）→在隔离环境用显式解释器跑该工作的测试选择器验证完整性。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:855926d8-3b7a-4a6d-9c5e-34631b59df2b:661:23facfce03654720b75e
evidence_refs: learning:learn:03392fb94a30
created_at: 2026-09-19T08:58:54.866355+00:00
updated_at: 2026-09-19T08:58:54.866355+00:00
---
## Trigger
需要对脏工作树做保护性/抢救性提交，或环境中存在周期性运行的破坏性 git 操作（reset --hard / clean / 自动 release 流程），或要把 main 上未提交的在途工作迁入分支/worktree 之前

## Discriminator
任务第一步的 git status 完整输出（76 行）已同时列出 M 与 ?? 两类条目；git reflog 已证明 reset --hard 只杀未提交 tracked 状态、untracked 幸存。两份事实合起来在动手前即可断定：任何只 stage tracked 修改的收编必然漏掉 ?? 资产（本集：?? tests/...reclaim_authority_gate.py 当时已在 status 中可见，仍被排除在收编范围外）

## Short path
- 并行取两个事实：git status --porcelain（M+?? 完整在途资产清单）与 git reflog --date=iso（破坏操作确切语义：杀什么、留什么）
- 由 reflog 的自然实验定保护形态（幸存流=分支+commit；stash 是多流共用应急槽，排除），不先做文档/目录级 broad search
- 建分支后，按工作流归属把 M 修改与相关 ?? 新文件一起 stage 进同一个保护性提交，提交后立即打 tag + backup ref
- 在隔离 worktree 内用绝对路径解释器（主树 .venv/bin/python，不依赖 ambient PATH）跑该工作的测试选择器：无 file-not-found 即收编完整，全绿即停
- 主树回到干净基线后停止；push 等超出本地可逆范围的决定上报用户，不自行扩大动作

## Stop conditions
- 保护性提交同时覆盖该工作流的 M 与 ?? 资产，git show --stat 确认无遗漏
- 全新 checkout/worktree 内该工作的测试选择器全绿且无 file-not-found
- 分支/tag/backup ref 已落盘、主树恢复干净，用户所需决策（是否 push）已上报

## Verification
- git show --stat 对照第一步 porcelain 清单：本工作流相关的 M 与 ?? 条目全部进入提交
- 在全新 checkout/worktree 内运行该工作引用的全部文件/测试：出现 file or directory not found 即清单不完整，回到 stage 步骤补收
- 复核 ref 与主树 status：破坏性操作重演时损失面为零

## Counterexamples
- 工作树没有 untracked 文件，或 ?? 条目全部与该工作流无关：?? 清扫无增量，diff 驱动 staging 已足够，不应为此扩大提交范围
- ?? 条目是多个并行流的大量草稿（本集 docs/evals 下数十条）：禁止 git add -A 兜底；归属判断是模型语义决策，宁缺勿滥
- untracked 文件是密钥/凭证/构建产物（.gitignore 或安全扫描范围）：保护方式是移入隔离目录而非入库
- 破坏源是 git clean 或外部同步而非 reset --hard：?? 才是首要受害者，两类资产的保护优先级与 reset 场景相反
