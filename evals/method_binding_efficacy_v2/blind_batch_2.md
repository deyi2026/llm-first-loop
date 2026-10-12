# Blind batch 2/4

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. b970ae014e14

TASK

某门禁脚本依赖只存在于分支 X 的 artifact；当前 cwd 在分支 Y，直接运行会报 working tree 找不到文件。任务是先把执行上下文绑定到 artifact 所属 ref/worktree 再运行门禁；并不存在文件缺一族锚点的 checker 断言。

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

## 2. efd1d51dcf17

TASK

一个 complete 动作此前已经发起，结果存疑；当前有唯一 action ID。需要先按裸 ID 取最新状态决定是否已经完成，而不是处理 requires evidence/reason 参数缺失。

METHOD CARD

name: batch-complete-required-fields-on-parameter-rejection
method_id: batch-complete-required-fields-on-parameter-rejection-71b35b88bd44
description: 对状态变更类 control API（closure/acknowledge 类）首次调用前，先从工具 schema/help 或既往回执枚举必填字段全集；若已被 'requires <field>' 类错误拒绝，把错误当作部分 schema，一次补齐所有必填字段（含语义成对字段如 evidence+reason），而不是每次只补一个字段、靠连续拒绝逐个学参数。本集把 3 次闭合调用缩为 1 次。

## Trigger
需要在本会话中首次调用某个会改变系统状态的管理/闭环 API，其必填参数尚不完全可知；或调用刚被 'requires evidence/reason/...' 这类参数缺失型错误拒绝，正准备重试

## Discriminator
拒绝信息是显式的参数 schema 提示（点名缺失字段），而非状态冲突或权限错误——这意味着正确的下一步是补全参数而不是换动作；同时该类闭环 API 的回执/文档惯例是 evidence 与 reason 成对必填

## Short path
- 诊断阶段保持原路径：沿 provenance 读失败动作台账，找到持有 admission barrier 的具体 action_id（本集此段高效，不变更）
- 首次调用变更类 API 前，从工具 schema/help/同类回执确认必填字段全集（本例为 evidence + reason）
- 一次调用同时提供全部必填字段闭合过期单，消除 '每次拒绝学一个字段' 的串行试错
- 受理新单后按成功回执内嵌的指引异步核对终态（status, action_id=...），未查到 succeeded/failed 不宣布结果

## Stop conditions
- 变更调用返回 accepted:true / verdict:accept，且后续受理动作不再出现 barrier 冲突
- 补全字段后仍失败且错误类型不再是参数缺失（转为状态/权限冲突）→ 停止补参数，转向冲突诊断
- 用户问题所需事实已由权威回执确认，不再追加确认性查询

## Verification
- 重试一次即通过，不再出现第二个字段缺失型拒绝
- barrier 释放被间接验证：下一个受理动作成功 accepted
- 异步终态通过 status(action_id=...) 或 event_stream 核对，而非假设完成

## Counterexamples
- 工具是 strict schema、对多余字段报 unexpected keyword → 只补错误点名的字段，不得批量猜测
- 拒绝原因是状态冲突或权限不足而非缺参数 → 补字段无效，应改查状态/权限
- 只读查询类调用试错成本低 → 最小重试即可，先读文档反而绕远

## 3. 7f9879d49604

TASK

要验证重启后的 CDP 端点与 TARGET_ID 是否仍匹配，且 .env 已给连接参数；没有 kill/清理动作，也不存在把端口误当 PID 的风险。

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

## 4. d4f5cb3c0d3c

TASK

用户只问系统现在健不健康。系统本身已经有一个权威状态接口直接返回 healthy/status，我需要决定是否还值得展开更宽的诊断。

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

## 5. efdf84f769b4

TASK

CI 在后台执行，目标文件只有流水线成功才会生成。我正准备每隔几十秒检查一次文件是否出现，但流水线自身的 run 结论其实可查询。

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

## 6. 5b94341349ed

TASK

拿到一条或一组观测 artifact（如审计 ledger、事件日志），其写入代码线未确定，且任务问题（该数据是否代表生产行为、对应机制是否影响目标指标）依赖写入者归因；仓库存在多条部署线/worktree；artifact 内含罕见字面 token。

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

## 7. a3892e6fad72

TASK

要把同一个版本号从旧值改成新值，旧字面量在多个文件中出现；预检 grep 已显示各目标行。目标是从这些已显示的字面行派生替换并逐表面复查，没有指标分母、行为语义或测试期望需要重新定义。

METHOD CARD

name: assertions-as-spec-first-for-behavior-edits
method_id: assertions-as-spec-first-for-behavior-edits-c1f836aa31cd
description: 修改既有行为/指标口径（分母、判定规则、文案）时，把测试断言点当作当前行为的权威契约：先做一次跨 src+tests 的 grep 定位目标符号的定义点与断言点，从断言中的期望值与 note 文案反推现行口径，再让实现与断言同批修改、三处口径一致（实现/断言/note），按受影响子集→全量顺序验证。避免先分块通读上千行源文件、最后才'看看测试了解现有规范'导致的口径返工与调用数膨胀。

## Trigger
任务为修改/优化既有实现中的行为或指标口径（如改某指标分母、判定规则、note 文案），且早前 find/grep 回执已列出对应测试文件；此时尚未查看这些测试对该符号的断言。

## Discriminator
测试中对目标行为存在精确断言（期望值、比率、note 文案），且这些测试文件路径在更早的列目录/find 回执中已出现——断言点本身就是'当前契约+必改面'，一次 grep 即可在通读源码前获得。本 episode 中模型读完两个约 540 行源文件后才执行 'grep honesty tests/unit/test_evaluator.py'，而该 grep 一次就给出了精确现行口径（含 note 原文）。

## Short path
- 把变更清单逐项映射到文件/符号（此类任务起点通常已有明确项列表）
- 对目标符号做一次 src+tests 的 grep，得到定义点与断言点清单
- 只精读断言点附近与定义点区域：从断言的期望值/note 反推当前口径（分母、单位、文案）
- 实现与断言同批修改，保持实现、断言、note/文档三处口径一致
- 先跑受影响单测子集，绿后再全量测试与 lint 各一次收尾

## Stop conditions
- 受影响单测子集通过，且 grep 确认 src 与 tests 中无旧口径残留字面值（旧期望值、旧 note 文案）
- 实现、断言、note 三处口径一致；全量 suite 与 lint 已各跑一次并绿

## Verification
- grep 目标符号及其 note/文案关键字，确认无旧口径残留
- 先跑受影响测试子集再跑全量；若有失败，先核对是否为断言与实现的口径差而非环境问题

## Counterexamples
- 全新功能/新增指标（无既有断言可作 spec）：grep-first 无对象，仍需按现有结构阅读源码并新写测试
- 纯结构重构、行为不变：断言是回归护栏而非变更面，通读定义仍然必要
- 目标文件很小或变更覆盖大半文件：整体阅读成本低，先读全文件不构成绕路，不必强套本方法

## 8. 0ee29cd6256c

TASK

用户报告外部访问失败并问是否要重启；监督者进程存活且公网端到端请求返回应用级 303，任务是据此否决重启并转查客户端路径，不涉及裸文件名引用。

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

## 9. a7ef9307788d

TASK

我要调整一个已有指标的分母与相关说明文字，测试目录里已经有对这个比率和 note 的精确期望，但我还没读这些断言。

METHOD CARD

name: assertions-as-spec-first-for-behavior-edits
method_id: assertions-as-spec-first-for-behavior-edits-c1f836aa31cd
description: 修改既有行为/指标口径（分母、判定规则、文案）时，把测试断言点当作当前行为的权威契约：先做一次跨 src+tests 的 grep 定位目标符号的定义点与断言点，从断言中的期望值与 note 文案反推现行口径，再让实现与断言同批修改、三处口径一致（实现/断言/note），按受影响子集→全量顺序验证。避免先分块通读上千行源文件、最后才'看看测试了解现有规范'导致的口径返工与调用数膨胀。

## Trigger
任务为修改/优化既有实现中的行为或指标口径（如改某指标分母、判定规则、note 文案），且早前 find/grep 回执已列出对应测试文件；此时尚未查看这些测试对该符号的断言。

## Discriminator
测试中对目标行为存在精确断言（期望值、比率、note 文案），且这些测试文件路径在更早的列目录/find 回执中已出现——断言点本身就是'当前契约+必改面'，一次 grep 即可在通读源码前获得。本 episode 中模型读完两个约 540 行源文件后才执行 'grep honesty tests/unit/test_evaluator.py'，而该 grep 一次就给出了精确现行口径（含 note 原文）。

## Short path
- 把变更清单逐项映射到文件/符号（此类任务起点通常已有明确项列表）
- 对目标符号做一次 src+tests 的 grep，得到定义点与断言点清单
- 只精读断言点附近与定义点区域：从断言的期望值/note 反推当前口径（分母、单位、文案）
- 实现与断言同批修改，保持实现、断言、note/文档三处口径一致
- 先跑受影响单测子集，绿后再全量测试与 lint 各一次收尾

## Stop conditions
- 受影响单测子集通过，且 grep 确认 src 与 tests 中无旧口径残留字面值（旧期望值、旧 note 文案）
- 实现、断言、note 三处口径一致；全量 suite 与 lint 已各跑一次并绿

## Verification
- grep 目标符号及其 note/文案关键字，确认无旧口径残留
- 先跑受影响测试子集再跑全量；若有失败，先核对是否为断言与实现的口径差而非环境问题

## Counterexamples
- 全新功能/新增指标（无既有断言可作 spec）：grep-first 无对象，仍需按现有结构阅读源码并新写测试
- 纯结构重构、行为不变：断言是回归护栏而非变更面，通读定义仍然必要
- 目标文件很小或变更覆盖大半文件：整体阅读成本低，先读全文件不构成绕路，不必强套本方法

## 10. 8b222bd93ad3

TASK

我要在带 generation 的受管 desired-state 系统上做 publish/restart，但当前只知道模型工具面有 status/restart，不确定发布动作是不是只能由 operator 完成。

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
