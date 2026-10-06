# Subject-Binding v3 confirmatory holdout blind sheet

Judge whether the Method card is applicable to the task. Return APPLY or SKIP and one concise Chinese reason comparing task purpose with Method purpose.

## 1. a29bdd646e62

TASK

一份 lesson 声称某隐藏状态导致工具失败，并给出清除该状态的修复办法。任务是原样复现，再只叠加该修复项，结合独立工具对照判断这条机制归因是否成立。

METHOD CARD

name: denial-signature-records-first
method_id: denial-signature-records-first-b749e7b81591
description: 当命令以环境级写拒绝签名失败（自有路径上 open-for-write 统一 EPERM，多个不同命令同点失败），且用户把故障归因于近期状态变化（如'重启禁用了你的工具'）时：先做两件窄检查——(1) 用被怪子系统自己的状态回执（admission/exception 记录）证实或证伪用户归因；(2) 用拒绝签名查询本环境沉淀的记录（experience store / docs / known-issues）。若命中 verified 记录，直接采用其规定的人机分工（如 staging+runbook：agent 出定向操作手册、用户在自己的终端通道执行）并停止；只有未命中才展开'谁施加了该边界'的全新 RCA，且止于解释与移交，绝不自行放宽安全边界。

## Trigger
工具/命令失败，且失败签名是按操作类或路径类一致的环境拒绝（如 EPERM 'Operation not permitted' 落在账户自有路径的写操作上，多个不同命令在同一写点失败）；同时用户提出一个把故障归因于近期事件（重启/变更/开关）的因果理论

## Discriminator
回执级事实：失败点是对锁文件的 open-for-write EPERM 而非命令特异错误（stop 与 restart 死在同一处 mutation lock 写），说明是写类/路径类环境边界而非'某工具被禁'；随后被怪子系统自己的回执显示 admission/exception 均为空——当场即可证伪用户归因，并把候选空间从'任何可能禁用工具的机制'缩为'已知环境写边界，查有没有既有记录'

## Short path
- 执行用户指定的动作一次，抓取精确失败签名（errno 落在哪个操作/路径上）——解决未知量：失败是命令特异还是类级写拒绝
- 用被怪子系统自己的状态回执（admission/exception/pending）做一次归因检验——解决未知量：用户的因果理论是否成立
- 以拒绝签名（errno + 操作类 + 路径类）为关键词查询环境沉淀记录（experience store / docs / known-issues）——解决未知量：该边界是否已知且有既定应对模式
- 若命中 verified 记录：按其规定的分工输出定向 runbook（命令与回执中的失败路径/命令一一对应），交用户在自己的通道执行，并给出修正后的因果解释，停止
- 若未命中：才展开全新 RCA（边界施加者、配置来源、历史变更），且止于解释与移交，不自行改动安全边界

## Stop conditions
- 已用被怪子系统的回裁判定用户归因不成立，且一条 verified 记录解释了拒绝签名并给出可执行的人机分工
- 交付的 runbook 命令与回执中的确切失败路径/命令一一对应，用户侧可一次执行完成原目标

## Verification
- 确认拒绝是类级而非单次抖动：至少 2 个不同命令在同一路径类的写操作上以同一签名失败
- 引用的记录为 verified/active 状态，而非过时假设或未验证推测
- runbook 中的命令指向回执里的确切路径与命令，而不是泛化建议
- 被怪子系统的回执确无任何禁用/异常条目，归因证伪成立

## Counterexamples
- EACCES 源于真实权限位（如误 chown 给 root）：应修所有权而非套 runbook，EPERM 沙箱类记录会误导
- 失败是暂态锁竞争（BlockingIOError、锁超时、挂起进程持锁）：应查进程与锁状态，而不是查边界记录
- 环境中不存在 experience/docs/known-issues 记录库：短路不可用，全新 RCA 就是正路
- 被怪子系统回执确有 admission barrier 或异常记录：用户归因成立，应调查该子系统本身而非环境写边界

## 2. 9cd6e254d095

TASK

研究任务中的一个来源连续返回 403，UA 轮换和备用抓取后端也得到相同结果；首轮候选列表还有多个未读同主题来源。任务是换到下一未读来源继续满足信息需求。

METHOD CARD

name: deterministic-404-is-an-answer-pivot-to-canonical-candidate
method_id: deterministic-404-is-an-answer-pivot-to-canonical-candidate-daaa7d2b6d35
description: 核实'具名资源'类说法（GitHub org/仓库、URL、包名）时，对说法给出的标识符探测返回确定性 404 后，不要把它当访问故障做换 UA/多轮回退重试；把 404 记为'该标识符不存在'的一次性反证并冻结该分支，立即转向同轮搜索里已出现的平台规范候选（描述精确匹配的仓库/端点），再沿其自带 provenance 边（官方站点、给 AI 的聚合文档、api.github.com 等权威元数据端点）补齐其余待核事实。搜索空间从'猜测 URL 怎么抓通'收缩为'一个已命名的规范候选是否坐实其余说法'。

## Trigger
事实核查/验证任务中：说法包含具体标识符（如文章声称的 GitHub org/仓库名），对该标识符的抓取返回确定性 HTTP 404；或首轮定向搜索已返回与实体描述精确匹配的平台规范候选，而尚未探测该候选。

## Discriminator
当时已可见的两条事实：① 抓取回执明确是 HTTP 404（'资源不存在'的确定性状态），不是 timeout/403/429/5xx 等瞬态或访问层错误——换 UA、curl 回退都不可能改变存在性判定；② 同轮搜索结果第 1 条已给出平台规范标识符及与目标实体完全吻合的官方描述（HiThink-Tech/Financial-API：'同花顺官方 A股金融数据服…'），窄下一跳在 404 之前就已在手。

## Short path
- 对说法中的具名标识符做一次抓取以取得存在性反证（只做一次，不做 UA/重试变体）
- 收到确定性 404 → 直接记为'该标识符不存在'的证据，冻结这条猜测分支
- 转向搜索结果中的规范候选，抓其本体 README 与权威元数据端点（如 api.github.com/repos/...），一次性取得创建时间、stars、license、活跃度
- 沿候选自带的 provenance 边补齐其余事实：README 里的官网链接、站点给 AI 的 llms.txt/快速接入文档
- 逐条对照原说法，标记为 已证实/需修正/未验证 三态，停止

## Stop conditions
- 说法中每个可核事实都已映射到权威来源，或已显式标记为'未验证'，无新增未知量
- 具名标识符的存在性已由确定性状态码判定并记录，规范候选已由平台元数据/官方文档证实

## Verification
- 最终报告同时引用两类证据：404 回执（用于修正'标识符'说法）与规范候选的原文/元数据（用于证实其余说法）
- 报告区分 已验证/需修正/未验证 三态，未清点的项目（如端点/工具总数）显式标注，不默认当作已证实
- 检查对同一确定性 404 目标没有发出第二次带参数变体的重试

## Counterexamples
- 返回 403/429/5xx/timeout：这些可能是 UA 拦截、限流或瞬态故障，轮换与重试是合理的，本方法不适用
- 搜索结果中没有与实体描述匹配的规范候选：404 只说明'说法暂未证实'，此时才需要扩大发现（平台内搜 org/用户、站内搜索），而非立即下结论
- 目标站点对爬虫返回伪装 404（反爬 cloaking），而搜索快照强表明页面存在：应换权威替代端点（API、缓存、镜像）再判定，不能直接判'不存在'

## 3. 2011313157cd

TASK

PR checks 已显示一个具名 gate FAILURE 并给出 run/job ID。任务是只读取该检查的失败步骤输出，提取 gate 自身的错误行与违规清单，确定下一跳诊断对象。

METHOD CARD

name: failed-ci-gate-diagnose-from-local-gate-script-repro
method_id: failed-ci-gate-diagnose-from-local-gate-script-repro-04eed411f3de
description: CI 门禁失败阻塞合并/部署时，不要反复翻整段 run 日志（多为 runner/setup 样板）。先只取失败步骤专属日志段；失败步骤的命令通常已点名一个仓库内门禁脚本及其 --base/--head 入参——把该脚本当作失败的权威定义：读脚本与所需工件目录（既有清单即模板），用 CI 同样的 base/head SHA 在本地复现门禁（若 CI base 与本地 parent 不一致，先 fetch 再算真实差分），本地迭代到 PASS 后再推送一次，重跑全绿才合并/部署。

## Trigger
PR 上某项 status check 为 FAILURE 且阻塞合并/部署（如用户约定"没问题才部署"），且 run 元数据/日志中可见失败步骤实际执行的命令。

## Discriminator
首次查看失败 run 时已可见：失败步骤运行的是仓库本地脚本（带显式 --base/--head 参数），且检查名自述为机械 presence/coverage 类检查——失败定义就在仓库内、可本地复现；而普通 gh run view 输出多为 runner/setup 样板，继续翻页不会缩小任何未知量。同时可见 CI 的 base SHA 与分支 parent 不一致（main 已前移），真实差分需重新计算。

## Short path
- 多 remote worktree 下 gh 命令显式带 --repo（必要时先 git remote -v 消歧），查看 PR 状态，定位失败 check 及其 run/job 链接。
- 只取失败步骤日志段（gh run view --log-failed 或按 job 取 log），拿到精确失败信息；未知量：到底违反了什么。
- 失败步骤命令已点名仓库内门禁脚本及入参 → 本地读该脚本 + 其所需工件目录（既有清单即格式模板）；未知量：权威要求与样例。
- 用 CI 同样的 base/head SHA 本地复现门禁（CI base ≠ 本地 parent 时先 fetch main 再算真实差分），迭代修复到本地 PASS。
- 推送一次并等待重跑；所有必需 check 全绿后才合并/部署。

## Stop conditions
- 用失败步骤同款脚本、同款参数在同一 base..head 区间本地跑出 PASS。
- 失败为瞬态基础设施问题（报错指向 runner/网络而非策略违规）——直接重跑而非改代码。
- 失败步骤无仓库内定义（外部 SaaS/托管检查）——停止本地复现，只依赖 annotations/厂商文档。

## Verification
- 本地复现使用的脚本路径与 --base/--head SHA 与失败 CI 步骤中显示的完全一致。
- 推送后 CI 重跑中原失败 check 变 SUCCESS，且其余必需 check 全绿，才执行合并/部署。
- 补交的工件精确满足门禁的"恰好数量/分区"要求，无缺失或多余条目。

## Counterexamples
- 失败 check 是外部服务（SaaS 安全扫描、托管 API），无仓库内脚本可读可复现——只能用 annotations 和厂商文档。
- 失败信息本身已完整列出可操作错误（如缺失文件的精确清单）——直接修复即可，再读门禁源码属多余动作。
- 瞬态 infra 失败（runner OOM/网络超时）——本地复现会假绿，须先由报错文本区分策略失败与 infra 失败。
- CI workflow 检出的门禁脚本版本与本地 checkout 不同（不同 ref/pin）——本地结果与 CI 背离，须先核对 workflow 实际检出的脚本版本。

## 4. dbba385a2299

TASK

服务重启后 status 给出新的 live PID，而先前记忆中的端口属于旧进程。任务是从新 PID 读取实际监听端点，再执行一次 canary 探针。

METHOD CARD

name: derive-endpoint-from-live-pid-before-probe
method_id: derive-endpoint-from-live-pid-before-probe-64db93a2fd0f
description: After a restart replaces service processes, remembered endpoint literals (ports/hosts) are unverified against the new runtime. Before a canary/health probe, derive the actual bind endpoint from the live pid the status receipt already provides (e.g., lsof filtered by pid), then probe once. If a probe fails with a definitive refusal signature (connection refused, HTTP 000, exit code 7), read it as 'no listener on that port' and resolve the real listener from the live pid rather than retrying or broad-scanning. Turns a stale-literal failed probe into a deterministic pre-probe check.

## Trigger
A post-restart/deploy acceptance check requires probing a service endpoint (health/canary), and the port/host is taken from memory, a prior session, or pre-restart config, while a current authoritative status receipt already provides the live process identity (fresh pid, started_at) of that same service.

## Discriminator
Two knowledge-at-time facts: (1) before any probe, the receipt already showed newly started processes (web pid 18241 at 13:39) — the runtime was replaced, so any port remembered from before the restart is unverified, and the live pid is an authoritative handle from which the actual LISTEN address:port can be read in one command; (2) after the failed probe, curl exit code 7 / HTTP 000 is connection refused — definitively 'no listener on that port', not an auth, timeout, or transient issue.

## Short path
- Read the restart/status receipt → unknown: did the deploy reach desired generation and are target processes alive? Output: live pids + started_at proving the runtime was replaced at 13:39–13:40.
- Resolve unknown 'which address:port is the service actually bound to' directly from the live pid (lsof/netstat filtered by pid) instead of assuming the remembered port (8787).
- Probe the derived endpoint once; expected status (401 unauthenticated) confirms both aliveness and auth enforcement.
- If a probe already failed with exit 7 / HTTP 000, treat it as 'no listener on that port' and jump straight to step 2 — do not retry, swap hosts, or scan broadly.
- Stop when every checklist item is verified against receipt or live process state; explicitly report the corrected literal (8903 vs 8787) so stale memory is overwritten.

## Stop conditions
- Endpoint was derived from live process state and a single probe returned the expected status code with normal latency
- All acceptance checklist items are verified from authoritative receipts or live state, with any stale-literal corrections disclosed
- No further probing after the checklist is fully green (avoid post-sufficiency actions)

## Verification
- lsof on the live pid shows the LISTEN port actually held by the current process generation
- curl against the derived port returns the expected code quickly (here 401 in milliseconds), consistent with service alive + auth enforced
- Cross-check: the failed port has no listener among the new pids, confirming the remembered literal was stale rather than the service being down

## Counterexamples
- The status receipt itself exposes the bound port as an authoritative field — use that value directly; an extra lsof is redundant overhead.
- Probe fails with a timeout rather than connection refused — the unknown is network/firewall reachability, so local lsof on the server pid will not resolve it.
- The service runs in a different host/container namespace; local lsof on the pid does not reflect the client-reachable endpoint — service discovery/DNS is the right source.
- The receipt proves config unchanged across the restart (same config hash/generation settings) — probing the known port directly is acceptable and cheaper.

## 5. 61fe8a082e6c

TASK

失败步骤日志已经显示仓库内 gate 脚本及其 --base/--head 参数，错误指向 submission manifest 覆盖。任务是读取该脚本与样例，在本地用 CI 相同差分复现并迭代到 PASS。

METHOD CARD

name: failure-scoped-ci-log-triage
method_id: failure-scoped-ci-log-triage-f602c22331b4
description: 当 PR/status 查询已按名称定位某个 FAILURE 检查时，下一步只取该检查的失败输出（如 --log-failed / 按 '##[error]'、FAIL 过滤），而不是拉全量 run 日志逐段翻。若日志开头是 runner 版本/镜像等 provisioning 样板，这是"查询未命中失败内容"的信号，应立即收窄查询范围，而非以近似参数重发同一宽查询。一次定向调用即可拿到门禁自身的失败消息（规则名+违规清单），再与 PR 列表中的栈式关系交叉定位根因（如基线错位），避免多次无信息样板日志往返。

## Trigger
CI/PR 状态查询（如 gh pr view --json checks）已返回按名称标记为 conclusion=FAILURE 的检查，且带有 run/job id 或 detailsUrl，需要定位失败根因。

## Discriminator
两个当时已知的事实：(1) 失败检查的名称、conclusion=FAILURE 及其 run/job id 已出现在 PR view JSON 中——未知量已收窄为"这一个检查输出了什么错误行"；(2) 日志输出以 'Current runner version'/'Runner Image Provisioner' 等开头 ⇒ 当前查询拿到的是无信号样板，是重定范围的信号而非重试信号。

## Short path
- gh pr list（+目标/goal 状态）确定开放 PR 集合与栈式关系（如 slice4→slice5、两者 base=main）
- gh pr view <PR> --json checks,mergeable,state：按名称锁定唯一 FAILURE 检查与其 run/job id
- 一次失败范围调用：gh run view <run> --log-failed（或 job 日志管道 grep '##[error]|FAIL'），直接读门禁自身消息
- 若返回仅 runner 样板：立即换 --log-failed/--job 定向，不再重发同形宽查询
- 用失败消息中的违规清单交叉 PR 列表事实（父 PR 绿且各含单 manifest）推断基线错位→给出机械修复顺序：合并父 PR→update-branch→重跑→合并

## Stop conditions
- 已取得失败检查自身输出的错误行（含具体规则与违规项清单），足以归因
- 确认失败为 transient/基础设施问题（失败步骤无门禁消息）→ 转重跑或全量日志，本方法停止
- PR view 已内联展示失败原因，无需任何日志调用

## Verification
- 提取的失败消息能命名具体规则（如 'expected exactly one X'）并列出违规文件，且清单项可归属到某个开放 PR 的变更集
- 据此给出的修复不改动内容：仅合并父 PR + 更新分支基线后，原 FAILURE 检查应转绿

## Counterexamples
- 失败是 runner OOM/网络超时等 transient：失败步骤日志无门禁消息，收窄查询无实质内容，应重跑而非继续过滤
- PR 状态中已内联给出失败摘要（外部 required check 的 description），再取日志是多余动作
- 外部系统报告的 required check 没有可访问的日志 URL：gh run 日志不可用，必须去外部系统查询

## 6. 31dd5901d37c

TASK

用户用一个平台俗称询问外部来源的更新是否已经并入当前运行版本。任务是枚举 remotes，比较 main 与各 remote/main 的提交集合，并结合进程 HEAD 给出生效结论。

METHOD CARD

name: external-update-merge-status-via-remote-setdiff-not-label-search
method_id: external-update-merge-status-via-remote-setdiff-not-label-search-36ab77644027
description: 用户问"某外部来源的更新(常为俗称,如开发平台名)是否已并入并生效"时,不要在分支名/提交信息/记录/文档里做标签文本搜索——俗称常与仓库对象名不匹配,全部 miss 也推不出任何结论。应把问题重述为拓扑问题:"运行时 HEAD 是否包含各远端/分支的提交"。枚举 remotes,对每个 remote 计算 main..remote/main 集合差,用 patch-id/cherry 排除"换形态已并入",结合进程 HEAD 与 FETCH_HEAD 新鲜度给出生效结论;仅当多个未并入批次造成歧义时才回问用户要 PR/分支号。

## Trigger
用户用非仓库对象名的俗称询问"某来源的更新有没有并进来/生效",且运行环境是 git 管理的部署(仓库路径或语境表明是 mirror,存在多个 remote)

## Discriminator
进入宽搜索前已知三条事实:pwd 显示仓库路径含 '-mirror'(外部更新经 remote refs 到达);用户问句用"并进来"这一 merge 语汇;进程状态工具按 git HEAD 报告运行版本——合并状态是可达性/集合差问题,与标签能否文本匹配无关。标签在分支/记录/文档里搜不到 ≠ 答案不可知,只说明该名称是俗称

## Short path
- 1. 用部署/进程状态核"重启生效":各服务 pid、started_at、git_head、generation 匹配、无 admission barrier
- 2. git status --porcelain 把 dirty 告警分类为 tracked 修改 vs 纯 untracked,确认"进程代码=HEAD"是否成立
- 3. 由 mirror 事实导出下一跳:git remote -v 枚举外部来源;对每个 remote 执行 git log --oneline main..<remote>/main;查 FETCH_HEAD 时间评估 refs 新鲜度
- 4. 对差集里每个提交做 git cherry / patch-id 等价性检查,排除"以别的形态已并入本地"
- 5. 恰好一个未并入批次 → 报告其内容摘要与"未并入未生效"结论并回问用户确认俗称所指;差集为空且 refs 新鲜 → 报告外部更新均已并入
- 6. 可选:对新 HEAD 引入的特性跑聚焦测试回答"有没有问题",然后停止

## Stop conditions
- 所有 remote 差集为空且 FETCH_HEAD 新鲜 → 断言外部更新均已并入并停止
- 唯一未并入批次经 patch-id 证实本地无等价形态 → 给出"未并入未生效"结论并停止,等用户确认后再执行合并
- refs 陈旧且网络 fetch 失败 → 结论必须附新鲜度 caveat,不得把"本地看不到"当作"上游没有"
- 多个未并入批次无法唯一归因于俗称 → 停止枚举,回问用户要 PR 号/分支名

## Verification
- 确认运行中各服务的 git_head 等于本地 main tip(部署与源码一致)
- 确认未并入提交在本地 main 无 patch-id 等价物(git cherry 双向核)
- 确认 dirty 告警已分类:tracked 零修改才可声明"代码=HEAD"
- 确认新特性聚焦测试全绿作为功能级生效证据

## Counterexamples
- 更新不经 git 交付(热改文件/镜像 tag/制品投递)——拓扑差集看不见,应改对比部署清单或制品哈希
- 仓库无 remote 或单仓单源——问题退化为 log 检查,remote 枚举步骤多余
- 用户俗称恰好就是真实分支/remote 名——直接单条 diff 即可,无需歧义分支处理
- remote refs 严重陈旧且网络不可用——差集为空也可能是假阴性,必须先修复新鲜度再下"无未并入"结论
- 运行环境非 git 管理(工作区含 tracked 未提交热改)——HEAD 可达性不代表运行代码,须先核 working tree

## 7. d783e2c5e7ff

TASK

守卫脚本因复制的旧路径清单报红，而权威契约测试通过。任务是把守卫改为调用权威测试并透传退出码，增加 runner 缺失、超时和负向探针验证。

METHOD CARD

name: false-red-guard-delegate-to-truth-source
method_id: false-red-guard-delegate-to-truth-source-e38f5294fa10
description: 当守卫/校验脚本因复制了别处权威测试所拥有的契约而假红（脚本红、真相源测试绿、失败项恰为脚本内钉死的字面量/旧路径）时，不要逐字修补复制品（那只会等下一次漂移再红一次），而是把该项检查改为 subprocess 委托权威测试并透传退出码；配 runner 缺失显式 fail-closed 与超时守卫，再用负向探针（临时副本破坏一处契约→脚本必须变红）证明委托非空洞，回归受影响测试后提交并在 detached HEAD 上钉引用。

## Trigger
守卫/CI/verify 脚本非零退出报同步失败，而同一契约的权威单元测试在相同环境下通过；或脚本被发现硬编码了某份已由专门测试维护的契约副本（固定编号清单、已迁移路径、关键词表）

## Discriminator
修前取证三件套：(a) 脚本 exit=1 且失败行全部指向脚本自身硬编码常量（固定规则编号、旧文件路径）；(b) 权威契约测试 exit=0 全绿；(c) 脚本 docstring 甚至自称"复用该测试逻辑"而实现实为复制。三者合证：红来自复制品过期，而非仓库真实漂移——这把修法空间从"继续逐字更新钉死清单"缩为"消除复制、委托单一真相源"

## Short path
- 先跑守卫脚本逐行记录失败文本，并在同一环境跑权威契约测试；未知量：红是脚本过期还是真漂移
- 若测试绿且失败项恰为脚本内钉死字面量/路径→判定假红=契约复制体过期，选委托方案而非改字面量
- 把该项检查改为 subprocess 委托权威测试并透传退出码；runner 缺失→显式非零 fail-closed，加超时守卫
- 当前树复跑脚本必须绿
- 负向探针：临时完整副本中破坏一处契约标记→脚本必须 exit≠0 且报委托来源，随后清理副本；未知量：委托是否变成永远绿
- 回归可能引用脚本内部的兄弟测试；detached HEAD 提交后钉分支引用防 GC

## Stop conditions
- 脚本当前树绿 且 负向探针能使其变红 且 兄弟测试无回归，即闭环停止
- 权威测试本身红→停止改脚本，先修真实漂移
- 脚本红源于运行环境（无 venv/pytest 缺失）而非契约→修调用环境与 fail-closed 语义，不改契约判断

## Verification
- 保留修前红的原始输出作为假红存在性证据
- 真相源测试与脚本在同一运行环境（同解释器/venv）验证绿
- 变异探针：破坏契约任一标记，脚本退出码必须非零并指向委托的测试
- 引用脚本内部行为的测试文件全部通过；语法编译与安全扫描过

## Counterexamples
- 不存在覆盖该契约的权威测试→无法委托，需先抽出台架测试或直接修脚本自身断言
- 脚本检查的是测试不覆盖的独有内容（废弃措辞扫描、README 关键词、目录遍历/跳过策略）→只委托重叠部分，独有检查保留本地实现
- 脚本红是缺 pytest/错 venv 等环境问题→"真相源绿"仅在当前 shell 成立，直接委托会把环境故障伪装成通过，必须靠显式 fail-closed 区分
- 脚本与权威测试同时红→那是真红，改脚本只会掩盖真实漂移

## 8. fc9409074ad0

TASK

服务重启替换了进程，status 回执给出新的 live PID。任务是从该 PID 推导当前实际绑定端口，再对得到的端点执行一次健康探针。

METHOD CARD

name: failing-daemon-own-log-first-fix-at-real-supervisor
method_id: failing-daemon-own-log-first-fix-at-real-supervisor-297cab3af0ce
description: 复发型守护进程故障诊断：公网/本地各测一次定位故障层；用同机健康同类实例作对照排除环境；随后立即读故障进程自己的错误日志（经 lsof stderr 或 supervisor 元数据定位），而不是重复验证症状或做启动脚本/配置考古。若日志中拨打的地址与当前系统解析结果不一致，判定为进程内存缓存了坏地址，仅重启可清除；且修复必须写进真正托管进程的 supervisor 配置（launchd plist/systemd unit），否则 KeepAlive 会用旧配置把旧状态复活。

## Trigger
用户报告'上次修过但服务又坏了'，故障方是常驻后台进程（隧道/代理/web 守护），进程仍存活而对外服务异常（如公网 5xx、本地源站 200）

## Discriminator
同机同刻对照事实：故障实例进程存活但健康指标为 0（如 cloudflared ha_connections=0），同机另一同类实例指标全绿、本地源站 200。该事实当时即可把候选原因从'网络/DNS/配置/脚本'收窄为'该进程自身的边缘连接'，而答案就在该进程自己的错误日志里

## Short path
- 公网探测得症状码 + 本地源站 curl 200：故障隔离在 connector 层，不再重复验证已确立的症状
- ps 枚举同类进程：识别服务该域名的实例，以及是否存在同配置的重复 connector
- 逐实例查本机 metrics 健康计数：故障实例=0、健康对照>0 → 环境正常，问题在该进程内部连接
- 一步定位故障进程自己的错误输出（lsof -p PID 的 1w/2w，或 launchctl/systemctl 元数据里的 stderr 路径）并 tail：拿到直接失败原因，如持续 dial 某固定坏 IP 超时
- 用与进程一致的解析路径现场解析它正在拨的地址：结果正常而进程仍拨坏 IP → 进程内存地址池中毒，仅重启可清；结果仍坏 → 先修解析/代理层
- 确认真正的 supervisor 入口（plist/unit 及 KeepAlive），把修复参数写进该入口并由它重启，清掉重复实例后验证

## Stop conditions
- 故障进程日志给出的失败原因与当前独立观测（实时解析结果、健康计数）互相印证，即可执行 supervisor 级修复，不再扩大排查面
- 本地源站非 200：转修源站，本方法不适用
- 无健康对照且当前解析仍返回异常 IP：转向 DNS/代理层而非进程内部

## Verification
- 修复后该实例健康计数>0，且公网症状请求多次连续 200
- ps 确认运行参数与修改后的 supervisor 配置一致，且无同配置重复实例残留
- 所读日志时间戳与当前故障时段吻合，排除读到历史残留错误

## Counterexamples
- 源站本地即失败（local != 200）时读隧道进程日志无法定位，应先修源站
- 健康对照走不同协议/网络路径（如 QUIC/UDP vs TCP），其'全绿'不能证明故障进程的路径正常，对照只是弱证据
- 进程日志写入 journald/云端而非本地文件：lsof 找 stderr 无效，需改用对应日志接口
- 当前解析仍返回代理假 IP 时重启无效，须先恢复解析层，本方法不适用
- 无 supervisor 的手动前台进程：直接以正确参数重启即可，无需入口考古

## 9. 0ed299452fe2

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

## 10. 8b3c19b8db1b

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

## 11. b247f0db2ef8

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

## 12. 02ce9e50b318

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

## 13. b17dd9b7c582

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

## 14. 967c9b31fbed

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

## 15. ec044b3fddcf

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

## 16. 8f79095a3cd2

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

## 17. 299f7cddac23

TASK

append-only action 台账可按 origin 与 target 统计。任务是核对被指责的 publish 机制是否实际派发过动作，以及 target 分布是否支持“漏掉某服务”的前提。

METHOD CARD

name: dup-forensics-volatile-field-identity-plus-copy-lineage
method_id: dup-forensics-volatile-field-identity-plus-copy-lineage-2e19786207b7
description: 排查跨实体记录重复（同一 id/事件/行在多个 session 出现）时，先用重复对的易变字段（时间戳、运行时 id）是否逐字一致对机制空间做二分：逐字一致 ⇒ 物理字节复制（fork/clone/migrate/backup 恢复）；存在差异 ⇒ 重发/重放/并发再生成。随后只审计执行字节级复制的代码路径，并用谱系关联（parent/fork 标记）做全量验证与残差证伪，而不是枚举全部写入方。

## Trigger
需要为某数据层的跨 session/实体重复记录定案根因与归属规则，候选机制空间大（复制、迁移、重放、竞态、损坏），且已有权威文档登记过重复规模

## Discriminator
当时已可观察的事实：重复 attempt_id 连同微秒级 ts、call_id、payload 逐字段一致（设计文档§7/搜索回执已给出）。任何再生成类机制（重放、重试、并发写）必然产生新的时间戳与运行时 id；只有字节级物理复制能保留全部易变字段。系统内被文档化的物理复制机制是 session-fork。

## Short path
- 从重复记录本身提取字段一致性指纹：比较易变字段（ts、运行时 id）与业务字段（payload）；未知量：复制 vs 再生成
- 只读系统内文档化的字节级复制机制代码（fork/migrate/backup），确认其保留哪些字段、重分配哪些字段；未知量：该机制能否解释逐字一致
- 推导次级预测并与观测对账（大历史复制超 10MB 滚动阈值 ⇒ 双方成多段目录，解释重复集中在多段层）；未知量：层分布成因
- 写只读验证脚本：为每个重复 id 建 parent/fork 谱系边，预测 100% 可链接；未知量：是否存在无解释重复
- 对复制解释不了的残差单独证伪（如 settled 在所有会话均不存在），按失败模式重新定性；未知量：残差归属
- 冻结归属规则成 mini-design，实现+幂等复跑+回归门，与既有文档数字精确对账后停止

## Stop conditions
- 重复集合 100% 被谱系链接解释（UNLINKED=0），且最大簇数字与权威文档既有记录精确对账
- 残差已被证伪性证据重新定性并落档
- 谱系链接率显著低于 100%，或重复对易变字段存在差异 ⇒ 放弃复制假设，转向重发/竞态路径

## Verification
- 抽样重复对做字段指纹检查：确认易变字段逐字一致，而非仅业务字段一致
- 读复制路径源码确认：ts/payload 原样保留、仅重分配 id 类字段
- 全量谱系链接：每个重复 id 均有 parent/fork 边，输出 UNLINKED 计数
- 数字对账：簇统计与决策文档既有登记一致；修复后幂等复跑 0 新增；回归门全绿

## Counterexamples
- 重复记录业务字段一致但时间戳/id 不同 ⇒ 属重发/重放/至少一次投递，应查写入点幂等与去重，本方法的复制谱系路径会误导
- 单文件内部的重复（截断/追加损坏、同文件重复追加）无跨实体谱系边，不适用
- 复制路径合法重写了部分字段（如本集 session_id/seq/event_id 设计性重分配）且覆盖了易变字段时，指纹需按'该复制路径保留哪些字段'重新定义，不能照搬 ts 一致性

## 18. d205979ff96e

TASK

后台组件的 journal 连续记录 requeue reason；任务是统计 reason 分布，锁定占绝对多数的字面量，再到实际运行代码树追踪该 reason 的发射点。

METHOD CARD

name: drilldown-via-named-source-kind-before-keyword-search
method_id: drilldown-via-named-source-kind-before-keyword-search-7cee909454b4
description: 当回执/报告已把每个指标映射到具名 record kind（如『来源 declaration_check』『来源 exception_log』）或已示范 kind= 检索语法时，下钻核查应直接用该具名结构化过滤，而不是先猜自由关键词组合。本集在搜索发生前检索轴就已完整可见，仍先发了 2 次 keyword miss 后才切换到 kind 维度命中。关键词搜索仅作为无名轴或具名查询失效时的后备，不应作为对结构化记录库的默认开局。

## Trigger
任务需要核查某个结构化报告/回执中的指标构成（如 self_eval 的 honesty_rate/exception_rate），且该报告在首次搜索动作之前已显式标注各指标的来源 record kind，或示范了 kind= 检索语法。

## Discriminator
搜索动作发出前，上下文中已可见具名检索轴：指标行内标注『来源 <kind>』（declaration_check、exception_log 等），且回执明示 search_records(kind=...) 语法。此时检索维度不是未知量，无需关键词枚举。

## Short path
- 执行 self_eval；未知量：当前健康指标。同时把回执中每个指标的来源 kind 记为后续合法检索轴，不要丢弃。
- 读取 context/status；未知量：本会话与历史样本的边界（本会话 exception_log 是否为空）。
- 对要下钻的指标直接 search_records(kind=<报告标注的来源 kind>)；未知量：该指标的原始样本构成。
- 抽样阅读返回记录，判断失败是否可归因于自身决策（如本集 exceptions 全为 LLM 传输层/Provider 错误）。
- 目标指标核查完即停止，成稿时区分『回执支撑的事实』与『未验证推断』。

## Stop conditions
- kind 过滤查询返回记录的 kind 标签与报告标注来源一致，且已覆盖目标指标的样本构成
- 目标指标全部核查完毕，无剩余未知量，进入成稿
- 具名 kind 查询连续两次返回空 → 转向 schema/kind 枚举发现，而不是继续换关键词重试

## Verification
- 返回记录的 kind 标签 == 指标行标注的来源 kind（如 exception_log 记录确来自 exception_rate 的来源）
- 报告中引用的每个发现都能对应到至少一条抽样记录原文，而非仅凭聚合数字
- 最终答复保留 fact/inference 区分标注（如对 honesty_rate checker 误判推断的显式未验证标注）

## Counterexamples
- 记录库不提供 kind/结构化过滤参数，仅支持自由文本检索 → 关键词搜索是合法首步
- 报告/回执未标注来源 kind，只给聚合数值 → 检索维度确实是未知量，需先探索
- 任务是语义探索（按主题/内容找记录），没有具名轴可依赖 → 不适用本方法
- 具名 kind 已被证实失效（改名/清空，查询为空）→ 沿用具名轴会空转，应转 schema 发现

## 19. aa947481ca45

TASK

异步 restart action 已进入 failed 终态，action_id 可直接定位逐操作记录。任务是读取 failure detail、problem_kind、next_step，验证前置条件后执行规定补救序列。

METHOD CARD

name: durable-job-defer-terminal-check
method_id: durable-job-defer-terminal-check-2a5ca0503c58
description: 后台任务受理回执已确认（ok=true 且带 action_id/job_id 查询句柄）、任务元数据为 durable/running 时，剩余未知量只是『何时到终态』这一时间型未知，而非信息型未知。此时应立刻注册一次性延迟唤醒（间隔按已知或估算时长设定），到点读一次终态输出再做验证；不要调用无关命名空间的等待/感知工具（如对重启中的 webui 做 browser perceive），也不要零延迟重复轮询同一 job_output。

## Trigger
长时物理操作（服务重启/部署/批量迁移）以 durable 后台任务提交，回执 ok=true 且状态 running，唯一待解决量是终态何时出现

## Discriminator
首查 job_output 已同时给出：受理回执 ok=true + action_id + generation 匹配，且 durable=true/running。这两个事实把『继续查信息』与『只需等时间』区分开；紧随其后的零延迟重查返回逐字节相同输出，证明再查无新信息。任务仍在 stop/start 阶段时，对目标服务做外部感知也不可能成功

## Short path
- 核对部署 manifest，确认目标 generation/git_head/code_root 已固定（未知量：目标代是否已发布）
- 提交受控重启并读受理回执，确认 ok/action_id/generation（未知量：是否被受理）
- 单次 job_output 查询确认回执可见、任务 running——据此把剩余未知量归类为时间型而非信息型
- 立即注册一次性延迟唤醒，间隔按已知时长参照设定；受理与唤醒之间不再调用任何等待或轮询
- 唤醒后读一次终态输出，核对 action_id/generation 与受理回执一致，再执行验证清单（manifest/回执/屏障/渲染）

## Stop conditions
- 回执非 ok 或首查即失败：不延后，立即转诊断
- 首查已到终态（带终态输出）：立即验证，不再注册唤醒
- 唤醒后取得终态输出且验证清单通过：停止

## Verification
- 延迟间隔须由已知时长参照（如上一代同类操作耗时）导出，而非任意值
- 终态输出的 action_id/generation 与受理回执一致
- 受理与唤醒之间不应出现产生新信息的轮询；若出现，说明间隔判断错误，需修正而非继续等

## Counterexamples
- 任务为亚秒级同步操作：受理后立刻单次复查即可拿到终态，注册延迟唤醒反而拖慢整个流程
- 任务系统不提供延迟唤醒原语：只能退避轮询，不应套用此法
- 任务日志为流式增量输出，每次轮询都有新行：短间隔轮询有信息量，不算冗余，禁止强行延后

## 20. ded7907eee4f

TASK

PR checks 中某机械 gate 在数秒内失败。任务是读取该 gate 的失败步骤一行判定，沿判定点名的 artifact 路径读取 schema 与最近通过样例，再按相同 base/diff 语义本地复跑。

METHOD CARD

name: fastfail-ci-gate-filtered-verdict-then-named-artifact
method_id: fastfail-ci-gate-filtered-verdict-then-named-artifact-14e1acb2a084
description: 当 PR/CI checks 表中某 gate 以秒级时长失败时，把它当作该 gate 自身机械检查脚本输出的确定性一行判定：先用只读失败步骤的方式（gh run view --log-failed，或按 ##[error]/checker 错误前缀过滤）拿到这行判定，再沿判定中点名的确切 artifact 路径去读 checker 的 schema 段与一份最近通过的样例，据此构造修复物并用与远端相同的 base/diff 语义本地复跑验证。不顺序分页原始日志，不重跑碰运气。

## Trigger
远端 PR/CI checks 表出现 fail 项且完成时长为秒级（远短于任何测试/构建，如 <60s），并行长任务仍 pending/pass，需要定位失败根因并准备修复。

## Discriminator
checks 表中失败项的完成时长（本例 6s，对照安全扫描 40s pass、门禁 pending）在拉取日志之前就已可见——秒败意味着失败发生在 gate 自身的前置机械检查脚本内，其输出是一行确定性判定，且通常点名期望的确切路径/文件；gh CLI 提供 --log-failed 只取失败步骤日志。

## Short path
- 从 checks 表确认失败项与秒级时长 → 未知量：该 gate 到底拒绝了什么？
- 只读失败步骤日志（gh run view --job <id> --log-failed，或 grep '##[error]'/'expected' 等错误标记）→ 一次取得一行判定，其中点名确切 artifact 路径（如 expected exactly one manifest under docs/.../submissions/, found 0）
- 沿判定点名的路径：列出该目录 + 读 checker 脚本的 schema/required-keys 段 + 读一份最近通过（已合入）的样例 → 未知量：合规格式与覆盖要求
- 按 schema+样例构造修复物（如覆盖精确变更路径全集的 manifest），以与远端相同的 base 与 three-dot 语义本地复跑同一 checker，确认 PASS
- 停在授权边界：原授权为 exact-SHA 且不含新提交时，报告根因与已备好的修复，等待授权后再 push

## Stop conditions
- 已取得 checker 的一行判定且其点名具体 artifact 路径（机械确认，非猜测）
- 本地以相同参数复跑同一 checker 结果 PASS，且修复物逐字段对照 schema 与既有通过样例一致
- 修复动作超出当前授权字面范围（如 exact-SHA push 不覆盖新增提交）→ 停止并请示，不自行扩大授权

## Verification
- 提取的判定行包含具体可执行期望（如 expected exactly one X, found 0: []）而非泛化/基础设施错误
- 本地复跑同一 checker、同一 base 与 diff 语义（three-dot），结果可复现地在加入修复物后翻转为 PASS
- 最终报告的根因与远端失败日志中的判定行逐字对应，且修复物路径与判定点名的路径一致

## Counterexamples
- 失败项运行了数分钟（真实测试/构建套件）：失败可能藏在多行 traceback 中，单行过滤会丢失上下文，应改用带邻域的日志阅读
- 秒败源于 runner/infra（checkout/setup 之前退出、网络或配额问题）：判定是基础设施错误，正确动作是重跑或换 runner，而非研究仓库 schema
- 判定点名的路径不在仓库内（环境变量、外部服务、secret）：无法沿路径本地跟进，需改从配置来源或文档取证

## 21. db50b0a1d2ed

TASK

多个不同命令都在账户自有路径的 lock open-for-write 上返回 EPERM，用户认为近期重启禁用了工具。任务是用被指责子系统的状态回执和既有经验记录，裁定该因果说法并确定人机分工。

METHOD CARD

name: falsify-mechanism-attribution-via-remedy-reproduction
method_id: falsify-mechanism-attribution-via-remedy-reproduction-23940a181dc9
description: 审查带『根因+自述修复』的机制断言（文档/lesson/交接）时，不要先逐条复核周边事实，也不要照抄其归因。先原样复现失败，再只叠加自述的修复项：若修复不翻转结果、而一个独立工具对同一问题给出相反判定，归因即被证伪；随后做最小单变量矩阵（旗标/路径形态/隐藏状态各算一维），并用直接状态查询确证决定性因子，再改写或采纳该断言。搜索空间从『复核全部事实』缩为『先证伪/证实一个机制假设』。

## Trigger
任务要求审查或复核一份文档/lesson，其中对某工具行为给出了机制归因与修复方法，且该行为可用本地廉价命令复现

## Discriminator
复现中自述修复单独叠加后结果不翻转，同时另一独立工具对同一问题给出相反判定——两条当时已可见的事实的组合足以断定归因必错，真因子只可能在未被变动的维度（命令旗标、路径形态、改变工具默认行为的隐藏状态）中

## Short path
- 提取断言的机制归因与自述修复；用文档原样命令复现一次，建立失败基线
- 只叠加自述修复重跑一次，观察结果是否翻转
- 同时用一个独立工具回答同一问题，做交叉判定
- 若修复不翻转且独立判定相反：做最小单变量矩阵，每次只改旗标/路径形态/对象状态之一，并加入一个已知会成功的对照用例
- 对定位出的决定性因子做直接状态查询确证（而非仅靠差分行为）
- 确证后才改写、采纳或驳回该断言/lesson

## Stop conditions
- 自述修复单独叠加即可翻转结果 → 归因自洽，接受并停止，不再跑全矩阵
- 某个单变量翻转结果且被直接状态查询确证 → 根因已定，停止
- 复现不可行或成本高于该断言的决策权重 → 将断言标为未验证，不深挖

## Verification
- 决定性因子必须有直接状态证据（如查询对象是否处于改变工具默认行为的隐藏状态），不能只依赖差分行为
- 单变量矩阵中至少含一个已知成功的对照用例，证明实验装置本身能区分
- 改写后的 lesson 须在原失败场景与对照场景各验证一次才可落盘

## Counterexamples
- 断言所涉动作不可复现或不可逆（外部服务一次性状态、环境已变更）→ 用独立旁证而非因子矩阵
- 自述修复在复现中即翻转结果 → 归因与事实自洽，接受并停止，勿过度设计实验
- 机制断言不影响任何审查结论（纯措辞/低风险细节）→ 标注未验证即可，不值得消耗调用预算

## 22. 3a3d0c248801

TASK

上轮提议以“机制只计算而不产生效果”为前提要求接入新闸门。任务是先检索 reason_code、BLOCKED 回执和判定函数调用点，验证该前提后再决定是否设计改动。

METHOD CARD

name: falsify-behavior-premise-before-inherited-change
method_id: falsify-behavior-premise-before-inherited-change-6c6091650c9c
description: 当用户或上轮结论以'机制X只计算/声明而不产生效果'为前提提议改动（常带'差一根线'式表述）时，先检索X的效果证据（reason_code、BLOCKED回执、状态枚举、判定函数调用点）证伪前提，再决定是否进入设计。本episode中一次内容检索命中'executed=false; reason_code=convergence_boundary'，即推翻'算而未拦'前提：闸门已是双层阻断，提议的改动分支整体作废，真缺口转移到别处。该方法在动工前把设计空间缩为零。

## Trigger
用户或先前轮次的自己提出以'当前代码/artifact 缺少某种效果'（如'算出来了没接闸门'）为前提的改动建议，且该机制是本地可检索的代码，断言可机械检验。

## Discriminator
该机制的效果面是否已有痕迹：检索 reason_code、状态串、BLOCKED/异常回执、判定函数调用点。任一命中（本例 executed=false; reason_code=convergence_boundary）都把候选空间从'如何设计改动'直接缩为'改动是否还有必要'——此事实在读取任何实现文件之前就已可见。

## Short path
- 把提议还原为前提断言：'机制X目前只计算，不改变任何执行结果'，明确这是待证伪的未知量
- 在本地代码检索X的效果证据（reason_code/回执/状态/调用点），先于任何外部资料发现或方案设计
- 若命中强制效果，精读判定点与执行点两处实现，确认强度等级（提示级 vs 面收窄+WAL栅栏级）
- 前提被证伪则宣告改动作废、显式报告新事实错误，并重排剩余分支——真缺口往往随之转移
- 仅对幸存分支行动，所需材料从已验证的权威来源直取，读至无具名缺口即停

## Stop conditions
- 前提已被本地效果证据证实或证伪：证实则进入设计，证伪则该分支作废并明告用户
- 断言对象不可本地检验（外部服务/他人仓库）时停止本地枚举，转向权威外部来源
- 已确认改动必要且其形态由证据定级后，停止核验进入实现或提请治理流程

## Verification
- 核对该效果字符串/行号确属当前版本代码，排除相似命名或二进制误报（本episode先例：.pyc 撞字节误报）
- 追溯'缺失'断言的原始出处（哪一轮、依据哪段文本），与刚读到的实现对照，矛盾处显式报告而非静默修正
- 确认前提原文的真实语义：如'不注入不持久化'是prompt-neutral承诺，并不等于'不阻断'，不得据半句文本下结论

## Counterexamples
- 前提是新增尚不存在的能力（如'加重试'），并无'现有行为是惰性'的断言——无对象可证伪，直接进入设计
- 断言是语义/架构判断（如'是否长成第二套解释器'），效果面grep命中无法裁决，需通读上下文与设计文档
- 断言针对外部系统的行为（hosted API限流、他人仓库内部状态），本地检索只能得到证据缺失，须直取权威外部来源

## 23. 151490f348ca

TASK

后台部署任务已受理并返回 action_id，当前状态为 durable/running。任务是安排一次延迟检查，到点读取该 action 的终态并据结果继续。

METHOD CARD

name: failed-action-keyed-ledger-lookup-then-prescribed-remediation
method_id: failed-action-keyed-ledger-lookup-then-prescribed-remediation-efed0f93c3f4
description: 当异步控制面操作卡住/失败且其精确 action_id 已知时，直接按键检索该操作自身的台账记录（按 ID find/glob），而不是枚举目录结构或盲目重试。读取 detail/problem_kind/next_step；独立验证记录中陈述的前置条件（如仓库 HEAD 与记录的 actual/desired 是否一致）；再按记录提示或既有成功调用的参数形态执行规定的补救序列，最后才重新发起原操作。

## Trigger
状态/审计结果或先前提交已给出失败异步操作的精确 action_id 及终态（failed），且按该 ID 键存的逐操作记录存在；当前未知量是失败原因与安全重发路径

## Discriminator
在做任何文件系统探测之前，已从状态/审计输出中持有精确的失败 action_id 与终态 failed——该 ID 对应的记录文件是唯一因果下一跳，其中含 failure detail 与机器给出的补救提示（含所需参数提示），无需枚举目录布局来发现它

## Short path
- 从状态输出提取失败 action_id 与终态；未知量=失败原因
- 按键检索：在台账根下按精确 ID find/glob 记录文件（如 'svc-<id>*.json'），读取完整记录的 detail/problem_kind/next_step
- 对独立事实核验记录前置条件：git status/HEAD 须与记录的 actual head 一致且树干净；不一致先调和
- 按 next_step 规定执行补救（先把 desired 推进到当前 HEAD），参数形态取自记录内 argv 提示或先前被受理的调用（如必须的 code_root、合法 target 枚举）
- 以合法参数与新的 expected_generation 重新发起原操作，取得新 action_id，接受两阶段/轮询终态后停止

## Stop conditions
- 已取得含 detail/next_step 的完整记录——停止目录探测与宽枚举
- 前置条件（树干净、HEAD 与记录 actual 一致）已核验后才重发
- 重发操作已被受理（返回新 action_id 与 expected_generation），不再追加探测

## Verification
- 记录中的 actual git_head 与独立检查的仓库 HEAD/status 一致
- 补救结果（publish 的 git_head/generation）与当前代码树一致，且成为重发操作的 expected_generation
- 发布时 tracked 树 0 处修改，无未验证假设

## Counterexamples
- 操作仍处 pending/瞬时超时而非终态 failed——应轮询等待，不要进入补救路径
- 记录的 detail/next_step 均为空——按键记录是死路，应扩大到服务日志/运行时状态
- 控制面提供按 ID 直接查询的 API——应使用该 API 而非文件系统 glob（方法核心是按键检索，不是文件系统本身）
- 工作树脏或 HEAD 与记录 actual 不符——publish-then-restart 不安全，须先调和树/版本

## 24. 4966e1595ecb

TASK

一次发布已经完成并返回 generation 与 git_head。任务是依据该变更身份检查受影响文件、运行针对性测试，并核验新进程、入口和启动后日志。

METHOD CARD

name: explicit-redeclare-target-env-on-generation-switch
method_id: explicit-redeclare-target-env-on-generation-switch-6e73ca09c81d
description: 部署/重启类脚本常从 ambient 环境变量解析目标根（code/runtime root、generation）。当持久 shell 此前操作过旧目标（旧 worktree、同日旧 .env）而任务已切换到新目标时，直接调用会在残留守卫处被拒（本例 preflight rc=2，LFL_RESTART_* 指向 gen63 旧根）。方法：首次调用前只读探测目标变量；在调用点显式重声明全部目标变量及确认标志，不跨世代继承 ambient。遇 operator-only 控制面动词被拦截时不重试不绕过，产出含已验证参数的精确命令移交操作员。

## Trigger
持久 shell 中要调用以环境变量解析目标根/世代的部署、重启或预检脚本，且任务已切换到新目标（新 worktree/新世代/新根），同时存在近期对旧目标的操作痕迹（旧 worktree、同日 .env、会话引用）

## Discriminator
进入调用前已可观察：runbook/.env 模板明示脚本经 env 解析双根且『两处必须保持一致』；磁盘上并存旧世代 worktree（gen63）与本日早间操作痕迹；本次目标为 gen64 新根。三者合并即把『直接跑 preflight』缩为『先只读探测 env、再显式重声明双根+确认标志』。

## Short path
- 按已读 runbook/源码要求准备新目标（新 worktree、.env 模板复制、gitignored artifact 复制）
- 首次调用目标解析类脚本前，只读探测 ambient：env | grep <runbook 列出的目标变量前缀>
- 探测到指向旧目标的残留（或不确定）时，在调用点显式重声明全部目标变量与确认标志后调用；无残留则显式声明后直接调用
- preflight 通过后，用只读 show 核对当前/期望 generation，再进入发布动作
- mutating 动词被 operator-only 边界拦截时：停止重试与绕过，把带已验证参数（含 --expected-generation）的精确命令移交操作员

## Stop conditions
- preflight 双 PASS 且 binding 输出的 code_root/experiences_source 与新目标一致、无 legacy divergence
- 控制面所有权拦截已发生且已产出精确移交命令（模型侧不再推进依赖该步的动作）

## Verification
- binding JSON 中 code_root=新 worktree 根、experiences_source=explicit_env
- 显式声明的双根与脚本回显的生效根一致（无 A3-RESIDUE 拒绝）
- 移交命令的 --expected-generation 与只读 show 显示的当前 generation 一致

## Counterexamples
- 一次性干净 shell（如 CI runner）无 ambient 残留：探测为空，方法只带来无害冗余而非收益
- 脚本目标来自位置参数或配置文件而非环境变量：env 重声明不被读取，应改为调用参数显式化
- ambient 残留与新目标恰好一致（同根复用）：不构成风险，只读探测即可排除，无需预判拒绝
