# Blind batch 1/3

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

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
