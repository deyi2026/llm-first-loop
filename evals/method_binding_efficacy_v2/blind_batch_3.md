# Blind batch 3/4

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. b5bafc6128e9

TASK

需要在受管 desired-state 系统执行 publish/restart；工具 schema 只暴露 status/restart，源码注明 desired 由 operator 发布。任务是先判动作权限归属，不涉及长文件写盘。

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

## 2. 985377af6b96

TASK

用户问还是连不上要不要重启。系统没有 authoritative status/dashboard 可用，但监督者显示进程 running，且公网端到端探测得到应用级 HTTP 303。需要据此决定是否重启。

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

## 3. 0c5feb2f4dc7

TASK

用户说把前两个收口项完成；当前对话缺少那个清单，但 active Goal 回执已经列出恰好两个对应条目、各自完成时间，且 open=0。需要直接映射并回答。

METHOD CARD

name: anchor-sufficiency-stop
method_id: anchor-sufficiency-stop-959b50a21a4c
description: 对用户回指型短发言（依赖先前讨论）做 grounding 时：一次主题 memory 检索若返回当天/本会话的精确主题锚点，指代未知量即告解决；一次 docs 检索若未命中但返回的目录列表已含同线文档名，该列表即足够 provenance。两种情形下都停止对同一工具换同义词重查，直接组织回应。本集可省 1-2 次零信息检索。

## Trigger
用户发出简短、回指先前讨论/决策的发言（如'必要的规则还是得优先注入'），需先定位所指的既有决策再回应；且检索工具的未命中结果会附带完整的最近条目/目录列表

## Discriminator
首次 memory 主题检索的顶部命中是否为'当天或本会话内、主题与发言关键词精确对应'的锚点记录；或首次 docs 检索虽未命中、但返回的目录列表中已含与主题同线的文档名——任一成立即信息已足，此时对同一工具换同义词重查只会返回相同列表或更旧的无关记录

## Short path
- 识别发言为回指型，定义未知量 U1=它修订/补充的是哪条既有决策；做一次带主题关键词的 memory 检索（可与 get_goal 等廉价状态检查并行）
- 顶部命中为新鲜（当天/本会话）精确主题锚点 → U1 已解，不再对 memory 换词做第二次枚举
- 如需正式文档佐证：仅做一次 docs 检索；未命中但列表已给出相关 SPEC 名称即为足够 provenance，不换词重查同一工具
- 以'发言是对锚点的补充/边界而非推翻'为框架组织回应，抛出需先钉死的定义问题后停止

## Stop conditions
- 回指未知量已被一条新鲜且主题精确的锚点记录解析，且跨来源核对（至多一次）结果不与锚点矛盾
- 检索未命中但已取得含相关条目的完整目录列表，且无更细粒度的直接读取手段

## Verification
- 最终回应引用的每条依据均可追溯到已取得的锚点记录或列表条目，无凭空引用
- 复盘确认不存在'同一工具仅换参数的第二次调用'其返回与首次完全相同（如两次未命中+同一列表）或其结果未进入最终回应

## Counterexamples
- 锚点记录陈旧（数周前）或仅关键词相邻而非精确同题：主题可能已演进，补一次不同切面的检索是合理的
- 用户发言与锚点冲突而非补充：必须先检索是否存在更新的取代性决策，单锚点不足以裁决','任务本身要求穷尽相关规则/文档清单（如撰写需引用全部相关 SPEC 的综述）：枚举即目标，本停止规则不适用

## 4. c8e632597e27

TASK

用户用一句很短的回指继续之前讨论，首次 memory 检索已经返回当天精确主题锚点；任务是停止继续检索并直接组织回答，不存在来源不明 artifact。

METHOD CARD

name: attribute-artifact-via-unique-token-before-impl-deep-read
method_id: attribute-artifact-via-unique-token-before-impl-deep-read-28d50e49311f
description: 面对来源不明的观测 artifact（日志行/审计记录），且任务结论依赖其写入者归属时，先用行内全局唯一 token 做跨线归因（git log --all -S / 跨 worktree 精确 grep），再决定读哪份实现。artifact 自带的测试特征（占位工具名、单 pid 毫秒级突发）可先行降级其“生产信号”地位。多部署线仓库中，未归因就深读某一条线的实现，容易把 A 线数据套在 B 线代码上，发现 token 缺失后才返工归因。

## Trigger
拿到一条或一组观测 artifact（如审计 ledger、事件日志），其写入代码线未确定，且任务问题（该数据是否代表生产行为、对应机制是否影响目标指标）依赖写入者归因；仓库存在多条部署线/worktree；artifact 内含罕见字面 token。

## Discriminator
第一跳工具结果中已可见：ledger 行含全局唯一 kind 名（receipt_pointer）、占位工具名 "xyz"、全部 7 条来自单 pid 的毫秒级突发；同时已给出当前部署 worktree 标识，且仓库存在 .worktrees 多线。这些当时已知事实足以先用唯一 token 一次 pickaxe 定位写入 commit，并预判数据为测试写入，而不必先深读主线实现再事后发现 token 缺失。

## Short path
- 读 artifact 本体，提取唯一 token 与元数据（pid/ts/工具名/来源标签）；未知量：这是谁写的、代表生产还是测试？
- 用唯一 token 做全历史/全 worktree 归因（git log --all -S <token> 或跨 worktree 精确 grep）；未知量：写入 commit 与所在线。
- 对比写入线与当前部署标识；若不在运行线，则 artifact 降级为“候选线功能存在性证据”，与生产行为解耦，不再用其推断生产。
- 对真正运行线只核验会到达 wire 的注入路径：落点（前缀区/尾部追加）、确定性（一次冻结/每轮重渲染）、默认开关态。
- 取运行时指标验证时，先按会话 id 列目录定位日志文件（不猜扩展名，滚动分段目录是常见形态），构造层+实测层双确认即停。

## Stop conditions
- artifact 已归因到具体 commit/线，且其与当前生产部署的关系（在/不在运行线）已明确判定
- 运行线实际注入面的 wire 影响（位置/确定性/默认态）已由源码确认，并有运行时锚点指标（如前缀指纹不变率）佐证

## Verification
- 归因 commit 所在 worktree 与当前部署 worktree 不一致时，记录两者部署标识差异作为解耦证据
- 实测指标窗口覆盖含注入/失败事件的轮次，且前缀指纹等锚点指标在窗口内保持不变

## Counterexamples
- 仓库只有一条部署线且唯一 token 一击即中实现：归因平凡，直接读实现挂点即可，全历史 pickaxe 是多余开销
- 任务只问 artifact 的语义（这行记录是什么意思）而不问写入者或生产影响：读 schema/注释即可，无需作者归因
- token 是常见词（如 error/cache）不具备唯一性：git log -S 机制失效，需组合更长唯一串或改用结构化字段（pid、路径、事件名组合）归因

## 5. 6f096e5b8b23

TASK

用户要求终止两个数字标识，但目前不知道它们是 PID 还是端口；任务是先做身份映射再决定是否 kill，不涉及任何 UI 文案或前后端数据源。

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

## 6. 7071083a3752

TASK

一个受管服务刚完成重启，部署记录已经给出 runtime_root、git_head；现在只需要从当前进程列表验证所有目标实例是否运行在该部署身份上。没有要解释的跨代日志或历史连接证据。

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

## 7. 941899b88528

TASK

要通过 shell heredoc 写一份约 120 行文档；历史上出现 exit 0 但文件只写了 8 行的输入截断。任务是分块写入并逐块核行数；不是读取 pytest/命令输出被截断。

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

## 8. de61d84f462b

TASK

要把版本号在 pyproject、源码常量和 README 三个表面同步替换；预检 grep 已给出每个完整字面行，任务是替换并逐表面验证，不存在异步 action_id。

METHOD CARD

name: async-action-terminal-ledger-first
method_id: async-action-terminal-ledger-first-7f9a435b6e99
description: 异步两阶段动作（restart/publish/deploy 类）的受理回执不等于终态。当被问"上次是否成功/是否被记录/为何没反馈"时，不要从全局健康快照或重新发现入手：沿 action_id -> 专属台账记录读终态与失败原因，再用同一 id 逐一核对各反馈通道（事件流/待办队列/开场注入），得出"已落盘但通道断"的结论。沉淀 verified 经验时必须在同一次写入附 evidence，避免参数被拒后重试。

## Trigger
用户询问此前发起的异步动作的最终结局、是否留痕或为何未被反馈；或异步动作已受理回执但尚未确认终态、需要闭环时。

## Discriminator
当时已知：会话内 event_trace/上一轮回复已明确该动作的 action_id、其专属台账文件路径（如 service-control-actions/<id>.json）及 status=failed。该事实可立刻把"所有可能相关信号"缩为"一份权威终态记录 + N 个指定反馈通道"，无需重新 grep 发现路径，也无需先拉全局审计快照。

## Short path
- 用会话内已见的 action_id 直接读其专属台账记录，取得终态 status 与失败原因（未知量：最终结局）
- 若终态 failed，用同一 id 逐个核对指定反馈通道：事件流检索、pending 队列字段、会话开场注入（未知量：哪个通道断了）
- 对照得出"已落盘但无通道主动推送"，并归因（受理回执不含终态、执行发生在发起会话之外）
- 沉淀经验/提交改进时，evidence 引用与结论同一次写入，verified 状态不再被参数校验拒绝
- 终态经权威记录验证、通道核对完毕且留痕被接受后停止

## Stop conditions
- 权威台账中的终态与期望版本/id 一致（succeeded），或失败原因已定位并可复述证据链
- 所有指定反馈通道均用同一 action_id 核对完毕并能解释静默原因
- 经验/改进写入被接受且携带 evidence，无遗留未验证断言

## Verification
- 台账的 status/updated_at 与事件时间线相互印证
- 每个通道的查询使用同一 action_id，结果能回答"为何没反馈"而非泛泛健康信号
- 写入类调用一次成功（含 evidence），未出现 verified-without-evidence 类参数拒绝

## Counterexamples
- 同步动作的回执本身已含终态：读回执即停，不需要再追台账
- 用户问的是"现在什么东西坏了"且无具体 action_id：此时全局健康/审计扫描是正确起点，本方法不适用
- 台账本身疑似过期或损坏：应交叉核对活体进程（PID/版本/运行状态），不能只信台账记录

## 9. 60d373c6e982

TASK

用户询问此前发起的异步动作的最终结局、是否留痕或为何未被反馈；或异步动作已受理回执但尚未确认终态、需要闭环时。

METHOD CARD

name: async-action-terminal-ledger-first
method_id: async-action-terminal-ledger-first-7f9a435b6e99
description: 异步两阶段动作（restart/publish/deploy 类）的受理回执不等于终态。当被问"上次是否成功/是否被记录/为何没反馈"时，不要从全局健康快照或重新发现入手：沿 action_id -> 专属台账记录读终态与失败原因，再用同一 id 逐一核对各反馈通道（事件流/待办队列/开场注入），得出"已落盘但通道断"的结论。沉淀 verified 经验时必须在同一次写入附 evidence，避免参数被拒后重试。

## Trigger
用户询问此前发起的异步动作的最终结局、是否留痕或为何未被反馈；或异步动作已受理回执但尚未确认终态、需要闭环时。

## Discriminator
当时已知：会话内 event_trace/上一轮回复已明确该动作的 action_id、其专属台账文件路径（如 service-control-actions/<id>.json）及 status=failed。该事实可立刻把"所有可能相关信号"缩为"一份权威终态记录 + N 个指定反馈通道"，无需重新 grep 发现路径，也无需先拉全局审计快照。

## Short path
- 用会话内已见的 action_id 直接读其专属台账记录，取得终态 status 与失败原因（未知量：最终结局）
- 若终态 failed，用同一 id 逐个核对指定反馈通道：事件流检索、pending 队列字段、会话开场注入（未知量：哪个通道断了）
- 对照得出"已落盘但无通道主动推送"，并归因（受理回执不含终态、执行发生在发起会话之外）
- 沉淀经验/提交改进时，evidence 引用与结论同一次写入，verified 状态不再被参数校验拒绝
- 终态经权威记录验证、通道核对完毕且留痕被接受后停止

## Stop conditions
- 权威台账中的终态与期望版本/id 一致（succeeded），或失败原因已定位并可复述证据链
- 所有指定反馈通道均用同一 action_id 核对完毕并能解释静默原因
- 经验/改进写入被接受且携带 evidence，无遗留未验证断言

## Verification
- 台账的 status/updated_at 与事件时间线相互印证
- 每个通道的查询使用同一 action_id，结果能回答"为何没反馈"而非泛泛健康信号
- 写入类调用一次成功（含 evidence），未出现 verified-without-evidence 类参数拒绝

## Counterexamples
- 同步动作的回执本身已含终态：读回执即停，不需要再追台账
- 用户问的是"现在什么东西坏了"且无具体 action_id：此时全局健康/审计扫描是正确起点，本方法不适用
- 台账本身疑似过期或损坏：应交叉核对活体进程（PID/版本/运行状态），不能只信台账记录

## 10. 4b5a887b25f0

TASK

需要用 shell heredoc/cat 把长文档（数十行以上）写入文件交付物，或对一次写盘后的内容完整性没有独立回执、只能靠 exit 0 判断的场景。

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
