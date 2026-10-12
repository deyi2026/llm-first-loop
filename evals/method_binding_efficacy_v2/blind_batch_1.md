# Blind batch 1/4

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. 155988cea3b3

TASK

第一次调用 closure API 被明确拒绝为缺少 evidence 与 reason；任务是一次补齐必填字段后重试，不需要归因任何日志 artifact 的写入者血缘。

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

## 2. 91baff38edab

TASK

用户问题中逐字出现了产品 UI 可见的指标、状态词或错误文案（如面板上的计数、状态标签），并询问该数字/行为为何如此变化；代码库同时包含前端与后端源码。

METHOD CARD

name: anchor-quoted-ui-label-to-its-data-source
method_id: anchor-quoted-ui-label-to-its-data-source-4ae2f64ced6c
description: 当用户逐字引用产品 UI 上的计数/标签/文案并追问其行为原因时，把该字面量当作 provenance 锚点：先用精确字符串搜索定位渲染该文案的前端组件，再沿组件的数据请求边（fetch 端点+参数）走到后端 route 读计数口径；持久化/去重类子问题则分流到已确认的唯一写路径（如 save_candidate→store）去读，而不是先做跨前后端的全库内容搜索或按概念枚举文件名/猜文件类型（前端实为 .tsx 却搜 *.js 这类死胡同即可避免）。

## Trigger
用户问题中逐字出现了产品 UI 可见的指标、状态词或错误文案（如面板上的计数、状态标签），并询问该数字/行为为何如此变化；代码库同时包含前端与后端源码。

## Discriminator
t0 即存在的事实：用户消息本身包含被引用面板的逐字文案（具体标签与数值），该字面量可直接定位其渲染组件；同时首轮搜索已确认系统存在唯一写路径 save_candidate，足以把『去重/重复生产』类子问题收窄到 store 与 reflection payload 两处，无需全库枚举。

## Short path
- 对被引用标签做精确字符串搜索（优先前端源码范围）→ 定位渲染组件；未知量：这个数字由哪个组件渲染、从哪个 API 拉取、带什么参数
- 读该组件，确认计数字段（如 counts.saved）与 fetch 调用及 limit 参数 → 得到后端端点名；未知量：计数在后端何处、按什么口径聚合
- 读该端点的 route handler：counts 在 recent_jobs(limit) 窗口内按 state 统计 → 直接回答『为何有增有减』（滚动窗口而非累计，卡未删除）
- 去重子问题沿已确认唯一写路径读 store：method_id = name-slug + sha256(body) 截断，同 id 已存在即返回旧记录 → 仅字节级幂等、无语义去重
- 读 reflection payload 构造，核对是否注入已有方法池 → 回答重复生产与 token 浪费；三个未知量均有权威代码出处后停止

## Stop conditions
- 被引用计数的数据源与聚合窗口语义已由定义该端点的同一文件直接证实
- 去重语义已从唯一写路径的 id 生成逻辑中读到，而非凭函数名推断
- 重复生产判断已核对反思 payload 是否包含已有方法池信息

## Verification
- 确认精确命中的组件确实渲染目标计数（如 counts.saved），而非同短语在无关模块（聊天流式提示）中的假阳性出现
- 计数聚合逻辑读自后端端点实现本身，未用前端展示反推
- 幂等/去重结论引用 method_id 计算所在代码行；token 浪费结论引用 payload 组装处可见字段

## Counterexamples
- 问题只涉及存储/去重语义且用户未引用任何 UI 文案 → 应直接从唯一写路径/store 出发，UI 锚点方法无增益
- 被引短语是高频常用语（如『已生成内容』同时出现在流式聊天模块）→ 精确搜索大量假阳性，必须先验证命中组件确实渲染目标计数再跟随
- 前端仅有编译产物、源码不在仓库 → 标签搜索无法定位渲染组件，应回退为后端 API/路由枚举

## 3. 08ca9269f286

TASK

上轮 git fetch 挂死；现在到点决定是否重试。需要先对 remote host 做一条不超过 8 秒的网络探针，判断传输层是否恢复，再决定是否执行阻塞式 fetch。

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

## 4. 6ae0aee051b0

TASK

工具契约已经明确模型拥有 restart 权限、没有 operator-only 发布动作；但部署记录 git_head 与当前 HEAD 不一致，且并行会话留下 dirty 增量。任务是做 binding drift preflight，避免变更被 fail-closed。

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

## 5. e805a3302ea4

TASK

同一份运行日志跨过了几次服务重启。我已经拿到当前实例的 pid 和启动时刻，现在要判断只在新进程里出现的连接缓存异常是否仍能复现。

METHOD CARD

name: anchor-evidence-to-instance-lifecycle-window
method_id: anchor-evidence-to-instance-lifecycle-window-fffe781df7d0
description: 当待解释的证据流（日志、缓存、连接行为）横跨多次重启或多个进程生命周期时，不要按固定行数/体积采样后直接解释，而应先用已在手的当前实例标识（PID、启动标记、启动时间）划出证据窗口，只解释窗口内证据；若窗口内没有目标事件，且故障域被判定为“进程内长期存活对象”，则验证必须在同进程内用真实失败源复现（而非另起进程、mock 或寻找内建探针），并以可区分的前后状态作为结论依据。本次摩擦点发生在按固定行数读取跨代日志、随后不得不回头定位启动边界重读的那一步。

## Trigger
需要对一个跨多次重启/多进程生命周期累积的证据流（日志、缓存、连接状态）下结论，并判断“当前实例”是否健康或能否复现故障。

## Discriminator
当前实例的可机械定位标识是否已在手——进程/部署探测的同一批回执里已经给出当前 web 实例的 PID 与约 1 分钟前的启动时刻（且该日志体积表明其横跨多代重启），因此存在一个无需按体积采样的精确窗口锚点。

## Short path
- 从部署/进程回执中取出当前实例标识（PID + 启动时间），未知量：哪些证据属于当前实例。
- 用该标识直接定位日志中的生命周期边界（对应 PID 的启动标记行 / 服务监听行），得到行区间，而不是先读固定行数。
- 只读取该区间到文件末尾的片段；未知量：当前实例窗口内是否真的发生了目标事件。
- 若窗口内无目标事件，先判定故障域：故障只出现在进程内长期存活对象、而新起进程与命令行客户端正常，则排除“另起进程探针”和“找内建探针”两条路。
- 在同一进程内用真实失败源复现（指向一个必然拒连的端口），观察失败信号、回调触发、以及下一次取用时是否返回重建后的新实例。
- 取得可区分的前后状态后停止，并显式标注仍未证的部分（原始触发条件未复现）。

## Stop conditions
- 已能用完全属于当前实例窗口的证据回答“当前实例是否存在该故障”
- 窗口内无目标事件时，已在同一进程内用真实失败源复现并观测到可区分的前后状态
- 用户所需结论已由权威来源或可复现实验支持，且未证部分已显式声明

## Verification
- 最终断言中的每条日志/行为证据都能回溯到当前实例窗口内的具体行或同一次实验输出
- 复现实验使用真实失败源（真实拒连端口）而非 mock，并同时观测到失败分类、回调触发与缓存对象被替换为不同标识的新实例
- 记录被替换实例与新建实例的可比较标识（如对象 id / 生成序号）作为“重建确实发生”的证据

## Counterexamples
- 证据流没有重启边界（单实例、单次运行），按体积读取尾部即可，锚定动作纯属浪费
- 故障属于外部共享资源（上游代理/端口整体不可达），新起进程同样失败——此时必须做跨进程横向比较并验证外部可达性，进程内复现会得出错误结论
- 任务本身是“失败从何时开始”的跨窗口审计或统计，强行锚定单一窗口会漏掉历史证据

## 6. 7a3b70a04db8

TASK

需要审查一份报告，其中所有待核验事实都已经附有 commit/hash/URL/内部 ID；目标是逐个解析这些指针并给出证实、不可核验或证伪。报告不含需要优先刷新排序的 live 状态快照。

METHOD CARD

name: anchor-first-claim-audit
method_id: anchor-first-claim-audit-81071f5c9dc1
description: 审计一份此前写好的系统分析时，先从来文枚举全部可检验断言并三分类：可各用一条廉价命令核实的持久状态锚点（git HEAD、deployment/manifest JSON、action receipts、journal 统计）、有明确指向位置的代码行为断言、不可独立复核的遥测统计。第一批并行核实所有状态锚点——它们最廉价、因分析写作时刻滞后而失真率最高，且证伪会级联改变方案（如版本漂移层数、部署排序）。代码断言只在被指向的确切 file:line 验证；遥测类显式标注'未独立复核、按来源采信'。行动方案只从已核实事实重排，每条修正须可追溯到第一手命令输出。本 episode 中 git HEAD 锚点首轮即证伪'main=606755367'，但 deployment/receipts 等同级廉价锚点拖到第 7/8 轮才查，且开场只声明核'三处'导致各轮被动扩围——前置批量锚点可近乎减半轮次。

## Trigger
收到一份先前写成的分析/评审/报告，其中混合引用持久运行状态（版本号、部署代、action 回执、统计计数）与代码行为断言，且后续行动方案依赖这些断言成立

## Discriminator
来文本身是否点名了可各用一条廉价命令直接核实的持久状态工件（git HEAD、managed deployment/desired-state JSON、service action receipts、journal 计数）。这类断言存在写作滞后、失真率最高，且单条证伪即可级联改变方案优先级；该判别在收到消息当时即可做出，无需任何后续发现。

## Short path
- 通读来文，枚举全部可检验断言并三分类：持久状态锚点 / 代码行为断言（记录其指向的确切位置）/ 不可独立复核的遥测统计
- 第一批并行核实所有状态锚点（git log/status、deployment JSON、最近 action receipts、journal 计数，各一条命令），立即标记被证伪或滞后项
- 仅对未被锚点证伪的代码断言，按其指向的确切 file:line 读取验证，标 ✅/❌/nuance
- 无法廉价复核的遥测统计显式标注'未独立复核、按来源采信'，不与已核实事实混列
- 用核验表重排行动方案：每条修正给出第一手输出出处，并说明对方案的影响（如漂移层数、gen 发布排序）

## Stop conditions
- 所有影响行动方案的断言均已核实或显式标注采信
- 新出现的待核断言先入表分类，不再无清单地临时补查
- 对已核实断言不再追加'再确认'式读取

## Verification
- 最终核验表每行 ✅/❌ 均引用确切 file:line 或第一手命令输出
- 每条修正可追溯到锚点命令输出，而非用户复述或事后推断
- 未核项与已核项在结论中显式区分，方案仅基于已核项

## Counterexamples
- 来文只含纯代码语义断言、未引用任何持久状态工件 → 无锚可批，直接按位置读码
- 状态工件读取昂贵或有副作用（生产库、破坏性命令）而代码在本地 → 反转顺序或仅抽样
- 分析是本会话实时生成、无滞后窗口 → 锚点失真概率低，无需前置批量复核
- 用户只要求核验单一断言 → 不建全量清单

## 7. c06c44d33af1

TASK

浏览器重启后要验证 CDP binding 是否仍一致，任务上下文已明确 .env 记录真实端口和 TARGET_ID；应先读 .env 再按值探测。当前没有 connection refused，也不是判断能否接入。

METHOD CARD

name: attach-feasibility-gate-then-authoritative-config
method_id: attach-feasibility-gate-then-authoritative-config-42e640eda0c3
description: 当浏览器/自动化工具连接被拒且用户称目标已打开时：先用一次进程参数+端口监听检查判定接入是否根本可行（如无 --remote-debugging-port 即为终局性答案），据此先回答用户问题；若继续追内容，读取唯一权威配置源（如系统代理设置）而非枚举猜测端口与协议变体；遇登录墙/反爬等需用户凭证的硬阻塞时停止叠加绕过层，转为给出最小用户动作（分享链接/粘贴/带参重启）。

## Trigger
browser/自动化工具对用户已打开的目标返回 connection refused（终局性错误而非瞬态）；或连接失败后正要开始枚举环境候选（猜端口、换协议、叠绕过层）

## Discriminator
目标主进程启动参数是否缺少所需调试/服务标志且对应端口未监听（实测 Chrome 无 --remote-debugging-port、9222 未开）——此单一已观察事实把『拒绝原因的众多假设：端口错/代理干扰/工具bug/进程陈旧』收敛为『当前无法接入』并终结可行性问题；若目标改为取内容，scutil --proxy 一条权威读取即可给出真实代理端点，替代对猜测端口做多协议探测

## Short path
- 复现一次连接错误并读错误类别：refused（终局性）vs timeout/transient（可重试）
- 查目标主进程启动参数与所需端口监听状态 → 判定 attach 可行性
- 若不可行：这即是对『能否操作』的最终答案——报告阻塞+最小解除动作（带调试参数重启），并确认用户底层目标是否为取内容
- 若底层目标是内容：读权威配置源（系统代理设置）得到确定端点，做一次连通验证即止
- 遇登录墙/反爬 403 等需用户凭证的硬阻塞：停止枚举绕过（猜端口/换指纹/渲染代理叠加），转为请求用户动作（生成公开分享链接/直接粘贴）

## Stop conditions
- 进程证据证明目标无调试/服务端点 → 可行性问题已终结，输出答案而非继续诊断
- 内容源被证明需登录态或被反爬硬拦且绕过已一次证伪 → 请求用户操作，不再尝试更多绕过
- 任一取回路径已返回真实目标内容 → 停止发现，进入分析

## Verification
- 报告的根因与观察证据一致（ps 无调试参数、错误类型为 refused 而非超时）
- 建议的解除动作与根因一一对应（调试参数↔attach 失败；公开分享链接↔登录墙）
- 回查轨迹：在可行性已有定论后，未再对同一环境分支做端口/协议枚举或叠加同质绕过

## Counterexamples
- 错误为 timeout/5xx 等瞬态故障：可行性检查不能终结问题，应重试/健康检查而非下结论
- 用户实际诉求就是取回内容而非『能否操作』：代理与抓取路径从第一步即主任务，不算绕路
- 环境中不存在权威配置源可读：此时枚举监听端口/协议反而是合理的收窄手段
- 直连抓取已成功返回正文：无需渲染代理或任何进一步绕过，直接分析并停止

## 8. e98ab3b22128

TASK

一致性检查说某文件少了一整组标记；直接搜这个文件一个都找不到。我要判断这些标记是这次分支改没的，还是契约早就陈旧。

METHOD CARD

name: anchor-history-sweep-before-cross-branch-reproduction
method_id: anchor-history-sweep-before-cross-branch-reproduction-f37203595eca
description: 当一致性 checker 报『文件F缺锚点』且F对该锚点家族零命中时，用一次跨已知 commit refs 的 git 历史横扫完成归因（预存失效 vs 本次回归），而不是到其他 worktree/分支复跑 checker 或起全量测试套件：历史 0 命中⇒锚点从未存在于F⇒stale-contract 假红；再看锚点现居模块与契约跟踪单测即可定向修复（对齐契约或委托测试）。一条命令同时回答『分支特异性』与『是否回归』，删除冗余复现运行。附带纪律：门禁退出码不经管道中间环节读取，❌输出与 exit=0 并存的矛盾须当场解决，不得先报后改。

## Trigger
同步/一致性 checker 失败，报错形如『文件 F 缺少预期锚点』；且此前对 F 的直接搜索已显示锚点家族在 F 中零命中（整体缺失而非部分缺失）；需要归因：预存失效 vs 本次变更引入的回归

## Discriminator
两个当时已知事实的组合：(1) 对 F 的 grep 显示锚点家族零命中（类别性缺失）；(2) checker 断言逻辑要求这些字面量出现在同一路径。二者把候选原因{回归、分支特有、环境}收窄为一个可单步判定的问题——『锚点是否在 F 的 git 历史任何时点存在过』；且全部待采样 commit refs（各线/worktree HEAD）在早期 status/log 输出中已经暴露，无需先做任何运行即可横扫

## Short path
- 当前树跑一次 checker 并读其断言逻辑：确认它要求哪个文件包含哪些字面锚点（复现+契约读取合并为一步）
- 用已知的全部相关 commit refs 做一次 git grep -c <锚点> <refs> -- F 的历史横扫：同时回答『是否曾存在』与『是否分支特有』
- 全仓 grep 锚点家族现居何处（当前模块/契约跟踪单测），只跑该单测文件确认现行契约状态，不起全量套件
- 历史 0 命中 + 锚点现居他处 + 跟踪测试绿 ⇒ 判定 stale-contract 假红、预存成立；停止一切复现性运行
- 检查 checker 是否接入 CI/Makefile 等门禁以定影响面；量化陈旧副本差异并执行带备份的低风险修复；checker 修复定向为对齐现行契约或直接委托跟踪测试

## Stop conditions
- 历史横扫覆盖两条线/全部 worktree 的采样 refs 均为 0 ⇒ 归因完成（预存 stale contract），停止复现，转入修复决策
- 任一 commit 上锚点计数 >0 ⇒ 放弃 stale-contract 假设，转入回归定位/bisect 分支
- 契约跟踪单测绿而 checker 红 ⇒ 双契约漂移确认，修复收敛为对齐或委托，不再扩大调查

## Verification
- 门禁脚本退出码直接读取（不经 tail 管道）；❌ 输出与 exit=0 并存属矛盾信号，当场排查，不得留到终稿更正
- 根因结论须三证齐备：锚点在 F 全历史 0 命中、锚点现居位置、契约跟踪测试结果
- 宣布影响面之前先 grep checker 的门禁接线（Makefile/.github/CI 配置）

## Counterexamples
- F 仍含家族部分成员（如缺 02..05 但有 01）或锚点在近期 commit 存在过 ⇒ 是真回归，跨分支/worktree 复跑与 bisect 才是正确工具
- 失败形态是崩溃/超时/环境依赖而非锚点字面缺失 ⇒ 必须复现以隔离环境，历史横扫无信息量
- F 未跟踪或不在版本控制内 ⇒ 无历史可扫，退回单次新鲜运行+读 checker 源码
- 该 checker 本身就是唯一契约载体（无独立跟踪测试）⇒ 它红即内容真漂移，应修内容而非修 checker

## 9. 6e97e323c1d9

TASK

要审计一次会话为什么出现重复工具调用；会话经历 wake、compact 和 handoff，需要先拉完整未过滤事件流并定位控制流边界。问题不是某 lifecycle 是否完成，也不是统计 save/use/activate 阶段转移。

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

## 10. bbbd211ba8a9

TASK

本轮代码改完后定向测试全绿，但更大测试集出现几项失败。我需要判断这些失败是这次改动引入，还是当前基线本来就有。

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
