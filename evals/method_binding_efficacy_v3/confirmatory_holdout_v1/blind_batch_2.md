# Blind batch 2/3

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. 0ed299452fe2

TASK

定时唤醒到点后没有生成新 run；系统快照显示 pending=0、runtime healthy、执行槽被单一前台任务占用。任务是转向系统级调度生命周期事件，定位触发到 run 交接层并制定不依赖共享授权的兜底。

METHOD CARD

name: deferred-action-failure-layer-scoped-lifecycle-trace
method_id: deferred-action-failure-layer-scoped-lifecycle-trace-ae4184904e2b
description: 当定时/延迟动作未按期执行时，先取系统快照（待办数、运行时健康、执行槽并发）判定失败层级；若待办为0且运行时健康但并发=1，失败锁定在'触发→run交接'层，其生命周期事件通常不归属于请求会话——应直接按系统/全局范围查触发时刻前后的调度生命周期事件（注册/触发/降级/通知去向），而不是在会话日志上反复加大窗口重查。定位为共享授权竞争且降级不重试后，用不依赖该授权的兜底（程序侧轮询/重试策略）而非原样重挂同一唤醒。

## Trigger
用户报告某个已注册的定时/延迟唤醒（schedule/wake/deferred job）没有执行，需要定位原因；环境中存在事件流或调度日志可查

## Discriminator
状态快照在扩散前已给出三个可判别事实：(1) pending_actions 全为0 → 唤醒确实未生成新run，症状成立；(2) 运行时健康、无程序故障 → 排除调度器未触发和运行时崩溃；(3) 执行槽 prompt/decode 并发=1 → 共享单授权，任何唤醒要与占用方竞争。另一次成功唤醒以系统级生命周期事件（delegated_ingress）入列，说明唤醒生命周期事件不归属请求会话、只在更大范围可见。这四点已把'一千种可能'缩到一个层级、一个查询范围。

## Short path
- 取系统状态快照，确认：待办=0（未成run）、运行时健康、无故障、并发=1 → 失败层级锁定在触发→run交接，且授权竞争为首要假设
- 按该层级事件的归因范围（系统/全局scope而非当前会话）拉取唤醒注册时刻至今的生命周期事件；若支持按sid或时间窗过滤则直接用
- 读事件链：注册成功→准点触发→降级为通知（reason=授权不可用）→通知仅被观测未注入run → 根因=单槽授权被其他会话占用且降级后不重试；同流中的busy_retry行可直接指认占用方
- 缓解：为依赖该授权的延迟动作配置不依赖授权的兜底（后台watcher轮询或释放后重试/退避），并确认兜底在授权再次不可用时仍能推进；不要原样重挂同一唤醒

## Stop conditions
- 生命周期事件链三证齐全（触发时间戳+降级原因+通知去向）且与快照中并发=1互相印证，根因有原文可溯，停止诊断
- 若快照显示待办>0、恢复积压或程序故障非空，失败层级不同，立即切换到对应证据源，不再沿授权竞争分支
- 若生命周期事件显示唤醒根本未注册成功或注册参数错误，转向注册参数核对，停止查交接层

## Verification
- 结论中每个环节（注册、触发、降级原因、通知去向）都有事件流原句支撑，时间戳单调合理
- 降级原因与快照中的单槽并发事实一致，占用方可从同一事件流指认
- 兜底机制验证为不依赖被竞争授权即可推进（如由程序侧轮询），且下一次授权被占时仍能续跑

## Counterexamples
- 唤醒实际执行了但结果错误：证据在会话run日志（会话scope），不应跳到系统范围查生命周期事件
- 快照显示多槽并发且授权空闲：授权竞争假设不成立，应查注册参数（时间/目标会话/消息）而非交接层
- 调度系统支持按sid精确过滤检索时，直接按sid查询即可，无需也不应按limit逐步加宽任何scope
- 快照显示recovery积压或program_faults非空：失败在恢复/故障层，先查故障记录，本方法不适用

## 2. 8b3c19b8db1b

TASK

服务发布回执给出 generation 与 git_head，验收项点名会话隔离和 SSE 行为。任务是沿该 commit 的改动文件选择针对性测试，并完成进程、入口与新启动日志验证。

METHOD CARD

name: derive-delivery-gates-from-repo-history-preverify-locally
method_id: derive-delivery-gates-from-repo-history-preverify-locally-0f4fbb2a1558
description: 向共享远端同步提交前，先从本地已可见证据推导交付契约：git log 中按变更路径配套的治理清单提交（A.5 submission manifest）与 PR-only 合并记录，说明 main 受保护、需 PR + 必需检查 + 变更路径清单精确覆盖。据此在推送前按已有清单归属分组提交、为每个 PR 生成恰好一份路径集合精确相等的 manifest，并用本地门禁脚本预验证，再走分支→PR→检查→合并；而不是直推被拒→开 PR→auto-merge 失败→A.5 检查失败后逐个救火。

## Trigger
需要把本地领先提交同步到共享/受保护远端分支，且初始状态读取（git log/status）或推送回执中已出现治理信号：PR-merge 提交、按变更路径配套的 submission manifest/清单类提交、或列出必需检查的保护提示。

## Discriminator
推送前第一次状态读取输出中已有多条 'add A.5 submission manifest for ...'、'A.5 提交清单' 类提交，且最近合并均为 'Merge pull request #NN'——当时即可断定该仓交付契约是 PR + 必需检查 + 每个变更路径被清单覆盖；忽略它会必然撞上直推被拒与 A.5 检查失败两道闸。

## Short path
- 初始状态读取时提取交付契约信号：PR-merge 提交、治理清单提交、remote 列表；形成假设：目标远端 main 受保护且变更需清单覆盖
- 用一次廉价调用确认门禁（gh api branches/main/protection 或看上一 PR 的 checks），不把直推 main 当探针
- 先完成内容提交（如 experiences 28 文件），再用 git diff --name-status -z 算出计划 PR 的精确变更路径集合
- 按已有 manifest 归属把提交分组（自带清单的提交独立成 PR）；为每个 PR 恰好一份新 manifest，路径集合与其 diff 精确相等、无 glob；格式不明时一次性读门禁脚本+schema
- 推送前在本地以与 CI 相同方式运行门禁脚本（check_architecture_submission.py 的 --staged 或 base...head 模式），确认无 'missing changed path' 再推分支开 PR
- gh pr checks 到绿后合并（auto-merge 不可用则等绿手动合并），fetch 后核对 ahead=0/behind=0

## Stop conditions
- 目标远端确认无分支保护且无门禁 workflow 在跑 → 直接推送即止，不造 manifest
- 历史中的清单流程已被停用（对应 workflow 缺失或 disabled）→ 以当前实际必需检查为准，不照抄旧契约
- 本地门禁对计划 diff 全绿、PR 全部必需检查通过并合并、本地与目标远端 ahead=0/behind=0 → 交付完成

## Verification
- 推送前本地运行与 CI 同参数的门禁脚本，确认 coverage 报告零缺失、且变更的 manifest 恰好一份
- PR 打开后 gh pr checks 直到全部必需检查通过；auto-merge 未启用时不重试而是等绿手动合并
- 合并后 git fetch 目标远端核对 ahead=0/behind=0，并抽查 manifest 路径数与 PR 变更路径数一致

## Counterexamples
- 个人仓或无保护远端（如 legacy origin、fork）：直推是正确路径，预造清单与查保护规则纯属浪费
- 历史中的治理清单属于已废弃流程（workflow 已删除或不再触发）：须先确认门禁真在运行，否则照抄旧契约会做无用功
- 只推一个不打算立即开 PR 的临时实验分支：PR 级门禁暂不适用，按分支自身 CI 处理即可

## 3. b247f0db2ef8

TASK

记录库查询返回 tool_timeout，而系统另有事件流与精确标识符检索入口。任务是把这次失败视为存在性零信息，改用窄查询和独立 provenance 通道确认决议是否保存。

METHOD CARD

name: documented-availability-limits-and-logs-before-config-archaeology
method_id: documented-availability-limits-and-logs-before-config-archaeology-ad25f7196c99
description: 诊断『功能不可用，是不是没设置对』类问题时，优先消费任务起点已有的窄证据：用户粘贴的官方文档明文限制、本地注册表/模型目录回执、异常日志中的错误码，再用一次带对照组的最小实时调用收尾；不要先对文件系统做宽枚举或逐文件配置考古。文档限制与日志签名一致即可闭合结论。实时探测时若对照组也失败，先怀疑探测凭据提取被污染（如 KEY= 行内联注释被一并取出），而非上游 key 失效。

## Trigger
用户报告某模型/功能『用不了，是不是没设置对』，且该功能可用性可能受服务端套餐/权限/灰度限制（订阅制 API 模型等），需要判定是本地配置问题还是服务端未放开。

## Discriminator
任务起点已可见：用户粘贴的官方文档明文写着『套餐当前暂未开放 GLM-5.3-FlashX』，且首个工具回执（模型目录）显示 flashx 已在本地注册。这两个事实当时就把『本地配置错误』假设空间压到很小，剩余未知量仅为本地失败签名是否等于文档所述权限错误（429/1311）。

## Short path
- 读用户提供的文档/公告，提取关于该功能可用性的明文限制；未知量：配置问题还是服务端限制
- 读本地模型注册表/目录一次，确认目标模型是否已注册（本集首个回执已给出：已注册）
- 用 search_records 查目标模型名+HTTP 码的异常日志，与文档限制比对（本集：429/1311 与文档一致）
- 如需实时确认，做一次凭据清洗后的最小调用，并附带一个已知可用模型作对照组
- 三方一致即停止，输出『配置正确、权限未放开』结论与可选路径

## Stop conditions
- 注册状态、日志错误码、文档声明三方一致，即可下结论，无需继续翻配置文件
- 实时探测中目标模型返回文档所述错误而对照模型返回 200

## Verification
- 结论须同时被注册表、日志、用户文档三个来源解释，不能只靠单一来源
- 实时探测必须含对照组；对照组也失败时先怀疑探测凭据被污染（如 .env 值行尾内联注释被 grep/cut 一并取出），清洗后重测再下结论

## Counterexamples
- 文档/公告无任何可用性限制且目标模型未注册：应优先排查本地配置（注册表 schema、env、base_url），不套用『权限未放开』
- 日志错误签名是 401/404/参数错误而非套餐权限类错误：沿该错误码排查，不预设套餐结论
- 目标是本地二进制/依赖缺失类问题，文档的可用性声明与失败机制无关
- 用户文档明显过期且与带时间戳的实测回执冲突：以实测回执为准，不盲信文档

## 4. 02ce9e50b318

TASK

守卫脚本的固定清单落后于权威契约测试，权威测试当前为绿。任务是删除复制的判定逻辑，改成 subprocess 委托权威测试并加入超时、runner 缺失和负向探针。

METHOD CARD

name: diagnose-known-failing-tests-via-node-scoped-max-tb-rerun
method_id: diagnose-known-failing-tests-via-node-scoped-max-tb-rerun-25ece289a3f8
description: 权威回执已列出精确失败节点后，诊断重跑必须按节点最小化并预选能穿透固定输出噪声的详细度。本集在拿到含精确 FAILED 节点的全量回执后，先做了文件级批量 + 低细节(--tb=short/line)重跑，回执被仓库固定 46 行 audit 告警块淹没并截断，断言正文不可见，被迫多次重复调用；直到改为单用例 --tb=long 才直接读到根因（精确环边、env 残留键名）。可程序化：解析回执 FAILED 行构造单节点命令；回执含固定噪声签名或截断且无断言行 → 立即升级单用例最大详细度，不做同粒度重试。

## Trigger
已有一份权威测试回执（精确 FAILED 节点 ID 在手），需要对各失败诊断根因；或上一条诊断回执被固定告警块/截断淹没、未含可读断言内容。

## Discriminator
knowledge-at-time：回执中已存在精确失败节点 ID（tests/unit/...::test_x）；随后诊断回执出现固定噪声块与截断标记，证明该输出通道下『文件级 + 低 traceback』的重跑不可能缩小『为何失败』这个未知量——当时即可预判应直接单节点 + 高详细度。

## Short path
- 从权威回执提取精确失败节点 ID 清单，不重跑全量、不按文件批量诊断
- 按失败模式分组，对每组构造单节点命令，并预置输出过滤或直接 --tb=long
- 回执若含固定噪声块/截断且无断言行 → 立即改单用例 --tb=long，不重复同粒度命令
- 根因可读后做最小修复，仅重跑该节点验证转绿
- 全部节点修复后跑一次全量收口，得到 0 failed 即停止

## Stop conditions
- 每个失败节点的断言/根因已从回执中直接可读
- 修复后对应节点单独重跑通过
- 最终全量回执 0 failed，与修复清单计数一致

## Verification
- 诊断命令的目标节点必须与回执 FAILED 行逐一对应（机械可核对）
- 每条诊断回执必须能指认出断言行；指认不出即视为无效调用并升级详细度，而不是原样重发
- 最终全量回执的 passed/failed 计数与所修节点数一致（本集 6 节点 + 1 处顺手发现的 ledger 项）

## Counterexamples
- 尚无权威失败清单时：先跑一次全量拿名单是正确第一步（本集首步即属此类，不因本方法跳过）
- 输出通道无固定噪声且低细节断言自解释（本集 resolved_episode 的一行断言即可定位泄漏串）：此时批量 --tb=line 更省，不必强行单节点 --tb=long
- 疑似测试间污染 / env 泄漏类失败，单节点隔离可能无法复现：需按文件/模块级重跑，但即便升粒度也应保持足够 traceback 详细度，方法只约束『范围升级』不约束『详细度降级』

## 5. b17dd9b7c582

TASK

本地分支准备同步到受保护共享仓库，git log 显示历史提交总伴随 submission manifest 与 PR merge。任务是推导交付契约、按路径分组生成清单并在推送前本地预验。

METHOD CARD

name: deploy-acceptance-follow-change-identity
method_id: deploy-acceptance-follow-change-identity-b334d83e67f1
description: 部署/重启验收时，若部署状态或回执已给出明确变更标识（git_head/commit/generation），功能层验收应沿该标识走：查看该 commit 改动的文件，运行覆盖这些文件的针对性测试；而不是先枚举 scripts/tests 目录找通用冒烟脚本（本次踩到烧 API 配额的无关回归脚本、又陷进无凭据的登录死路，共浪费 3~4 次探测后才转向）。运维面（进程/端口/入口/回执）照常逐项验证；日志以最后一次 startup 标记为界只扫新段，旧错误按行号归因旧进程。凭据不可得的端到端项明确声明为验证缺口并停止，不再继续找替代脚本。

## Trigger
用户要求对一次发布/重启做验收，且第一个工具结果（部署状态/回执）中已出现变更标识（git_head、generation、commit、版本号），同时验收清单点名了具体被修复的行为或子系统（如会话隔离、SSE 不中断）

## Discriminator
变更身份早已在手：第一次工具调用即返回 git_head=696f97268 + generation=29，且验收项点名具体子系统。这两点当时已把『如何做功能验证』收窄为『看该 commit 改了哪些文件 → 跑覆盖这些文件的测试』，无需泛搜通用 e2e 脚本

## Short path
- 读部署状态：确认 generation/git_head 与发布期望一致，记下变更标识（未知量：这次部署到底改了什么）
- ps 过滤出本次新起进程 PID；lsof 只按该 PID 查监听端口，不做全端口宽列（未知量：新进程是否健康、web 端口是哪个）
- curl -sL 跟随重定向探入口（未知量：WebUI 是否可达，303→login→200）
- 按当前时间窗 grep 重启回执：三服务 rc=0、时间晚于发布点（未知量：重启是否全部成功；早于发布的失败回执直接归因历史）
- 定位日志中最后一次 startup-complete 行号，只扫其后新段（未知量：新进程是否零错误；ref collision/shutdown 异常按行号归因旧进程）
- lsof -p 桥进程查上游 ESTABLISHED（未知量：桥是否真活着，stdout 缓冲不可信）
- 由变更标识列出改动文件，运行覆盖这些文件的针对性测试作为功能证据；无登录凭据的浏览器端到端项明确列为缺口并停止找替代脚本

## Stop conditions
- 部署标识=发布期望、新进程健康、入口可达、回执全 rc=0、最后启动标记之后的日志段零错误、改动文件的覆盖测试全过
- 遇到必须有凭据/真实账号才能闭环的端到端项（如浏览器登录）→ 声明验证缺口并停止，不再枚举脚本目录找替代路径

## Verification
- 回执 git_head、部署状态 git_head、发布期望三方一致
- 日志中发现的错误行号均早于最后一次启动标记（归因旧进程而非新进程）
- 实际运行的测试选择器与该 commit 改动文件集有交集（测试确实覆盖被改子系统）

## Counterexamples
- 部署状态不含变更标识（无 git_head/版本），或真实改动未提交、不在这个 commit 里 → 变更身份路线失效，通用冒烟脚本或黑盒探测才合理
- 验收纯属运维面（进程在、端口听、HTTP 200）→ 做代码级测试考古是浪费
- 仓库有强制性的标准验收门脚本（不论改动都必须跑）→ 直接跑它，不必做改动映射
- 改动文件没有任何覆盖测试 → 该路线断裂，退回端到端/手工探针

## 6. 967c9b31fbed

TASK

结构化工具回执把 artifact_missing 指向调用方提供的 code_root；按回执处方执行后同一错误逐字复现。任务是对照权威 status 与路径存在性，确定规范 root 的真实来源并纠正输入。

METHOD CARD

name: failure-receipt-is-zero-info-not-absence
method_id: failure-receipt-is-zero-info-not-absence-20ac7bad5b0a
description: 检索回执分两类：成功+零命中（存在性的弱否定证据）与失败/超时（对存在性零信息）。本集曾把记录库查询超时当查空，得出『决议从未进入保存通道』的错误断言；架构 exception_log 确认是 tool_timeout，改用精确标识符窄查询+事件流交叉后全部捞回。方法：下『未记录/未发生』结论前必须持有 success 零命中回执并交叉独立 provenance 通道；失败回执只触发『查故障状态→窄查询重试→换通道』，不触发否定结论。检索工具不可用时停止伪装调用，直接汇报已验证事实。

## Trigger
检索/查询类工具回执为超时或执行错误（如 tool_timeout、异常、故障），而下一步倾向于得出『内容未记录/从未保存/不存在』这类否定存在结论；尤其当系统设计上承诺记录（core loop 含『记住』阶段、存在事件流/declaration/provenance 层）使『未记录』成为需要强证据的低先验假设时。

## Discriminator
回执状态字段本身可直接观察：『[success] 未找到匹配』（查询已执行、真零命中）与『[执行超时] / error_type=tool_timeout』（查询未完成、对存在性无信息）是两种性质不同的证据；且架构状态/异常日志通道当时即可查到失败类型。这个分类在收到回执当刻就能完成，不需要任何事后信息。

## Short path
- 收到检索回执先分类：success+命中 / success+零命中 / failure(超时/错误)。若是 failure，标记『对存在性零信息』，禁止在其上建筑『没记录』结论。
- 查架构状态/异常日志通道确认失败类型（如 tool_timeout），把未知量从『有没有记录』缩为『该查询是否根本没执行』。
- 用精确标识符（具体编号、时间戳、文档名）做窄查询重试，避开导致超时的宽查询词组合。
- 窄查询仍 miss 时交叉独立 provenance 通道（事件流 declaration_check、action_trace 中的写入动作）获取同一事实。
- 只有 success 零命中 + 独立通道同样无记录，才向用户（当事人）求助或提出『未记录』假设；若可用工具集已不含检索类工具，停止把检索意图塞进控制类工具字段，直接汇报已验证事实。

## Stop conditions
- 权威来源（记录库 success 命中或事件流 declaration/trace 条目）已给出所需事实且相互印证——停止检索，直接汇报。
- 检索类工具持续失败或不可用——停止重试与伪装调用（勿往 convergence/控制类工具的声明字段里塞待办检索），向用户呈交已验证事实并请其补缺。
- 用户本人是事实当事人且仅缺少量具体值——直接问用户，不再枚举检索路径。

## Verification
- 每条『已验证』事实都能指回一条 success 回执（记录库命中条目或事件流 declaration_check/action_trace）。
- 最终结论中不依赖任何 failure 回执作为存在性证据；否定存在断言必须由 success 零命中 + 至少一个独立 provenance 通道同样无记录支撑。
- 重试后的窄查询与原失败查询指向同一目标事实（标识符一致），确认是重试而非换了问题。

## Counterexamples
- 回执是『[success] 未找到匹配』（真零命中）且系统无独立 provenance 通道时，『未记录/不存在』假设可直接进入下一步，无需先查故障日志或交叉通道。
- 目标系统没有记录承诺、也没有事件流（如查询纯外部网站/第三方 API），超时后的正确动作是换数据源、降级或放弃，而非交叉内部通道或反复窄查。
- 查询有副作用或重试代价高（写操作、付费接口、破坏性探测）时，不应机械窄查重试，应改走降级路径或直接求助。

## 7. ec044b3fddcf

TASK

重构把原先内联 query.lower() 替换成共享 helper，diff 显示新 helper 保留了其他逻辑。任务是在接线前用大小写对照探针验证归一化语义等价，再决定是否继续重构。

METHOD CARD

name: diff-normalization-parity-probe-before-wiring
method_id: diff-normalization-parity-probe-before-wiring-13850e612a58
description: 重构把既有内联归一化（如 q = query.lower()）替换为共享 helper 时，编辑回执 diff 里被删除的归一化行就是最强判别事实：若新实现未等价恢复（本例 _query_terms 漏 .lower() 而 hay 侧仍 .lower()），含大写的查询（EVO-…/DC-1）会结构性落空；回归失败后又易与外部事件（merge 吞改动）混淆归因。方法：写入时逐行核对被删预处理是否有等价替代，用跨大小写最小探针验证 helper 语义后再接入多调用面；确定性单测失败先自查最近 diff 与文件 sha/快照一致性，最后才归因环境。附带：全仓搜私有下划线名只会命中 evals 归档副本，找测试应搜公共入口符号。

## Trigger
用 helper/重构替换既有内联归一化或匹配语义（lower/strip/decode 等），或：编辑后确定性本地单测失败，且同时存在自身改动与环境事件多个候选归因。

## Discriminator
编辑回执 diff 本身：被删除的归一化行（q = query.lower()）与新增实现是否等价。本例 _query_terms 的 docstring 承诺“小写化”但函数体无 .lower()，而 hay 仍以 .lower() 构建——这一不对称在写入回执时即已可见，无需等回归测试暴露，也不依赖事后才知道的答案。

## Short path
- 改前先跑基线测试，记录通过数作为对照。
- 写入 helper 时逐行对照 diff：每处被删除的预处理/归一化必须在新路径有等价替代，不一致就地修复（如补回 .lower()）。
- 用一个跨大小写最小探针验证 helper 语义（如 _hay_matches('evo-1', _query_terms('EVO-1')) 应为 True），通过后才接入其余调用面。
- 统一接入后回归 + 一个含大写真实标识（如 EVO-…）的端到端查询各一次。
- 若回归失败：先核最近 diff 的归一化对称性，再核文件 sha/快照与预期一致（排除外部事件吞改动），最后才考虑环境归因。
- 定位测试覆盖面时在 tests 目录搜公共入口符号（如 RecordSearcher），跳过 evals/*/results/runtime-* 下的归档源码副本。

## Stop conditions
- 跨大小写探针通过且回归结果与基线逐项一致（含大写 id 查询能命中），即停止诊断，不再枚举其他归因假设。
- 失败被定位为单一可复现因素、修复并验证一次后即停，不重复确认。

## Verification
- 回归测试与改前基线完全一致（本例 44/44）。
- 真实数据端到端：按含大写的真实记录 id 查询能命中。
- git diff 中不存在“docstring/注释承诺归一化但实现缺失”的不对称。

## Counterexamples
- 旧代码本无任何归一化（查询侧与 hay 均原样比较）时无不对称可查，直接跑回归即可，探针无增益。
- 失败测试位于未改动模块且标记为环境敏感/非确定性（网络、顺序依赖）时，应先隔离环境因素，自查 diff 收益低。
- helper 为纯结构拆分、两侧共用同一归一化路径（无语义契约变化）时，无需归一化对等检查。
- 写入回执的“复读一致”只证明字节正确，不能替代归一化语义探针。

## 8. 8f79095a3cd2

TASK

仓库守卫脚本报红，而同一契约的权威单元测试通过；失败项对应守卫脚本内的旧路径常量。任务是把复制的契约检查改成委托权威测试，并用负向探针验证委托有效。

METHOD CARD

name: failing-test-red-triage-by-failure-signature
method_id: failing-test-red-triage-by-failure-signature-86ac002c4e46
description: When a repo has multiple failing tests, first run the failing tests to capture exact assertion/validation signatures, then follow each signature to the test, implementation/contract, and recent commits. Classify each red as environment, code regression, or fixture/contract drift before broad search or fixes.

## Trigger
A task asks to diagnose several failing tests or test-suite reds, especially guard/contract tests, and the cause is unknown.

## Discriminator
The fastest narrowing fact is the actual failure output: assertion text, validation message, or guard ID that points to a specific contract or fixture mismatch.

## Short path
- Confirm repo/branch/HEAD and working-tree cleanliness.
- Run the failing tests with the repo's interpreter and capture exact failure signatures.
- Use each failure signature to target the relevant test node, implementation, or contract file.
- Inspect recent commits touching that contract to identify whether implementation changed or fixture did not.
- Classify each red as environment, regression, or fixture/contract drift and propose a minimal aligned fix.

## Stop conditions
- Each failing test has an authoritative failure signature and a mapped contract/fixture cause.
- The distinction between environment and code/fixture drift is established.
- A minimal fix direction is identified without editing governance-sensitive files unless authorized.

## Verification
- Re-run the failing tests after the proposed fix or check that the failure signature matches the identified contract change.
- Confirm the fix does not raise guard baselines or weaken contracts merely to make tests pass.
- Check git status/diff to ensure only intended files are touched.

## Counterexamples
- A single test fails due to missing dependency, network, or interpreter mismatch; first repair environment before contract analysis.
- Tests are intentionally flaky or timing-dependent; failure signatures do not map to a stable contract.
- The task is to add tests for new behavior, not diagnose existing reds.
