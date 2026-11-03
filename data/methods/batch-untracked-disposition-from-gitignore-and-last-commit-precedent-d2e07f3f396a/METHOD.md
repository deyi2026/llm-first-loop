---
method_id: batch-untracked-disposition-from-gitignore-and-last-commit-precedent-d2e07f3f396a
name: batch-untracked-disposition-from-gitignore-and-last-commit-precedent
description: 把一批未跟踪资产按仓库既有惯例入库时，入库边界不靠文档关键词考古或反复重列 status 得出：一次 porcelain -uall 实测全量候选后，处置规则直接读两个机械且现行的权威面——.gitignore 白名单/例外注释（哪类保全、哪类运行时产物排除）与最近一笔同类提交的信息+stat（惯例的现成模板）。每个候选按规则三分类（保全入库/策略排除/无先例需显式处置），只对将入库集跑脱敏与安检闸。用户'同属入库惯例、与上项一起处理'的断言本身就是先例指向，上项往往就在同一份未跟踪清单里。
aliases: untracked 一堆文件怎么决定哪些进 git, 批量提交经验卡遵循什么白名单, 入库范围按 gitignore 查还是翻文档, 照搬上一笔入库提交当模板, 待提交数量和用户报的对不上, check in learning assets convention
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:013a2f99-8a33-45df-9ce6-06fff25db7d8:0:af7141182b05a6651f6b
evidence_refs: learning:learn:e9f69a01a6f0
created_at: 2026-11-03T07:27:42.266963+08:00
updated_at: 2026-11-03T07:27:42.266963+08:00
---
## Trigger
用户要求把 N 个未跟踪文件（经验卡/方法卡/分析文档等知识资产）按仓库既有入库惯例提交，常附带上一轮记忆中的数量与'与上项一起处理'的指示

## Discriminator
三个当时已在手的机械事实已把问题缩成'逐类分类'：(1) 用户断言这些资产同属入库惯例且与上项同批；(2) .gitignore 例外注释逐类写明保全/排除边界；(3) 最近一笔同类提交的信息与文件清单就是现行惯例模板。对文档做'未跟踪/入库'关键词 grep 只会返回历史讨论，不改变现行边界

## Short path
- 一条 quotepath 安全的 git status --porcelain -uall（含超大文件检出）实测全量候选，与用户报数对账并显式报差值；此后不再重列 status
- 读 .gitignore 策略注释/例外 + 最近一笔同类提交（log -1 --stat），导出逐类处置规则：保全类、策略排除类、无先例类
- 按规则三分类每个候选；无先例/超限项做显式处置（精确 .gitignore 登记或单独裁决），不静默跳过也不整包 add
- 只对将入库集执行仓库强制的脱敏与安全扫描闸，命中按仓内既有掩码形态改写
- 用实测路径显式暂存，git diff --cached --stat 核对暂存集==分类集；沿用惯例句式提交并用 ls-files/log 验证跟踪而非再看 status
- 推送过闸：整批审查材料超时/超字符预算且 git_push 不收 paths 收窄时，按 commit refspec 分段、逐段独立过审后推

## Stop conditions
- 全量清单只测一次，处置规则来自现行 .gitignore + 最近同类提交先例，暂存集与分类清单精确相等，脱敏/安检闸 exit 0，远端 ref 核对一致
- 所有无先例项均已显式处置（入库或精确 ignore 登记），无既未提交也未登记的悬空项

## Verification
- git diff --cached --stat 与实测分类清单逐项对账，无夹带无遗漏
- 排除项有 check-ignore -v 回执；入库项以 ls-files/git log 为准，不回看 status
- 推送范围被隐私扫描覆盖且 exit 0；推后 ls-remote SHA 与本地一致

## Counterexamples
- 仓库 .gitignore 无策略注释、近期也无惯例命名的同类提交——策略面缺失，此时读治理/设计文档或询问才是必要路径
- 最近同类提交早于一次策略改版、与现行 .gitignore 互相矛盾——以现行 .gitignore/check-ignore 实测为准，不盲从旧提交先例
- 候选含 tracked 修改的抢救性收编（reset 会抹掉的 M 类）——那是 inventory-driven-salvage-commit 的机制，不是本卡
- 用户明确点名排除某些匹配保全类的文件——用户指令优先于惯例先例
