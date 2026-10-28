---
method_id: untracked-backlog-disposition-from-gitignore-whitelist-and-tracked-prece-69e465a2a643
name: untracked-backlog-disposition-from-gitignore-whitelist-and-tracked-precedent
description: 重启/接手后要处置一大批未跟踪文件（"N 条未跟踪需要处理"）时，不逐文件判断也不 add -A 一把梭：让仓库自己的声明做分类。(1) .gitignore 的白名单/例外与意图注释说明哪些未跟踪类别是"应入库资产"——未提交≠待分类垃圾；(2) 各类目录下已跟踪文件名分布给出先例：白名单目录内零先例的文件名类（如 pool.jsonl/GATE-RESULT.md）是过程数据，加精确排除而非删除。计数用 ls-files --others -z 精确口径（porcelain 行数会被引号折叠/换行文件名拆行，536 实为 544）；暂存只用实测显式路径；敏感/隐私扫描以 git diff --cached 的 staged 全集为口径——add 之后再扫 untracked 列表必得假阴性。
aliases: 一堆未跟踪文件怎么处理, 未跟踪文件该提交还是忽略, gitignore 白名单资产批量入库, 重启后几百个 untracked 收拾, 过程文件不入库只排除不删除
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3e24aff2-8af5-497f-882a-a249bcc66acd:281:efc2c3d9830cf7417e7b
evidence_refs: learning:learn:b6dfcf594646
created_at: 2026-10-28T09:19:42.221905+08:00
updated_at: 2026-10-28T09:19:42.221905+08:00
---
## Trigger
重启后或跨会话接手时，用户要求处理规模较大的未跟踪文件集合（几十到几百条），且仓库存在既定入库约定（.gitignore 白名单、已跟踪同类资产先例）

## Discriminator
第一次 status/grep .gitignore 时即可获得两个分类信号：该类别是否有显式白名单/例外与意图注释（申报"入库保全"）；该类目录下已跟踪文件名分布——某文件名类有大量已跟踪先例 vs 零先例，直接区分"入库资产"与"过程数据"，无需逐文件试错

## Short path
- 跨会话/重启后先取当前事实：pwd + quotepath 关闭的 status + ls-files --others -z 精确计数；记忆中的数字只是 porcelain 行数口径，与精确计数对账并报告差值
- 按 top-level 目录聚合分类并使计数闭合（各类之和 = -z 精确总数，含中文名须关 quotepath）
- 读 .gitignore 白名单/例外与注释，确定每类申报意图：显式保全资产 vs 运行时排除
- 对每类目录取已跟踪文件名分布核验先例：白名单+有先例→入库候选；白名单目录内零先例文件名→过程数据，gitignore 精确排除（保留文件不删除），存疑处交用户裁决
- 入库前批量校验该类资产结构不变量（frontmatter 完整、id 与目录名一致、敏感/隐私模式），扫描口径为 git diff --cached 的 staged 全集而非 untracked 列表
- 只暂存实测显式路径，按主题分批提交；最终以 status --porcelain=0 与逐提交分类计数核验

## Stop conditions
- 分类计数与 -z 精确总数闭合，无未归类条目
- status --porcelain 为 0 行，且每个提交的文件分类与 message 申报一致
- staged 全集（git diff --cached）敏感/隐私扫描 0 命中

## Verification
- git show --name-only 逐提交统计分类数，与处理明细对账
- 已跟踪同类文件数增量 = 新入库数（如 METHOD.md 1003→1521）
- 被排除的过程文件仍存在于磁盘，仅被精确路径 ignore

## Counterexamples
- 仓库无既定约定（全新/临时仓库，gitignore 无白名单结构）→ 白名单与先例推导无依据，先与用户确认处置策略，不自定
- 零先例文件名其实是新制度的正式资产（有文档/规则宣告的新报告格式）→ 零先例≠不入库，查宣告来源或交用户裁决，不能机械排除
- 仅个位数未跟踪文件 → 直接逐个判断即可，整套分类机制成本大于收益
