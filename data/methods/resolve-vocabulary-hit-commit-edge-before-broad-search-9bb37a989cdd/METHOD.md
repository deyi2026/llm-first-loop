---
method_id: resolve-vocabulary-hit-commit-edge-before-broad-search-9bb37a989cdd
name: resolve-vocabulary-hit-commit-edge-before-broad-search
description: 新任务首个定向动作（git log / manifest / 目录列表 / CHANGELOG）的输出中，若已出现与任务核心词汇逐字重合的具名条目（本集：任务词 'durability observe surfaces' 与 commit 主题 'register durability write surfaces' 重合），该条目就是指向权威工件（注册表/guard/设计文档）的 provenance 边：先对它做 git show --stat（或直接打开其指向工件）解析落点，再做任何文件名/内容宽枚举。本集实际在 git log 之后又做了 2 次 search_files 和 1 次 ls（命中 20+30 条、大量 evals 无关噪声）才走到同一条 git show，多花 3 个发现动作。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:506:e9d9bb14ffa5fe6411e0
evidence_refs: learning:learn:36f244fff646
created_at: 2026-10-08T08:13:33.381792+08:00
updated_at: 2026-10-08T08:13:33.381792+08:00
---
## Trigger
在代码库内做定位/审计类任务，完成首个定向动作后，其输出中存在与任务关键词重合的具名 commit 或条目，且当前未知量是『权威工件（注册表/契约/配置）在哪里、内容是什么』。

## Discriminator
git log 输出中已可见 '0f0ef7892 register durability write surfaces' 与任务词 'durability surfaces' 逐字重合；主题含 'register ... surfaces' 的提交按定义就是注册面落点，其 --stat 直接点名注册表 json、guard 测试与设计文档。该事实在宽搜索发生之前即存在（knowledge-at-time 满足），足以把候选空间从『全仓库文件』缩到『一个 commit 的 4 个改动文件』。

## Short path
- 定向 git log：发现任务关键词与 commit 主题逐字重合，锁定 0f0ef7892 为 provenance 边
- git show 0f0ef7892 --stat：一步解析出注册表 tests/guards/function_size_baseline.json、guard 测试 tests/unit/test_arch_guards.py、设计文档 DESIGN-20261007-durable-run-contract.md
- 读注册表 durability_registry：得到全部 surface 的 tier/status 清单，observe 面即审计对象
- 读 _doc 与设计文档：确认 observe=『已分类未核验』语义与 tier 契约，形成审计标准
- 按注册表 paths 逐面核对源码写入语义；每个下一跳都是注册表点名的路径，不需要再枚举
- 任务2：既有 grep 已把 restart cli/action_worker 定位到 service_control.py:3480/3646，直接读该区间上下文

## Stop conditions
- 已从注册表+设计文档取得用户所需事实（surface 清单与 observe 语义），转入逐面审计本身，停止任何进一步发现动作
- 沿 commit 边解析后 diff 与目标工件无关 → 判定该边断裂，回退宽搜索，不再沿同名主题继续

## Verification
- 注册表与 guard 互证：test_arch_guards.py 的 _load_baseline 指向同一 function_size_baseline.json
- 设计文档 surface 表与注册表条目一致（如 schedule_store=T2、conform 状态两处吻合）
- 路径对比：实际路径为 2 次 search_files + 1 次 ls（20+30 命中，多为 evals 噪声）后才到达同一条 git show；反事实路径省 3 个发现动作与 ~130 行噪声输出

## Counterexamples
- 定向输出中条目名均为泛化措辞（'fix bug'/'update code'），与任务词无重合 → 无边可沿，应正常做宽搜索
- 主题重合的提交很旧且工件已迁移/删除（如 baseline 自 4bd0b9356 漂移后路径失效）→ 需 git log --follow 或回退搜索，不能盲信旧 commit 点名的路径
- 任务要核验的是运行时写入行为是否符合 tier 契约，而非『登记在哪』→ commit 边只完成定位，不替代逐面读源码与行为核验
