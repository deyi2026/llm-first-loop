---
method_id: named-registry-member-resolve-by-convention-before-search-b08de413a1c1
name: named-registry-member-resolve-by-convention-before-search
description: 请求逐字点名一个注册表成员（如某 skill）需要定位文件落点时，若上下文回执中已出现同类成员的同构路径实例（如 skills/<名>/SKILL.md），直接按约定构造路径或一次列举注册表根目录即可命中，不要先走名称/内容搜索：搜索层的 glob miss 不是存在性证据。本集：成员名已在请求中逐字给出、收件箱消息已展示同构路径实例，却先发 search_files 得『无匹配』，随后一次 ls 注册表根目录立即命中目标目录。
aliases: 点名改 skill 别搜索直接拼路径, 搜不到 skill 不代表文件不存在, skills 目录一次 ls 定位落点, 用户说的 skill 在哪个文件, 搜索无匹配不等于没有这个东西
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:1848:d125f5502a8a60f91308
evidence_refs: learning:learn:8be719207d30
created_at: 2026-11-06T15:57:29.296165+08:00
updated_at: 2026-11-06T15:57:29.296165+08:00
---
## Trigger
请求逐字点名某注册表成员（skill/规则卡/脚本等）且需定位其文件以读取或编辑；上下文中已可见同类成员的路径实例或命名约定

## Discriminator
两个当时已知事实的合并：①目标成员名已逐字出现在请求里；②更早的回执（如收件箱消息、git 记录、其它工具输出）中已出现同构路径实例（skills/<他名>/SKILL.md）。二者叠加即可直接构造目标路径——而搜索层『无匹配』只说明搜索面没覆盖，不构成成员不存在的证据

## Short path
- 从请求提取精确成员名
- 套用上下文已见的同构路径约定构造目标路径；对约定不确定时对注册表根目录做一次列举（如 ls skills/）确认存在
- 直接读取命中文件，进入编辑/分析
- 仅当构造与根目录列举都未命中（口语名/别名/无约定实例）才降级到名称或内容搜索

## Stop conditions
- 目标文件已按约定路径成功读取，且其名称/frontmatter 与请求所指成员一致
- 根目录列举也未命中，证实成员名与目录命名不一致——转入搜索/发现层，不再重复约定构造

## Verification
- 读到文件的标题/frontmatter 与请求点名的成员一致
- 存在性判断以注册表根目录列举为准，不以搜索层『无匹配』回执为准

## Counterexamples
- 用户用口语/意译名指代且与目录命名不一致——约定构造必然落空，应直接搜索或先问清规范名
- 任务要找某主题下全部相关成员而非单个具名成员——需枚举/词根检索，构造单路径不够
- 同一实体在多面有副本（skill 文档/docs/代码）且权威面未定——定位到一处不等于可以改，须先确认权威面
- 上下文中没有任何约定实例可见——第一未知量是命名方案本身，应先读声明该方案的文档再构造路径
