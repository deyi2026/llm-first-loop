# Blind batch 1/4

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. db6fd74071ba

TASK

用户询问服务是否健康，系统提供权威 status 接口并直接返回 healthy 与状态字段。任务是先用该 self-report 回答，再决定诊断缺口。

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

## 2. 776b355da180

TASK

CI 原始日志可完整读取，任务是从 short summary 与 FAILED/ERROR 行建立完整失败清单和数量，作为后续诊断输入。

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

## 3. 1d48851b7316

TASK

同一运行日志跨过数次服务重启，当前实例的 pid 与启动时刻已知。任务是切出当前实例证据窗口并复现连接缓存异常。

METHOD CARD

name: anchor-process-verification-on-deployment-identity
method_id: anchor-process-verification-on-deployment-identity-1a2a8ee84ad1
description: 验证重启/部署是否真正落地时，进程枚举的过滤键应从已拿到的部署记录（runtime_root、git_head、统一启动器命令模式）推导，而不是猜测组件关键词（如 uvicorn/服务名）。本例首轮 ps 用猜测关键词，漏掉一个服务并混入多个无关进程，被迫换过滤键重跑；若一开始就用部署身份作过滤键，一次查询即可精确枚举全部目标实例。

## Trigger
重启/部署动作完成后，需要核实全部目标服务实例已按期望代际（generation/git_head）真正运行，例如用户问“重启已完成，下一步”时的落地验证

## Discriminator
部署状态查询当时已返回部署身份：runtime_root/code_root 与 git_head；且 ps 输出中任一已匹配的目标进程行本身揭示了统一启动器模式（同一 runtime_root 下以同一 launcher 模块启动各服务）。这两条已知事实足以把过滤键从“猜测关键词”收敛为路径/模块精确匹配，一次枚举全部实例、零无关命中

## Short path
- 查询部署/服务管理器状态，记录 desired generation、git_head、runtime_root（部署身份）
- 以 runtime_root 或已见的统一启动器模式作为进程过滤键，一次枚举全部服务实例及其启动时间
- 核对每个实例启动时间晚于重启动作时间，且服务端口/端点健康响应
- 核对 git HEAD 等于部署记录 git_head 且 tracked 工作区干净，确认新进程未夹带未提交代码
- 输出核实结论（实例表+证据）与下一步建议，停止发现类动作

## Stop conditions
- 全部预期服务实例均在运行、启动时间晚于重启动作、代码指向期望 git_head、端点健康、tracked 工作区无修改
- 若任一实例缺失或启动时间早于重启，转查重启动作终态/服务管理器日志定位原因，而不是放宽或更换 ps 关键词重试

## Verification
- 用部署身份派生的过滤键重跑进程枚举，结果应恰好等于预期服务集合，无同名无关进程（如聊天客户端、cron 常驻脚本）混入
- 各实例的代码根/HEAD 与部署记录一致，端点探测返回预期状态码
- 对照部署记录中的代际/时间戳确认实例代际无误

## Counterexamples
- 部署管理器已直接返回每服务 PID/uptime 等权威存活状态时，无需 ps 模式匹配，直接信任管理器输出即可
- 部署记录不含 runtime_root/启动命令，且服务经 systemd/docker/supervisor 等多样方式包装运行时，单一路径过滤不可行，应按管理器逐服务查询
- 核实对象是一次性脚本或用户自装应用（非受管部署）时，关键词 ps 本来就是自然工具，本方法不适用
- 部署状态与实际运行环境分离（如 status 查询的是 desired 而非 live 状态）时，需另取 live 权威来源，仅靠身份锚定的 ps 不足以闭环

## 4. b9347146b8c9

TASK

会话出现重复工具调用，期间经历 wake、compact、handoff。任务是拉取完整事件流并定位重复从哪个控制流边界开始。

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

## 5. 75c44552f7fa

TASK

一条回执提供证据文件的完整绝对路径 `/tmp/run42/ATTRIBUTION.md` 与 sha256。任务是读取该路径、校验 sha256，并提取结论。

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

## 6. 07a5b704cb73

TASK

受管 desired-state 系统准备执行 publish/restart，当前工具面与源码对发布权限的归属需要先核实。任务是确定动作 authority contract 后再做变更。

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

## 7. 60f3ad5cead6

TASK

失败清单已经固定，定向测试也有结果。任务是把失败主题与本次 touched set 求交，并用 clean HEAD worktree 对照判断因果归属。

METHOD CARD

name: complete-failure-inventory-before-root-cause
method_id: complete-failure-inventory-before-root-cause-ce230cde7fa6
description: 从截断的 CI 失败日志切片直接得出"共 N 个失败"并开始归因，会漏掉未被看到的第 N+1 个失败，导致第一轮修复推送后才重新开诊断循环。应把"失败全集"当作待解未知量：先从权威完整来源（如 short test summary 段、对全量日志 grep FAILED/ERROR）钉死清单与数量，再本地批量复现、对触发提交做 diff 归因。本集第 5 个失败与已修同根因纯属侥幸，通常需整轮重推重验。

## Trigger
CI/门禁失败后，通过带截断迹象的渠道读取失败日志（行数上限、输出在记录中途结束、未见 runner 的完整汇总段），并准备宣布失败数量、进入根因诊断时。

## Discriminator
工具回执可见截断事实：输出被行数上限截断、内容在 traceback 中途戛然而止、且未出现 pytest 'short test summary info' 等权威失败清单段——此刻即知失败全集尚未被任何完整来源钉死，不能从可见切片外推失败数量。

## Short path
- 从失败 check 取权威失败全集：对完整 --log-failed 做 grep（FAILED|ERROR）或定位 short test summary 段；解未知量：确切失败集合与数量 N
- 按失败测试所属模块分组，diff 触发提交在这些模块上的改动，建立失败→改动映射；解未知量：每组根因落点
- 修复前在本地一次性批量复现全部 N 个失败，确认清单无遗漏
- 按根因修实现（而非放松测试），本地失败集全绿后推送
- 以重新查询的 statusCheckRollup 全 SUCCESS 确认 CI，再进入合并→checkout→restart→receipt 部署链

## Stop conditions
- 失败全集已由完整权威来源钉死，且每个失败都已本地复现或明确归因到具体改动
- 推送后重新查询 statusCheckRollup 无 FAILURE，原失败 check 全绿，才进入合并/部署步骤

## Verification
- 已诊断并修复的失败数 == 权威汇总段列出的失败数（无"日志截断漏看"缺口）
- 合并决策基于推送后重新查询的 check 状态，而非推送前或截断日志的推断

## Counterexamples
- 日志渠道已给出完整汇总段（无截断、失败清单可见）时，全集步骤冗余，直接归因
- 单一确定性失败且带明确 file:line（如 lint 错误）时，失败集平凡，无需全集步骤
- 失败疑似 flaky/网络瞬态时，应先重跑收敛再清点，穷尽归因每个失败反而扩大搜索空间

## 8. 5b468be45fd9

TASK

浏览器重启后，.env 给出 CDP 端口和 TARGET_ID。任务是按这些值探测端点并确认目标绑定一致。

METHOD CARD

name: binding-identity-gate-before-destructive-ops
method_id: binding-identity-gate-before-destructive-ops-9e1d9ef8f671
description: 对破坏性操作（kill/清理）的目标 ID 先做存在性检查，并把检查结果当作硬分支：零命中意味着 ID 类别判断错误（如把端口当 PID），必须先经映射证据（lsof 端口→PID）重建真实目标并核对命令行归属，再执行；命中且归属匹配则直接执行。不分支的'装饰性 pre-check'不算门控。本卡片只覆盖破坏性操作的身份门控，不构成绕过工具策略门控的依据。

## Trigger
用户要求清理/终止一组数字标识（如 45918/62427），且当前证据未直接确认它们是 PID 还是端口。

## Discriminator
杀前同一命令内 `ps -p 45918,62427` 已返回零行（表头下无任何进程），该事实在 SIGTERM 执行前即已可见；且任务上下文本就是浏览器调试端口（9222），提示这类数字更可能是端口而非 PID。

## Short path
- 未知量：45918/62427 是 PID 还是端口？先单独跑存在性检查（ps -p），空结果 ⇒ 排除 PID 假设
- 按任务上下文假设为 debug 端口 ⇒ lsof -iTCP:<port> -sTCP:LISTEN 映射到监听 PID（98741/63901）
- 杀前核对：ps -p <pid> -o command 确认 user-data-dir 与待清理目标匹配（browser_mount_test / .worktrees），排除误杀 9222 实例
- kill 已核对 PID（含确认由其拉起的父 shell 98739）
- 验证两端口无 LISTEN、目标 PID 消失、9222 实例仍在，停止

## Stop conditions
- lsof 对目标端口返回无 LISTEN（exit≠0）且 ps 确认目标 PID 已退出
- 任一候选 PID 的 command line 不在用户指定的清理范围内时，停止等待澄清而非继续

## Verification
- 杀后复查 lsof 两端口：应无监听（对应本次 lsof_exit:1）
- 复查剩余带 debug-port 的 chrome 主进程：只剩用户在用的 9222 实例

## Counterexamples
- 杀前检查已返回匹配行且 command line 含预期 user-data-dir ⇒ 直接杀，重新映射只会浪费一轮
- 空结果本身即目标（验证进程已死/清理已完成）⇒ 空 ps 是成功信号，不是'换解释再杀'的触发器
- 证据或用户已明确标注这些数字是 PID ⇒ 直接使用，不必改走端口映射
- 目标是非破坏性读取（如查询端口占用）⇒ 无需同等级硬门控
