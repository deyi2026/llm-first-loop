# Harness Evolution 论文核验与 LFL v0 评测规格

- 日期：2026-09-16
- 状态：正文核验完成；v0 为待实现的 pilot 规格，不是运行结果或晋级批准。
- 关联提案：[PROPOSAL-20260916-harness-evolution-eval.md](PROPOSAL-20260916-harness-evolution-eval.md)
- 本地取证身份：mirror HEAD `832b4dfaa2d6dba8143bd91239aa0b22b8f8dbf9`；工作区有既存修改。该 SHA 是源码检查锚，不是生产进程身份认证。
- 本次范围：论文正文/附录、作者仓库 README、LFL 锚钉接线与已有 eval 协议；没有执行模型实验。

## 1. 原文已确认的事实

来源为 Wang 等人的 [arXiv 2607.12227v2](https://arxiv.org/html/2607.12227v2)，版本日期 2026-08-27，页面标注 CC BY 4.0。下表为压缩转述。

| 核验项 | 原文事实及定位 |
|---|---|
| K 与重复 | §4.1：K=5；AHE 每任务每候选 m=1；结果平均两次独立运行。各法共享初始 harness。 |
| 上限 | A.4 表4：context 200k；128k 是每个 model turn 的 generation 上限。Code/Debugger/Meta 最大 turns 分别为 300/25/500。 |
| held-out | §4.4：45 train / 10 validation / 34 test；train 优化，validation 选 harness，test 报告。 |
| 指标 | A.5：pass@1 为 rollout reward 均值；pass@k 为至少一次成功的任务占比；基础设施异常记失败。 |
| 新闻稿数字 | 表2：86.0 与 75.8 为两模型平均的 Parallel Sampling 与 Harness Evolution 的 pass@1 栏；表3：held-out 67.7→68.3，即 +0.6 个百分点。 |

**指标解释的必要限制：** §3.2/§4.3 的 Parallel Sampling 在有测试时经过 oracle 选择，表2 该方法 pass@1=pass@5；不能把 86.0 描述为未经搜索的首个 attempt 成功率。A.5 的均值公式与“完成整个搜索流程后输出”的统计单位需区分。[原文 §4.3 与 A.5](https://arxiv.org/html/2607.12227v2#S4.SS3)

**预算解释的必要限制：** 正文能确认 rollout 数与配置上限对齐；没有给出足以验证各方法实际总 input/output tokens 严格相等的完整成本账本。相同 K 不自动包含 debugger、meta、selection 成本的等价性。

**构造法未闭环部分：** 正文说明 split 大小及角色，未充分交代 split seed、逐任务清单、分层/去近重复规则。作者 [README](https://github.com/rethinking-harness-evolution/code#readme) 给出 train/test/val 配置入口和 held-out 脚本；本次未成功读取配置/脚本正文，因此不声称已经代码级复现划分或评分。§5.2 将 benchmark 对 harness 不敏感作为可能解释，不是已经证明的普遍事实。

## 2. 对原提案的修订建议

以下为 LFL 自己的设计建议，不是论文提出的规则。原提案保持独立，本文件供审阅后采纳。

| 原提案项 | 建议澄清 | 原因 |
|---|---|---|
| 同轮数 K | K 仅表示每任务独立 attempt 数；内部 tool/model turns、fix_loop rounds、优化 iterations 各自命名 | 避免把额外搜索藏在一个 attempt 内 |
| 同 token | 改称同预算上限 + 实际成本账本；同时报 input/output/cached/reasoning 的观测口径 | 相同 max_tokens 不代表花费相同 |
| pass@1=首试 | 同时报 single_attempt_pass_rate、first_attempt_pass_rate、pass@K | 均值、时间顺序首试、oracle coverage 不应混称 |
| A: Δpass@1>0 即强证据 | 正增益只是必要信号；需独立测试、预注册最小收益与不确定性、回归检查 | 6–8 个任务的随机波动不能支持强结论 |
| B: Δpass@K>0 且 tokens 不升 | B 也必须来自未参与候选选择的最终测试；标明依赖 oracle 的 coverage，不能自动等同可部署成功率 | 否则 B 可绕开 held-out，且把 oracle 当真实选择能力 |
| held-out 一个集合 | 分 dev、validation、final test；验证集用于选择，最终测试只在候选冻结后评估 | 反复看同一 held-out 决定修什么，会把它变成验证集 |
| v0 36–48 run | 固定 8×3×2=48；定位 pilot，输出数据链与机制检查 | 任务少，先验证测量有效性 |
| 五域都是 harness 瓶颈 | 作为待验证假设；保留无压缩/无需锚的对照任务 | 防止只选候选必然占优的场景 |
| self_eval 首试指标 | 工具首调、fix_loop 首轮、任务首试分别定义分母 | 它们是不同层级信号，不能相互替代 |

晋级判断留给模型/维护者审阅证据；runner 只产出预算、来源、隔离、评分和完整性事实。
未来若把证据规则变成生产控制机制，须另按 AGENTS.md 的 admission asymmetry 说明必要性及可调用的人工/模型 override；本次没有引入新控制器。

## 3. v0 的问题与实验单位

唯一主问题：同一模型和共同预算下，完整锚钉候选是否改善压缩后继续执行任务的可靠性？

本轮是“已冻结候选的消融 A/B”，不评估自动 method/EVO 发现算法本身。
若未来声称“自动演化比把相同预算花在重试上更有效”，必须追加优化阶段成本及 fixed-harness test-time scaling 对照；48-run 本身回答不了那个问题。

- N=8 个 dev/pilot 任务，K=3 个互不共享反馈的完整 attempt，两组，共 48 个计划行。
- 每个 attempt 从相同的任务初始快照重新开始，可包含内部多轮工具调用；内部 round cap 单独记录。
- K=3 是 LFL pilot 的成本选择，不是照搬论文的 K=5。v1 是否 K=5 需在看正式结果前确定。
- 三次 attempt 全部运行；不得成功即停止，否则改变成本统计及 single-attempt 分母。
- baseline/candidate 按 task×attempt 配对，预先用 seed=20260916 冻结执行顺序；组内顺序平衡。
- 逻辑上的独立 sampling 可以物理串行执行。涉及唯一 8901 时严格串行，不双开、不重启健康模型。
- 每行新 session、独立可写 data/evidence/memory namespace；两组读取相同冻结初始知识快照。
- 每行恢复同一初始文件/外部状态；已完成动作不能泄漏给下一行。
- grading oracle 在行结束后运行；其反馈不进入后续 attempt、method、experience 或 memory。

### 3.1 完整消融边界

当前源码的两个机制相互独立：

1. `history.py` 的 `task_anchor_pin_user_messages` 保护最近真实 user 原文组。
2. `history.py::_maybe_inject_task_anchor_block` 由 `task_anchor_snapshot_provider` 提供压缩态快照；`core/loop/build.py` 将 callback 传给 history pipeline。

所以只将 `TASK_ANCHOR_PIN_MESSAGES=0` 不能证明 anchor-off。

| 组 | 最近 user pin | 压缩态 snapshot |
|---|---|---|
| baseline | 关闭本候选新增的 pin 行为，保留共同基线既有保护 | callback=None 或经资格化的等价禁用 |
| candidate | 冻结的候选 N，初始拟定 N=2 | 使用同版本真实 callback |

实现应在独立评测入口/隔离候选上暴露消融能力；不要为实验切换生产配置。
两组工具、模型、共同源代码版本及其余配置相同；若选择反向补丁方案，记录确切 patch SHA 和 source tree SHA。
正式每行保存实际 provider-visible payload 的 exact ref/hash；检查 baseline 无新增 snapshot，candidate 在压缩触发及下一轮稳态确实存在。
检查原文在场与 Goal/evidence ref 正确性只能证明机制生效；任务通过必须由独立外部 oracle 判定，不能以“快照出现”代替任务成功。
压缩压力通过相同前史/物理预算构造。记录两组实际压缩发生情况；不能仅给 candidate 一个更大 context。
可先用统一的压缩前快照做机械 preflight；实际任务评测必须经过完整历史构建路径，保留由候选产生的轨迹差异。

### 3.2 任务构成：仅公开类别，不在这里生成 final-test 实例

| 域 | pilot 数量 | 可观测任务结果 |
|---|---:|---|
| 压缩存续 | 3 | 压缩触发、压缩后稳态、多次压缩后，准确继续未完成操作 |
| 中断恢复 | 2 | 重建会话后接最近未完成状态；已完成操作不重复 |
| 证据分页 | 1 | 获取末页指定事实；offset 单调且无第一页循环 |
| 跨会话记忆 | 1 | 使用允许的已存事实，同时不混入别的 session 的 Goal |
| 多代理首轮 | 1 | fix_loop max_rounds=1 下由外部检查确认产物正确 |

主分析预先限定压缩存续+中断恢复的 5 项；其余 3 项作跨域/回归诊断，分别报告。
跨会话记忆与多代理用例可作为无压缩条件，具体前提需在 task manifest 中先冻结。
多代理调用仍计入该 attempt 的总成本；使用 8901 时内部请求也须符合单 slot 约束。
每项 oracle 检查任务外部产物、精确状态或动作次数；不依赖模型自报完成。
本表只是设计框架；真实 task bytes、oracle 与 fixtures 的 hashes 必须在第一行执行前写入 manifest。

## 4. 指标、预算和异常口径

对某组记 r[i,j]∈{0,1}，i=1..N，j=1..K；oracle 成功为1。

- `single_attempt_pass_rate = sum(r)/(N*K)`：独立 attempt 成功率估计，可标注为本文采用的 pass@1。
- `first_attempt_pass_rate = sum(r[i,1])/N`：预先排定的第1次 attempt，禁止事后挑一次。
- `pass@3 = sum(max_j r[i,j])/N`：三次独立尝试的 oracle coverage。
- 若真实部署采用 self-selection，另报 `selected_success_rate` 并计 selector tokens；本 pilot 不把 oracle coverage 冒充选择后部署效果。
- task级分别列候选与对照的成功数、paired difference、胜/平/负；主分析与跨域诊断分开。
- 48条轨迹不是48个独立任务。v0 只报描述性结果；正式推断以 task 为聚类/配对单位，并保留域划分。

### 4.1 共同预算

每个 attempt 冻结以下上限：context、每请求 output、全部模型调用累计 output、model/tool turns、wall time。
预算约束属于评测资源边界，不向生产引入语义式提前终止策略。
原始任务前史、固定知识快照、工具面、模型权重/量化/模板、sampling、reasoning设置全部绑定版本。

实际账本逐请求累计 input/output，另列 cached-input、reasoning 的 provider 语义。
不得将已包含在 output 的 reasoning 或已包含在 input 的 cached tokens 再次相加。
缺失 usage 写 null/unknown，不补零，不据此声称 tokens 不升。
包括任务主 agent、subagent、summary、judge，以及失败/重试请求可观测的消耗；区分是否已含重复计费。
记录逐行成本、组总量及成功/失败分层；K 次已执行失败也计入成本。
缓存策略在两组保持一致，记录缓存观测与时间；共享 endpoint 的延迟只作诊断，不自动作性能 Gate。

本候选的历史开发成本没有可验证完整账本：标 `optimization_cost=unknown`。
v0 只能比较冻结候选的运行成本，不能声称演化全过程具有净成本优势。

### 4.2 异常与有效性

- 模型/工具任务失败、超预算：TASK_FAIL/TIMEOUT，保留原始证据。
- 已启动行的基础设施错误：INFRA_FAIL，端到端描述性成功率记0，同时单列比例。
- 另可给 valid-run 条件统计，但必须显式标注过滤条件和分母；不能选择有利口径替换主表。
- 未启动的计划行：NOT_RUN；矩阵不完整，不给完整试验的通过结论。
- 消融无效、身份错、预算错、跨组泄漏或 scorer bug：协议无效；保留旧行，新版本重新资格化。
- 不覆盖或挑选重跑。因 infra 追加数据须留存原行并形成事先解释的新 run identity。

## 5. v1 的隔离与晋级证据

以下是建议，不是已存在的冻结任务集：

- dev：包含本 v0 的所有任务和失败轨迹，允许优化。
- validation：另建候选选择集；只用于选择及调参，不承载最终迁移结论。
- final test：25 项，五域各5项；在候选和评测协议冻结后评估，不参加候选排序。
- 按任务模板/来源事件分组隔离，不能仅换随机值就把近重复 dev 任务算 unseen。
- 路径排除不足以证明不可见：优化者不得挂载 final fixtures/answers，scorer 位于执行上下文外。
- task 内容、正确答案、轨迹、summary、失败报告及派生 embedding 一并排除出优化检索与记忆写入链。
- 执行者只获得当前任务所需输入，不能接触别的 final tasks 或 oracle；行结束后清理可写 namespace。
- 首次泄露逐题信息后，该集合对后续优化已不再是 untouched test；记录 disclosure/re-freeze 事件，不继承原结论。
- 每次 freeze 保存清单与 hashes；冻结者、可见范围、访问/披露记录与候选选择历史应可审计。

A/B/C 是证据标签，不是论文给出的自动晋级规则。
A 与 B 都需要最终测试来源、有效消融、预算/usage 完整性、预注册实用收益阈值及不确定性说明；
C 只支持局部机制记录。无对照或有泄漏应标 insufficient/invalid，不能用 C 掩盖协议失效。
B 若只提高 oracle pass@K，必须标“采样覆盖收益”；真实可部署效率需验证选择器或外部 verifier 的可用性与成本。
不把仅有正 Δ、单次偶然胜出或缺失成本当成 promotion 资格。
正式统计计划、样本量和多候选比较处理需在验证集上规划后冻结，不从 final 结果倒推。

## 6. runner 的最小产物与开跑前未决项

建议复用现有 evals 的 `protocol.py / run_ab.py / results/<run-id>/` 结构；不直接复用其 domain oracle。

每次运行至少写：

- `manifest.json`：source/config/model/fixture/oracle hashes，消融开关，预算数值，seed，完整48行计划。
- `rows.jsonl`：task/domain/arm/attempt/status/reward/usage、request/session identity、证据 refs。
- 每行 exact request/response/receipt 与 oracle 原始事实；敏感数据沿用项目已有授权与保存边界。
- `summary.json + report.md`：三项成功指标、实际 tokens、异常分母、paired task 表、主分析/诊断分离。
- `integrity.json`：预算、身份、隔离、消融与矩阵完整性事实；不替模型宣告生产任务完成。

**尚未冻结、实现阶段必须补齐的具体值：**

1. candidate 的完整 source tree 与共同基线身份；当前 832b4dfa 仅是本次检查点，不能直接等同用户所报部署 604e143e。
2. 完整 anchor-off 的评测入口与 preflight 证据；单 env 开关不足。
3. 当前合格 runtime 的解析后数值预算与 sampling 配置；不能复制论文128k/300 turns作为本机默认。
4. 八项实际 task/oracle/fixture bytes 与 hashes；每项预期触发条件及首个 attempt 标识。
5. usage 的 provider 含义和缺失处理；若不完整，B 类效率结论不可得。

这些项是开跑前机械 preflight，不是额外的人类审批。
本阶段交付到论文核验及 pilot 规格；runner 实现和正式执行是下一阶段。
