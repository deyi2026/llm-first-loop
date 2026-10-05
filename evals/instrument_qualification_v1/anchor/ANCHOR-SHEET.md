# IQ v1 人类锚补验评分表（12 例；呈序 seed=20261007；题面逐字取自 iq_sheet.md，无标签无格号）

> 假设你正在执行下面的【任务】，手头只有这张【方法卡】。该卡对本任务是否适用？
> APPLY = 采纳其指引会实质改变/正确化本任务的执行；SKIP = 不适用。
> 请附一行理由（12 例每例一行，APPLY/SKIP + 一句理由）。

**答卷**：直接在本会话按呈序粘贴 12 行，或填 `ANCHOR-ANSWER.jsonl`：
`{"opaque_id":"…","verdict":"APPLY|SKIP","reason":"一行理由","ts":"ISO时间"}`

## 1. `140487a03a55`

**【任务】**

CLI --help 列出的必填参数均为运行时状态值（根目录、代号、data 目录），同时任务叙述已引用对应记录存在于本地（如'记录 generation=55、git_head=…'、manifest head）

**【方法卡】**

````
name: align-repo-advice-with-recorded-decisions-first
method_id: align-repo-advice-with-recorded-decisions-first-0973b39f2d2e
description: 对『某类内容该入库/忽略/删除』的建议，先读仓库既有决策记录（ignore 规则及其意图注释、同类产物的排除先例、git 状态、候选删除项的 mtime），把每个『待决策问题』先区分为：已有记录→对齐执行（如规则已白名单但文件从未 add，落差本身就是核心发现）；无记录→按原则判（人写不可再生文本入库，可再生运行产物本地保留+补 ignore）；删除建议先核 liveness（近期时间戳、无进行中操作、dirty 状态）与磁盘余量，默认保守。本集两条初步判断被第一手记录反转，证明记录先于判断。

## Trigger
用户要求对仓库内容（文档、数据目录、运行产物、worktree、临时目录）给出入库/忽略/删除建议，且系统中存在可读的治理记录（ignore 文件及注释、同类排除先例、版本控制状态、文件时间戳）

## Discriminator
第一手读取的决策记录是否已直接回答该问题：ignore 文件中存在带意图注释的白名单/排除规则、同类大体量可再生产物已有排除先例、临时目录 mtime 显示为近期而非陈旧——任一命中即把『开放决策』坍缩为『对齐执行』或『不可删』

## Short path
- 建议形成前先读决策记录：ignore 规则+意图注释、同类产物的既有排除先例、status/分支状态、删除候选的 mtime 与进行中操作标记（如 rebase 目录是否存在）
- 逐项对照分类：记录已明确收录→对齐执行补纳入；有排除先例的可再生产物→本地保留+补 ignore；无记录→按『人写不可再生入库、可再生本地留』原则判
- 发现记录与现实不一致（规则存在但内容从未纳入版本控制）时，把『决策-执行落差』作为核心发现报告，而非重新发起决策
- 删除类建议先核 liveness：最近时间戳、无进行中操作、dirty 文件计数、磁盘余量；磁盘充裕且误删代价非零时默认保留并给验证步骤（如先 diff 再删）
- 每条建议附其记录/事实依据，全部可溯源即停止，不再枚举新候选

## Stop conditions
- 每个建议项都能引用具体记录（规则行/先例/状态/时间戳）或『明确原则+已验证事实』，无一依赖未验证的陈旧/未决假设
- 所有决策-执行落差已列出并报告，无剩余未分类候选

## Verification
- 用 check-ignore 类命令复核所声称的收录/排除状态与最终建议一致
- 逐个删除候选复核 mtime、进行中状态、dirty 计数，确认不存在『近期却被判为陈旧可删』的反例
- 抽查被建议入库的内容类型（纯文本、无大二进制），确认与记录意图（如『文本资产保全』）相符

## Counterexamples
- 新仓库无任何 ignore 惯例或意图注释——没有记录可对齐，须与用户从原则出发决策，不得虚构权威先例
- 用户明确要求重新评估既有策略（记录可能已过时违背当前意图）——记录是待呈现的冲突证据，而非直接执行的结论
- 磁盘真正紧张（余量低）时删除收益上升，『默认保守保留』分支失效，需按空间收益重排优先级
- 目标内容性质未知且记录无注释——白名单/排除规则的意图无从判定，须先探内容类型再归类
````

- verdict(`140487a03a55`)：APPLY / SKIP　理由：…

## 2. `8088461bd30d`

**【任务】**

聚合指标（缓存命中率/前缀复用）持续下降，用户提名的解释（如模型切换）已被用户自己否定但需验证，剩余候选原因有多个（切换/重启/TTL/LRU挤兑/运行时逐轮改写前缀）。

**【方法卡】**

````
name: allowlist-names-from-authoritative-definition-not-summary
method_id: allowlist-names-from-authoritative-definition-not-summary-28a550ac5cac
description: 当修复需要写出逐字枚举标识符的工件（契约测试允许集、字段清单、schema）时，名字必须从当前权威定义（投影函数体逐行列出的键、Schema 字段声明、前端类型）机械提取，而不是转录此前审查/讨论摘要里的描述。写入前先对两个名集做 diff：只出现在摘要、不在任何定义里的名字即是幻影，进了补丁必然在集成阶段的契约测试被拦截，造成返工 commit。修复方向（扩测试允许集还是收窄代码投影）由独立消费者（前端 types、平行 roundtrip 测试）是否存在来决定，而非默认某一方正确。

## Trigger
需要新建或修改一个逐字枚举标识符集合的工件（契约测试允许集、API 字段清单、类型/schema、fixture），且手上还存在一份更早的审查摘要、会议记录或上轮结论也用自然语言描述过这批名字

## Discriminator
权威枚举定义已在当前代码中存在或一步可达：投影函数体逐字列出的键、Schema 字段声明、前端类型定义，可与摘要名集做机械对比；只出现在摘要中、任何定义面都找不到的名字，在写入补丁前即可判定为未证实的幻影名

## Short path
- 定位并读取权威定义面（投影函数/Schema/类型定义），未知量：真实契约名集到底是什么
- 从定义体逐字机械提取名集，与摘要/记忆名集做 diff，显式标出仅存在于摘要中的幻影名
- 用独立消费者确定修复方向：前端 types 或平行测试在消费这些字段→属计划内扩展、扩允许集；无任何消费者→收窄代码投影
- 补丁只写入从定义提取的名字；计划内扩展同时补登记注释/平行测试
- 先单点跑该契约测试转绿，再 merge+集成全量；对账所有定义面键集一致即停止

## Stop conditions
- 工件名集与从权威定义机械提取的结果集合相等，且目标契约测试单点转绿
- 后端投影/Schema/前端类型等全部定义面名集一致，无单边新增或丢键
- 摘要独有的幻影名已被证伪且未进入任何提交

## Verification
- 用 grep/AST 从权威定义机械提取键集，与补丁内容断言集合相等（不允许手抄）
- 单点契约测试转绿后再执行 merge/集成全量，确认无同类失败复现
- 对账所有定义面（后端投影函数、Schema、前端类型）的键集三方一致

## Counterexamples
- 契约尚未实现的设计/TDD 任务：权威是 spec 而非代码，应按 spec 写键、允许测试先红，此时按落后于设计的代码取名集是错的
- 允许集是故意冻结的 ratchet，目的就是强制每个新键必须人工裁决：不能仅因代码已出现某键就机械扩集，必须先判定计划内/计划外并留下裁决记录
- 多个定义面互相矛盾（投影≠schema≠前端）时不存在单一权威，取任一单边都会残留不一致，须先三方对账再定名集
````

- verdict(`8088461bd30d`)：APPLY / SKIP　理由：…

## 3. `b9beb0e14c29`

**【任务】**

用户提出"要不要重启/回滚/重部署X"式二元干预请求，且报告的故障在操作侧尚未复现

**【方法卡】**

````
name: anchor-background-job-polling-to-duration-prior
method_id: anchor-background-job-polling-to-duration-prior-1dfd748c4afb
description: 等待必须完成后才能继续的长时后台任务（回归门/构建/批量作业）时，把轮询节奏锚定在可观测的 duration prior（同一命令最近一次实测耗时）与剩余独立工作量上：先做完真正独立的等待期工作；工作耗尽且 elapsed<prior 时不发起零信息查询；首次查询定在 ≈prior 时刻，其后递增间隔；怀疑挂起用进程 CPU 时间是否推进来判定，而非重复查状态。本集 prior（248.73s）在启动门之前就已从旧 job 输出读得，但同一 running job 仍被约 19 次零输出 job_output 连查（episode 指标 duplicate_calls=49）。

## Trigger
已启动或即将启动一个已知分钟级耗时的后台任务（全量回归门、构建、批量作业），下游动作依赖其完成，且轮询回执在完成前恒为 running/无增量输出。

## Discriminator
两个当时已在手的事实：(1) 同一命令最近一次运行的实测耗时已可见——本集第 1 步旧 job 回执即给出 `... in 248.73s (0:04:08)`，预期完成时刻可算，且模型自己已知并发 ruff/pyright 会更慢；(2) 每次查询回执恒为 `状态=running`、`输出（0 行）`，即 prior 未到时 job_output 是零信息动作。

## Short path
- 启动后台任务前，先读同一命令最近一次的历史 job 结果，取实测耗时为 duration prior（本集第 1 步即得 248.73s）。
- 单次启动门（后台 + pipefail，保证退出码真实），只启动一次。
- 等待期先完成所有真正独立的预检工作（scoped diff 审查、ruff/pyright、测试覆盖核对、tree/index 一致性），并记录每步耗时。
- 独立工作耗尽后：若 elapsed < prior + 合理余量（本集已知 CPU 争抢应放宽），不发起 job_output——停等优于零信息连查。
- 首次查询定在 ≈prior 时刻；回执仍 running 则按递增间隔再查；怀疑挂起时改用一次 `ps` 看 CPU 时间是否推进来判定，而不是连发状态查询。
- 回执变为 done + exit=0 + 通过计数可读即停止轮询，直接进入下游动作（commit）。

## Stop conditions
- job 回执 status=done 且 exit=0、结果计数可读 → 停止轮询。
- 回执显示失败/被取消/进程消失 → 停止轮询，转入错误处理。
- elapsed 显著超过 prior 且最近一次进程级检查显示 CPU 时间无推进 → 停止盲目等待，改做挂起诊断或按取消意图处理。

## Verification
- 对比反事实：本集对同一 running job 的零输出 job_output 查询约 19 次（episode 指标 duplicate_calls=49）；锚定 prior 后应 ≤3–5 次，且每次查询要么已到 prior 时刻、要么状态有变化。
- 最终结果与旧门同格式可对照（本集 6368 vs 6337 passed，exit=0 由 pipefail 保证），确认等待换来的事实真实可用于下游 commit。

## Counterexamples
- 首次运行、无任何 duration prior 且任务无进度输出：轮询是唯一信号源，不能套『prior 未到就不查』，应使用适中的固定间隔。
- 任务本身有增量输出（pytest -v 逐行、进度条、日志流）：每次轮询都带回新信息，频率应跟随进度速率而非 prior。
- 用户明确要求流式观察，或存在需要盯 cancel_requested/硬超时的时限约束。
- 等待期仍有大量真实独立工作可做：穿插查询合理，本方法只约束『独立工作耗尽后』的节奏，不应推广成一律不许中途查询。
````

- verdict(`b9beb0e14c29`)：APPLY / SKIP　理由：…

## 4. `885f3cc78bf7`

**【任务】**

用户发出极简续跑指令（项目代号 + '继续'），当前无活动 goal，需要先重建项目状态才能行动。

**【方法卡】**

````
name: resume-continuation-via-named-provenance-and-git-delta
method_id: resume-continuation-via-named-provenance-and-git-delta-948a229d7f50
description: 极简续跑指令（如 'X 继续'）且无活动 goal 时，不要对同一 evidence 库反复换措辞搜索。首次 search miss 的回执通常已显式列出项目最新权威文档参考；schedule/wakeup evidence 常已点名续跑备忘；而版本库 unmerged commits 是『还剩什么』的真值账。沿这三条已点名的 provenance edge（最新停点文档、被点名备忘、git cherry/diff 量化 delta）重建状态，把『继续』转成『N 条未吸收 commits + 冲突面』的量化事实后再执行，可省去重复查询，并让分批移植有客观依据。

## Trigger
用户发出极简续跑指令（项目代号 + '继续'），当前无活动 goal，需要先重建项目状态才能行动。

## Discriminator
首次 search_docs miss 的回执已显式列出该项目最新文档参考（含最新停点/裁决文档）；且 schedule evidence 命中的续跑清单已点名具体备忘项并给出优先级——状态来源在当时已被收窄到一两个；同时 git 分支 unmerged commits 是剩余工作的真值。

## Short path
- 收到续跑指令且无活动 goal → 先读 miss 回执已列出的最新项目文档，取得停点与下一步命名（未知量：上次停在哪）
- 用项目 token 检索一次 schedule/续跑 evidence，只取被点名的那份备忘，不换措辞重查（未知量：续跑计划原文）
- git 真值账：log main..branch 全量清单、git cherry 等价性标记已在 main 的 commits、merge-base 双边 diff 得冲突文件集（未知量：剩余工作量化）
- 以量化 delta 建 goal+worktree，按 commit 分组批量执行；已在 main 的等价项显式跳过并记录
- 门禁/PR/检查通过即停

## Stop conditions
- 续跑状态已被权威来源完全量化：未吸收 commits 数、已在 main 的等价项、双边冲突面均已确定
- 备忘指定的下一步为纯等待/机械步骤（如等 PR 检查后 merge）时按字面执行，不再展开新发现

## Verification
- 最终执行范围与 git cherry 未吸收清单一一对应；已在 main 的等价 commits（如 B1）被显式跳过且有记录
- 汇报中的分批数与冲突数与 merge-base 双边同改文件集一致

## Counterexamples
- 会话 evidence 已含完整 kickoff 计划且有直接 evidence_ref → 直接读该项按字面执行即可，无需再展开 git delta 移植
- 续跑对象无版本库或是外部服务状态 → git 真值账不适用，只剩文档/备忘两条边
- miss 回执的参考列表与所指子项目语义无关（同名不同物）→ 该 edge 不可信，需语义判断或直接问用户
- 指令本身含糊且无任何点名备忘/文档参考 → 宽 evidence 搜索或向用户澄清才是正确动作
````

- verdict(`885f3cc78bf7`)：APPLY / SKIP　理由：…

## 5. `0f030fffc8b6`

**【任务】**

用户消息很短且含无先行词的代词/指示语，所需事实大概率已存在于先前会话产物（报告、附件、抓取文件）中，必须先恢复上下文才能作答

**【方法卡】**

````
name: anaphora-artifact-first-context-recovery
method_id: anaphora-artifact-first-context-recovery-42e2e7649585
description: 当用户提问含未解析指代（如'他''那个项目''过去一下'），任务本质是恢复先前会话产物并基于它回答。正确首步是按新近度枚举会话记录/已发送附件/工作目录工件并直接读取，而不是对以 provenance 元数据索引的证据库拼内容关键词查询——此类查询对 source/coverage 型索引天然弱命中。读到工件后只做定向提取（如联系方式），再按目的分支回答、声明能力边界、对仍含糊的指代提出澄清。可省去 2-3 次无效检索。

## Trigger
用户消息很短且含无先行词的代词/指示语，所需事实大概率已存在于先前会话产物（报告、附件、抓取文件）中，必须先恢复上下文才能作答

## Discriminator
消息本身可观察：单句、含无先行词的'他'与预设既定目标的'过去'——这直接表明首个未知量是'指代对象与先前产物是什么'，而非新事实发现。对'未知指代'，按新近度取记录/产物即命中；而猜内容关键词查证据库（其 ref 以 source=工具:命令号 等 provenance 字段索引）不解决指代问题且必然弱命中。

## Short path
- 识别消息含未解析指代 → 首未知量=先前主题与产物：按时间取最近 action_trace/记录或列出最近 evidence（source 字段直接标明产物类型：已发送附件、命令快照）
- 由记录定位具体工件（附件/临时目录中的报告文件）→ 读取工件本体，确认其覆盖用户问题域（主体、疑点、联系渠道）
- 在工件上做定向提取（grep 联系方式/渠道标记等），不扩大枚举其他来源
- 输出：已核验渠道/事实表 + 按交流目的分支的条件建议 + 自身能力边界说明 + 针对仍含糊指代的一个澄清问题，停止

## Stop conditions
- 先前工件已提供回答所需全部事实（如完整联系渠道），且逐条能在工件中定位
- 工件主体与用户指代语义匹配（同一项目/人物），无需再发现新来源

## Verification
- 回答中引用的每条事实（邮箱、渠道、疑点）均能在先前工件中逐条定位（grep/读取命中行）
- 未引入工件之外未核验的说法；'值不值得交流'类判断明确标注为依赖用户目的的条件性建议而非断言

## Counterexamples
- 消息自含完整上下文、无指代 → 直接回答，做工件恢复是浪费
- 证据库实际支持全文/内容检索 → 关键词查询可作首步，本方法不适用
- 用户问的是当前实时状态（如'服务现在可达吗'）→ 旧工件已过期，必须重新实测而非读历史报告
- 指代在当前对话上文已有先行词 → 无需跨会话恢复
````

- verdict(`0f030fffc8b6`)：APPLY / SKIP　理由：…

## 6. `2914fb67544e`

**【任务】**

复用/改写仓库内别处的冻结 runner 或 worker 契约，且执行环境是新建的 git worktree 或全新 checkout；即将进行第一次端到端启动（dry-run 或 measured run）。

**【方法卡】**

````
name: anchor-declared-worktree-root-before-commands
method_id: anchor-declared-worktree-root-before-commands-695487311c0e
description: 在多 worktree 仓库中恢复一个已有冻结计划的会话任务时（PLAN/PROTOCOL 已落盘于特定 worktree）：第一条仓库命令就用 `cd <工作根> && …` 锚定到该 worktree，而不是在默认 cwd 失败后再枚举全部 worktree；且在首次启动复用的 runner/worker 前，用一次存在性检查确认其源码显式引用的 gitignored 运行时资产（如 data/ 下文件）确实存在于当前 checkout——新建 worktree 不会自动带上被 ignore 的文件。把『在哪个 checkout 工作』和『运行前提是否在该 checkout 内齐备』这两个未知量提前各用一条命令解决。

## Trigger
多 worktree 仓库中恢复/继续会话任务：任务工件（冻结 plan/protocol、前次 commit）位于某个特定 worktree，且接下来要执行 git 命令或复用既有 runner/worker 启动真实运行。

## Discriminator
进入扩散前已可见的事实：失败命令自身的输出显示 cwd 落在主 checkout 的无关分支，而会话内先前的 commit/工件路径已把任务工作根钉在一个具名 worktree；且被复用契约的源码在读取时就显式引用了 repo 根下的运行时资产路径（如 PROVIDERS = REPO/'data'/providers.json）。这三点当时就足以把下一步从『枚举所有 worktree / 直接开跑』缩为『cd 到声明根 + 预检资产存在』。

## Short path
- 从恢复上下文（checkpoint/goal/已落盘 plan 的路径）确定声明的工作根 worktree；未知量：该根下已落地什么、还缺什么。
- 第一条仓库命令即 `cd <工作根> && git log -3 && git status -sb`，一次取得任务分支状态；不在默认 cwd 先试探失败。
- 只读冻结 PLAN/PROTOCOL 点名的复用契约文件（fixture、worker、既有 runner）；未知量：复用什么、改什么。
- 实现后先跑 fixture 自检与无模型 dry-judge 门；全过才允许进入 measured run。
- 启动前一条存在性检查：复用契约引用的 gitignored 运行时资产是否存在于本 checkout；缺失则先补齐或加受控回退，再启动。
- measured run 在正确 checkout 内启动（输出转日志）即停止发现，等待收割。

## Stop conditions
- 任务 worktree 内最新 commit 与冻结 plan 对齐，无未预期脏文件
- 自检与 dry-judge 门全部通过，且运行前提资产已确认存在或有回退
- measured run 已在声明工作根内启动，不再追加环境探查

## Verification
- 每条 git/运行命令的输出分支名与路径均属于任务 worktree，而非主 checkout
- fixture 自检 + dry-judge 在新 checkout 内全 PASS 后才启动 measured run
- 复用契约引用的每个 repo 根运行时资产在当前 checkout 内存在或已有受控回退

## Counterexamples
- 单 checkout 简单仓库，默认 cwd 即任务根：锚定与预检是多余开销，直接执行即可。
- 任务目标本身就是盘点/清理多个 worktree：全量 `git worktree list` 是目标动作而非搜索扩散，本方法不适用。
- 复用契约引用的资产受版本控制或由 runner 自己生成：无需预检存在性，直接运行。
````

- verdict(`2914fb67544e`)：APPLY / SKIP　理由：…

## 7. `e98730ec0f28`

**【任务】**

即将执行用户已授权、且以远程状态为闸门的变更动作（merge/deploy/重启），同时用户消息中已明确前提条件（如 CI 终态）和锚点（基线 SHA / PR 号 / 资源 ID）

**【方法卡】**

````
name: anchor-complete-gate-query-before-remote-mutation
method_id: anchor-complete-gate-query-before-remote-mutation-f3e6129501ef
description: 用户已授权某远程状态变更（合并/部署/重启）并给出前提条件与锚点（基线 SHA、PR 号、ID）时，先从这些推导出闸门所需的完整事实集（如 CI 终态、可合并性、head OID），用一次权威查询全部取回，并在变更前校验锚点一致；不要在闸门判定中穿插无关的状态查询（如旧 goal 状态）。远程变更落地后，先同步本地 ground truth，再读取随该变更到达的工件。

## Trigger
即将执行用户已授权、且以远程状态为闸门的变更动作（merge/deploy/重启），同时用户消息中已明确前提条件（如 CI 终态）和锚点（基线 SHA / PR 号 / 资源 ID）

## Discriminator
用户消息里的锚点+前提条件在发起任何查询之前，就已能枚举出闸门所需的完整事实集；若首次状态查询缺少锚点字段（如 head OID 未随 CI 状态一起返回），就必须补一次查询，且两次查询之间容易穿插与闸门无关的宽状态读取（返回的是上一个已完结 goal 的内容）

## Short path
- 从用户目标+动作前提推导闸门事实集：检查终态结论、mergeable/clean、head OID（用于与用户给出的基线锚点比对）
- 用一次权威查询（显式包含 head OID 字段）取回全部闸门事实；未知量：当前 head 是否就是用户锚点且全绿可合并
- 全绿且 OID 与锚点一致 → 立即执行变更；用变更回执验证 merge commit 的父提交恰为已验证的 head
- 远程 main 已被变更 → 在读取随变更到达的本地工件前先做 ff-only 同步，建立本地 ground truth
- 进入下一子任务（读模块现状 → RED 测试 → 实现），不再回头做发现类查询

## Stop conditions
- 闸门事实已在一次权威查询中全部取回且 head OID 与用户锚点一致 → 执行变更，不再追加状态查询（除非存在并发写者）
- 任一检查非终态/非绿，或 OID 与锚点不符 → 停止变更并报告差异
- 远程变更已落地且本地已同步、目标工件已可读 → 停止同步/发现类动作，进入下一子任务

## Verification
- 变更回执中 merge commit 的父提交包含已验证的 head OID，且用户锚点出现在合并后历史（log/merge-base 可证）
- 本地同步后 HEAD 与远程 main 一致，随合并到达的文件可直接读取且无需重试

## Counterexamples
- 分支可被他人并发推送：变更前的即时重查是必要的 freshness 守卫而非重复调用，过早的一次性查询反而会合入过期 head
- 检查仍在 PENDING：闸门不可判定，正确动作是轮询/延后，而非先取锚点字段
- 用户未给锚点且下游动作不需要 OID：按常规模板查询即可，刻意取全字段徒增噪声
- 纯本地工作流（远程与本地无分歧）：既无一次性闸门查询问题，也无同步步骤
````

- verdict(`e98730ec0f28`)：APPLY / SKIP　理由：…

## 8. `0afaa4940645`

**【任务】**

需要执行一个外部动作（发附件/调用服务/通知），但缺少一个可检索的参数值（如 receive_id、endpoint、绑定的别名），且该动作本身会产生可观察的成功/失败回执

**【方法卡】**

````
name: act-on-provenance-rich-record-hit-receipt-verifies
method_id: act-on-provenance-rich-record-hit-receipt-verifies-ca3c9572705a
description: 动作缺一个参数（收件人ID/端点/绑定别名）时先定向检索 records/memory：若命中同时携带①值的确切存储来源(provenance) ②唯一/当前绑定标记 ③曾用同一工具+同类负载成功的先例，且该动作失败可观察、重试廉价，则直接以该值执行动作，把动作回执(message_id/成功码)当作参数验证，不再回读底层配置文件二次确认。仅当记录跨越该事实的可能变更窗口、动作不可逆或高爆炸半径、或失败静默时才预核实时源；预核时被引用的运行态相对路径(data/)应按 runtime_root 解析而非代码 worktree。收益：把'记录+源文件双验'缩为'记录→动作→回执'单链，省一至两个确认轮。

## Trigger
需要执行一个外部动作（发附件/调用服务/通知），但缺少一个可检索的参数值（如 receive_id、endpoint、绑定的别名），且该动作本身会产生可观察的成功/失败回执

## Discriminator
检索命中是否同时含三要素：值的确切存储来源（写明配置于哪个文件）、'当前/唯一绑定'类标记、'曾用同一工具同类负载成功'的先例；且目标动作失败会明确报错（如 receiver 不存在即报错），重试代价低。本例命中首条即同时写明配置文件位置、唯一私聊绑定、曾用同一发送工具成功发过同类报告附件，三要素齐备

## Short path
- 定位当前子任务缺失的唯一未知量（如发送所需的 receive_id），用 records/memory 定向检索该量，不做宽枚举
- 命中带 provenance+唯一绑定+同工具成功先例三要素 → 直接以该值调用动作工具
- 以动作回执验证参数：success 回执（含 message_id/成功码）即完成验证，转入下一子任务
- 仅当回执报参数类错误（receiver 不存在等）才回退读实时绑定源，重取值重试一次
- 若确需预核实时源：其 data/ 运行态相对路径按 runtime_root 解析（运行态数据不在代码 worktree 下），避免先猜错基路径再 find 兜底

## Stop conditions
- 动作回执成功且带标识（message_id/成功码）后，不再对同一参数做二次来源确认
- 用户所需的各子任务（生成/发送/起草）均已有成功回执或落盘产物后停止，不追加'再确认几个'类动作

## Verification
- 动作回执为 success 且带唯一标识，无 receiver/param 类错误，即认定参数正确
- 若跳过预核后动作失败：回退读实时绑定源应能解释差异（值已变更），纠正后重试成功，说明回执作为验证器闭环有效

## Counterexamples
- 记录时间跨过该事实的可能变更窗口（绑定支持多用户、近期有换绑操作）→ 回执验证不再是廉价保险，必须先读实时源
- 动作不可逆或误发即造成泄露/高爆炸半径（敏感收件人、群发、删除类）→ 不能靠'失败再重试'兜底，必须预核
- 动作无回执或失败静默（fire-and-forget）→ 回执无法充当验证器，本方法不适用
- 命中只有裸值、无 provenance 与成功先例标记 → 不满足判别条件，需先溯源再决定是否直接行动
````

- verdict(`0afaa4940645`)：APPLY / SKIP　理由：…

## 9. `a5f0a69da346`

**【任务】**

用户要求对仓库内容（文档、数据目录、运行产物、worktree、临时目录）给出入库/忽略/删除建议，且系统中存在可读的治理记录（ignore 文件及注释、同类排除先例、版本控制状态、文件时间戳）

**【方法卡】**

````
name: align-repo-advice-with-recorded-decisions-first
method_id: align-repo-advice-with-recorded-decisions-first-0973b39f2d2e
description: 对『某类内容该入库/忽略/删除』的建议，先读仓库既有决策记录（ignore 规则及其意图注释、同类产物的排除先例、git 状态、候选删除项的 mtime），把每个『待决策问题』先区分为：已有记录→对齐执行（如规则已白名单但文件从未 add，落差本身就是核心发现）；无记录→按原则判（人写不可再生文本入库，可再生运行产物本地保留+补 ignore）；删除建议先核 liveness（近期时间戳、无进行中操作、dirty 状态）与磁盘余量，默认保守。本集两条初步判断被第一手记录反转，证明记录先于判断。

## Trigger
用户要求对仓库内容（文档、数据目录、运行产物、worktree、临时目录）给出入库/忽略/删除建议，且系统中存在可读的治理记录（ignore 文件及注释、同类排除先例、版本控制状态、文件时间戳）

## Discriminator
第一手读取的决策记录是否已直接回答该问题：ignore 文件中存在带意图注释的白名单/排除规则、同类大体量可再生产物已有排除先例、临时目录 mtime 显示为近期而非陈旧——任一命中即把『开放决策』坍缩为『对齐执行』或『不可删』

## Short path
- 建议形成前先读决策记录：ignore 规则+意图注释、同类产物的既有排除先例、status/分支状态、删除候选的 mtime 与进行中操作标记（如 rebase 目录是否存在）
- 逐项对照分类：记录已明确收录→对齐执行补纳入；有排除先例的可再生产物→本地保留+补 ignore；无记录→按『人写不可再生入库、可再生本地留』原则判
- 发现记录与现实不一致（规则存在但内容从未纳入版本控制）时，把『决策-执行落差』作为核心发现报告，而非重新发起决策
- 删除类建议先核 liveness：最近时间戳、无进行中操作、dirty 文件计数、磁盘余量；磁盘充裕且误删代价非零时默认保留并给验证步骤（如先 diff 再删）
- 每条建议附其记录/事实依据，全部可溯源即停止，不再枚举新候选

## Stop conditions
- 每个建议项都能引用具体记录（规则行/先例/状态/时间戳）或『明确原则+已验证事实』，无一依赖未验证的陈旧/未决假设
- 所有决策-执行落差已列出并报告，无剩余未分类候选

## Verification
- 用 check-ignore 类命令复核所声称的收录/排除状态与最终建议一致
- 逐个删除候选复核 mtime、进行中状态、dirty 计数，确认不存在『近期却被判为陈旧可删』的反例
- 抽查被建议入库的内容类型（纯文本、无大二进制），确认与记录意图（如『文本资产保全』）相符

## Counterexamples
- 新仓库无任何 ignore 惯例或意图注释——没有记录可对齐，须与用户从原则出发决策，不得虚构权威先例
- 用户明确要求重新评估既有策略（记录可能已过时违背当前意图）——记录是待呈现的冲突证据，而非直接执行的结论
- 磁盘真正紧张（余量低）时删除收益上升，『默认保守保留』分支失效，需按空间收益重排优先级
- 目标内容性质未知且记录无注释——白名单/排除规则的意图无从判定，须先探内容类型再归类
````

- verdict(`a5f0a69da346`)：APPLY / SKIP　理由：…

## 10. `44a7a3fecceb`

**【任务】**

User reports a service/session as unresponsive (no model work visible; a session/UI element vanished). Status output already exposes process lifecycle metadata (per-service started_at, restart receipts), and the event stream shows the affected session's activity stopping — repeated pre-call events with no completion events — near one of those lifecycle timestamps.

**【方法卡】**

````
name: align-session-gap-with-restart-timestamps-before-broad-search
method_id: align-session-gap-with-restart-timestamps-before-broad-search-73202fbb57ff
description: For 'service/session appears dead' reports, first align the failure window with process lifecycle metadata already visible in status outputs (started_at, restart receipts) and with the session's event-stream gap (activity stops without completion events). If the gap sits on a restart boundary, read that process's lifecycle-specific artifact (exit/shutdown log, restart receipt) at those timestamps before any directory enumeration or record-store keyword search; broaden only if that artifact is absent or cannot explain the symptoms.

## Trigger
User reports a service/session as unresponsive (no model work visible; a session/UI element vanished). Status output already exposes process lifecycle metadata (per-service started_at, restart receipts), and the event stream shows the affected session's activity stopping — repeated pre-call events with no completion events — near one of those lifecycle timestamps.

## Discriminator
Knowledge-at-time: before any log was opened, the runtime status already showed both frontend service processes had same-day started_at timestamps (i.e., a mid-session restart), and the event stream showed the affected session emitting repeated pre-call events (message-building) with zero completion events — an activity gap aligned with that process turnover. This pair alone narrows 'why no response' from 'anything (model/network/UI/storage)' to 'what the outgoing process did at shutdown', and names the artifact to read: that process's exit/shutdown log.

## Short path
- Read runtime/process status: confirm the stack is alive; record each service's started_at / restart receipts as candidate lifecycle boundaries.
- Read the event stream for the affected session's window: determine whether activity stops silently (pre-call events present, completion events absent) and where the last activity sits.
- If the gap boundary coincides with a lifecycle timestamp, go directly to that process's exit/shutdown log and service log at that boundary — do not enumerate the project directory or keyword-search record stores first.
- Extract the causal shutdown evidence (forced kill after grace timeout / graceful-shutdown timeout cancelling in-flight tasks) and confirm the process generation change via restart receipts and pids.
- Sanity-check current health (other sessions completing normally) to separate 'was broken then' from 'still broken now', then report; stop once symptoms are explained.

## Stop conditions
- A verified lifecycle event coincides with the session's last-activity boundary and each reported symptom is explained (silent run = in-flight stream cancelled; vanished session = severed frontend connection; missing work = output never persisted).
- The lifecycle-aligned artifact is missing, rotated away, or contains no cancel/timeout around the boundary — stop this method and switch hypotheses.

## Verification
- Cancel/timeout/kill entries must timestamp inside the aligned window and belong to the pre-restart process; pid/generation must match the restart receipts.
- Every user-reported symptom must map onto the same lifecycle event; any unexplained symptom keeps the investigation open.

## Counterexamples
- Status shows no restart near the failure window (process start predates all failures): the gap must be explained by upstream request errors or network (e.g., connection-refused retry clusters), not shutdown cancels.
- Event stream shows explicit per-request errors/timeouts instead of a silent gap: read upstream/request error logs; exit logs are irrelevant.
- The gap is explained by a user-initiated interruption that cleanly resumed afterward: no service fault; do not hunt restart evidence.
````

- verdict(`44a7a3fecceb`)：APPLY / SKIP　理由：…

## 11. `aeeb08e9bcf3`

**【任务】**

用户提出对过去工作/设置的存在性核查问题（"之前不是配置过/决定过 X 吗？"），需以记录检索证否或证实；且可检记录面数量有限、可枚举（会话 Evidence、归档、docs、配置文件），不存在并发写者。

**【方法卡】**

````
name: absence-proof-store-coverage-then-conclude
method_id: absence-proof-store-coverage-then-conclude-f0f333894129
description: 用户问"我们之前是不是设置/决定过 X"这类历史存在性核查时，结论由权威记录面的一次性覆盖决定：每个不同记录面（会话Evidence、归档、docs、工作区配置）用一条含同义词的复合查询各查一次。当所有面均未命中、且回执已浮出与用户措辞部分吻合的邻近记录（可解释记忆来源）时，否定结论即已确立：停止发现、不再排队后续读取，直接从现有回执提炼"不存在 + 疑似混淆源"作答。检索回执（如 docs 参考引导列表）常已含足够解释材料。

## Trigger
用户提出对过去工作/设置的存在性核查问题（"之前不是配置过/决定过 X 吗？"），需以记录检索证否或证实；且可检记录面数量有限、可枚举（会话 Evidence、归档、docs、配置文件），不存在并发写者。

## Discriminator
两个同时成立的当时已知事实：(1) 每个不同的权威记录面都已被恰好一条复合查询（含中英文同义词）覆盖且全部未命中；(2) 某条回执（如 docs 检索的参考引导列表）已展示一条标题/主题/决策行与用户措辞部分吻合、但作用对象不同的记录——即候选混淆源。此时更多搜索或排队更多读取不可能改变是/否结论，只会延迟。

## Short path
- 把用户声称的设置拆成中英+同义关键词，列出全部权威记录面——未知量：该设置可能被记录在哪类面？
- 每个面执行一次复合查询并记录命中/未命中——未知量：任何面是否存在该记录？
- 全部未命中后检查已有回执：是否已含与用户措辞部分吻合的邻近记录——未知量：用户记忆的真实来源是什么？
- 用回执中的标题/决策行（必要时仅单次读取该记录做内容级确认）比对"吻合部分 vs 不吻合部分"，形成混淆源归因
- 结合相邻已知事实（如 provider 配置目录无 OpenAI）给出"不存在该设置 + 疑似与 Y 混淆"及后续选项，立即停止

## Stop conditions
- 所有可枚举记录面均已恰好一次覆盖且未命中，且回执或一次确认读取已建立邻近记录与用户措辞的部分吻合关系
- 用户所需的"是否存在"已由覆盖性否定证据 + 混淆源解释共同回答，不再声明任何待执行的后续动作

## Verification
- 复核每个记录面确实各被查询过：无遗漏面、无仅靠单一措辞覆盖的面（中英同义已并入查询）
- 混淆源归因只基于回执已展示的标题/摘要/决策行或一次实际读取，而非臆测内容
- 结论输出前确认没有遗留"已声明待执行"却未兑现的动作（self-history 中不应出现重复 pending 项）

## Counterexamples
- 记录可能存在于未被全文索引的位置（源码、git 历史、外部系统、聊天导出）：一次未命中不能证否，需直接检查最可能路径
- 用户点名了具体工件（某文件/端点/配置项）：应直接读该工件，而非做面级搜索后靠回执推断
- 检索工具有已知盲区，或记录措辞语言与查询不一致且未做同义覆盖：未命中证据力弱，不可立即下否定结论
- 目标是存在并发写者的共享资源上的终局性断言：须按 fresh-read 原则在成稿时重读权威记录，而非依赖检索回执
````

- verdict(`aeeb08e9bcf3`)：APPLY / SKIP　理由：…

## 12. `b39949ff3dc1`

**【任务】**

在代码/证据库用 content 搜索定位规则、实现或入口；且此前回执或用户原话已展示可逐字复用的 token（标识符、原文短语、路径）

**【方法卡】**

````
name: anchor-content-search-on-observed-literal-tokens
method_id: anchor-content-search-on-observed-literal-tokens-8d7925c691d2
description: content 类搜索是字面子串匹配，不是语义检索。每次构造查询词必须逐字取自已观察材料：此前命中行的原文短语、用户原话中的标识符、import/docstring 中的符号名、回执中的精确路径。概念级检索要锚定『必然与目标同现的 token』（规则 ID、函数核心名、路由路径），而非把概念翻译成自拟自然语短语或猜测完整函数签名。一次无匹配后，先从已有回执提取更准 token，再发下一次查询。

## Trigger
在代码/证据库用 content 搜索定位规则、实现或入口；且此前回执或用户原话已展示可逐字复用的 token（标识符、原文短语、路径）

## Discriminator
回执本身证明 content 为字面匹配（无匹配回执显示 content=...）；且已观察命中行中存在与目标同现的逐字 token——本集第 1 次命中行已逐字给出权威短语『不因 accepted 放宽』与精确路径 src/llm_loop/...，随后仍用释义词『审批不放宽』、猜测名『def _evolve_review』、探索性 ls llm_loop/ 各浪费一次调用

## Short path
- 用用户原话中的精确标识符（requires_human）做首次定位（未知量：规则实现在哪）
- 直接复用命中行中逐字出现的短语/ID（『不因 accepted 放宽』）二次定位铁律落点（未知量：判定顺序在哪定义）
- 读定义文件，从 docstring/import 提取符号名与命令名（未知量：入口在哪）
- 入口定位用稳定核心 token 做多选一 grep（evolve_review|evolve-review|evolution/review），不猜完整签名
- 取证覆盖定义+入口+文档三层后停止搜索，进入修改

## Stop conditions
- 精确 token 检索已命中定义处并读取到判定代码
- 连续 2 次未锚定查询无命中时，禁止第三次猜测，强制改从回执提取 token 或直接读已见路径

## Verification
- 回查每次查询词能否在此前回执/用户原话中逐字找到；找不到即为违规查询
- 无匹配次数应为零或仅首探性一次；按本集最短路径可省 ≥3 次失败调用

## Counterexamples
- 全新主题、已观察材料中目标概念零字面出现：只能先做宽概念词枚举，锚定规则无从谈起
- 工具本身是语义/向量检索：逐字短语锚定反而收窄召回，应按语义表述查询
- 已有直接 provenance（import 边、路由表、回执中完整路径）：直接读文件比再发一次搜索更短
````

- verdict(`b39949ff3dc1`)：APPLY / SKIP　理由：…
