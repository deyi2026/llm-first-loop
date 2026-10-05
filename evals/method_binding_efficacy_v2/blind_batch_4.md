# Blind batch 4/4

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. ab0813242878

TASK

任务形态为『把组件 X 接线到生产装配点（factory/entrypoint），settings 显式开启、缺省与现状零差异』，且任务本身已知是窄接线而非新组件设计；典型信号是开始猜测组件文件路径、反复重读同一装配区域、或对很短的权威文档做多轮关键词搜索。

METHOD CARD

name: anchor-narrow-wiring-at-construction-site
method_id: anchor-narrow-wiring-at-construction-site-7f3ff30de391
description: 当任务是『把已存在注入点的组件经 opt-in settings 接进生产装配点、缺省零差异』时，把全部取证锚定在装配点那一次构造调用上：调用的实参清单就是完整接线面，装配文件的 import 行就是组件真实模块路径（不猜目录）；settings 命名先查权威短文档（短文档一次整读，不做关键词 grep 往返），无权威再取同一装配文件里最近的 opt-in 惯例；先写含缺省零回归守卫的 RED 再改码；测试绿后如实标注构造级测试覆盖不到的运行时行为边界。

## Trigger
任务形态为『把组件 X 接线到生产装配点（factory/entrypoint），settings 显式开启、缺省与现状零差异』，且任务本身已知是窄接线而非新组件设计；典型信号是开始猜测组件文件路径、反复重读同一装配区域、或对很短的权威文档做多轮关键词搜索。

## Discriminator
动手前已可见的三个事实把搜索空间缩到极窄：(1) 装配点对组件的构造调用已完整列出全部实参（本例 factory 构造 SubAgentRunner 的逐 kwarg 清单）——这就是全部接线面；(2) 装配文件必然 import 该组件——import 行唯一确定模块路径，无需猜 src/xx/runtime/ 之类目录；(3) 组件 __init__ 中注入参数默认 None=关（slice 已预落地注入点），说明剩余工作只是 settings 字段+条件构造+传参。第一处扩散正是抛开了 (2) 去枚举猜测的文件布局。

## Short path
- 定位装配点对组件的唯一构造调用并整段读一次：实参清单=接线面，同文件的 import 行=组件真实模块路径；不再猜测目录布局
- 读组件 __init__ 签名一次：确认注入点已存在且缺省 None=关；若不存在则本方法终止，转入设计/切片任务
- 权威设计文档若很短则一次整读：确认是否规定 settings 命名/行为；未规定才采用同装配文件最近的 opt-in 惯例（env 前缀+空值=关闭），并引用该惯例代码位置作为命名依据
- 读被注入组件的构造签名一次（如 coordinator 的必填字段），逐字段推导应由 settings 提供什么、缺省值是什么
- 先写 RED：opt-in 路径构造出被注入组件且 spawn 产生预期副作用；缺省路径写显式零回归守卫（无该组件、无其落盘产物、既有工具回执行为不变）
- GREEN→相邻测试套件→全量；最终回答如实标注构造级单测覆盖不到的运行时行为（如 live spawn/跨进程），停止

## Stop conditions
- 构造级 RED→GREEN、相邻套件与全量测试 exit=0，且缺省零回归守卫通过
- 组件注入点不存在（需先做设计变更落地注入参数），本方法不适用即停
- 权威文档/schema 已固定命名或接线约定——遵循权威并停止惯例推导

## Verification
- 缺省配置下：装配产物中无被注入组件、无其落盘状态文件、既有工具回执与接线前逐字一致
- opt-in 配置下：被注入组件以 settings 推导的实参构造并传入目标组件
- RED 先失败、实现后 GREEN；相邻测试与全量套件通过
- 最终答复中显式标注单元/构造级验证未覆盖的行为边界，不以构造级测试宣称端到端验证

## Counterexamples
- 组件尚无注入参数（前序 slice 未落地注入点）：这是设计任务而非窄接线，锚定构造调用会漏掉真正的工作量，应先做接口设计
- 权威 spec 已明确规定 settings 命名或 wire schema：必须遵从权威，套用仓库惯例会制造第二套命名
- 接线正确性只能在 live/跨进程运行中观察（真实子会话完成、跨代 CAS reclaim）：构造级单测不能作为行为验证，需另行 live qualification，本方法的 stop 条件不满足

## 2. 31d2eda57d15

TASK

目标文档（结论稿/报告）中出现对某证据工件的裸文件名或无路径引用，且任务需要定位该工件取证、立案或把引用修正为精确路径

METHOD CARD

name: bare-citation-anchor-not-path-guess
method_id: bare-citation-anchor-not-path-guess-c0caae461a97
description: 当文档以裸文件名引用证据工件（如 ATTRIBUTION.md）时，不要按『引用出现在哪份文档就猜它在同目录』定位。先用本episode已取回的目录列表核对缺席（列表完整时缺席即证伪根路径假设），再沿引用的上下文锚（所属行/节/ID）与既有层级约定（rows/<行ID>/）构造行级路径直读，或做一次限定范围的文件名搜索。工具回执已登记『路径不存在(TTL内)』的路径禁止重试。本例可省掉一次必败的根路径读取，并让后续引用修正一次写对精确路径。

## Trigger
目标文档（结论稿/报告）中出现对某证据工件的裸文件名或无路径引用，且任务需要定位该工件取证、立案或把引用修正为精确路径

## Discriminator
猜测路径之前已可见的事实：①早前 ls 已完整列出 run 根目录全部条目（total 328 全量可见），其中不含 ATTRIBUTION.md——根路径假设当时已被证伪；②草稿第7行已暴露 rows/ 层级约定与行命名（t3::b0::k1），且归因引用挂在 t3 行上下文——真实位置可由锚+约定一步推出

## Short path
- 读目标文档，记下裸引用及其上下文锚（该引用挂在哪一行/节/ID）；未知量：需要定位哪个工件、为什么要它
- 用已取回的目录列表核对工件是否在当前位置；本次列表为全量输出→缺席即证伪『同目录』假设，不再尝试该路径
- 按上下文锚+层级约定构造行级路径（rows/<行ID>/ATTRIBUTION.md）直读，或一次 search_files 按文件名定位；未知量：工件真实路径与证据细节
- 读命中工件取证（错误码1261、独立重放细节），据此提交外部修复项立案；未知量：追踪号
- 快照+原子编辑把精确路径与追踪号写回文档，推广定稿本并标注被取代的旧稿；写后复读校验一致性后停止

## Stop conditions
- 裸引用已解析为经验证的真实路径，且工件内容与引用上下文相符
- 工具回执登记某路径不存在（TTL内）→停止对该路径族的任何重试，立即切换为锚定推断或文件名搜索
- 立案拿到追踪号且文档三处引用（标题/正文/收尾）均已写入，复读一致

## Verification
- 最终写入文档的引用路径与搜索/直读命中的路径逐字一致（本例 rows/t3_compact_multi_b0_k1/ATTRIBUTION.md）
- 编辑走文件契约：前置快照 ref 匹配、原子写入、写后复读 sha256 一致
- 立案证据锚指向已实际读取过的工件路径，而非任何猜测路径

## Counterexamples
- 目录列表是被截断的输出（如 head -N、limit 截断）：缺席不能证伪文件不存在，此时一次直读尝试可能反而是最短路径
- 工件位置由固定契约约定（如 harness 规定根级 MANIFEST.json/固定配置路径）：应直接读约定位置，无需锚定推断或搜索
- 引用本身已含完整路径或明确相对路径：直接使用即可，无需上下文锚定

## 3. c62d5b85f676

TASK

多分支/多 worktree 共享同一数据目录的环境中，需要判断某机制是否影响运行时指标，且已拿到带独特符号与元数据（pid/时间戳/工具名）的证据工件和被审计部署代码根

METHOD CARD

name: artifact-symbol-lineage-before-mechanism-reading
method_id: artifact-symbol-lineage-before-mechanism-reading-e22289ec79cf
description: 当审计'某机制是否影响运行时指标'且证据来自共享数据目录的工件（ledger/审计行/事件日志）时，先提取工件自带的独特符号（kind/事件名/写入函数名）并与被审计部署代码根做血缘匹配：符号零命中即证明写入者另有其人，应立即用 VCS 溯源（git log --all -S 符号）定位真实写入提交与所属分支，先判定'生产影响是否存在'，再决定读哪份实现。避免血缘未定前深读非部署实现、把开发期测试写入当生产证据，或按猜测的文件布局写聚合脚本。

## Trigger
多分支/多 worktree 共享同一数据目录的环境中，需要判断某机制是否影响运行时指标，且已拿到带独特符号与元数据（pid/时间戳/工具名）的证据工件和被审计部署代码根

## Discriminator
工件的独特符号（如 kind 标记、对应写入函数/import）在被审计部署根的 grep 中零命中，同时工件行带测试痕迹（单 pid 突发、'xyz' 类非生产工具名、时间戳早于引入提交）→ 该工件不是被审计运行线写出的，下一步应查写入者身份而非继续读当前实现

## Short path
- 一次取三组事实：工件内容（提取独特符号+pid/ts/tool 元数据）、被审计部署根、指标观测面字段；后续所有 grep 限定在该部署根内
- 在部署根 grep 工件独特符号：命中→直接读该实现与开关；零命中→部署代码不是写入者，未知量切换为'谁写的'
- 用 git log --all -S <符号> 溯源引入提交及其分支/worktree，检查该提交是否在部署根 HEAD 祖先中；不在→工件属未部署线/开发期写入，经此路径的生产影响为零
- 读真实写入者的实现验证影响面：是否只写旁路审计文件、fail-open、有 kill switch、不触碰 wire 字节
- 对已部署的残余同类路径：读实现确认作用位置（历史尾部追加、一次写入冻结）并核对默认配置/开关是否使其根本不进正文
- 先确认本会话数据文件实际布局（单文件 vs 滚动分段目录）再聚合实测指标，比对前缀指纹稳定性与变更原因字段

## Stop conditions
- 符号在部署代码命中且配置证明其运行：写入者问题消解，转实现与实测核验
- 工件被证实为非部署线/测试写入，且已部署路径的影响面与实测指标均已验证，血缘/实现/实测三面一致
- 实测指标覆盖目标会话全部分段且前缀指纹全程单一不变、变更原因全空

## Verification
- git -S 找到的引入提交所属分支与部署根 HEAD 的祖先关系一致（不在祖先中=未部署）
- 工件行 pid/时间戳落在写入提交的开发期窗口而非生产运行窗口
- 聚合脚本前先列出数据目录实际布局，结果覆盖全部滚动分段
- 结论同时具备按构造安全（实现/开关）与实测零扰动（指纹/命中率）两路证据

## Counterexamples
- 符号在部署代码中直接命中：写入者即当前代码，无需 VCS 溯源，直接读实现
- 单工作区无分支歧义：符号缺席意味着'从未存在'，工件可能来自其他环境或陈旧数据，git -S 无意义
- 用户只关心当前运行时行为且证据工件与之无关：不应追工件血缘
- 符号命中但位于死代码或默认关闭路径：存在≠运行，必须补配置/开关核验才能下结论

## 4. dd4c7c1dddf2

TASK

用户用唯一 EVO ID 引用一条已批准记录并要求按规格继续；records 搜索只返回截断预览，但持久台账可按该 ID 取全文。任务是先取完整权威记录再执行。

METHOD CARD

name: anchor-verification-over-narrative-recovery
method_id: anchor-verification-over-narrative-recovery-73fa76a07438
description: 核对'过去的建议/交付是否落实'时，不要循环恢复旧报告全文：首次截断或检索无命中后，把旧报告当作待验证的声明清单而非证据。从预览与 git 历史提取每条建议的可查锚点（fix commit、record/EVO id、部署 gen/head、job id），逐个到权威源验证（git show / branch --contains、records 检索、status 回执）。验证通过→已落实；验证失败（如修复 commit 不在部署线上）→该失败本身即下一步行动项。若一致性检查（declaration_check）已标记旧报告含与回执不符的声明，则恢复原文更无证据价值。仅当某条建议不存在任何机器可查锚点时，才升级为更宽的原文恢复或向用户确认。

## Trigger
用户要求确认'此前交付/建议是否已落实'，而过去的自述报告仅以截断形式存在（事件流折叠、日志截断）或 evidence 检索无命中，但预览或仓库历史中已可见报告所指涉的锚点（commit hash、记录键、部署代次、任务 id）

## Discriminator
一次恢复尝试已返回截断或无命中，且更早已可见两个事实：(1) declaration/consistency check 已标记该旧报告含与工具回执不符的完成声明——原文不具证据效力；(2) 预览与 git 历史已暴露每条建议的锚点（修复 commit 的权威 commit message、EVO id、gen/head、服务状态回执），每个锚点都可在权威源直接查询。二者合起来表明：验证锚点比恢复散文更便宜且更权威

## Short path
- 读当前权威回执（部署状态、服务 code_current、pending 队列），确立'现在'的真值基线
- 对旧报告至多做一次恢复尝试；无论成败，从预览与相关 git 历史提取每条建议的锚点：fix commit、EVO/record id、部署 gen/head、job id
- 逐锚点查权威源：git show 取修复的权威描述；git branch --contains 判断是否进入部署线；search_records 判断登记是否闭合；status 回执判断服务新旧
- 分类输出：源验证通过→已落实；验证失败（如修复不在部署线）→直接定义为下一步行动项，进入执行
- 仅当某条建议没有任何机器可查锚点（纯方向性建议）时，才升级为更宽的原文恢复或向用户澄清

## Stop conditions
- 每条建议都已映射到一个权威源的验证结果（git 输出 / 记录查询 / status 回执），状态表完全不依赖恢复出的报告原文
- 所有验证失败的条目均已转为明确的下一步行动并开始执行

## Verification
- 最终逐项'已落实/未落实'结论均引用 live 权威回执（branch --contains 输出、records 查询结果、服务 status），而非恢复的叙事文本
- 对每条'已落实'声明，核验所用权威源与该建议指涉的对象是同一锚点（同一 commit、同一记录键、同一服务）

## Counterexamples
- 用户要的就是上一轮报告的原文内容（原文本身即交付物）→ 恢复原文就是任务，本方法不适用
- 建议条目无任何机器可查锚点（如'以后考虑引入 A/B 评估'）→ 锚点验证无法分类，必须依靠原文或用户澄清
- 预览与历史中完全提取不出锚点（报告只以不可检索的摘要存在）→ 此时扩大恢复范围（提高 event limit、evidence 检索）才是正确的升级路径，而非强行套用锚点验证

## 5. 47790159f6d3

TASK

上轮已经发起异步 restart，action_id 与专属台账路径都在手。用户只问动作最终是否成功以及为什么没反馈；不需要查这个 ID 在代码里由谁生产或消费。

METHOD CARD

name: anchor-on-unique-identifier-to-find-mechanism
method_id: anchor-on-unique-identifier-to-find-mechanism-ae14900fecb5
description: 当状态/工具回执返回含唯一字面标识（schema 名、专有字段名、全局部署 ID）的结构化数据，而下一个未知量是『谁生产/消费它、对应操作流程是什么』时，先用这些精确字符串做定点定位：浅层 find 找数据/manifest 文件，grep 标识（scope 到已知的 code_root 的 src/docs/tests）找实现与操作文档；不要先做模糊关键词的 evidence/docs/files 宽搜，也不要全库无界 grep。唯一标识近乎零误报，能把搜索空间从『全仓库』缩成两三个可读文件。

## Trigger
结构化回执已给出全局唯一、可直接 grep 的字面标识（schema 字符串、专有字段名、ID），且回执同时给出了可作 grep scope 的路径（如 code_root），而任务需要弄清该数据的读写机制或操作步骤

## Discriminator
回执中是否存在非通用的唯一字面量（schema 版本串、复合专有字段名、全局 ID）——存在即意味着任何包含该字符串的文件定义性地属于机制本身（实现/文档/测试），模糊关键词搜索在此时是低信息动作

## Short path
- 读状态回执，提取唯一标识（schema 串、专有字段名、ID）与 scope 路径（code_root/runtime_root）
- 用标识定点定位：runtime_root 浅层 find 找 manifest 数据文件；grep 标识但 scope 到 code_root 的 src/、docs/、tests/，命中实现、操作指南、测试三类文件
- 读实现确认操作语义（操作是专用命令还是手改数据；派生字段如哈希如何计算），读指南确认人机分工与步骤
- 按指南核对前提（目标 HEAD、产物在位、新旧提交是否触及产物目录），全部通过才生成命令
- 命令中所有 expected/CAS 值来自刚读到的回执，禁止凭记忆或旧会话填入

## Stop conditions
- 实现代码与操作文档双重确认了操作方式，前提检查（HEAD、产物、diff）全部有直接证据，命令已生成并含读回校验
- 唯一标识 grep 无任何命中（机制不在本仓库）→ 此条因果边断裂，才扩大到模糊 docs/files 搜索或外部询问

## Verification
- grep 命中应同时覆盖实现、文档、测试三类文件并互相印证；只有一类命中时先补另一类再下结论
- 生成命令前用只读子命令（show/status）读回当前代次/版本作为 expected 值，不硬编码
- 对『无需重建/可直接发布』类结论必须持有直接 diff 证据（如新旧提交对产物目录零改动）而非推断

## Counterexamples
- 标识是通用词（id、version、name）→ grep 泛滥误报，应改用路径 scope 或组合键，本方法不适用
- 回执内容已完整回答用户问题 → 直接停止分析，不追生产者代码
- 标识只出现在运行时数据文件、由外部系统生成（仓库内无实现）→ 边断裂，需宽发现或问人
- 仓库巨大且无 scope 路径可用 → 无界 grep 会超时，应先从回执或目录结构推出 scope 再执行

## 6. 775cc1024fcc

TASK

一个 CI workflow 正在后台跑，成功后才会生成 release artifact；任务只是查询 run conclusion 并在失败时读失败日志，不涉及 factory 装配或 settings 接线。

METHOD CARD

name: anchor-narrow-wiring-at-construction-site
method_id: anchor-narrow-wiring-at-construction-site-7f3ff30de391
description: 当任务是『把已存在注入点的组件经 opt-in settings 接进生产装配点、缺省零差异』时，把全部取证锚定在装配点那一次构造调用上：调用的实参清单就是完整接线面，装配文件的 import 行就是组件真实模块路径（不猜目录）；settings 命名先查权威短文档（短文档一次整读，不做关键词 grep 往返），无权威再取同一装配文件里最近的 opt-in 惯例；先写含缺省零回归守卫的 RED 再改码；测试绿后如实标注构造级测试覆盖不到的运行时行为边界。

## Trigger
任务形态为『把组件 X 接线到生产装配点（factory/entrypoint），settings 显式开启、缺省与现状零差异』，且任务本身已知是窄接线而非新组件设计；典型信号是开始猜测组件文件路径、反复重读同一装配区域、或对很短的权威文档做多轮关键词搜索。

## Discriminator
动手前已可见的三个事实把搜索空间缩到极窄：(1) 装配点对组件的构造调用已完整列出全部实参（本例 factory 构造 SubAgentRunner 的逐 kwarg 清单）——这就是全部接线面；(2) 装配文件必然 import 该组件——import 行唯一确定模块路径，无需猜 src/xx/runtime/ 之类目录；(3) 组件 __init__ 中注入参数默认 None=关（slice 已预落地注入点），说明剩余工作只是 settings 字段+条件构造+传参。第一处扩散正是抛开了 (2) 去枚举猜测的文件布局。

## Short path
- 定位装配点对组件的唯一构造调用并整段读一次：实参清单=接线面，同文件的 import 行=组件真实模块路径；不再猜测目录布局
- 读组件 __init__ 签名一次：确认注入点已存在且缺省 None=关；若不存在则本方法终止，转入设计/切片任务
- 权威设计文档若很短则一次整读：确认是否规定 settings 命名/行为；未规定才采用同装配文件最近的 opt-in 惯例（env 前缀+空值=关闭），并引用该惯例代码位置作为命名依据
- 读被注入组件的构造签名一次（如 coordinator 的必填字段），逐字段推导应由 settings 提供什么、缺省值是什么
- 先写 RED：opt-in 路径构造出被注入组件且 spawn 产生预期副作用；缺省路径写显式零回归守卫（无该组件、无其落盘产物、既有工具回执行为不变）
- GREEN→相邻测试套件→全量；最终回答如实标注构造级单测覆盖不到的运行时行为（如 live spawn/跨进程），停止

## Stop conditions
- 构造级 RED→GREEN、相邻套件与全量测试 exit=0，且缺省零回归守卫通过
- 组件注入点不存在（需先做设计变更落地注入参数），本方法不适用即停
- 权威文档/schema 已固定命名或接线约定——遵循权威并停止惯例推导

## Verification
- 缺省配置下：装配产物中无被注入组件、无其落盘状态文件、既有工具回执与接线前逐字一致
- opt-in 配置下：被注入组件以 settings 推导的实参构造并传入目标组件
- RED 先失败、实现后 GREEN；相邻测试与全量套件通过
- 最终答复中显式标注单元/构造级验证未覆盖的行为边界，不以构造级测试宣称端到端验证

## Counterexamples
- 组件尚无注入参数（前序 slice 未落地注入点）：这是设计任务而非窄接线，锚定构造调用会漏掉真正的工作量，应先做接口设计
- 权威 spec 已明确规定 settings 命名或 wire schema：必须遵从权威，套用仓库惯例会制造第二套命名
- 接线正确性只能在 live/跨进程运行中观察（真实子会话完成、跨代 CAS reclaim）：构造级单测不能作为行为验证，需另行 live qualification，本方法的 stop 条件不满足

## 7. 5e91f424cf89

TASK

CI 日志视图明显截断且没有 short test summary；当前只需要从完整日志固定全部 FAILED/ERROR 清单，不是在核对注册表或配置条目的 live contract。

METHOD CARD

name: authoritative-artifact-first-then-live-contract-probe
method_id: authoritative-artifact-first-then-live-contract-probe-6867db304150
description: 当被问“某注册表/配置条目是否有缺口需要修复”时：若权威 live 工件的位置已在前次会话或线索中确立，直接重读该文件取最新现状，跳过全库宽搜；与同类兄弟条目 diff 找缺失字段，grep 代码消费点定影响面；再按真实 client 契约（复刻 client 实际 payload 形状）做一次最小 live 探测裁决实际能力。明确拒绝型错误（如 400 且列出合法取值范围）视为“标志缺失即正确状态”的权威证据，不要好心补齐；正向多模态结论须用独立通道交叉验证（token 计量跳变 + 独立图像识别对照）防幻觉。只修被证实的缺口，写入后验证解析与选择路径生效。要点：记忆中的路径只当指针用，内容必须现读；路径失效（read 失败回执）即退回定向 search，不反复撞同一死路径。

## Trigger
用户询问某注册表/配置中具体条目（能力标志、字段缺失类）“是否有缺口需要修复”，且权威 live 工件路径已在前次会话、注释或线索中确立；宽搜命中几乎全是归档/备份（.env.bak、evals/*/results）时尤应触发。

## Discriminator
当时已知：上一轮修改的就是 live 的 data/providers.json（同款缺口 flashx 即修于此），而 search_files 命中几乎全为 eval 归档与 .env 备份。该事实把“全库枚举定义”缩成“直接重读这一个已知权威文件取现行 flags”，且读到的内容天然是最新状态、无需再确认归档副本。

## Short path
- 直接重读已知权威工件（如 data/providers.json）中目标条目；未知量：两模型现行 flags 现状
- 与同库兄弟条目 diff（已修好的 flashx、deepseek-flash 均带 multimodal+note）；未知量：按本库规范到底缺什么
- grep 缺失 flag 的代码消费点（解析器+vision 选择逻辑+路由权重注释）；未知量：缺 flag 是否有功能后果
- 按 client.py 真实 payload 形状对每个模型做最小 live 探测：流式 include_usage / tools+tool_choice / 图片输入；未知量：实际行为是否与元数据一致
- 对结果定向裁决：正向图像结论用 token 计量差（1432 vs 基线 17）+ 独立图像工具描述对照做防幻觉交叉验证；明确拒绝（400/1210 列出合法取值 ['text']）视为权威负证据
- 只修被证实的缺口，写入后在解析器读出 True、显式 provider/model 选择从 None 变命中后停止；顺手确认 fallback 链第一跳可用即可，不扩展到未询问的模型

## Stop conditions
- 每个被询问条目的实际能力均已由 live 探测+交叉验证或权威拒绝错误定论，能逐条给出有证据的 yes/no
- 修复已写入且被解析/选择路径验证生效（读出 True、显式指定命中）
- 权威工件路径失效（read 失败且已登记不存在）时，仅做一次定向 search 重新定位，不重复撞死路径也不退回全库枚举

## Verification
- 注册表标志与实测行为一一对应：实测收图的条目有 multimodal:true；被 1210 拒绝的条目保持无标志，并在 note 写明勿补，防后人好心补错
- 图像正向结论具备两路独立证据：prompt_tokens 相对纯文本基线的显著跳变 + 独立图像识别工具对同一图片描述一致（防模型幻觉凑巧）
- 修复后动态读注册表的路径即时生效（无缓存依赖），显式指定从 None 变命中；未支持的模型显式指定仍正确返回 None
- 探测 payload 与 client.py 实际发送形状一致（stream_options/tools 条件发送/max_tokens），保证测的是真实契约而非简化版

## Counterexamples
- 首次接触的仓库、权威工件位置未知——此时适度的目录/内容发现是必要前置，不能跳过直接猜路径
- 问题纯读配置即可回答（如“默认模型是什么”），无需 live 探测——探测徒增调用并产生真实 API 费用与副作用
- 离线/无 key 环境或探测为写操作、计费敏感——live 契约探测不可行或不该做，退化为官方文档+错误码+兄弟条目对照
- 宽搜命中本身就直接指向权威文件（无归档噪声稀释）——此时先读完命中再决定是否缩小，不必另行定位

## 8. 3f8868a097b4

TASK

CI 失败日志在 traceback 中途被截断，连 short test summary 都没看到。当前唯一目标是先从完整日志钉死全部 FAILED/ERROR 清单与数量；尚未进入这些失败是不是本次 diff 引入的归因阶段。

METHOD CARD

name: attribute-suite-failures-via-touched-set-and-clean-head-worktree
method_id: attribute-suite-failures-via-touched-set-and-clean-head-worktree-8d92c40cb6dc
description: 编辑已落地、触面测试全绿但更大范围测试出现失败时的归因闸门。先用失败回执点名的文件/模块/环名与本次触碰文件集求交集，形成可证伪假设（空集→存量债务假设；非空→直接修自己，不做归因实验）；再用 pinned 干净 HEAD 检出做单变量对照证明零因果。对照前先盘点既有 worktree（'already exists' 回执即证明基线环境已存在、可复用），并覆盖 venv 的 editable 路径解析（PYTHONPATH 指向 worktree 的 src），确保基线真的运行基线代码。归因结论附 HEAD hash，比对按测试身份逐一进行，然后停止。区别于通用根因诊断法：本卡是编辑收尾处的确定性归因协议，核心新判别式是触碰集∩失败点名主题。

## Trigger
任务内已完成代码修改且目标触面验证通过后，全量/更大范围测试报告若干失败，需判定这些失败是本次改动引入还是存量提交债，以决定是否阻塞收尾。

## Discriminator
两条当时即可读的事实：(1) 失败回执（traceback/guard 输出）点名具体文件、计数或环名，与本次 diff 触碰文件集求交集即可分出假设方向；(2) `git worktree list` 是既有干净检出的权威清单，新建命令返回的 'already exists' 回执本身即证明基线环境已存在、应复用而非重建。

## Short path
- 对失败测试用 --tb=short 重跑，收集失败身份与回执点名的文件/符号。
- 与本次触碰文件集求交集：空集 → 存量债务假设；非空 → 放弃归因实验，直接修改动。
- `git worktree list` 先盘点既有干净检出；存在 pin 在当前 HEAD 的 worktree 则直接复用，没有才 `git worktree add`。
- 在基线 worktree 上只跑那几个失败测试；venv 为 editable 指向主仓 src 时，用 PYTHONPATH=<worktree>/src 覆盖解析，确保加载的是基线代码。
- 逐一比对失败身份：基线失败集 ⊇ 观察集 ⇒ 记录为存量债务（附 HEAD hash）并停止；任一失败在基线消失 ⇒ 归因本次改动，转修复。

## Stop conditions
- 干净 HEAD（记录 commit hash）上复现同一组失败身份 ⇒ 判定存量债务，登记结论后停止归因。
- 任一失败在基线不出现 ⇒ 归因本次改动，停止归因流程、转入修复。
- 失败点名主题与触碰集相交 ⇒ 属确认级归因，跳过基线实验直接修复。

## Verification
- 基线运行 pin 到具体 HEAD commit 并记录 hash；比对按测试身份逐一进行，不做印象式'应该没问题'。
- 确认基线进程实际加载 worktree 代码（PYTHONPATH 覆盖 editable 安装），而非主仓工作区代码。
- 复用既有 worktree 前核对其 pin 的 commit 与当前 HEAD 一致；不一致则新建对照环境，不得拿旧基线充当当前 HEAD 基线。

## Counterexamples
- 失败 traceback 直接命中自己刚改的文件/函数：无需基线对照，修就是了。
- 失败具 flaky/时间依赖特征：单次基线对照不足以下零因果结论，需重复采样或显式标记，不得套用单次对照流程。
- 工作区无可用 commit 基线（测试依赖未提交生成物、工作区即唯一真相）时，worktree 对照无效，应改用 git stash 往返等其他隔离手段，而非强行套用本卡。

## 9. 812338a5a875

TASK

用户询问某注册表/配置中具体条目（能力标志、字段缺失类）“是否有缺口需要修复”，且权威 live 工件路径已在前次会话、注释或线索中确立；宽搜命中几乎全是归档/备份（.env.bak、evals/*/results）时尤应触发。

METHOD CARD

name: authoritative-artifact-first-then-live-contract-probe
method_id: authoritative-artifact-first-then-live-contract-probe-6867db304150
description: 当被问“某注册表/配置条目是否有缺口需要修复”时：若权威 live 工件的位置已在前次会话或线索中确立，直接重读该文件取最新现状，跳过全库宽搜；与同类兄弟条目 diff 找缺失字段，grep 代码消费点定影响面；再按真实 client 契约（复刻 client 实际 payload 形状）做一次最小 live 探测裁决实际能力。明确拒绝型错误（如 400 且列出合法取值范围）视为“标志缺失即正确状态”的权威证据，不要好心补齐；正向多模态结论须用独立通道交叉验证（token 计量跳变 + 独立图像识别对照）防幻觉。只修被证实的缺口，写入后验证解析与选择路径生效。要点：记忆中的路径只当指针用，内容必须现读；路径失效（read 失败回执）即退回定向 search，不反复撞同一死路径。

## Trigger
用户询问某注册表/配置中具体条目（能力标志、字段缺失类）“是否有缺口需要修复”，且权威 live 工件路径已在前次会话、注释或线索中确立；宽搜命中几乎全是归档/备份（.env.bak、evals/*/results）时尤应触发。

## Discriminator
当时已知：上一轮修改的就是 live 的 data/providers.json（同款缺口 flashx 即修于此），而 search_files 命中几乎全为 eval 归档与 .env 备份。该事实把“全库枚举定义”缩成“直接重读这一个已知权威文件取现行 flags”，且读到的内容天然是最新状态、无需再确认归档副本。

## Short path
- 直接重读已知权威工件（如 data/providers.json）中目标条目；未知量：两模型现行 flags 现状
- 与同库兄弟条目 diff（已修好的 flashx、deepseek-flash 均带 multimodal+note）；未知量：按本库规范到底缺什么
- grep 缺失 flag 的代码消费点（解析器+vision 选择逻辑+路由权重注释）；未知量：缺 flag 是否有功能后果
- 按 client.py 真实 payload 形状对每个模型做最小 live 探测：流式 include_usage / tools+tool_choice / 图片输入；未知量：实际行为是否与元数据一致
- 对结果定向裁决：正向图像结论用 token 计量差（1432 vs 基线 17）+ 独立图像工具描述对照做防幻觉交叉验证；明确拒绝（400/1210 列出合法取值 ['text']）视为权威负证据
- 只修被证实的缺口，写入后在解析器读出 True、显式 provider/model 选择从 None 变命中后停止；顺手确认 fallback 链第一跳可用即可，不扩展到未询问的模型

## Stop conditions
- 每个被询问条目的实际能力均已由 live 探测+交叉验证或权威拒绝错误定论，能逐条给出有证据的 yes/no
- 修复已写入且被解析/选择路径验证生效（读出 True、显式指定命中）
- 权威工件路径失效（read 失败且已登记不存在）时，仅做一次定向 search 重新定位，不重复撞死路径也不退回全库枚举

## Verification
- 注册表标志与实测行为一一对应：实测收图的条目有 multimodal:true；被 1210 拒绝的条目保持无标志，并在 note 写明勿补，防后人好心补错
- 图像正向结论具备两路独立证据：prompt_tokens 相对纯文本基线的显著跳变 + 独立图像识别工具对同一图片描述一致（防模型幻觉凑巧）
- 修复后动态读注册表的路径即时生效（无缓存依赖），显式指定从 None 变命中；未支持的模型显式指定仍正确返回 None
- 探测 payload 与 client.py 实际发送形状一致（stream_options/tools 条件发送/max_tokens），保证测的是真实契约而非简化版

## Counterexamples
- 首次接触的仓库、权威工件位置未知——此时适度的目录/内容发现是必要前置，不能跳过直接猜路径
- 问题纯读配置即可回答（如“默认模型是什么”），无需 live 探测——探测徒增调用并产生真实 API 费用与副作用
- 离线/无 key 环境或探测为写操作、计费敏感——live 契约探测不可行或不该做，退化为官方文档+错误码+兄弟条目对照
- 宽搜命中本身就直接指向权威文件（无归档噪声稀释）——此时先读完命中再决定是否缩小，不必另行定位

## 10. fa2b99204855

TASK

我只想确认几个已知测试到底过没过，但 pytest 会吐出大量 warning，之前工具窗口把最后的 summary 和退出码截掉了。

METHOD CARD

name: bound-verification-output-to-survive-truncation
method_id: bound-verification-output-to-survive-truncation-5879c1e4cca7
description: 当一次验证只为回答一个小而离散的未知量（如『干净树上这6个具名测试是否通过』），而命令原始输出很长时，先塑造命令使关键事实能扛住输出截断：精确选择条目、tail 汇总行、显式 echo 退出码，并对 stash/pop 等状态改动加守护回显。若截断已发生且实验廉价、确定、近似幂等，直接带界重跑一次，胜过依次枚举 evidence hydration / evidence search 等恢复路径。本集一个二元事实消耗了 5 次动作（截断的复合命令→hydrate→search_evidence→grep 重试→tail 重试），带界单次运行即可闭合。

## Trigger
需要用一个命令验证离散事实（测试是否全过、退出码、汇总行、守护标记），且可预见原始输出很长（此前同命令已产出多屏输出、含大量警告前导或进度条），或工具回执已显示输出被截断

## Discriminator
跑之前已经可见的事实：上一轮 pytest 输出同时暴露了（a）所需答案只占输出末尾一两行（short test summary / 最终计数 / 退出码），（b）完整输出很长（warnings 前导+进度条），（c）6 个失败测试的具名清单已知、可精确选择。这三点在运行前就足以推出：不限输出的全量复合命令必然把答案截在界外，而『选择+tail+echo 退出码』可把输出压到几行内。

## Short path
- 明确本次验证的唯一未知量（干净树上这6个具名测试是否通过），不捆绑其他子目标到同一命令
- 把输出压到只含答案：pytest 用具名/-k 选择加 -q，管道 tail 汇总行，或显式 echo 退出码；stash/pop 包裹时加 POP_OK 类守护回显
- 一次运行读出二元答案（退出码0/1 即够），不做第二次同源确认
- 据答案立即决策（该 WIP 不随 publish 上线：存补丁、还原工作树），进入下一未知量
- 交付前对树状态做一次终检（HEAD+零 diff），然后发出零 $ 符号、绝对路径的最终命令

## Stop conditions
- 关键事实（退出码/汇总行/守护标记）已在本次输出中完整可见，即停止验证并决策
- 实验昂贵、非确定或有外部副作用（长构建、变更外部状态）时，不再重跑，改走证据恢复或分页读取
- 同一未知量已由权威来源回答后，不再重复确认

## Verification
- 确认答案行来自本次运行的完整输出，而非截断片段或事后猜测
- 状态改动型验证（stash/pop）结束后确认工作树恢复原状：守护标记回显 + git status 零改动
- 最终交付物（命令）在目标 shell 语义下可原样粘贴执行：无会被 UI 渲染吞掉的符号、路径绝对

## Counterexamples
- 静态只读查询且结果已完整返回（如结构化 JSON 回执）：直接使用，无需重塑命令或预防截断
- 截断发生在所需内容中部而非尾部（如长 diff 的中段）：tail 汇总无效，应改用带 range 的分页读取
- 昂贵或非幂等实验（长构建、触网、变更外部状态）：截断后不应盲目重跑，证据恢复/日志检索才是正解
- 输出本身很短且无截断风险：加管道和守护回显反而增加命令复杂度与新的出错面
