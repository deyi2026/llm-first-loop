# Blind batch 2/4

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. 8e85cd3efe97

TASK

需要用 shell heredoc 生成约 260 行报告，历史传输曾在命令成功时留下短文件。任务是分块写入并逐块核对行数与最终 sha256。

METHOD CARD

name: bounded-chunk-write-verify-for-long-file-artifacts
method_id: bounded-chunk-write-verify-for-long-file-artifacts-45c00c2ebf00
description: 通过 shell heredoc/cat 写入长文档时，传输可能静默截断内容，而命令仍返回 exit 0——回执证明的是'执行了'，不是'写完整了'。对长度超过单次命令可靠规模的交付物，应预先切成有界块（首块 cat >，后续 cat >>），每块后核对回执中的累计行数，末块附文末哨兵；一旦回读发现行数不足或句中截断，不要追加修补，而是删除后按更小块重建。

## Trigger
需要用 shell heredoc/cat 把长文档（数十行以上）写入文件交付物，或对一次写盘后的内容完整性没有独立回执、只能靠 exit 0 判断的场景。

## Discriminator
写入后立即可观察的事实：回执仅 exit 0 无输出，但 read_file 显示文件只有 8 行且在句中截断（预期约 115 行）——证明退出码与'成功'字样不等于内容完整；后续每个 ~30-45 行的 chunk 写入均完整到达预期行数（33→73→115、44→64→95），说明有界分块+逐块行数核对+文末哨兵可稳定绕开该失效模式。

## Short path
- 起草时按目标长度预切有界块，每块规模远小于出现截断的单次写入（本环境中 ~30-45 行的块均成功，单次 ~115 行写入在第 8 行被截断）
- 首块 cat > 写入，回执累计行数应等于该块预期行数
- 后续逐块 cat >> 追加，每块后核对累计行数（如 33→73→115）
- 末块确认最后一句完整并追加文末哨兵（如 NO_CORRUPTION_MARKER）
- read_file 抽查头/尾与句界完整性，再声明交付

## Stop conditions
- 累计行数与逐块预期一致，且文末哨兵在位/最后一句无句中截断，即可停止写入进入交付
- 某块后行数不符或尾部截断时，停止追加，删除重建为更小的块，不继续在同一文件上修补

## Verification
- 每个 chunk 后以回执中的累计行数核对预期值
- 最终 read_file 至少覆盖文件头、尾与截断敏感位置，确认无句中截断、哨兵在位
- 不以 shell exit 0 或'执行成功'作为长文档内容完整的证据

## Counterexamples
- 短文件（几行、远低于单次写入可靠规模）：单次写入+一次回读即可，分块只增加噪音与调用数
- 写入由专用 write_file 工具完成且回执自带字节数/行数：以该回执为准，无需 shell 分块
- 文件会被并发读者立即读取、不能容忍中间态：分块追加会暴露部分写入状态，应写临时文件后原子 rename，而非套用本方法
- 截断根因不是传输规模（如磁盘满、权限错误，通常表现为非零退出码或显式错误）：分块写不解决该类失败

## 2. edfe85267bcc

TASK

需要证明一条 Method 生命周期是否真正从 save 经过 use 到 activate 完成闭环。任务是读取阶段转移事件与回执，核对每个 transition 的终态。

METHOD CARD

name: audit-closure-via-transition-event-receipts-not-artifact-grep
method_id: audit-closure-via-transition-event-receipts-not-artifact-grep-da92ba3b84c6
description: 审计“某流程是否闭环/是否被用到”时，先把问题拆成阶段转移清单（如 save_candidate→record_use→record_qualification→activate），用统一事件流中该生命周期工具的 action 回执逐段证明转移发生过；『用了几次』只从 action 回执计数。不要 grep artifact 文本里的动作名来计数——正文提及≠发生（本例 grep 命中 6 个含 record_use 的文件但结构化 use 记录为 0）。各 store 的最新时间戳检索只用来补没有转移事件的阶段（如 self_eval/lesson 停摆多久）。

## Trigger
被问『X 流程闭环了吗 / 方法、经验有没有被用到』这类流程审计问题，且工作区存在逐条记录工具调用的统一事件流（action/tool 回执）

## Discriminator
事件流回执里已可见 action.tool_loop tool_call method_manage 等生命周期调用被逐条记录——说明阶段转移有一等回执可直接查询，先于对每个 store 做内容枚举；另一个判别信号：grep store 文件命中动作名 6 处但结构化决策 JSON 为 0，即『提及≠发生』

## Short path
- 从用户问题列出的阶段名导出需证明的转移清单（Episode 产生 / Reflection 运行 / candidate 全链 / use 反馈生效）
- 按工具名查统一事件流（workspace scope）中该流程生命周期调用的回执，一次拿到全链时间戳与首次发生时间
- 仅对无转移事件的阶段做各 store 最新时间戳检索（如 self_eval、lesson 的最后日期）
- 计数『用了几次』：统计事件流 action 回执条数；机制生效用运行时事实验证（当前进程 head 是否包含相关 commit），不用 artifact 文本 grep 计数
- 四段证据齐即停，输出每段状态+硬证据

## Stop conditions
- 所有阶段转移均已由事件回执或权威记录证明（发生/未发生/停摆时长）
- use 计数与生效性已由 action 回执和运行时事实双重确认，不再追加确认性查询

## Verification
- 事件流中的转移时间戳与 store 记录交叉一致（如 active 卡的时间戳）
- 计数口径复核：以 action 回执为准；与 grep 命中数不符时优先信回执并向用户解释差异（提及 vs 发生）

## Counterexamples
- 没有统一事件流或留存窗口覆盖不到要审的时间段→只能退回 artifact 时间戳/mtime 审计
- 问题问的是 artifact 内容质量而非『某动作是否发生过』→内容检索才是正确工具
- 事件流是采样/截断的（如 limit 30 条）→流内计数会低估，需结合 store 全量记录
- 单 artifact 的事实问题、无流程阶段概念→不适用本方法

## 3. 275301ff2e2c

TASK

上轮 git fetch 挂起；当前任务是对 remote host 做 8 秒网络探针，分类传输层状态并决定下一次 fetch 时机。

METHOD CARD

name: async-wait-on-pipeline-conclusion-not-artifact
method_id: async-wait-on-pipeline-conclusion-not-artifact-03a2fa7c25cb
description: 等待异步流水线（CI/发布 workflow）产出最终产物时，不要把等待条件设为'产物存在'并用固定 sleep 盲轮询：流水线失败是吸收态，产物永远不会出现，存在性轮询注定超时；后台 job 完成也不会唤醒会话。应每步先查流水线结论（run list/view），失败立即读失败日志定位根因；仍需等待时注册定时唤醒按典型耗时接管，而非前台 sleep 碰运气。

## Trigger
设置（或准备设置）对异步流水线最终产物的等待/轮询：成功条件只有'产物存在'、用固定 sleep 循环等待、而流水线状态本身可查询时

## Discriminator
等待脚本的成功条件只有产物存在（如 release view 非空），而该产物的唯一生产者是可查询结论的流水线；失败一旦发生即为吸收态，存在性轮询必然 TIMEOUT；且后台 job 完成不会唤醒会话，固定 sleep 只能靠碰运气命中完成时刻

## Short path
- 设置等待前（或每轮迭代）先查产生该产物的流水线结论（按触发 tag/branch 过滤 run list/watch）——解决未知量：流水线是否已终止、结论是什么
- 结论=success→读产物并核对一致性；结论=failure→立即读该 run 的失败日志（如 --log-failed）——解决未知量：失败步骤与根因
- 仍需等待时注册定时唤醒（时长≈流水线典型耗时）接管后续动作，替代前台 sleep 盲轮询
- 唤醒后第一步重新查 run 结论再决定下一步（合并/重触发/发布），不重复盲等

## Stop conditions
- 流水线结论已被权威来源确认：success 且产物与预期一致，或 failure 且根因已定位并修复
- 已注册唤醒接管且当前没有前台阻塞等待

## Verification
- 等待逻辑包含对流水线结论的显式分支（in_progress/success/failure），failure 分支立即转入日志读取而非继续等待
- 唤醒/接管后的第一个动作与最新 run 结论一致：fail→读日志定位，success→核对产物后收尾

## Counterexamples
- 产物来自无法查询状态的第三方系统（无 run/conclusion API）→ 只能存在性轮询，但须设硬超时并把超时本身视为失败信号
- 流水线数秒内完成且环境不支持定时唤醒 → 短的同步 watch 可接受，无需排程
- 产物存在多个独立 writer、无单一权威流水线 → 只监控一条 workflow 会漏因，应回到产物核对+多源检查

## 4. a99f9c893519

TASK

此前异步 restart 已受理，action ID 和专属台账路径都已知。任务是读取终态并核对反馈通道的呈现状态与动作结果。

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

## 5. 21fbdef7437b

TASK

给定 session ID 和完整事件流，任务是定位两次相同工具调用之间的 wake/compact/handoff 边界并解释重复来源。

METHOD CARD

name: audit-report-by-resolving-cited-pointers
method_id: audit-report-by-resolving-cited-pointers-4cbbd66a7689
description: 审查一份对本环境可访问系统的分析/评分报告时，不按叙述语气采信，也不全量重推导：先抽取带可解析指针的声明（generation/commit/配置键/内部 ID/测试计数/时间窗事件断言/引用 URL），逐个用权威来源解析——内部声明查本地系统回执，外部声明直接抓取被引 URL 而非关键词搜索。解析结果三分类：证实、不可核验（指针失效或全 surface 无落盘 artifact）、被权威记录反证；'我已核验'类叙述若无落盘证据一律降级为转录。评价性分数不解析，只标注其测量不可复现性。

## Trigger
用户要求审查/评估一份关于本环境有工具访问权的系统的分析报告（外部模型分析、前任会话总结、评审意见），报告混杂事实声明与评价性声明，且事实声明带有具体指针（ID、hash、配置键、计数、时间窗内事件断言、引用 URL）。

## Discriminator
任务起点报告中已自带全部可解析指针，这在调用任何验证工具之前就把'如何审查'的空间从{全盘采信, 全量重做}缩小为{逐指针解析+对不可解析声明保持沉默}；其中引用 URL 本身就是显式 provenance edge（本集对'Agent Harness'先做 2 次关键词搜索只得到首页噪声，抓取被引 URL 才命中）；指针解析结果本身就是降级证据：get_goal 返回'目标不存在'、'136/136'在文件/docs/records/evidence 全部零命中=无落盘、事件流在声称窗口内出现一条反例事件=全称断言被推翻。

## Short path
- 通读报告，抽取全部带指针的事实声明，标记结论承重的 3~5 条优先核验
- 内部指针逐个用权威本地来源解析：runtime 快照、配置文件行号、git log、ID 解析工具、事件流；外部指针直接抓取被引 URL
- 按回执三分类：证实→保留；指针失效或全 surface 检索无落盘→降级为'不可核验'；权威记录在声称窗口内出现反例→标为'与事实冲突'
- 评价性声明（分数/排名/对比表）不解析，只检查测量可复现性与维度自指，标注为不可证伪
- 成稿：每个 ✅/⚠️/❌ 引用具体回执（file:line、事件时间戳、hash、工具失败消息），被审材料中未获回执的内容一律标注为转述

## Stop conditions
- 所有承重指针均已解析并三分类，最终审查中不存在任何一条无回执支撑的事实断言
- 指针全部解析且与叙述一致时，停止深挖非承重细节，避免为审查而审查
- 目标系统完全不可访问且无公开引用时，停止尝试，输出'不可核验'而非伪造核验

## Verification
- 审查结论中每条事实判定都能指出具体回执来源（文件行、事件时间戳、git hash、工具失败消息），而非被审文本本身
- 对'稳定/全部/已验证'类全称断言，已检查权威事件流在声称时间窗内是否存在单个反例（如重启后仍出现的旧状态自报）
- 外部引用结论来自被引 URL 原文，而非搜索结果标题或首页

## Counterexamples
- 报告为纯观点/战略建议、无任何可解析指针：没有解析对象，直接评估论证质量，不要虚构检查来套用本方法
- 指针指向你无权限访问的外部/私有系统且无公开引用：只能标注不可核验，不得用本地工具假装核验，也不得用搜索首页噪声充数
- 指针可解析但所附声明是语义评价（如'9.8 分'）：解析成功只证明对象存在，不证明评价正确，此时方法不适用
- 待核声明数量巨大且大多不承重：只抽结论依赖的承重子集，全量解析属于过度执行

## 6. 299a5703663f

TASK

部署记录的 git_head 与当前 HEAD 出现差异，并行会话还留下 dirty 增量。任务是完成 binding drift preflight，判断受管变更是否会被 fence 接纳。

METHOD CARD

name: authority-contract-before-managed-mutation
method_id: authority-contract-before-managed-mutation-62e4436f179e
description: 在受管 desired-state 控制面执行变更前，先从契约（工具 schema、源码注释、清单字段）确认动作权限归属：若 desired 状态被明确标注为 operator-published，且自己的工具面只暴露只读/重启类动词，则把'发布'归为 operator 手工步骤，而不是先假设自己能跑全部 CLI 再靠拦截报错学习边界。自己的职责收敛为：只读核验前置（HEAD、工作树干净、绑定产物新鲜度，源码有变更则先测试再重建产物）→ 从源码提取 CLI 签名，组装带 CAS expected-generation 的精确命令与预期输出交给 operator → 待确认后用自己拥有的 restart 动词执行并轮询愈合、canary 收尾。

## Trigger
用户要求在带 CAS generation 的受管生命周期/desired-state 服务上执行发布、重启等状态变更，且模型只通过受限工具面（或共享拦截层）操作该系统

## Discriminator
尝试变更之前已经在工具输出里读到的角色归属事实：源码注释明确写着 'desired: operator-published deployment'（且工具契约只提供 status/restart）。这一条当时就足以把候选动作从'我自己执行 publish'收缩为'备齐前置+精确命令交 operator 执行'，无需等拦截报错

## Short path
- 调控制面只读 status，取当前 desired generation 与绑定（未知量：现状与 CAS expected-generation）
- 读工具 schema 与关键源码注释，确认角色归属与自己的动词集（未知量：publish 归谁、发布绑定哪些字段）
- 若发布属 operator：只读核验 HEAD/工作树干净；diff 上一 desired 提交..当前 HEAD 判断绑定构建产物是否过期，过期则跑相关测试后重建（未知量：前置是否全部满足）
- 从源码提取发布 CLI 签名，组装含 expected-generation 与根路径的精确命令，附预期成功输出（新一代号、当前 HEAD、新产物哈希），一次性交给 operator
- operator 确认后：用自己工具面的 restart 动词携带新 expected_generation 执行，轮询 status 至新 PID、live 绑定与 stable 收据愈合到新一代，canary 验证后收尾

## Stop conditions
- 契约显示发布动词在自己的工具面内 → 直接自行执行 CAS，不做 handoff
- 无任何角色标注且无拦截证据 → 允许一次廉价探测；被拦截即转 handoff，不重复尝试同一路径
- 前置核验失败（工作树脏、产物无法重建、门禁测试红）→ 停止并上报，不把命令交给 operator
- restart 后 status 显示各进程新 PID、live git_head 等于 desired、收据愈合 → 任务完成，停止轮询

## Verification
- operator 命令的预期输出：generation = expected+1、git_head = 当前物理 HEAD、新的构建产物哈希
- restart 后 status：live 绑定与 desired 一致、restart_required 归 false、stable 收据 generation 匹配新一代
- canary：健康端点鉴权行为正常，build 标识包含新提交的 short sha

## Counterexamples
- 工具 schema 本身向模型暴露 publish/deploy 动词 → 应直接用工具执行 CAS 发布，做 operator handoff 反而增加摩擦与延迟
- 无共享拦截层的单机脚本环境（单用户、无权限边界）→ 直接执行是默认正确动作，先查权限契约纯属浪费
- desired 状态由 CI/外部系统自动发布 → 没有人工 publish 步骤，应等待并轮询外部发布者推进 generation，而不是交命令给 operator
- 源码中的 operator-published 只是历史惯例描述、CLI 实际对本地所有进程开放 → 一次探测即可澄清边界，不应零探测直接 handoff

## 7. 24076c231c5a

TASK

用户报告外部访问异常并询问是否重启；监督者显示进程 running，公网端到端请求返回应用级 HTTP 303。任务是据此裁决重启动作。

METHOD CARD

name: anchor-on-self-report-then-probe-gaps
method_id: anchor-on-self-report-then-probe-gaps-003c0af478b6
description: When user requests a health/status check on a system exposing an authoritative self-report tool, use the self-report's healthy/status field as the primary discriminator. Skip broad internal searches after self-report confirms healthy; only probe dimensions self-report does not cover with targeted queries.

## Trigger
用户请求健康检查/状态快照/系统状态类查询，且系统暴露有 authoritative self-report 工具（status / monitoring / dashboard 接口）

## Discriminator
self-report 工具回执已直接给出 healthy / status / health 字段（例如 healthy=true、status=consistent、model_fact_integrity.healthy=true）

## Short path
- 调 self-report 工具，解析 healthy / status 字段
- 对照用户需求，列出 self-report 已覆盖与未覆盖的维度
- 仅对未覆盖维度（host 资源、外部依赖、历史异常、独立指标）做定向 probe
- 若 self-report healthy=true 且定向 probe 无异常，停止

## Stop conditions
- self-report healthy=true 且对未覆盖维度的定向 probe 无异常
- 用户所需事实已被 self-report + 必要 probe 覆盖
- self-report 显示 unhealthy，转入对应子系统的详细诊断分支

## Verification
- self-report 的 healthy 字段与外部 probe（host shell / 独立 metrics）结果一致
- self-report 中 healthy 字段与子模块 breakdown 不自相矛盾
- 报告中的每一行都能溯源到 self-report 或一次定向 probe

## Counterexamples
- 用户明确要求独立验证（审计、压测后、self-report 刚重启未稳定）
- self-report 工具本身处于被怀疑状态（刚出过故障或正在变更/降级）
- 用户需要历史趋势或异常历史，而 self-report 只提供当前瞬时快照

## 8. 506d16bcc6b7

TASK

用户询问系统当前健康状态，权威 status 接口直接返回 healthy 与状态摘要。任务是据此判断是否需要展开更宽的诊断。

METHOD CARD

name: binary-intervention-sufficiency-gate
method_id: binary-intervention-sufficiency-gate-7631f80e335c
description: 当用户以"还是连不上，要重启吗"这类二元干预问题报告故障时，先用最小事实对决定答案：(1) 监督者报告的进程状态，(2) 一次穿透完整公网路径的端到端探测。两者皆为正向即否决重启，下一个未知量应转向报告方（客户端环境或告警源自身的探测路径），而不是继续枚举服务端健康维度。本例中这两条事实在前两步已定案，其后8次工具调用属于事后充分性确认。

## Trigger
用户提出"要不要重启/回滚/重部署X"式二元干预请求，且报告的故障在操作侧尚未复现

## Discriminator
在首次搜索扩散前已可见的两条事实：监督者（launchd）state=running 且 pid active；root/app/origin 三处均返回由源站应用生成的 HTTP 303（若隧道真挂，应表现为超时或 5xx，而非应用级重定向）。这两条事实当时已把候选空间从"服务可能挂了需重启"缩为"服务存活，问题出在报告路径一侧"

## Short path
- 1. 查监督者状态（如 launchctl print | grep state）→ 解决未知量：脚本是否已死、重启是否有据
- 2. 一次跟随重定向的端到端黑盒探测（curl -sL 公网域名取最终状态码）→ 解决未知量：完整服务路径是否可用
- 3. 两者皆正常 → 立即停止服务端健康枚举，转向收集报告方的判别信息（设备/网络/错误类别：超时、DNS、证书、5xx），或复现告警源自身的探测路径
- 4. 任一事实失败 → 重启或深挖才有依据，按失败维度继续诊断

## Stop conditions
- 监督者报告存活 且 一次端到端探测取得源站生成的成功响应（如跟随重定向后的 200）→ 回答"无需重启"并向报告方索要客户端侧判别信息
- 端到端探测超时/5xx，或进程已死/僵死 → 不满足停止条件，重启与继续诊断均有据

## Verification
- 成功响应必须是源站生成（重定向到应用真实页面/内容），而非边缘缓存页或错误页
- 探测必须走用户实际使用的同一公网域名和完整路径（含重定向链）

## Counterexamples
- 监督者显示 running 但端到端探测超时或 5xx：两事实分歧时重启反而有据，不得在"running"处提前停
- 故障是间歇性或发生在过去时间窗：单次通过的探测不足以下结论，需先查看覆盖故障窗口的日志
- "连不上"的报告来自探测路径不同的外部监控（如 DoH、443 被阻断的探测脚本）：本机 curl 成功不能证伪该告警，必须复现监控自身的探测方式后才可判定误报
