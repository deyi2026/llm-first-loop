# Blind batch 4/4

Return one JSON object per case with opaque_id, verdict APPLY|SKIP, and one-line Chinese reason comparing task purpose with Method purpose.

## 1. b8c08c09f876

TASK

浏览器重启后，.env 中记录了当前 CDP URL 与 TARGET_ID。任务是读取这些值并验证端点和目标仍保持同一绑定。

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

## 2. 9385ddfb3f25

TASK

分析报告中的事实声明都带 commit/hash/URL/内部 ID。任务是逐个解析这些指针，以权威来源给出证实、证伪或证据缺口。

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

## 3. 70b6a51b1e66

TASK

同一个版本号需要同步到 pyproject、源码常量和 README；预检 grep 已列出三处完整字面行。任务是完成替换并逐表面核对新值。

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

## 4. b76b8de38dd0

TASK

本轮改动的定向测试全绿，更大测试集出现已知失败清单。任务是用 touched set 与 clean HEAD 对照判定这些失败是否由本轮改动引入。

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

## 5. 35401242d2d9

TASK

用户说把前两个收口项完成；active Goal 回执恰好列出两个已完成条目和时间戳。任务是把这两个条目映射到用户回指并直接答复。

METHOD CARD

name: anchor-verification-over-narrative-recovery
method_id: anchor-verification-over-narrative-recovery-73fa76a07438
description: 核对'过去的建议/交付是否落实'时，不要循环恢复旧报告全文：首次截断或检索无命中后，把旧报告当作待验证的声明清单而非证据。从预览与 git 历史提取每条建议的可查锚点（fix commit、record/EVO id、部署 gen/head、job id），逐个到权威源验证（git show / branch --contains、records 检索、status 回执）。验证通过→已落实；验证失败（如修复 commit 不在部署线上）→该失败本身即下一步行动项。若一致性检查（declaration_check）已标记旧报告含与回执不符的声明，则恢复原文更无证据价值。仅当某条建议不存在任何机器可查锚点时，才升级为更宽的原文恢复或向用户确认。

## Trigger
用户要求确认'此前交付/建议是否已落实'，而过去的自述报告仅以截断形式存在（事件流折叠、日志截断）或 evidence 检索无命中，但预览或仓库历史中已可见报告所指涉的锚点（commit hash、记录键、部署代次、任务 id）

## Discriminator
一次恢复尝试已返回截断或无命中，且更早已可见两个事实：(1) declaration/consistency check 已标记该旧报告含与工具回执不符的完成声明——原文不具证据效力；(2) 预览与 git 历史已暴露每条建议的锚点（修复 commit 的权威 commit message、EVO id、gen/head、服务状态回执），每个锚点都可在权威源直接查询。二者合起来表明：验证锚点比恢复散文更便宜且更权威

## Short path
- 读当前权威回执（部署状态、服务 code_current、pending 队列），确立'现在'的真值基线
- 对旧报告至多做一次恢复尝试；无论成败，从预览与相关 git 历史提取每条建议的锚点：fix commit、EVO/record id、部署 gen/head、job id
- 逐锚点查权威源：git show 取修复的权威描述；git branch --contains 判断是否进入部署线；search_records 判断登记是否闭合；status 回执判断服务新旧
- 分类输出：源验证通过→已落实；验证失败（如修复不在部署线）→直接定义为下一步行动项，进入执行
- 仅当某条建议没有任何机器可查锚点（纯方向性建议）时，才升级为更宽的原文恢复或向用户澄清

## Stop conditions
- 每条建议都已映射到一个权威源的验证结果（git 输出 / 记录查询 / status 回执），状态表完全不依赖恢复出的报告原文
- 所有验证失败的条目均已转为明确的下一步行动并开始执行

## Verification
- 最终逐项'已落实/未落实'结论均引用 live 权威回执（branch --contains 输出、records 查询结果、服务 status），而非恢复的叙事文本
- 对每条'已落实'声明，核验所用权威源与该建议指涉的对象是同一锚点（同一 commit、同一记录键、同一服务）

## Counterexamples
- 用户要的就是上一轮报告的原文内容（原文本身即交付物）→ 恢复原文就是任务，本方法不适用
- 建议条目无任何机器可查锚点（如'以后考虑引入 A/B 评估'）→ 锚点验证无法分类，必须依靠原文或用户澄清
- 预览与历史中完全提取不出锚点（报告只以不可检索的摘要存在）→ 此时扩大恢复范围（提高 event limit、evidence 检索）才是正确的升级路径，而非强行套用锚点验证

## 6. f5415533ffde

TASK

CI workflow 正在后台运行，release artifact 由成功终态产生。任务是查询 workflow conclusion，并依据终态决定后续处理。

METHOD CARD

name: bounded-probe-before-blocking-retry
method_id: bounded-probe-before-blocking-retry-e3e7b0a91b65
description: 重试一个此前挂死/超时的阻塞式网络操作（如 git fetch）前，先对同一依赖主机发一条有界廉价探针（curl -m 8，host 取自 remote get-url 的真实远端）做故障分类：exit 28/0字节/http 000 = 传输层断；拿到任何 HTTP 状态码 = 传输层通、问题在应用层。探针不通就跳过阻塞重试，不烧满 60s 工具超时；并把探针写成退避闹钟的前置条件，让未来自动唤醒自门控（不通即放弃、不再续设）。探针通再执行原操作，若仍失败则转应用层诊断。

## Trigger
到点要重试一个上一轮已挂死或超时的阻塞式网络操作（fetch/push/长请求），或要为这类操作设置自动退避重试闹钟。

## Discriminator
本次动作是'重试'且上轮症状是挂死而非明确报错（材料中助手自述'网络路径还没恢复'，说明先前已知疑似断网）——失败模式尚未分类。一条 ≤8s 的有界探针（对 remote get-url 得到的真实 host 发 curl -m 8）即可把'本机到远端网络层断 vs git/凭证问题'缩成一类：探针 000/超时即网络层，无需用 60s 阻塞超时去换这个结论。

## Short path
- 唤醒/到点时先确认：这是对已挂死操作的重试，未知量=故障原因是否已恢复，而非'操作会不会成功'。
- 单命令有界探针：git remote get-url 取真实 host + curl -m 8 探该 host + 顺带读当前 refs 做基线；≤8s 完成传输层/应用层分类。
- 探针 000/超时 → 不执行阻塞 fetch（省掉 60s 挂死）；判定网络层断，设退避闹钟并把'先探针、不通即本次放弃不再续设、通了只动 refs 后停手等裁决'写进前置条件。
- 探针通 → 执行原操作（限定 scope，如仅 fetch --prune）；若仍失败，按应用层/凭证路径诊断。
- 停止：故障已分类、下次重试已带探针门控、当前 refs/状态已汇报。

## Stop conditions
- 探针结果已给出唯一故障分类（传输层 vs 应用层），不再重复同类探测或盲试阻塞操作。
- 退避闹钟已含探针前置与明确放弃分支；本轮不再手动重试。
- 操作成功完成且结果已与重试前的 refs/SHA 基线核对无部分副作用。

## Verification
- 探针 host 必须取自 remote get-url 的真实目标，而非泛互联网连通性（避免代理规则差异导致误判）。
- 分类规则显式化：curl exit 28/0 字节/http 000 = 传输层断；任何 HTTP 状态码（含 4xx/5xx）= 传输层通。
- 闹钟文本包含探针命令、不通时的放弃分支、通时操作完成后的停手点（汇报分叉、等用户裁决）。
- 重试前后 refs/SHA 一致性核对，确认挂死的操作没有留下半完成状态。

## Counterexamples
- 首次执行（无先前失败）：直接执行即可，先探针是纯增延迟、无信息增益。
- 上轮是明确应用层报错（403/凭证拒绝/冲突，非挂死）：传输探针通了也不预示成功，应读错误本身做诊断。
- 操作自带短超时或异步非阻塞：直接重试比'探针+重试'两跳更便宜。
- 探针与目标操作走不同代理/路由路径时，探针成功不能证明操作可达，需同路径探测，否则分类失真。

## 7. 3639d7388503

TASK

此前 complete 动作已经发出，当前有 action ID 与状态存储入口。任务是读取该 ID 的最新记录并决定后续状态迁移。

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

## 8. 81fbc7109e80

TASK

服务重启回执给出目标 generation、runtime_root 与 git_head。任务是从进程列表核对所有目标实例是否运行在这组部署身份上。

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
