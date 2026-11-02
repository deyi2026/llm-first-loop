---
method_id: container-first-registry-claim-verify-then-local-feasibility-gate-3975d1a73046
name: container-first-registry-claim-verify-then-local-feasibility-gate
description: 核查文章/教程对命名工件（repo、skill、包、CLI）的存在、归属、『官方内置』断言时，把每条断言映射为权威 registry 的精确路径查询：先列容器（repo 根 / 官方 skills 目录）一次拿到布局与清单，再下钻具体名字，禁止猜中间子路径；github.com 页面的正文提取只给散文不给目录结构，结构必须来自 API 清单。确定性 404 是存在性答案，换 UA 重试无信息，只能靠列父目录区分『路径猜错』与『断言为假』。上游存在性核完后，『能不能装/用』必须由本地 runtime 事实（依赖是否在 PATH、加载器是否支持其文件结构、与现有技能是否重叠）单独裁决，不能由上游存在性代言。
aliases: 文章推荐的工具是真是假, 核实教程说的官方内置技能, 先列目录再查子路径, 装不装得看本机环境, 链接文章来源核查
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:7e91da8b-4d11-4df5-84fc-7666790cb2fb:0:f1d12925c1bd81df83de
evidence_refs: learning:learn:ab647864196f
created_at: 2026-10-31T19:05:20.915067+08:00
updated_at: 2026-10-31T19:05:20.915067+08:00
---
## Trigger
文章/教程/转述包含对命名工件的存在、归属或『官方内置』断言，需要逐条裁决真伪并给出采用/安装建议；典型入口：用户贴一条链接，正文是工具推荐文，提到多个具名仓库和技能

## Discriminator
断言里 owner/repo/工件名都是精确标识符，registry 目录清单一次调用即可证实/证伪；但仓库内部布局（工件在根还是 skills/ 子目录）事前未知——首未知量是布局，应列容器而非猜子路径。且已见 README 正文提取只含散文（依赖、安装说明），不含文件布局；registry 返回的 404 与 UA 无关。

## Short path
- 一次抓取原文后，把每条出处断言拆成 (工件名, 声称来源, 断言类型=存在/归属/内置) 核查清单
- 对每个声称来源 repo 调一次 contents 根清单：同一次调用解决『布局』与『是否含这些工件名』两个未知量，清单条目自带名字/大小可直接引用为证据
- 对『官方内置』断言列官方仓库对应目录：名字在场即证实；缺席且父目录已列过（排除层级猜错）即定伪，不再换 UA/换端点补救
- 存在性通过后，按候选 README 的硬依赖做 2-3 条本地探针：依赖是否在 PATH、本地加载器是否支持其文件结构（分片/大小上限）、与现有技能是否职能重叠
- 按断言逐条输出 证实/证伪/部分 表格，加上以本地事实为前提的采用建议，停止

## Stop conditions
- 全部断言均有判定，且每条判定可指回一条 registry 清单条目或一次本地探针回执
- 精确路径 404 且父目录清单已确认层级正确 → 该断言终结，禁止同参或换 UA 重试

## Verification
- 存在性证据是 registry 清单条目（名字/大小/sha），不是 README 散文或文章自述
- 每个判伪结论都补过一次父目录/容器清单，排除『只是子路径猜错』
- 可装性建议与本机探针一致：PATH 缺关键运行时的候选被标为『先补依赖再装』而非直接推荐

## Counterexamples
- 文章是观点/经验分享、无可核查的命名出处 → 只做摘要分析，不进 registry 核查流程
- 断言关于版本内容（『某版本起内置』）而非路径存在性 → contents 清单不足，需按 tag/ref 查询
- 目标是评估工件内容质量而非存在性 → 仍要读 SKILL.md/正文，清单只证明存在
- 本机即目标环境且加载契约已验证过 → 省去探针，直接安装并实测回执即可
