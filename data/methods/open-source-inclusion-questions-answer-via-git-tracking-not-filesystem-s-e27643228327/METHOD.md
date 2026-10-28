---
method_id: open-source-inclusion-questions-answer-via-git-tracking-not-filesystem-s-e27643228327
name: open-source-inclusion-questions-answer-via-git-tracking-not-filesystem-search
description: 『我们的开源是否包括某类内容』本质是 git 追踪状态问题，不是文件存在问题：工作树枚举会把 ignored 文件混进结果造成假阳性。权威链：remote URL 身份线钉死公开远端 → 读 .gitignore 排除策略（注释只是意图，行为以 git check-ignore -v 实测为准，后置目录规则可覆盖前置 negation）→ git ls-files 按类别前缀计数抽样 → ls-remote SHA 对齐公开 HEAD；若『开源』另指 wheel 链路则查 MANIFEST.in 分开口径。禁止先用 search_files/全目录枚举。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:b473294f-d550-4cf2-aeab-36f8b59c5153:0:2e56ca3d0f4a9163622d
evidence_refs: learning:learn:f9373bf7bd24
created_at: 2026-10-20T15:30:47.770539+08:00
updated_at: 2026-10-20T15:30:47.770539+08:00
---
## Trigger
用户问『开源/公开仓库是否包括某类内容（如开发过程文档）』，当前是多 remote 的 git 检出（含 mirror/legacy remote），且仓库存在把部分同类内容排除在库外的忽略规则。

## Discriminator
『包括在开源里』的判准是 git 追踪状态，其权威在当时已暴露：remote URL 身份线标出公开远端（lfl vs origin-legacy）、.gitignore 载明排除策略、ls-files/ls-remote 给出在库清单与 HEAD 对齐；而文件系统枚举（search_files）会把 ignored 路径（本例回执命中 evals/*/results/ 等实际被忽略的文件）混进结果，对『是否随开源发布』给出假阳性信号。

## Short path
- 未知量=哪个是权威公开远端：从 remote URL 身份线钉死（默认名 origin 不是权威信号），并确认本地分支与该远端同步状态。
- 未知量=哪些同类内容被显式排除：读 .gitignore 规则与注释；对每条疑似排除跑 git check-ignore -v，以实测行为为准——后置目录规则可覆盖前置 negation，注释与行为可能不一致，不一致要作为独立发现报告。
- 未知量=在库的开发过程文档有多少、什么形态：git ls-files 按目录/文件名前缀做范围计数，并抽最近若干 docs 提交样例。
- 未知量=本地结论是否对公开 HEAD 成立：ls-remote 取远端 SHA 与本地比对，一次即止。
- 未知量=『开源』是否另指分发链路：查 MANIFEST.in/打包配置，repo 与 wheel 两套口径分开回答。

## Stop conditions
- 在库数量与排除清单均由 git 权威来源（ls-files / check-ignore -v）证实且远端 SHA 对齐，即停止发现，不再做确认性抓取或二次枚举。
- 用户所指分发链路（repo vs wheel）已确认并分别回答完毕。

## Verification
- 每个『在库』断言以 git ls-files 命中为准；每个『被排除』断言以 git check-ignore -v 命中具体规则行为准。
- 公开性以无凭据 ls-remote 成功或公开页面可达验证一次，不重复多通道确认。
- 发现 .gitignore 注释意图与 check-ignore 实测不一致时，以实测作答并报告不一致本身，不照注释下结论。

## Counterexamples
- 用户问的是磁盘存在性（『代码库里有没有 X』而非『发布里有没有 X』）：文件系统枚举才是对的工具，加 git 追踪过滤反而漏掉 ignored 文件。
- 单 remote、无忽略规则的仓库：ls-files 与磁盘基本重合，本方法的额外步骤无增量收益。
- 用户明确指 wheel/PyPI 产物：repo 的 ls-files 回答错误链路，应以 MANIFEST.in/打包配置为权威。
- 忽略规则与意图完全一致且无 negation 冲突时，check-ignore 交叉验证可省略。
