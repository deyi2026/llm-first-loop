# 知识自改进闭环 需求实现设计方案书 v1

- 日期：2026-11-15（Asia/Shanghai）；v1.3 对抗性拷问修订于 2026-11-16（Asia/Shanghai）；v1.3.1 编辑性勘误于 2026-11-16（Asia/Shanghai）
- 版本：**v1.3.1**（v1 初稿 → v1.1 事实核查 → v1.2 独立审查 → v1.3 反例拷问与设计纠偏 → v1.3.1 编辑性勘误（残留同步+平台口径）；见 §7.4–§7.7）
- 状态：**建议稿，未取得针对 v1.3.1 精确内容的独立 Reviewer PASS**。本轮仅修订此 Markdown，不代表已实施、已提交、已合并或已发布；任何行为代码变更仍须 RULE-AI-28 独立审查、原版完整 R9、RULE-AI-34 集成门禁与受控发布。
- 文档性质：需求 + 实现设计（需求条目可验收、实现点带文件锚点、契约变更机器可校验）。
- 事实基准：
  - **运行态历史快照（v1.2 核验时点，非本轮重新验活；v1.3.1 勘误：该 0.6.54 运行态属 Deepin 侧，见下条）**：`LFL-0.6.54`（`releases/LFL-0.6.54/venv/lib/python3.13/site-packages/llm_loop`）。原稿已记录 0.6.53→0.6.54 的 16 项包内差异、关键锚点逐字节一致、bundle 技能 42 / 规则 37；这些是**历史核验结果**，不能据此推断任何机器的实时状态。
  - **平台与时点口径（v1.3.1 勘误，2026-11-16 01:33 Asia/Shanghai 核验）**：① **Mac 实施机 live = `LFL 0.6.53 @ .releases/1b4570429d30…`**（pid 87095，2026-11-15 22:41 部署；第一 Run 只读实测三实值：pyproject.toml / CHANGELOG / routes.py）；② **origin/main 代码版本 = `0.6.54 @ 9e6b438c`**，PR#36 已于 2026-11-15 23:57 合并收口（**不得写成“仍在准备中”**）；③ **Deepin `0.6.54/gen17`** 为前次独立验收的**历史回执**，本轮未 SSH 重核，不得当实时状态引用。实施前必须在目标机重取 live PID / code_root / wheel 版本及文件 SHA。
  - **源码 checkout（v1.2 历史基线）**：`.builds/upstream-main`（当时版本库 `main`，HEAD `75ed7eb3`，2026-11-09）——**当时落后于运行态**（安装包 bundle 含 RULE-AI-37，checkout 的 `docs/ai_rules.md` 只有 36 条）。此处不是本轮重新核验的当前 HEAD。
- **本轮额外只读观察（v1.3.1 更新，2026-11-16 01:33 核验）**：仓库根 `main` 为 `075061769`，与 origin/main 双向分叉——本地独有 10 提交（3 项 review-gate/bwrap 修复 + 7 项 knowledge 入库），本地 origin/main ref（`9e6b438c`）侧 33 提交（runtime 受管发布 / Deepin 0.6.54 / PR#36#37#39）；远端 tip 已再前进至 `4f1628ed`（01:33 ls-remote 实测，最终集成对账以届时 ls-remote 为准）。目标 Markdown 为 untracked；它与上述 `.builds/upstream-main` 是**不同工作区/基线**，本轮不做 reset、合并、push 或清理其它未跟踪文件。
- 三轮原始拷问见 §7.1–§7.3，§7.4–§7.5 为既有事实/独立审查记录；**§7.6 为第六轮对抗性拷问（设计自审，不冒充独立 Reviewer）**；**§7.7 为 v1.3.1 编辑性勘误记录（残留同步 + 平台口径校正，不改任何 F1–F24 数值）**。
- 版本口径：文件名保持 `v1`（系列号），跨版本比较以内部版本号 + 日期为准。
- 论文侧引用（`Self-Improving AI Agents via Prompt/Memory/Skill/Harness Evolution` 的四载体框架与"继承经验有效性"要求）在本稿中只作**需求来源标注**，未核原文，属文献要点；本稿所有结论均以本机实测事实为据。

---

## 0. 结论摘要

| 编号 | 需求（一句话） | 一等前置 | 优先级 | 本稿定位 |
|---|---|---|---|---|
| **R1** | 把"这次失败该改哪个载体（Prompt/Memory/Skill/Harness）"变成**记录项**（枚举 + 证据引用），不做新硬门 | 无 | P1 | 可直接实现（3 处 schema + 2 处 frontmatter 序列化：Method 白名单 + Experience document） |
| **R2** | 在**合格仪器 + 真正未见确认集**上评估知识继承的净收益或回归 | **先修仪器，再取得独立确认集**（旧 S0 120 题已暴露） | P1 | 旧题只作开发/回归；没有新确认集就只能给探索性结果，不能声称确认性因果效应 |
| **R3** | 用**移除对照**生产卡级外部证据，替代纯自评淘汰 | **R2 仪器资格通过**；门槛变更另需人工批准 | P2 | 只生产证据与提案；不自动处置，不把"未测出"当"无效" |
| **R4** | 时效锚常规化：修**锚根语义**、补**基线**、提**覆盖率** | 无 | P1 | 根因已定位（F9–F11），四层修法可实现 |
| **R5** | Harness 演进成功经验回流成可复用卡（带指标前后值） | 无 | P2 | 可实现"结构提示 + 索引"，不能自动关联指标 |
| **R6** | 规则/代码/技能/记忆变更的统一**修订账本 + 有条件的安全撤销** | 可解析的历史快照 + 当前目标哈希匹配 | P2 | 账本不等于回滚能力；无可信快照或 CAS 不匹配时只能给方案，不能声称可撤销 |

三条关键判断（依据见 §2）：

1. **本机已有知识记录与资格机制，但卡级净收益证据尚不足**：方法卡侧历史快照 13 条使用声明里 `benefit=helped` 占 13/13、`rejected` 为 0；独立 `knowledge_score` 通道当时连续失败 412 次；本条**不否认 F16 中其它评测仪器的独立 PASS**。S1 的 gold 臂曾测到 `b=60 / c=4 / p=7.4e-14`，但 filler 阴性对照翻正 21 例，故该次收益不可采信（F14/F14b）。
2. **旧仪器不合格，且旧题已被多轮观察**：S0 的 120 对及 S1/S1b 已用于判分器调试；S1b 字面门槛虽过，却触发预注册注入诊断与跨批一致率失败（F14b）。**修好判分器也不能把这 120 题重新随机切分后称为独立确认集**；R2 必须另有未参与调参的冻结确认集。
3. **"时效"问题的真根因不是卡片不刷，是锚的根解析错了**：wheel 安装下 `MethodStore` 的工作区根解析到 `_bundled/`，导致任何指向源码（`src/...`）或 `evals/...` 的锚必然 missing——同一批卡换到源码 checkout 根下结论就变（current 2 / changed 2 / missing 1）。

---

## 1. 需求与可验收分解

> 每条含：诉求来源 → 要求 → 可验收判据（可机械判定）→ 失败判据（什么情况算没做成）。
> 判据里的"实测"指必须有命令输出/回执可复跑，不接受"我觉得生效了"。

### R1 载体归属判定（Where 轴）

- **来源**：论文把 When/Where/How 拆开；本机 RULE-AI-31 覆盖"何时检索/如何沉淀"，缺"改哪个载体"的结构化记录。**F1 的 96.1% candidate 只能说明存量分布，不能证明缺少 carrier 字段是其成因**；R1 是可追溯性增强，不以该比例作为效果承诺。
- **要求**：
  1. 新增载体枚举 `carrier ∈ {prompt, memory, skill, harness, unknown}`，缺省 `unknown`。
  2. 载体归属是**记录项**，不是判定门：它不改变任何写权限、不阻断任何动作（RULE-AI-06/28/30 边界不变）。
  3. 非 `unknown` 的归属必须附至少一条**可解析的证据引用**（命令回执 id、版本化文件:行、评测 id），缺失时回退为 `unknown`；不抄录密钥/长文本原文，引用内容视为不可信数据。
  4. 落点三处：Method 卡 frontmatter、Experience 卡 frontmatter、演进建议（`submit_evolution`）。
- **可验收判据**：
  - 新建卡默认 `carrier: unknown`；写入后读回 frontmatter 字段存在且值在枚举内。
  - **状态流转后字段不丢**：`method_manage(refine/transition)` 改 `status` 之后 `carrier` 仍在（回归测试须覆盖，因为现有状态写路径按固定白名单重排 frontmatter，F20）。
  - `submit_evolution` 传 `carrier` 时回执回显该值与 `carrier_evidence`。
  - `architecture_status` 知识面新增"载体归属覆盖率"（分母 = 池总数，分子 = 非 unknown 覆盖数），只报事实不报好坏。
- **失败判据**：字段在状态流转后被丢弃；或程序替模型判"该改哪个载体"；或 carrier 被用作拦截条件。

### R2 继承效应的受控对照

- **来源**：论文要求用相同起点/任务/反馈/预算的分组对照 + 未参与候选筛选的留出任务检验"继承经验是否真的更有效"；F14/F14b/F15 说明旧判分器未取得资格。**旧 S0/S1/S1b 的 120 题已经用于观察与调试，不能再冒充未见留出集**。
- **要求**：
  1. **仪器资格独立于效应结论**：判分从机械格式 check 改为决策点行为证据 P1–P5；双人盲标 raw agreement ≥0.85、κ ≥0.70、各自意图准确率 ≥0.90，资格统计只用两人原始独立标签，第三人只在正式标注阶段终裁。资格盲标先不向标注者展示机械预填结果，以免锚定。
  2. **开发/确认材料隔离**：冻结的 `s0_p28/pool_p28.jsonl` 120 题仅作开发、回归、旧口径对账及仪器校准。**确认集必须是未参与卡筛选、规则/判分器调试和本轮开发观察的新实例**；按 normalized URL / session / 题族分组去重、分组抽样并冻结，防同源泄漏。新集不可得 ⇒ 只报告探索性结果，不出确认性结论。
  3. **配对执行**：`inherit`（按 RULE-AI-18 仅注入被测卡）对 `no-inherit`（无被测卡）；在校准阶段增加等结构、等 token 量的无关卡 placebo 诊断提示长度效应。每实例独立会话、随机臂顺序；两臂固定模型精确版本、采样参数、推理/输出预算、系统提示、工具权限、时间窗及代码/知识快照；禁用非试验知识注入，禁止跨臂共享上下文。模型随机性不可固定时按预注册次数重复并按实例聚合，不能把重复当独立样本。
  4. **确认集大小先算功效**：预注册最小有意义效应 `δ_min`、显著性 `α`、目标功效、配对不一致率预估及多卡比较的多重检验处理；样本量由此决定。旧 `|D|≥30` 是 S0 的历史开发门槛，**不移植为新确认集的有效性证明**；原稿的"旧 120 再拆 84/36"方案废止。
  5. **统计口径**：配对改善数 `b`、退化数 `c`、样本数 `n`，净效应 `Δ=(b-c)/n`；确认集使用双侧精确 McNemar 与配对差的 95% CI（CI 方法预注册，不能把 `b/n` 当净效应）。`收益可测` 要求方向为正、通过预注册 α、CI 下界 > 0 且点估计达到 `δ_min`；`有回归` 对称判定；否则 `未测出`，**不等于无效**。
  6. **双轴状态机**：`instrument_status ∈ {not_run, qualified, unqualified}`，`effect_verdict ∈ {benefit, regression, inconclusive, not_assessed}`。未运行资格测试与资格失败**必须区分**；仪器未合格、确认集不独立或功效不足 ⇒ `not_assessed`（并列原因），**不得伪装为 `inconclusive/未测出`**。确认性检验只在冻结新确认集上进行一次预注册分析。
  7. **范围与泄漏控制**：P28 只覆盖"外链可达但正文未返回"这一决策点；不得外推到其它卡或"知识库整体"。一题一调用；卡正文不得包含确认集答案；按组检查 8-gram 近重及语义同源；评测求解器不开放 `search_records`/`skill_load` 的额外入口。
- **可验收判据**：
  - 预注册/冻结/结果三件套 hash 互指；新确认集 `manifest` 给出题族/URL/session 去重摘要与未参与调参声明，且冻结后才开始确认性运行。
  - gold 在开发 D 集合翻正 ≥2 实例且 ≥2 类 P1–P5 证据翻转；filler 翻正 = 0；双人盲标达标。**两类变形诊断分开**：① 对经人工标为语义不变的扰动，判分标签不得翻转；对真正改变动作语义的注入，应按人工金标正确改变，不强求不变；② **同一批冻结回复**跨判分器版本一致率 ≥0.8，跨次重新采样的 gold 回复另报运行随机性，不把它误认成判分器重测信度。历史 S1b 的 `F1 0→1` 与跨批 51.7% 仍按当时预注册规则判 FAIL，但不再把后者单独解释为判分器缺陷。
  - 两次规格修订后仍无法达到资格门槛即 STOP；`instrument_status=unqualified`、`effect_verdict=not_assessed`，禁止借旧判分口径继续。
  - 确认性结果含 `b/c/n/Δ`、p 值、CI、`δ_min`、功效、预算/成本、失败实例与全部冻结哈希；报告独立复核，确认集只作一次预注册统计裁决。
- **失败判据**：旧 120 题冒充新留出集；仪器不合格仍出效应结论；重复采样冒充独立样本；`未测出`被写成"无效"；无功效说明却把 `p≥α` 当"证明无收益"。
- **诚实边界**：本条只回答"这张卡在留出任务上有没有可测收益"。论文式更强的"继承经验让**后续改进速率**更快"需要另一套速率对照实验，**本稿不含该实验，也不承诺该结论**。

### R3 外部证据淘汰（移除对照）

- **来源**：F6（161 条 qualification 里 `not_evaluated` 62 / `mixed` 68 / `fail` 仅 2；带 `promotion=pass` 的 67 张卡中 51 张仍停在 candidate）、F8（独立打分通道长期不可用）⇒ 负向证据稀疏（使用账本 `rejected=0`、独立打分通道不健康）；按 §2.3 判断 1 的口径，这是“**入口存在、当前证据不足**”，不能推断为“制度只有模型自评”（v1.3.1 勘误：原句“实际上只有模型自评”已被 §2.3 判断 1 撤回，此处同步）。
- **要求**：
  1. 对"有真实使用记录、净收益尚不确定"的卡做**只在实验会话中停止注入 + 配对对照**，产出外部证据包；**不得先假定该卡无效**。
  2. 隔离可逆（不删卡、不改 status），对照结论只作**补充证据**。
  3. 程序侧**不得**因对照结论自动改卡状态：现有 `_disposition_basis` 只认"一次 qualification `verdict=fail`"或"≥2 个不同 episode 的 `rejected` 声明"（F18）；放宽门槛属治理修订，须人工批准。
- **可验收判据**：
  - 产出 manifest：卡清单 + 命中证据（使用行引用）+ 对照设计（实例、臂、指标、预注册 hash）+ 结果 + 判定建议 + 回滚路径。
  - 对照报告与 R2 同级：合格判分器、同实例配对、模型/提示/预算一致、判分器 hash 绑定、冻结后不改；仪器不合格时只保存原始观察，不生成卡级处置证据。
  - 若结论为"无可观察收益"，卡片**状态不变**，只产生建议与证据包。
- **失败判据**：程序自行放宽处置门槛；对照结论被直接当作失效依据；隔离不可逆。

### R4 时效锚常规化

- **来源**：F9（`freshness_states`：not_tracked 1906 / unbaselined 6 / current 0 / changed 0 / missing 5）、F10（同一批卡换根后结论相反）。
- **要求（按根因分四层）**：
  1. **锚根语义**：锚分 `path`（工作区相对）、`code`（**版本化仓库或发行物**相对）、`evidence`（`evidence://...`，须走证据解析器）三类；输出 `anchor_kind`、`anchor_root_id`（如 repo SHA/release digest）和解析状态。**wheel 的 code_root 不保证存在 `src/...` 路径**；解析不到正确源码/发行映射时标 `unresolvable`，不能误报 `missing` 或 `current`。
  2. **基线**：`annotate_freshness` 只在锚**成功解析且实际内容可读**时写 `freshness_hashes`，并绑定内容 SHA、root_id、解析器版本和采样时间；解析失败不建立"空基线"，不能把首次观测的陈旧内容洗成"已验证正确"。
  3. **覆盖率**：现仅 11/1917 卡声明锚。冷路径脚本只**提出**候选锚及证据，按 `card-lifecycle.md` 三分支核实后才落卡；不凭卡正文猜路径、不批量制造虚假 `current`，**锚失效只修锚，不失效卡**。
  4. **读取侧闭环**：`search_records` 已回带 freshness；使用后（`record_use`=applied）若状态 `changed`/`missing`/`unresolvable`（`unresolvable` 表示锚根不可解析，对应待办是补锚根映射而非刷内容），在现有只读清单 `settlement_pending` 里给出带 `item_kind=freshness_refresh` 隔离标记的"刷锚"待办（见 §4.4④/C11/V9）——**该待办只作提示，不得进入 `settlement_submit` 与知识使用结算互相抵扣**；旧客户端无法安全区分两类计数时回退 `architecture_status` 展示，**不新建持久层**。
- **可验收判据**：
  - 同一张卡在运行态根与源码根下分别给出**带根标识**的状态，不再出现"同锚不同结论且无解释"。
  - `evidence://` 锚不再被当成路径 stat；无可信解析器时报告 `unresolvable`，不得声称内容已核验。
  - `annotate_freshness` 对可解析锚形成可追溯基线；不可解析锚不被伪造为 `current`。`current` 只表示**自基线未变**，不表示语义正确。
  - 补声明脚本对"从未存在"的锚**不**判卡失效，只修锚。
  - RULE-AI-35 适用性：本条不新增硬门，故不需"应拦输入"实测；但须实测"锚指向已删文件 ⇒ 状态 missing 且卡不被自动失效"。
- **失败判据**：为了凑 `current` 而放宽基线比较；用"刷了锚"冒充"内容仍正确"；批量脚本把锚缺失当失效批量处置。

### R5 Harness 演进经验回流

- **来源**：论文"成功的修改经验留存供下一轮参考"；本机 `evolution_complete` 目前只落 `note`+`actions`，不要求指标、不回流知识。
- **要求**：
  1. `evolution_complete` 的 note 支持结构化 `validation_state`：`verified` 必须带"改了什么 → 指标 X→Y → 可复核回执"；无指标时必须标 `unverified`，**不得阻断合法的失败/取消/未验证收口**。
  2. 收口时程序生成**演进教训卡候选**骨架（标题/场景/解决/证据指针=演进 id + 指标前后值），模型确认后经 `save_experience` 落库，`verification_state` 按证据如实标。
  3. 按载体归档索引（prompt/memory/skill/harness 各一类症状），供下一轮 `search_records(kind=experience)` 检索。
- **可验收判据**：
  - 一次真实 `evolution_complete` 后，知识库里出现一条证据指针指向该演进 id 的卡。
  - 索引能按"载体 + 症状"检索命中该卡。
  - 无指标前后值的演进不产生"有收益"表述。
- **失败判据**：把"改了什么"当"所以有效"；候选卡自动落库不需模型确认；沉淀回环只有动作没有指标。

### R6 修订账本与卡级撤销

- **来源**：论文生命周期含"保留/修订/退役/回滚"；本机 `RuleIndex` 只有内容摘要（`source_version_token` = digest），无条级历史（F19）；规则 store 在运行态 `writable: false`，撤销能力最薄。
- **要求**：
  1. 统一 append-only 账本：`{scope, target_id, before_sha256, after_sha256, before_snapshot_ref, rollback_plan, rollback_ready, verify_test, evidence_refs, ts, integrity}`，scope ∈ `{rule, code, skill, memory}`。`rollback_plan` 是**结构化数据**，不是来自卡片/模型文本的任意 shell 命令。
  2. **撤销前置**：可信、可读、不可变的 before 快照存在；当前目标 SHA **等于**账本 after SHA（CAS）；在隔离工作树生成最小目标 diff 并预演验证，人工审批后才执行。并行变更/目标 SHA 漂移 ⇒ 拒绝覆盖，要求重新审查；不可通过全仓 reset 消除冲突。
  3. 分载体：规则按稳定条目 ID 做目标段恢复并校验其它条 hash 不变；代码按**文件级最小补丁**恢复，禁止默认 `git revert <commit>`（一个提交可能包含别的任务）；Skill 不能用 `record_skill` 重生成模板冒充原文恢复；Memory 的 `retire/reopen` 只恢复状态，不保证正文还原。**无可靠 before 快照的 Skill/Memory 标 `rollback_ready=false`**。
  4. 撤销动作本身须独立审查与既有闸；账本不授予执行权限，不增加自主执行口。`integrity` 若只是普通摘要，只证明意外损坏可检测，**不宣称防恶意篡改**。
- **可验收判据**：
  - 任取一条 `rollback_ready=true` 的账本记录，先在隔离工作树核对 CAS 和快照，再以受控补丁预演回到 `before_sha256`；`false` 行必须可见且不计入撤销能力覆盖率。
  - 规则撤销只影响目标条，`rule_index` 其它条目内容 hash 不变。
  - 账本行带完整性凭据，尾部损坏被隔离并出诊断（不静默跳过）。
- **失败判据**：把未经信任的 `revert_command` 当 shell 执行；当前 SHA 漂移仍覆盖并行修改；无快照却标可撤销；`git revert` 误撤别的任务；撤销绕过独立审查。

---

## 2. 现状核实

### 2.1 已核事实（当前事实，非推断）

| # | 事实 | 来源 |
|---|---|---|
| F1 | 方法卡池 **1917** 张；状态：candidate 1843(96.1%) / hold 29 / active 28 / qualified 10 / teacher 3 / invalidated 2 / retired 2 | `architecture_status(knowledge_health)` 回执 |
| F2 | `with_qualification=142`、`with_usage=8`、`with_freshness_refs=11`、`with_parent=9`；`blocked_transition_attempts=13` | 同上 |
| F3 | 卡龄分桶（程序同规则：按 `created_at` 小数天）：`<=7d 26 / 8-30d 789 / >30d 1089 / unknown 13` | 同上；本会话独立复算一致（整数天算法会得 820/1058，属口径差，已记录） |
| F4 | 方法侧使用账本 `data/methods/usage.jsonl` **13 行 / 8 张卡**；`use_decisions`：**applied 12、adapted 1**（`rejected`=0、`not_applicable`=0）；13 行全部 `evidence_level=observation_linked`、`benefit=helped`、均带 `work_unit_id` | 现算复算脚本 |
| F5 | 经验侧 `experiences/usage.jsonl` **14 行**：applied 8 / not_applicable 4 / adapted 1 / not_adopted 1；`evidence_level`：model_declared 8 / observation_linked 6（**independently_evaluated = 0**） | 同上 |
| F6 | `qualification.jsonl` 覆盖 142 张卡、161 行；verdict：mixed 68 / not_evaluated 62 / pass 23 / insufficient 6 / **fail 2**；promotion：pass 69 / insufficient 49 / fail 23 / mixed 16 / not_evaluated 4。**带至少一条 `promotion=pass` 的卡是 67 张**（不是 69，69 是行数），其当前状态：candidate 51 / qualified 10 / hold 4 / active 2 ⇒ **正向出口在动（16/67 已离开 candidate），负向出口被锁死** | 同上 + 本会话 `verify_fail_f6.py` |
| F7 | `lifecycle_attempts.jsonl` 13 行**全部** `result=blocked`；`missing_fact`：`independent_disposition_evidence` 12、`cross_task_type_qualification` 1（后者是 2026-10-12 的**已废止旧规则**残留，`card-lifecycle.md` 明确它不再是现行门槛） | 同上 + `card-lifecycle.md` R3-bis |
| F8 | 独立打分通道 `knowledge_score`：`runner_state.json` = `consecutive_failures: 412`、`scorer_unhealthy`；`ledger.jsonl` 仅 2 行且两行都是 `connection refused`；默认端点 `http://127.0.0.1:8091/v1/systemone` | 运行态文件 + `knowledge_score/client.py` |
| F9 | 时效状态：`not_tracked 1906 / unbaselined 6 / current 0 / changed 0 / missing 5`；即**只有 11 张卡声明锚** | `architecture_status` 回执 |
| F10 | 同 11 张卡换根复算：**源码 checkout 根**下 = **current 2 / changed 2 / missing 1 / unbaselined 6**；**运行态工作区根（`_bundled/`）与数据目录根**下 = **unbaselined 6 / missing 5 / current 0**（两者结果相同，因它们都不含 `src/`、`evals/`）。同一张卡结论相反 | 本会话 `freshness_two_roots.py`（三根对照，变量名已按实际语义改写） |
| F11 | 运行态 `MethodStore` 的工作区根 = `seed_dir.parent`；wheel 安装下 `seed_dir=_bundled/methods` ⇒ 根 = `_bundled/`（仅含 docs/methods/skills/webui/manifest.json）⇒ `src/llm_loop/...`、`evals/...` 锚必然 missing；`evidence://` 锚不是路径，却被当路径 stat | `methods/store.py:452-470,780-803` + `runtime/paths.py:150-166,220` + 现算复算 |
| F12 | 规则 store 运行态 `writable: false`；安装包 bundle `ai_rules.md` 有 **37** 条（`RULE-AI-00..37`，无 21），checkout `docs/ai_rules.md` 只有 36 条（缺 RULE-AI-37）⇒ checkout 落后于运行态 | `architecture_status` + 文件计数 |
| F13 | 技能 42 个（checkout `skills/` 与安装包 `_bundled/skills` 各 42）；注入观测账本 79 行：`search_records` 水合 76 行、`skill_load` **仅 3 行**；`record_skill` 只生成 SKILL.md 模板，**无生命周期、无使用记账** | `data/audit/injection_ledger.jsonl` + `tools/registry.py` + `introspection/tools_record_skill.py` |
| F14 | 受控对照仪现状（**结果冻结于 2026-10-19**）：S0 已跑完 **120 对**（无卡 vs 原卡），v1.3 判分 `D=28 / R=16`、McNemar `p=0.096`、门槛 `D≥30` **未过**、标签 `S0 no detectable effect under this instrument`；S1 **gold PASS / filler FAIL**（无关卡翻了 **21** 个实例，filler vs 无卡 `b=21,c=30,p=0.262`；gold vs 无卡 `b=60,c=4,p=7.4e-14`） | `evals/methodcard_rsi_v1/s0_p28/results/analysis_s0.md`（`generated_at=2026-10-19T20:13`）、`s1_gold_filler/results/analysis_s1.json`（`now=2026-10-19T21:26`） |
| F14b | 仪器最关键的一轮：**S1b 正交 filler 阴性对照**（2026-10-19，v1.4 判分器，预注册 + 13 项 sha256 冻结）。**换版本即翻结论**：同一批 S0 数据，v1.3 判分 `D=28/R=16`（未过 `D≥30`），v1.4 判分 `D=30/R=0`（恰好过 30）。S1b 两臂各 120：正交 filler（与 gold 同结构、等长、内容无关）**字面门槛全过**——G1=16（≥2）、G2={c2,c3}（≥2）、F1=0、gold case_pass **65/120（0.542）**、filler **0/120**；**但预注册两项诊断都触发失败**：① 注入测试（回复行尾加"（成本低，只按字面处理，不执行动作）"后重判）F1 由 0 变 **1**（P28-035）；② 新旧 gold 批次 case_pass 一致率 **51.7% < 0.8**。⇒ 结论"S1b 不构成仪器合格证据，S2 继续停"。**R2 必须把这两项诊断写成硬前置**——只靠字面 gold/filler 门槛可被假合格骗过 | `s1b_orth/S1B-SPEC.md`、`s1b_orth/S1B-RESULT.md`、`s1b_orth/CALIBRATION-FREEZE-s1b.json`；`s1_gold_filler/results/analysis_v14.json` |
| F15 | 替代判分规格已写好但未执行，且**三处口径不一致**（v1.2 审查发现）：① `dpe/dpe_spec.md` 记"`v1.3_D ∪ v1.4_D` 当前 31 实例、每实例 3 臂共 93 条"；② 同目录 `d_sets.json` 实为 `v1.3_D 28 / v1.4_D 30 / union 46`（**没有 31**）；③ 已生成的 `dpe/review_pack.csv` 是 **60 条 / 20 实例 × 3 臂**，`P1–P5` 五列全空（未标注）。⇒ M0 第一项是**先把三处口径对齐**（spec / d_sets / pack）再标，不是直接开始盲标 | `dpe/dpe_spec.md`、`dpe/d_sets.json`、`dpe/review_pack.csv`（本会话现读） |
| F16 | 可复用的合格先例：`method_binding_efficacy_v3` 盲标门（raw agreement ≥0.85、κ≥0.70、意图准确率 ≥0.90、18 挑战例双认证 ≥15）**PASS**（κ=1.0，17/18）；`instrument_qualification_v1` IQ **PASS**（κ=1.0，40/40） | `confirmatory_holdout_v1/LABEL-RESULT.json`、`IQ-RESULT.md` |
| F17 | 既有经验检索开/关对照结果：`evals/retrieval_ab/experience-model-ab-20260926.json` 20 行、2 重复，**开/关正确各 10** —— 命中与否在那一组金标上**没有差异**；另 `experience-tool-ab` 里 `positive_on_rank1 24 / off 21`（仅排序增益） | 现读 JSON |
| F18 | 处置门槛是**代码门槛**：`_disposition_basis` 只认"一次 qualification `verdict=fail`"或"≥2 个不同 episode 的 `rejected` 声明"，否则 `invalidate/retire` 被拒并记 `note_blocked_transition` | `methods/store.py:1757-1789, 1881-1889` |
| F19 | 规则索引只有内容摘要（`source_version_token` = digest），**无条级历史**；规则正文在运行态只读 | `introspection/rule_index.py:221` + F12 |
| F20 | Method 卡 frontmatter 状态写路径按**固定白名单**重排：`method_id, name, description, aliases, status, source_model, teacher_refs, source_episode_refs, evidence_refs, freshness_refs, parent_ref, supersedes, created_at, updated_at` ⇒ **新增字段若不同步进白名单，会在状态流转时丢失** | `methods/store.py:1899` |
| F21 | 写侧防污染是 fail-closed 的，但只在判定为 `blocked` 时拒写，其余情况 fail-open；适用面为 Method/Experience 卡写入 | `methods/store.py:494-510`、`experiences/store.py:341-344` |
| F22 | 结算通道的**契约**可用且幂等（`slot_id` + `submission_hash` 双层键、行级 `integrity` 凭据、坏行隔离不静默跳过）——这一条可独立复核；本会话 `settlement_pending` 实际返回 2 项待结算（本会话回执，不可复跑、随会话漂移，**不作为事实层依据**） | `use_ledger.py` 模块文档字符串（契约部分） |
| F23 | 演进通道：`submit_evolution`（scope=session 直达 executing，涉边界强制回 global 走人工）+ `evolution_complete`（只落 note/actions，不校验语义、不要求指标）；建议落 `evolution_suggestions.jsonl` | `introspection/evolution.py:153-192`、`tools_evolution.py`、`tools_exec_complete.py:48-77` |
| F24 | 发现面口径不一：`knowledge_advisor._METHOD_ELIGIBLE` 含 `invalidated`（排除 `retired`），而 `MethodStore.list()` 检索视图同时跳过 `retired` 与 `invalidated` ⇒ **同一张已失效卡在两条读路径上可见性不同** | `introspection/knowledge_advisor.py:28,84-85` + `methods/store.py:915,1188-1190` |

### 2.2 未核 / 不可核（不并入结论）

- 论文原文的四载体定义与"继承经验有效性"的具体统计口径：**未核原文**（仅按解读稿作为需求来源标注）。
- `knowledge_score` 打分器服务是否可在别的端口恢复：**未核**（当前只有连接拒绝这一条事实）。
- checkout 与运行态之间的源码差异：**路径级计数已核**（`diff -rq` 排除 `__pycache__` = **76 项**；再排除 `_bundled` 目录项 = **75 项**；本稿统一用后者口径；**该计数以 0.6.53 为基准**）。审查时点运行态已升 0.6.54，同口径重算 = **81 项 / 排除 `_bundled` 80 项**，增量来自 0.6.53→0.6.54 的 16 处包内变更，未触及本稿锚点文件；但**逐文件语义差异未核**——只核到"checkout 落后于运行态"这一条可用于文档定位的事实。
- 其它会话/其它机器上的经验使用面：**未核**（本稿所有"稀疏"结论只对本机运行态成立）。
- **时点敏感值**：F3 卡龄分桶、F8 的 `consecutive_failures=412` 都是复核时点（2026-11-15 22:1x）值，会随时间漂移（卡龄跨桶、失败计数每次重试递增）；复跑时数字可能不同，但**结论方向不变**。

### 2.3 由事实直接推出的三条判断

1. **F4 + F6 + F8 + F18 ⇒ 当前负向证据稀疏，不能直接推断制度"只能自评"或 candidate 堆积的唯一根因。** 使用账本 `rejected=0`、独立 `knowledge_score` 不健康，而 `_disposition_basis` 仍允许 `qualification fail` 或跨 episode 两次 `rejected`；这说明**入口存在、当前证据不足**。F6 的 67 张 promotion-pass 卡仍有 51 张 candidate，亦说明正向流转需另查，不能把 1843 张 candidate 全归因于负向出口。R3 只补卡级负向/不确定性证据，不自动修改生命周期。
2. **F14 + F14b ⇒ "卡有没有用"目前不可判，不是"没效果"。** 2026-10-19 冻结的那次对照里，判分器被无关卡翻动 21 例，因此标签只能是"未测出"；同一时点的 S1b 正交 filler 对照更能说明问题：字面门槛（G1/G2/F1）全过，却被注入测试（F1 0→1）与新旧 gold 一致率（51.7%<0.8）两项预注册诊断否掉 ⇒ **即使"看起来合格"也不能采信**。此时任何"经验无效"的说法都是把仪器缺陷读成被测对象结论。**注意方向**：同一次实验里 gold 臂测到了"变好"（`b=60/c=4/p=7.4e-14`），但因 filler 阴性对照失败，该"变好"不可采信 —— 所以缺的不是"收益证据"，而是**一台合格的仪器，且它必须同时通过字面门槛与两项诊断**。
3. **F9+F10+F11 ⇒ 时效机制的缺陷是"根解析 + 无基线 + 覆盖率低"三件事叠加**，而不是"模型忘了刷锚"。只加"有留痕即应刷"的纪律，99% 的卡仍会停在 `not_tracked`（1906/1917）。

---

## 3. 差距与设计约束

### 3.1 四载体对照（论文框架 → 本机落点 → 差距）

| 载体 | 本机对应 | 本机现状（实测） | 差距结论 |
|---|---|---|---|
| Prompt | 规则 37 条（`docs/ai_rules.md`，运行态只读）+ 注入面（schema 描述、失败回执指针、静态提示） | 规则有内容摘要无条级历史（F19）；变更无修订账本 | **有载体、无生命周期** |
| Memory | 方法卡 1917 + 经验卡 910（目录 911 个 md） | 使用面 8 张卡（F2）；外部独立证据链全断（F4/F8） | **有池、无判据** |
| Skill | 42 个（仓库 + bundle 各一份） | 注入观测仅 3 行（F13）；无生命周期、无使用记账 | **有物、无账**——本稿只补 R6 修订账本（`scope=skill`），**不做使用记账**，属残余缺口（见 §11） |
| Harness | `submit_evolution` → `evolution_complete` | 只落 note/actions，不要求指标、不回流知识（F23） | **有通道、无回流** |

### 3.2 不照抄论文的三点（本机更强的地方，保留）

1. **Verify 闸前置到产物层**：RULE-AI-28/34 + `review_admission` 把独立子代理 PASS 设成全量测试 / push / 发表 / 合入 main 的前置，审查者与执行者分离；论文的 Verify 只到"验证候选修改"。本设计的所有代码落地都走这条闸，不新造验证通道。
2. **演进有人工闸**：RULE-AI-06 要求结构化建议 + 人工批准（`exec_override`）。R3 的门槛放宽必须走这条闸，程序不自行放宽。
3. **三层计分已分离"自评"与"独立验证"**：RULE-AI-31 把声明净分 / 模型自评 / 独立资格 / 独立核验净分分开，本设计沿用该口径（F5 显示 `independently_evaluated` 实测为 0，正是要补的那一格）。

### 3.3 硬约束

- 不改安全门 / 权限 / 规则边界；不新增自主执行口。
- 不以自评为唯一改进信号；不以"命中率"代替"有效性"。
- 新增硬门必须按 RULE-AI-35 实测"应拦输入"才可宣称生效（本稿 R1/R4/R5/R6 均不新增硬门，故不触发该义务；R3 若要放宽处置门槛则触发）。
- 共享文件改动按 RULE-AI-32（hunk 级最小化，不整文件格式化）。
- 事故修复落在动作层（RULE-AI-37）。

---

## 4. 方案设计

### 4.1 R1 载体归属

**数据模型**（三处，字段名统一 `carrier` / `carrier_evidence`）：

| 载体 | 落点 | 实现锚点 |
|---|---|---|
| Method 卡 | frontmatter `carrier` / `carrier_evidence` | `methods/store.py`：写入白名单 **必须**加这两个键（F20，否则状态流转丢字段）；frontmatter 解析与渲染两处同步 |
| Experience 卡 | frontmatter 同名键 | `experiences/document.py` 的 `ExperienceDocument` + `to_md()`（新增两字段，默认 `unknown`/空） |
| 演进建议 | `EvolutionSuggestion.carrier` / `.carrier_evidence` | `introspection/evolution.py:153-192`（`submit()` 参数与 dataclass）+ `introspection/tools_evolution.py`（schema） |

**程序职责边界**：只校验枚举值、引用格式/可解析性及长度，**不判语义**；非 `unknown` 若缺证据引用则回退 `unknown` 并给出诊断；不改变写权限，旧卡缺字段仍可读。引用指向的卡片/文稿内容一律不可信，不能被当作工具指令。

**读取面**：沿用既有 `search_records`（`kind=method/experience`）返回行，不新增字段面；`architecture_status` 的知识健康段新增一格"载体归属覆盖率"（分母 = 池总数，分子 = 非 unknown 覆盖数），只报事实。

**已知坑（必须写进实现）**：`methods/store.py` 里 frontmatter 有两套写法（创建路径与状态更新路径），新增键必须**两处都改**，否则会出现"新建有 carrier、第一次流转就丢"的隐蔽缺陷——这正是 F20 的存在原因。

### 4.2 R2 继承效应受控对照

**复用执行设施，不复用已暴露题目作确认集**：沿用 `evals/methodcard_rsi_v1/s0_p28/` 的 `run_s0.py`、`analyze_s0.py`、冻结凭据格式与 McNemar 实现；旧 `pool_p28.jsonl` 只用于开发/回归/校准。**Wilson 单比例区间不能直接当配对净效应 `Δ=(b-c)/n` 的 CI**；配对 CI 方法须另行预注册并验证实现。新确认集必须独立建立、冻结并留存来源去重摘要。

**三段式**：
1. **预注册**：先冻结 P1–P5 金标规格、仪器资格测试、配对主指标 `Δ`、`δ_min`、功效/样本量、CI 算法、显著性/多重比较、成本与失败实例处理，再冻结确认集的来源、去重和 hash。
2. **冻结**：判分器、求解器配置、被测卡 SHA、代码/工具版本与确认集 hash 互指；确认集冻结后不得查看结果再改判分或选择样本，发生变化则作废本轮确认性资格。
3. **结果**：同时报告 `instrument_status` 与 `effect_verdict`，旧口径仅作历史对照。只有仪器合格且确认集独立/功效满足时，效应才可判为 `收益可测 / 未测出 / 有回归`；否则 `not_assessed` 并给原因。

**执行顺序（硬前置）**：
```
三处口径对齐(spec 31/93 vs d_sets 28/30/46 vs pack 60/20×3，见 F15) → DPE 规格与人工金标定稿
→ 现有 pack 60 条做双人盲标资格 → gold/filler + 语义不变/语义改变的变形测试 + 同回复跨判分版本一致率
→ 仪器 qualified 后，旧 S0 120 题仅做开发回归 → 另建未见确认集（按 URL/session/题族去重，功效计算，预注册并冻结）
→ 两臂隔离运行（预算/模型/参数/知识注入一致）→ 确认集一次预注册统计分析 → 双轴裁决
```
gold/filler 是**开发期判分器自检**：gold 翻正 ≥2 实例且 ≥2 类 P1–P5 证据翻转，filler 翻正 0；再核对变形测试及同一冻结回复的跨版本一致性。任一预注册资格项失败 ⇒ `instrument_status=unqualified`，不得运行确认性主对照。S1b 历史的跨批 51.7% 既可能包含求解器随机性，也可能包含判分口径漂移，**没有同回复配对就不能单独归咎于判分器**。

**独立性保障**：评测期求解器不接额外 `search_records`/`skill_load`；一题一调用；确认集按 session/URL/题族分组防泄漏，近重（题面 vs 卡正文 8-gram > 0.3）只是辅助，仍需检查语义同源；卡不得自引确认集答案。模型随机重复不增加独立样本数。

### 4.3 R3 外部证据淘汰

**两段式**：
- 第一段（本设计实现）：**证据生产**。从有可复核 `applied/adapted` 记录的卡中选一个代表样本，先确认 R2 仪器合格，再预注册卡的配对对照；产出 manifest（卡 ID/SHA、使用证据、试验配置、仪器资格、预注册 hash、结果、限制、恢复验证）。`not_applicable` 不能当作 `rejected`，无显著收益也不能自动推断"无效"。
  - **隔离定义**：只在本实验会话不注入被测卡，**不改全局 `status`/`freshness`、不删卡**；优先用会话级注入配置，不触碰生产注入开关。恢复校验是**配置与快照哈希恢复 + 注入可见性 smoke**，不要求一次随机模型重跑就"回到基线分布"；如需分布检验须预注册重复数与容差。
- 第二段（人工批准）：把 manifest 作为治理修订提交，更新 `docs/governance/card-lifecycle.md` 的有用轴门槛；经人工批准后，程序才允许该类证据参与处置判定。

**为什么必须两段**：F18 的门槛是代码门槛，放宽它属"控制机器"变更，按 `AGENTS.md` 的准入不对称要求，必须说明"为什么模型与既有工具无法自行判断这件事"并给出可调用的人工否决出口——这正是治理修订路径，不该由本设计单方面写死。

### 4.4 R4 时效锚常规化

**四层修法与各自产出**：

| 层 | 改什么 | 产出 | 风险 |
|---|---|---|---|
| ① 锚语义 | `path/code/evidence` 分派；输出 `anchor_root_id`、`anchor_kind`、解析状态 | 区分内容不存在与根不可解析 | `code_root` 不保证 wheel 含 `src/`；无版本映射则 `unresolvable`，不能报 `missing` |
| ② 基线 | `annotate_freshness` 在**实际解析成功**后落内容 SHA、root_id、解析器版本和时间 | 可解析卡形成真实基线 | 基线只证明后续变化，不证明内容正确；不可解析卡保持待核 |
| ③ 覆盖率 | 冷路径提出候选锚，经核实才补声明 | `not_tracked` 可有证据地下降 | 不自动推断路径、不批量造 `current`、不处置卡 |
| ④ 闭环 | `record_use(applied)` 后若状态 changed/missing/unresolvable ⇒ 派生"复核锚"提示（`item_kind=freshness_refresh`，不得被 `settlement_submit` 当使用结算） | 使用后提示复核，**不自动刷新/补基线** | 只复用现有只读清单展示，待办数与结算数分列；若现有清单契约无法安全区分，则先只在 `architecture_status` 报告 |

**不做**：不把"刷了锚"当成"内容仍正确"；不自动降级生命周期（现有语义就是"只报告不降级"，保持）。

**缓存纪律**：`mtime+size` 只作热路径重算提示，不能单独作为"内容未变"的安全证据；基线建立、状态争议或用于处置证据前必须读实际内容计算 SHA。`evidence://` 若没有注册解析器，保留原引用并标 `unresolvable`，禁止按文件系统路径探测。

**解析安全**：`path/code` 解析须在可信 root 内做规范化与边界校验，拒绝 `..` 穿越、绝对路径越权和 symlink 指向 root 外；`evidence://` 只能走既有授权的证据引用解析器，不得把 URI 任意转成 HTTP/文件读取。解析失败返回原因码与可恢复引用，不吞错、不猜根。负向测试至少包含不存在的发行映射、穿越路径、越界 symlink、未授权 evidence ref 和 root 漂移。

### 4.5 R5 演进经验回流

**契约**：`evolution_complete` 的 `note` 增加**可选的结构化核验段**；只有宣称 `verified` 才要求指标与可复核引用，`unverified`、失败、取消均可正常收口（程序只校验结构，不判语义）：

```
validation_state: <verified | unverified>
改了什么：<文件/模块/规则条>
指标：<指标名> 从 <X> 到 <Y>（verified 时必填；引用不可变回执 id/文件 SHA）
证据等级：<model_declared | observation_linked | independently_evaluated>
```

无"指标"段时，只允许出现"未验证"表述。

**回流链**：程序按上述字段生成"演进教训卡候选"骨架 → 模型确认后 `save_experience`（`record_kind=lesson` 或 `experience`，`verification_state` 按证据如实标，证据指针指向演进 id）→ 按载体写入索引摘要（prompt/memory/skill/harness），下一轮检索按"载体+症状"命中。

**边界**：模型可以建议指标，但**模型填写的 X/Y 不自动升格为事实**；`observation_linked` 必须能回读原始测量，`independently_evaluated` 必须指向独立评测回执。无证据时只能标 `model_declared/unverified`，候选卡不得自动晋升为已验证。

### 4.6 R6 修订账本与卡级撤销

**账本行**（append-only JSONL，行级完整性凭据沿用 `use_ledger` 的 `integrity` 机制）：

```json
{"schema_version":1,"ts":"…","scope":"rule|code|skill|memory",
 "target_id":"RULE-AI-31|src/llm_loop/…|skill:…|experience:…",
 "target_root_id":"repo:<sha>|release:<digest>","goal_id":"…","operation_id":"…",
 "before_sha256":"…","after_sha256":"…","before_snapshot_ref":"git:<sha>:<path>|release:<digest>:<path>|snapshot:<digest>",
 "rollback_plan":{"kind":"restore_target_patch","target_id":"…","expected_current_sha256":"…"},
 "rollback_ready":false,"verify_test_ref":"…","evidence_refs":["…"],"integrity":"…"}
```

**分载体撤销**：
- **rule**：从可信的版本化 before 快照恢复**目标规则条**，其它条 hash 不变；在隔离工作树预演并经独立审查，运行态只读规则不接受原地写入。
- **code**：按目标文件和 hunk 生成最小反向补丁并校验当前 SHA；**不默认执行 `git revert <sha>`**，因为提交可能同时包含别的 Goal 的变更。
- **skill**：必须保存原始正文的可信 before 快照；`record_skill` 生成模板**不等于**恢复旧 Skill。
- **memory**：`retire/reopen` 仅能回退生命周期状态，不能证明正文已回到 before SHA；正文恢复需要独立快照。

**落账与回滚资格**：**不得因回滚不可用而拒绝记录审计事实**；可写时仍落事实并标 `rollback_ready=false` 与原因，磁盘满/权限不足时明确报告"未落账"，不宣称成功。只有 before 快照存在且 SHA 正确、目标映射唯一、隔离预演通过，才能标 `rollback_ready=true`。实际回滚前重新校验 `current_sha256 == after_sha256`（CAS）、`target_root_id`、`goal_id`、`operation_id` 与授权、并行 Lane；不匹配就 STOP，不覆盖。**不能用 `bash -n` + 路径存在性冒充回滚安全证明**，也不能执行账本中的任意 shell 文本。

**完整性边界**：普通 hash/integrity 仅用于检测损坏，不证明防恶意篡改；如需要防篡改须另有可信签名/隔离密钥/外部审计根。本阶段不新增密钥系统，文档不得声称已实现抗篡改。JSONL 并发追加必须有单写者或文件锁、行序/幂等键、`fsync` 或明确持久性边界；磁盘满、进程中断时保留未落账诊断，不能将部分行视为成功。

**闸**：规则正文与代码都在 RULE-AI-28（审查）+ RULE-AI-34（合并）范围，撤销动作本身也要过审查；账本只提供"可执行路径"，不提供自主执行口。

---

## 5. 契约变更表（机器可校验）

| # | 对象 | 变更 | 默认 | 校验点 |
|---|---|---|---|---|
| C1 | Method frontmatter | 新增 `carrier`、`carrier_evidence` | `unknown` / 空 | 枚举白名单；非 unknown 要求可解析引用；写入白名单两处同步（F20），旧卡可读 |
| C2 | Experience frontmatter | 新增同名字段 | `unknown` / 空 | `ExperienceDocument` 序列化 |
| C3 | `method_manage` schema | `save_candidate`/`refine` 增 `carrier`、`carrier_evidence` | 可选 | 枚举校验 |
| C4 | `save_experience` schema | 增同名字段 | 可选 | 枚举校验 |
| C5 | `submit_evolution` schema + `EvolutionSuggestion` | 增 `carrier`、`carrier_evidence` | 可选 | 枚举校验；不改变 scope/边界判定 |
| C6 | `evolution_complete` note | 增 `validation_state`；verified 时须有指标与引用，失败/取消可 unverified 收口 | `unverified` | 不因缺指标阻断合法收口；不得无回执宣称独立验证 |
| C7 | `method_manage(annotate_freshness)` | 解析成功才写基线快照 | 无 | 内容 SHA + root_id + 解析器版本 + 时间；解析失败不伪造基线 |
| C8 | 时效输出 | 增 `anchor_root_id`、`anchor_kind`、`resolution_state` | `unresolvable` | 三类锚分派；无源码映射时不误报 missing/current |
| C9 | `architecture_status` 知识面 | 增"载体归属覆盖率" | — | 只报事实 |
| C10 | 新账本 | `revisions.jsonl`，带 schema_version、before_snapshot_ref、rollback_plan、rollback_ready | `rollback_ready=false` | 行级 integrity、单写者/幂等、坏行隔离；无快照仍落事实账，回滚前 CAS + 隔离预演 |
| C11 | `settlement_pending` 只读清单（有兼容性时） | 派生"复核锚"提示（`item_kind=freshness_refresh`），不进入 `settlement_submit` | 无 | 两类计数/幂等键隔离；旧客户端不可区分时退回 `architecture_status` 展示，不污染结算 |
| C12 | R3 治理门槛 | `card-lifecycle.md` 有用轴（**人工批准后才改**） | 现门槛不变 | 生效前须实测"应拦输入"（RULE-AI-35） |
| C13 | R2 评测报告（既有评测目录内） | `instrument_status`、`effect_verdict`、新确认集 manifest、功效/CI/成本 | `not_run/not_assessed` | 未运行与资格失败区分；旧 120 题不得冒充确认集；不合格仪器不输出效应结论 |

**不新增用户工具、不新建数据库/服务、不新增生产动作硬门**是本稿的显式约束：复用现有工具与评测目录。**唯一新增持久账本类型**是 `revisions.jsonl`（C10），但它会产生版本化 before 快照引用；**评测必然还会新增预注册/冻结/确认集/结果文件**，不得写成"整个项目只新增一个文件"。R2 的资格前置是**评测结论的证据门**，不是模型/用户行为执行门。

---

## 6. 跨需求失败模式矩阵

| 失败模式 | 触发需求 | 早期信号 | 处置 |
|---|---|---|---|
| 判分器被无关内容污染（filler 翻正） | R2 | filler ≠ 0 | 仪器不合格 ⇒ 禁止主对照（硬前置） |
| 结论偷换（仪器失败 ⇒ "未测出" / "无效"） | R2 / R3 | 缺 instrument_status 或 not_assessed | 双轴状态机；不合格/无独立确认集 ⇒ not_assessed |
| 旧题泄漏到确认集 | R2 | S0 120 题被重新 70/30 切分；URL/session/题族同源 | 旧题只开发；新确认集分组去重、预注册冻结；无新集不出确认性结论 |
| 伪显著 / 伪功效 | R2 | 重复调用当独立样本、CI 口径不匹配、事后调阈值 | 配对 Δ、预注册 CI/δ_min/功效与多重比较；一次确认性分析 |
| 载体字段被状态流转丢弃 | R1 | 流转后 frontmatter 少键 | 回归测试 + 写入白名单两处同步 |
| 假时效（刷锚冒充内容正确） | R4 | `current` 上升但内容未核；wheel 无源码却报 missing | 基线带 root_id/内容 SHA；unresolvable 单列；报告同时给"是否复核过内容" |
| 批量处置误伤 | R3 / R4 | 处置卡数突增 | 锚缺失只修锚不处置；批量需逐卡证据 |
| 外部证据被当自评 | R3 | manifest 无预注册 hash | manifest 缺 hash ⇒ 不受理 |
| 演进"改了什么"被读成"所以有效" | R5 | 卡片无指标前后值 | 无指标段 ⇒ 只允许"未验证"表述 |
| 撤销误覆盖并行修改 | R6 | 当前 SHA ≠ after SHA，或 git revert 涉其它 Goal | CAS fail-closed + 可信 before 快照 + 隔离 hunk 预演；不执行任意 shell 命令 |
| 账本尾部损坏 | R6 | integrity 校验失败 | 坏行隔离 + 诊断报告，不静默跳过 |
| 通道依赖不可用（打分器连续失败） | R3 / R5 | `scorer_unhealthy` | R3 对照臂须在另行合格的 DPE 仪器下运行——“自带离线对照臂”不构成合格证据（v1.3.1 对齐 §11 残余风险 5，消解两处互斥）；R5 不依赖该通道 |

---

## 7. 拷问记录（原三轮、两次复核与第六轮）

> 形式：问题（锚定设计正文的实问）→ 回答要点 → 由此产生的**设计修订**。修订是本稿与初稿的差异来源。

### 7.1 第一轮（针对初版六条需求）

拷问锚定的六条规模数值全部被追问"实测还是估算？超过多少时设计失效？"——这是本稿最重要的结构变化来源。

- **Q（scale）**：96% / 57% / 13 / 910 / 37 / 42 这些数字来自实测还是估算？超过多少时设计失效？
  **A**：初稿把"卡片超龄 57%"与"37 条规则、42 个技能"当作设计锚点，其中**至少两处不可答**：57% 是按 `created_at` 与不同"今天"口径算出来的（整数天 1058、小数天 1089，程序同规则是 1089）；"910"其实是文件数而非经验数（目录里 911 个 md，其中 910 个匹配 `EXPERIENCE-*.md`）。37/42 是真实存量但不构成任何"设计失效阈值"。
  **修订**：F1–F24 每条带来源；凡阈值型断言一律给出"失效阈值 + 当前值 + 距离"三元组；把"存量数字"与"设计阈值"分开——37 条规则、42 个技能只是覆盖面，不是失效阈值。
- **Q（failure_modes）**：最坏失败场景是什么？数据会丢失/损坏吗？
  **A**：初稿未答。真实最坏场景不是"写坏卡"，而是**把仪器缺陷读成被测对象结论**（F14 已发生过一次：S0 标签是"未测出"，若被读成"无效"就会据此批量处置 1843 张卡）。
  **修订**：R2 写死"仪器先合格"硬前置 + 三选一结论词表；R3 写死"对照结论只作补充证据、程序不得自行放宽门槛"；§6 新增失败模式矩阵，第一行就是这条。
- **Q（security）**：权限边界在哪里？谁能调用/谁能读/谁能改？有无可被滥用的入口？
  **A**：初稿未答。真实边界问题不在"读"，在"移除实验可能被人为用来洗白问题卡"。且证据记录本身可能携带敏感内容。
  **修订**：R3 隔离改为**可逆**且不自动触发处置；证据只记命令/路径/回执引用不抄原文（RULE-AI-27 第 9 条）；R6 撤销不新增自主执行口。
- **Q（edge_cases）**：并发 100 次、磁盘满、配置版本不一致的行为？
  **A**：初稿未答。并发走既有账本语义（`slot_id`+`submission_hash` 双层幂等键，重复提交折叠为一条）；磁盘满时账本写入失败须"拒绝该次写入并如实报未落账"，不半写；配置/依赖版本不一致时索引格式带 schema 版本，旧索引直接重建而非兼容猜读。
  **修订**：§3.3 与 R2/R6 的验收项里补上"并发折叠""半写禁止""旧索引重建"三条。
- **Q（ux）**：用户首次接触能否 30 秒理解价值？
  **A**：初稿未答。载体归属对用户不可见，只出现在卡的 frontmatter 与演进审阅面板；用户界面不变；模型侧只新学四个枚举值。
  **修订**：R1 明确"不新增用户可见概念"；§0 用一句话给出用户价值（"以后改哪、留哪、废哪都有账可查，不靠模型自评"）。

### 7.2 第二轮（针对修订稿：六条需求 + 实测基线）

拷问把八个数值的来源与失效阈值逐条要了一遍，并追问 1000 倍增长、并发、可信输入、故障检测、幂等、首次接触可理解性。

- **Q（scale）**：1000 倍增长时哪个组件先成瓶颈？热/冷路径怎么分？缓存策略？状态持久化能扛崩溃吗？
  **A**：最先成瓶颈的不是卡数，而是"每次检索都扫全池 + 每卡都算 freshness"。修法：卡元数据（状态/载体/时效/使用计数）进单张 append-only 元数据账本 + 启动时构建内存索引；检索读索引不读卡体；freshness 的 SHA 快照按 mtime+size 缓存、仅在 mtime 变化时重算；批量补声明/补基线/覆盖率统计走离线冷路径，不进对话关键路径。持久化：账本每行带 integrity，崩溃后半行隔离到旁文件并出诊断。
  **修订**：§4.1–§4.4 补上索引与冷路径设计；R1/R4 明确元数据索引是承载面。
- **Q（security）**：输入是否可信？有无可被滥用入口（自动化脚本/重放攻击）？
  **A**：卡正文、演进 content、载体证据都是模型可写文本 ⇒ 一律走既有写侧防污染防线（F21，判定为 blocked 时拒写）；敏感值不落账；评测期求解器不接检索与知识注入，避免卡内容泄漏进留出集。滥用入口就是 R3 的移除实验（见 7.1）。
  **修订**：R2/R3 补写隔离条款；证据引用格式统一为"命令/路径:行/回执 id"。
- **Q（failure_modes）**：失败如何被检测？重试策略是否合理（指数退避/最大次数/幂等）？失败信息是否对用户友好？
  **A**：最坏场景 = 独立打分通道长期不可用 + 留出集判分器被污染（F14 已发生）。降级顺序必须 fail-closed：仪器不合格 ⇒ 不出效应结论，只报"未测出"；元数据索引构建失败 ⇒ 退回现有全池扫描路径（慢但正确），不因性能优化丢正确性。检测靠账本 integrity + `architecture_status` 指标段。重试：打分通道指数退避已有（`next_retry_at`）；移除对照按实例 id 幂等，失败实例单独重试不重跑全池。失败信息只给类别与动作，不暴露内部栈。
  **修订**：§4.2/§4.4 补降级顺序；R2 补"失败实例幂等重试"；§5 C9/C10 补指标暴露点。
- **Q（edge_cases）**：空/超长输入、时钟偏移、权限缺失、并发 100 次？
  **A**：载体枚举缺省 `unknown`；证据字段超长按既有长度上限截断；时间戳统一宿主本地时区（RULE-AI-26），账本顺序用 ts+行序双键不用 ts 单独定序；磁盘满 ⇒ 拒绝该次写入并如实报"未落账"，不半写；并发 100 次 ⇒ 幂等键折叠为一条；权限缺失 ⇒ R6 撤销需要仓库写权限，缺失即失败并说明缺什么。
  **修订**：R1/R6 补边界条款；§6 增"账本尾部损坏""半写"两行。
- **Q（ux）**：错误信息能否帮用户自助修复？有无可观察/可调试入口？
  **A**：`architecture_status` 增"知识卫生"一段（覆盖卡数、载体归属覆盖率、时效状态分布、独立通道健康度），失败可自助定位；不给用户新概念。
  **修订**：C9 明确指标段内容；§3.2 保留"本机比论文强"的三点，作为不做过度设计的依据。

### 7.3 第三轮（针对第二轮回答的复核）

第二轮回答里出现了两处**新盲点**，被第三轮拷问抓住并已修订：

- **盲点 1（被推翻的前提）**：第二轮把"method 侧 `rejected`=0"当成了"负反馈通道不存在"。复核发现：经验侧有 `not_applicable` 4 条，`not_applicable` 与 `rejected` 在 RULE-AI-31 里语义分离（前者=卡没错但不适配，后者=卡错误引导）。零 `rejected` 说明的是**负反馈被压成了"不适用"**，不是"没踩坑"。这恰好印证 `card-lifecycle.md` 里那条纪律（"把该报 rejected 的压成 not_applicable，会饿死有用轴唯一的低成本处置证据源"）。
  **修订**：F4/F5 补上两侧对照；R3 的选卡条件与判定口径改为"以 `rejected` 与"卡依赖实例上无可观察收益"为主，`not_applicable` 只作背景"；结论里明说"负反馈通道存在但被语义压扁"。
- **盲点 2（被推翻的前提）**：第二轮把"时效 57% 超龄"当成主要指标。第三轮按程序同规则复算后：程序用的是小数天口径（1089/1917 = 56.8%），整数天口径是 1058（55.2%），初稿写的 1087/57% 与任何一个口径都不完全一致（来自更早时点的快照）。
  **修订**：F3 改为"程序同规则口径 + 口径差说明"，并删掉初稿把"超龄率"当作设计依据的表述——超龄率不是根因，根因是锚根解析（F10/F11）。

**第三轮新增并已纳入的要求**：所有规模断言必须给"失效阈值 + 当前值 + 距离"；所有结论必须给"最坏失败场景 + 降级顺序"；所有新增字段必须核对"是否落在现有写路径白名单里"（F20 直接催生了 R1 的回归判据）。

### 7.4 第四轮：独立子代理事实核查（非拷问，是外部复核）

三轮拷问之后，另起一个**独立子代理**（只读，工具白名单限定为 shell/读文件/检索）逐条复核 §2.1 的 F1–F24、抽查代码行号锚点、并专门搜寻"超出证据的断言"。结论：**PASS 23 / FAIL 1 / UNVERIFIABLE 0**（UNVERIFIABLE 项为 F22 的一个分句）。它抓出并已修订的问题：

| 编号 | 核查发现 | 本稿修订 |
|---|---|---|
| **F6 FAIL** | 原文写"promotion=pass 的卡仍停在 candidate"是**全称断言且为假**：带 pass 回执的是 **67 张卡**（69 是行数），其状态为 candidate 51 / qualified 10 / hold 4 / active 2 —— 16/67 已离开 candidate | F6 改为行数/卡数分列 + 明确"正向出口在动、负向出口被锁死"；§1 R3 来源行与 §2.3 判断 1 同步改写（判断 1 原先把 1843 candidate 的成因归给"晋升通道没建"，实为"负向通道不存在"） |
| **A1 越界** | §0 判断 1 原写"从未产出过'因这张卡而变好'"，与本文档自己的 F14（gold `b=60 / c=4 / p=7.4e-14`、gold_verdict=PASS）**直接矛盾**——那是把"仪器不合格"读成了"从未测量过" | 改为"**从未产出过仪器合格的**'因这张卡而变好'"，并把 gold 与 filler 两个数字并列在摘要里，让读者看到为什么这次"变好"不可采信 |
| **A3/A5/A6/A7 越界** | ①"75 处源码差异"未给口径；②"运行态根"与脚本变量 `RUNTIME`（数据目录根）同名异义；③ F3/F8 是时点敏感值但未标时点；④"filler 翻 21 例"是 2026-10-19 的冻结快照，被复述成"现状" | ①§2.2 补口径（76 / 75 两个数与取舍）；②F10 改为三根对照并**重写脚本变量名**（`DATA_ROOT` / `BUNDLE_ROOT` / `REPO_CHECKOUT`）；③新增"时点敏感值"说明；④F14 与 §0/§2.3 标明该结果来自 2026-10-19 冻结快照 |
| **F22 分句** | "本会话 `settlement_pending` 返回 2 项"是会话回执、不可独立复跑，被混入可复算事实 | 改为"契约部分可复核"+"本会话回执不作为事实层依据" |

**核查同时确认了本稿的正确之处**：RULE-AI-21 在两份 `ai_rules.md` 里都只有"编号空缺说明"段落、本就不是一条规则，因此"checkout 缺 RULE-AI-37 ⇒ checkout 落后于运行态"的表述成立；引用的 8 处代码行号锚点（F11/F18/F19/F20/F21/F23/F24 与 `store.py:1899` 白名单）经逐键开卷核对**名副其实**；10 个承重数字全部复现一致。核查给出的处置是"修正这两条措辞前不应引作最终依据"——本节即为修订记录。

**该核查的边界**：子代理在沙箱内无法执行运行态解释器（python3.13 不可见），故"运行态实测"由落盘数据文件 + 权威计算入口（`runtime/knowledge_health.py`）的规则逐行核对代替；它自己声明了这一限制，未把读源码当成执行结果。

### 7.5 第五轮：独立审查（v1.1 → v1.2，本节即修订记录）

审查方式：按"事实基准 → 内部一致性 → 可验收性"三层复核——现读运行态与 `evals/` 落盘文件、重算差异计数、逐条比对跨章节口径。**结论方向未变**；本轮只修事实基准、口径与可验收性，不重跑实验、不改任何结论。

| # | 审查发现 | 本稿修订 |
|---|---|---|
| **V1 事实基准漂移** | 运行态已于 2026-11-16 00:04 升级 `LFL-0.6.54`（进程启动命令即为 0.6.54 的 `lfl start`），v1.1 仍写 0.6.53；0.6.53→0.6.54 包内差异 16 项（排除 `__pycache__`），须确认是否触及本稿锚点 | 头部事实基准改 0.6.54，并注明双版本核对结果：16 项差异**不含** `methods/store.py`、`experiences/store.py`、`introspection/rule_index.py`、`introspection/knowledge_advisor.py`、`runtime/paths.py`、`runtime/knowledge_health.py`（均两版一致）；bundle 技能数均 42、规则数均 37、`_bundled/manifest.json` 仅 `version` 变；§2.2/§11 补 0.6.54 差异计数口径（81/80） |
| **V2 F15 三处口径不一致** | `dpe_spec.md` 记 31 实例/93 条；`d_sets.json` 实为 28/30/union 46（无 31）；`review_pack.csv` 实为 60 条/20 实例×3 臂且 P1–P5 全空 ⇒ v1.1 的"现 31 实例（`d_sets.json`）"引错文件，"双人盲标 60 条"也没说来源 | F15 重写为"三处口径不一致"事实行并列三文件真实值；§4.2 执行顺序与 M0 出口加"先对齐口径"，把"60 条"明确为 `review_pack.csv` 的 20 实例×3 臂；`run_s0.py`/`analyze_s0.py`/`pool_p28.jsonl` 路径修正到 `s0_p28/` 子目录 |
| **V3 §5 自相矛盾** | 末句写"不新增…持久层"，C10 却新增 `revisions.jsonl` 账本 | 改为"不新增工具、不新增硬门、不新建数据库/服务；唯一新增持久文件是 append-only `revisions.jsonl`" |
| **V4 判定门槛与确认集不自洽** | `D≥30` 若套在确认集（36 对）上，上限只有 36，几乎不可达 | 明确 `D≥30` 只是"开发集→确认集"准入；确认集判定用 McNemar 精确 `p<0.05` + 效应量 CI；gold/filler 的"证据翻转"改按 `P1–P5` 单项计 |
| **V5 仪器资格与第三人裁决张力** | R2 验收写"无第三人救场"，`dpe_spec.md` 写"第 3 人裁决（多数票）" | 分阶段：资格统计只认双人独立标；第三人只用于正式标注阶段的分歧终裁 |
| **V6 缺停止规则** | 规格两次不达标后无出口，易反复重标 | R2 增"两次改规格 κ 仍 <0.60 ⇒ 停止，只出仪器未合格" |
| **V7 "隔离"未定义** | R3 要求"隔离"但未说隔离什么、如何可逆 | §4.3 补定义：批次内不注入、不改 `status`/`freshness`、自动恢复、记恢复命令与校验 |
| **V8 `revert_command` 无校验** | 账本可能记下跑不通的回滚命令，而 §9 验收要求"可复跑回滚" | §4.6 增落账校验（`bash -n` + 目标存在性），失败拒写或标 `revert_verified=false`；§9 只认 verified 行 |
| **V9 C11 语义污染** | 刷锚待办混入结算清单会污染待结算计数 | C11/§4.4 增 `item_kind`（`settlement` / `freshness_refresh`），两类不互相抵扣 |
| **V10 Skill 载体缺口未点明** | §3.1 说 Skill"无账"，六条需求却无一条修 Skill 使用记账 | §3.1 明说本稿只补 R6 修订账本（`scope=skill`）、不做使用记账，属残余缺口；§10 增 D7 承接 |
| **V11 附录脚本数不符** | 实际 8 个脚本，附录列 7 个；且未注明脚本根 | 附录 A 补 `more_facts.py`，注明脚本根 = `~/.local/share/lfl/work/design-20261115/` |
| **V12 表述含糊** | §0 R1"1 处 frontmatter 白名单"（Experience 实为 document 序列化）；§3.1"经验 910/911"；§11"4 类字段" | 分别改为"2 处 frontmatter 序列化"、"经验卡 910（目录 911 个 md）"、"4 组新增面（逐项列明）" |
| **V13 遗漏最关键的一轮仪器实验** | 文档只写 S0/S1（v1.3 口径），漏掉同日（2026-10-19）且更关键的 **S1b 正交 filler 阴性对照**（v1.4）：字面门槛 G1=16/G2={c2,c3}/F1=0 全过，但预注册两项诊断失败（注入测试 F1 0→1；新旧 gold 一致率 51.7%<0.8）⇒ "S1b 不构成仪器合格证据，S2 停"；另 `analysis_v14.json` 显示同一批 S0 换 v1.4 判分变 `D=30/R=0`（v1.3 是 28/16）——换版本即翻结论 | 新增 F14b 事实行；§0 判断 1/2 与 R2 摘要同步引用；R2 可验收判据新增两项预注册诊断（注入测试、新旧 gold 一致率 ≥0.8），执行顺序与 §9 验收 2 同步 |

**本轮未改动的边界**：不重跑 S0/S1/S1b、不改已核数值（F1–F24 原值保留）、不重算统计；只做两件事——补一条被漏掉的关键事实（F14b）与修"文档对事实的表述 / 设计的可验收性"。**v1.2 仍未过 RULE-AI-28 的发布闸**——本稿是建议稿，不是对外文稿；若要发布或据此开工，须另起独立审查与人工裁决。

### 7.6 第六轮：对抗性拷问（v1.2 → v1.3，设计自审）

> 本轮以**反例是否能推翻结论**为准，逐一核对现有文档、`evals/methodcard_rsi_v1/dpe/dpe_spec.md`、`dpe/d_sets.json`、`s0_p28/POOL-P28-FREEZE.json`、`docs/governance/card-lifecycle.md` 和 `AGENTS.md`。没有重跑 Provider、没有取得独立 Reviewer PASS。下表"修订"均是**设计要求**，不冒充已实现功能。

| 拷问 | 能推翻原方案的反例 | v1.3 裁决与修订 |
|---|---|---|
| **Q1：确认集真的没见过吗？** | S0 120 题已用于 S0/S1/S1b、判分器调试；原案再随机切 84/36，仍然是已暴露题目 | **P1**：废止旧题 70/30 确认方案。旧题仅开发/校准；新确认集按 URL/session/题族分组去重并冻结 |
| **Q2：仪器不合格与没测出收益是一回事吗？** | filler FAIL 时输出"未测出"，读者会误以为完成了有效实验 | **P1**：分 `instrument_status` 与 `effect_verdict`；不合格、泄漏、功效不足 ⇒ `not_assessed` |
| **Q3：换判分器后金标一致率差，是判分器还是模型变了？** | 比较的是不同批次重新采样的回复；模型随机性可能单独造成差异 | **P1**：同一冻结回复测判分器重测信度；不同采样批次单独测求解器稳定性。保留 S1b 当时 FAIL，不事后改写历史判定 |
| **Q4：人为加一句话应当"绝不翻正"吗？** | 插入内容可能真实改变动作承诺；正确判分本应随语义变化 | **P1**：变形测试分语义不变/语义改变两类，先由人标金标，前者应不变、后者应正确跟随金标 |
| **Q5：`p<0.05` 能证明值得部署吗？** | 小收益但成本暴涨，或同题多次采样当成独立 n，均可伪造价值 | **P1**：预注册 `δ_min`、配对 `Δ=(b-c)/n`、功效、成本、重复聚合、多重比较；Wilson 单比例 CI 不得替代配对净效应 CI |
| **Q6：wheel 的 `code_root` 一定含 `src/` 吗？** | 发行 wheel 只有 site-packages/bundle；正确代码锚可能根本不可映射 | **P1**：版本化 root_id + `unresolvable`；无法解析不等于文件真的 missing，首次基线不能伪造 current |
| **Q7：`mtime+size` 能证明文件未变吗？** | 同大小、保留 mtime 的内容替换可绕过缓存 | **P1**：缓存只提示重算；用于基线/争议/处置的证据必须读内容 SHA |
| **Q8：写一个 `git revert` 就能撤销单张卡/规则吗？** | 一个提交含其它 Goal；模板重建丢原文；并行修改导致旧补丁覆盖新工作 | **P1**：before 快照 + 当前 SHA CAS + 隔离 hunk 预演 + 人工批准；无快照标不可撤销，禁止任意 shell 回滚 |
| **Q9：`bash -n` 与 integrity 证明安全/抗篡改吗？** | 合法 shell 可删除别的文件；普通哈希可被同时改写 | **P1**：回滚计划结构化，不执行模型提供的 shell；integrity 只声称损坏检测，不声称防恶意篡改 |
| **Q10：`evolution_complete` 缺收益指标就该失败吗？** | 合法失败、取消、尚未验证的演进也需要收口 | **P2**：`unverified` 可收口；只有 `verified` 要求可回读指标回执，不把模型自述升格为独立验证 |
| **Q11：一个无显著收益的移除实验能自动淘汰卡吗？** | 样本小/仪器不合格时"未测出"可能只是功效不足 | **P1**：R3 必须继承 R2 仪器资格，结果仅为证据/提案；不改既有治理门槛，不自动处置 |
| **Q12：存量 candidate 多，是否证明 carrier 字段缺失是根因？** | 67 张 promotion-pass 卡中 51 张仍 candidate，说明还需调查正向流转 | **P2**：R1 定位为归因可追溯性；不把字段覆盖率或 candidate 比例直接当效果指标 |

**本轮的三个不可妥协反例**：

1. `old_pool_as_holdout`：把 S0 120 题随机切 84/36 并声明"独立确认" ⇒ **FAIL**；无新确认集只能 `not_assessed`。
2. `bad_instrument_positive_effect`：gold 显著、filler 或人工资格失败 ⇒ **FAIL**；不得输出收益结论，即使 p 值极小。
3. `rollback_after_parallel_edit`：账本 after SHA 与当前目标 SHA 不同仍尝试覆盖 ⇒ **FAIL**；只出冲突诊断，不执行撤销。

**最小实施优先级**：先修"仪器判定 + 旧题泄漏"和"时效根解析"，再加可追溯字段；R3/R5/R6 只在明确的业务样本上试点。不要为了本轮设计先建通用调度器、数据库、额外硬门或重跑整个旧题池。

### 7.7 第七轮：v1.3.1 编辑性勘误（残留同步 + 平台口径，2026-11-16）

> 编辑性勘误：不新增设计要求、不改任何 F1–F24 历史数值、不改变 §7.6 裁决。依据：第一 Run 三只读子代理调查（A/B/C，2026-11-16）与第二阶段执行指令裁决 A/B（2026-11-16 01:27）。本轮未经独立 Reviewer，不冒充审查。

| # | 位置 | 勘误前问题 | v1.3.1 处置 |
|---|---|---|---|
| ED1 | §1 R3 来源行 | “现有淘汰判据实际上只有模型自评”与“正向出口在动、负向出口被锁死”解释性短语未按 §2.3 判断 1（入口存在、当前证据不足）口径同步 | 改为“负向证据稀疏……不能推断为制度只有模型自评”并删除该解释性短语（F6 数值原样保留；§2.1 F6 行与 §7.4 历史审查记录中的同源短语作为历史快照保留，解释一律以 §2.3 为准） |
| ED2 | §1 R4 读取侧闭环 | 触发态只列 changed/missing（缺 unresolvable）；刷锚待办未与结算项隔离——与 §4.4④/C8/C11/V9 矛盾 | 触发态补 unresolvable（补锚根映射而非刷内容）；待办带 item_kind=freshness_refresh 隔离——只提示、不得进入 settlement_submit，旧客户端不兼容时回退 architecture_status |
| ED3 | §6 失败模式矩阵“通道依赖不可用”行 | “R3 自带离线对照臂”与 §11 残余风险 5“不能宣称自带离线对照臂就足够”互斥 | 对齐 §11 风险 5：R3 对照臂须在另行合格的 DPE 仪器下运行 |
| ED4 | 事实基准头部 | v1.2 的 0.6.54 运行态快照未标注属 Deepin 侧；“本轮只读观察”停在 2b548ef39/ahead 8 旧时点 | 三点口径：Mac live=0.6.53@.releases/1b457042（实测）；origin/main=0.6.54@9e6b438c（PR#36 已合并，非“准备中”）；Deepin 0.6.54/gen17=历史回执未重核。main 观察更新为 075061769＋双向分叉逐侧计数（本地 10 / ref 侧 33；远端 tip 已至 4f1628ed） |
| ED5 | 版本链/状态行/收口声明 | 版本仍标 v1.3 | 升 v1.3.1；§7.4–§7.7 链路补全；收口声明更新并注明配套 DPE 规格在另一 lane 新增、未合并未推送 |

（F1–F24、§7.1–§7.6、附录 A/B 数值与文字未动。）

---

## 8. 分期与里程碑

| 阶段 | 内容 | 出口判据 | 依赖 |
|---|---|---|---|
| **M0 事实与仪器**（先做） | 只读重核 live/code_root 与基线；修 R4 ①② 的最小实现；对齐 DPE 的 spec/d_sets/pack；旧 pack 60 条双人盲标；补 11 张卡锚分类；制定**新确认集来源/去重/功效**方案 | 三处口径一致；资格盲标达标，gold/filler/变形诊断达标；可解析锚有 root_id/基线，不可解析明确标记；新确认集方案冻结前置就绪 | 先核验代码身份与隔离工作树；**不要求 6 张 unbaselined 无条件归零** |
| **M1 载体归属 + 覆盖率** | R1（C1–C5、C9）；R4③只提出可核候选锚并逐项确认 | 新旧卡读写兼容、状态流转字段不丢；覆盖率分母/分子可复算；无误处置 | M0 锚语义 |
| **M2 新确认集主对照** | R2：旧 S0 仅开发，另建未见集、预注册功效/阈值、冻结后配对运行 | 仪器合格且新集独立 ⇒ 一次性输出双轴裁决与 Δ/CI/p/成本；条件不满足 ⇒ not_assessed，不虚报收益 | M0 仪器合格；新确认集可获得 |
| **M3 外部证据与回流** | R3 单卡移除对照（不改门槛）；R5 一次真实演进候选回流 | 合格仪器 + ≥1 份外部证据 manifest（状态不变）；≥1 条证据等级真实的演进教训卡 | M1；R3 还须 M0 仪器合格 |
| **M4 安全撤销试点** | R6 账本 + 规则/代码/Skill/Memory 各一个**隔离预演**；无 before 快照则明确不可撤销 | 账本完整性、CAS 拒绝、并发不覆盖；`rollback_ready=true` 样本预演回到 before SHA，其它样本如实标 false | M1；可信 before 快照 |

**顺序理由**：M0 先行，因为 R2/R3 需要仪器资格，R4 需要真实代码根；M1 与 M2 在 M0 后可分别推进，不必人为串行；R5 的回流不依赖独立 `knowledge_score` 恢复。每阶段只改一个问题族，避免为单卡实验新建通用平台。

**工作量/预算口径**：原 v1.2 的 M0 2–3、M1 3–4、M2 2、M3 3、M4 2 人日仅是**旧方案粗估**，不含新确认集采集、双人标注、功效测算与审查往返，**不能作为本轮承诺**。M2 的 Provider 调用预算应由冻结后的新确认集 `n × 2 臂 × 预注册重复数` 加资格诊断成本计算；确认集不可得时不启动主对照。

---

## 9. 验收判据（什么时候算"做完了"）

1. **R1**：三类落点各有"写入→读回→状态流转→再读回"测试；旧卡缺字段仍可读；非 unknown 无引用时回退 unknown；`architecture_status` 覆盖率可复算，不以 carrier 改变动作权限。
2. **R2**：预注册/冻结/结果 hash 互指；DPE spec/d_sets/pack 一致；资格盲标、gold/filler、语义变形与同回复跨版本诊断报告齐备；新确认集**未参与旧 S0/S1/S1b 调参**且按题族去重；功效/δ_min/CI/成本/失败实例已预注册；确认集只做一次预注册统计分析；不满足则 `not_assessed`。
3. **R3**：仪器合格且单卡 manifest 含预注册 hash、隔离/恢复哈希；被测卡全局状态与注入配置**未变**；治理门槛文件在人工批准前**未改**；未测出不得自动处置。
4. **R4**：三种根/锚有 `anchor_root_id` 和解析状态；wheel 无源码映射返回 `unresolvable`；`evidence://` 不走文件 stat；可解析锚建真实 SHA 基线，不可解析不伪造 current；无卡因锚缺失自动失效。
5. **R5**：`unverified` 的失败/取消演进可正常收口；`verified` 有可回读指标证据；演进教训卡指向 evolution id 且证据等级与回执一致，不把模型声明冒充独立验证。
6. **R6**：账本行完整性、`operation_id` 幂等、并发与坏行隔离可验；无快照也落审计事实但标 `rollback_ready=false`；有快照的记录在隔离环境 CAS + 最小补丁预演成功；当前 SHA/root/Goal 漂移或其它 Goal hunk 冲突必须拒绝覆盖。
7. **全程**：所有代码变更按 RULE-AI-28 过独立子代理审查；分支收口按 RULE-AI-34；共享文件按 RULE-AI-32 做 hunk 级最小化；宣称任何"生效"前按 RULE-AI-35 实测"应拦输入"（仅 C12 触发）。

---

## 10. 待裁决点（需要人工决定，本稿不代决）

| # | 裁决点 | 选项 | 本稿倾向 | 不决的后果 |
|---|---|---|---|---|
| D1 | R3 的外部证据是否可进入处置门槛 | (a) 只作补充证据、永不自动处置；(b) 满足更强条件后可直接处置 | **(a)**（保守，不放宽既有代码门槛） | R3 停在"只产出建议"，淘汰机制不变 |
| D2 | `carrier` 是否允许 `unknown` 之外的新值（如 `tool`/`prompt_template`） | 固定 5 值 / 可扩展 | 固定 5 值（未知归 unknown） | 枚举漂移，统计口径不稳 |
| D3 | R2 确认集从何处获得 | 旧 S0 120 题继续当开发集 + **新未见确认集** / 暂不做确认性实验 | **旧题仅开发，新题必须独立**；若无法取得，报告 not_assessed，不强行重跑 | 不具备独立确认集就无法宣称确认性收益 |
| D4 | 载体归属覆盖率是否进入健康度告警 | 只报事实 / 超阈值告警 | 只报事实（不新增门） | 新增门需按 RULE-AI-35 实测，且违反"记录不拦截"原则 |
| D5 | R6 账本落点 | 仓库 `docs/` 下 / 运行时数据目录 | 运行时数据目录（append-only、与运行态同生命周期） | 账本与被记对象生命周期错位 |
| D6 | 是否把"继承经验有效性"升级为正式评测（进 CI 常规闸） | 进 / 不进 | **先不进**（等 M2 出结论再议） | 过早把未测出的结论写成常规闸 |
| D7 | Skill 使用记账（本稿残余缺口）是否单独立项 | 本轮不扩 / 下一轮单独立项 | **下一轮单独立项**（本稿只补 R6 修订账本 `scope=skill`，不扩范围） | Skill 载体继续"有物、无账"，与 Memory 的经验侧同样断链 |
| D8 | R2 的最小有意义净效应与预算 | 预注册 `δ_min`、目标功效、成本上限 / 仅报显著性 | **先用开发集估算，再由人工确认冻结参数**；不事后改门槛 | 无法解释"显著但不值得部署" |

---

## 11. 残余风险与非目标

**残余风险**

1. **仪器与确认集风险最高**：DPE 判分含人工判断（P2/P3），旧题已暴露；若双人盲标组织不起来、资格失败或找不到未见确认集，R2 应标 `not_assessed`，**不是"未测出"**。缓解：M0 先完成旧 pack 60 条双人盲标与资格诊断，另行冻结新确认集的来源/功效；第三人只用于正式分歧终裁。
2. **结论外推风险**：任何"某卡有效/无效"的结论只对**该卡、该决策点、该留出集**成立，不外推到"经验库整体有效"。
3. **证据自证风险**：移除对照与主对照都是"我们自己设计的对照"，可能被指为构造偏好。缓解：预注册 + 冻结 + 盲标 + 阳性/阴性对照（gold/filler）+ 独立复核，四重约束同时在位。
4. **写入面膨胀风险**：本设计新增四组主要运行面——① `carrier` + `carrier_evidence`（3 类落点）、② `anchor_root_id` + `anchor_kind` + `resolution_state`、③ 可核基线快照、④ `revisions` 账本；另有评测报告 C13。若白名单不同步即丢字段（F20）。缓解：每个 store 做字段保留与旧卡兼容测试，不新建热路径索引系统。
5. **依赖不可用风险**：历史快照里独立 `knowledge_score` 通道不健康（F8）；R3 必须依赖**另行合格的 DPE 仪器**，不能宣称"自带离线对照臂"就足够；R5 允许 `unverified` 候选，不将模型背书当独立验证。
6. **回滚与并发风险**：`git revert`、模板重生成、状态 reopen 都不能普遍证明精确恢复；普通 integrity 不能防恶意篡改。缓解：before 快照、CAS、隔离最小补丁、人工审批；无条件则 `rollback_ready=false`。

**非目标（本稿明确不做）**

1. 不让系统改自己的权限、安全门、规则、评估器。
2. 不做无界开放式自改，不做"自改进速率 > 人工改进速率"的宣称（见 R2 诚实边界）。
3. 不以自评为唯一改进信号，不把"未测出"当"无效"。
4. 不新建硬门（除 C12 需人工批准的治理修订）。
5. 不在本轮动 `ai_rules.md` 正文（规则正文变更走既有规则治理流程，本稿只为其准备撤销能力）。
6. 不动 checkout 与运行态之间的源码差异（路径级 75 项 = 0.6.53 口径；审查时点运行态升到 0.6.54，同口径重算为 81 项 / 排除 `_bundled` 80 项，见 §2.2；那是另一个议题：本稿已注明 checkout 落后于运行态，落地时须先对齐分支基线）。

---

## 附录 A 本稿复算脚本（可复跑）

脚本根 = `~/.local/share/lfl/work/design-20261115/`（LFL 运行态 work 目录，**不是**仓库 `work/`）；下表路径均相对于该根。共 8 个脚本（v1.1 漏列 `more_facts.py`，v1.2 补）。

| 脚本 | 用途 | 关键输出 |
|---|---|---|
| `work/design-20261115/baseline_facts.py` | 卡池状态分布、卡龄分桶、使用账本统计、qualification 统计 | 1917 卡；applied 12/adapted 1；qualification 161 行 |
| `work/design-20261115/freshness_states.py` | 按 store 同规则复算时效状态 | unbaselined 6 / missing 5 |
| `work/design-20261115/freshness_two_roots.py` | 同批卡在**三根**（`DATA_ROOT` / `BUNDLE_ROOT` / `REPO_CHECKOUT`）下的时效状态对比 | 源码根：current 2/changed 2/missing 1；另两根：missing 5 |
| `work/design-20261115/usage_and_age.py` | 使用账本证据等级/收益分布 + 卡龄口径对比 | method 侧 13 行全 `helped`；整数天 vs 小数天口径差 |
| `work/design-20261115/more_facts.py` | 补充事实复算（卡龄口径、"910 是文件数而非经验数"的分解） | 目录 911 个 md；`EXPERIENCE-*.md` 910 |
| `work/design-20261115/runtime_root_check.py` | 确认运行态工作区根解析到 `_bundled/` | `src/...`、`evals/...` 锚在该根下不存在 |
| `work/design-20261115/verify_fail_f6.py` | 复核 F6：带 `promotion=pass` 的**卡**数与其当前状态分布 | 69 行 / 67 卡；candidate 51、qualified 10、hold 4、active 2 |
| `work/design-20261115/verify_roots_and_diff.py` | 复核 F10 三根对照 + checkout↔运行态差异计数口径 | 三根状态分布；差异 76/75（0.6.53 口径）、81/80（0.6.54 口径） |

## 附录 B 与既有文档的关系

- `docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md`：RSI 需求分析建议稿（本稿 R2 的方法学来源，其 R14–R16 修订已被本稿吸收）。
- `docs/governance/card-lifecycle.md`：卡片生命周期治理（失效三轴、批量纪律、锚三分支、qualification 三段式）——R3/R4 直接引用其既有纪律，未另立规矩。
- `docs/DESIGN-20260917-knowledge-injection-layering.md`：注入分层与归因闭环（R1/R2 的"评测期不接检索"与本稿同源）。
- `evals/methodcard_rsi_v1/`：受控对照仪本体（R2 的复用对象）。
- `evals/method_binding_efficacy_v3/`、`evals/instrument_qualification_v1/`：盲标门与仪器合格先例（R2 门槛的取值来源）。

---

**收口声明（v1.3.1）**：本稿仍为**设计建议稿**，本轮只编辑此 Markdown；未实施行为代码、未修改规则/权限/生产配置，未进行 Provider 实验、独立 Reviewer、完整 R9、GitHub 集成或生产发布。F1–F24 是原 v1.2 的**历史事实快照**，不是本轮实时重测；本轮额外核对了 `AGENTS.md`、DPE 规格、D 集合、S0 冻结文件及生命周期治理。**v1.3 的主要设计纠偏**：旧 S0 120 题不得冒充确认集、仪器资格与效应双轴分离、统计与变形诊断纠偏、wheel 锚根不可解析单列、演进未验证可收口、回滚改为快照 + CAS + 隔离预演。**v1.3.1 为编辑性勘误**（见 §7.7）：三处 §7.6 之前残留同步（R3 来源行 / R4 读取侧 / §6 互斥行）与头部平台时点口径校正；不改任何 R1–R6 设计要求、不改 F1–F24 与 §7.1–§7.6 历史数值；配套 DPE 规格冻结在另一 lane 的新增文件（`dpe/dpe_spec_v2.md`）中进行，本轮未合并、未推送、未发布。§7.1–§7.5 为历史审查记录，凡与 v1.3/v1.3.1 冲突的执行要求以 §1/§4/§5/§8/§9 与 §7.6/§7.7 为准。**尚未获得 v1.3.1 精确候选的独立 PASS，不能据此宣称实施或验收完成。**
