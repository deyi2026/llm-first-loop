# Blind batch 3/3

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. 299f7cddac23

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

## 2. d205979ff96e

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

## 3. aa947481ca45

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

## 4. ded7907eee4f

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

## 5. db50b0a1d2ed

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

## 6. 3a3d0c248801

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

## 7. 151490f348ca

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

## 8. 4966e1595ecb

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
