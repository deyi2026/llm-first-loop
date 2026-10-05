# IQ v1 预注册（Instrument Qualification v1）— 状态：**FROZEN @ 2026-10-05 22:32（O1–O3 全默认拍板，见 §10）**

**关联冻结件**：FORENSIC.md §3/§4.1（evals/method_binding_efficacy_v1，2026-10-05）｜RUNNER-V2.md 下一轮执行规约｜SYNTHESIS.md（M1/G2 裁决不回写）
**评者构成（operator 已拍板 2026-10-05 22:23）**：R1 = operator（人类，主参照评者）；R2 = agent（FORENSIC L/D 归类作者 + 本设计作者，代理评者，非独立性如实登记）
**零 provider 声明**：构建、评分、分析全程无任何模型 API 调用。R2 评分为会话内代理行为，非 harness provider 调用——差异如实登记（§8.1/8.2）。

## 0. 边界（不做什么）

- 不重跑效能矩阵、不增样本；gen177 三段标签与 M1/G2 冻结裁决一字不动。
- 不冻结下一轮 SPEC：IQ 通过仅解锁"构造器 v2 资格"；SPEC 的 n/阈值/设计另行预注册。
- 老 40 例池（sha256 17bd583c…）降级为 regression fixture（runner v2 回归对照），不再用于 promotion 主池。

## 1. 目标与通过定义

证伪对象：v1 构造器产出的高重叠陷阱中 ≥30% 标签实质无效（FORENSIC §3 噪声地板 6/20）。
IQ v1 在三件事上给资质：

| # | 资质项 | 通过定义 |
|---|---|---|
| Q1 | 评分可靠性 | κ(R1,R2) ≥ 0.70（原始双盲评分，先于任何裁定） |
| Q2 | 标签效度 | 各 cell 认证率达 §5 门槛（R1 与 R2 **均**判出 intended = certified） |
| Q3 | headroom | certified H⁺ ≥ 12 且 H⁻ ≥ 6（iq_headroom.py 机械复算） |

三过 → 构造器 v2 qualified，挂版本号 **IQ-CTOR-v2**；任一 FAIL → 构造器重做（换构造规则、整轮重评，禁止剔除凑数）；κ 落 HOLD 带 → 单轮指引修订 + 整表重评。

## 2. 评者构成与机械隔离

- R1 = operator：人类主参照评者；标签效度的载重证据。
- R2 = agent：代理评者。**已知污染源**：R2 是 L/D 归类作者、本设计作者，且评前上下文已含 FORENSIC 内容（无法真正盲）。缓解仅为程序性：盲表、封存、先交卷后开封（见下）；载重结论挂 R1 与 κ（§8.1）。
- **盲表**：每例仅呈现 opaque_id + 任务（trigger 原文）+ 方法卡原文（与引擎所见 pool 格式一致）；**不含** kind / expected / cell / 陷阱来源标注 / mb-XXX 原号。
- **封存**：opaque_id 映射与 cell/intended 写入 iq_sealed.json（构建时落盘，公布 sha256、不公布内容）；双份答卷提交并登记时间戳之前不开启。R2 评前不读取该文件、不重读 FORENSIC*。
- **时序**：R1、R2 独立评完各自落盘 iq_R1.jsonl / iq_R2.jsonl（每例 APPLY/SKIP + 一行理由 + 时间戳），先交卷后开封；开封前两评者间零交流。

## 3. 池结构（2×2）与机械构造规则

卡宇宙：与 v1 相同 20 卡（lifecycle rank → method_id asc，前 20）。相似度函数沿用 build_pool.py 冻结实现（bigram ov / jac）。
ov_self(i) = ov(trigger_i, description_i)。

| cell | 构造（确定性） | 例数 | intended | 角色 |
|---|---|---|---|---|
| A 正对照 | ov_self 降序 top-6 卡，trigger=自身 | 6 | APPLY | 天花板校准 |
| B 近失 | 全 20 卡，partner=v1 规则原样（argmax ov(trigger_j, desc_i)，孪生排除 J(trigger_j,trigger_i)≤0.35，tie-break method_id asc） | 20 | SKIP | **H⁺ 主池**；yield 直接复测 v1 噪声率（先验 ~70% 认证率，预期 ~14；v1 的 6 个 L 型配对预计复现并计为缺陷） |
| C 反向风险 | ov_self 升序 bottom-8 卡，trigger=自身 | 8 | APPLY | **H⁻ 主池**（表面弱关联、真适用） |
| D 负对照 | ov_self 第 9–14 名 6 卡，partner=argmin ov(trigger_j, desc_i)（同孪生排除） | 6 | SKIP | 地板校准 |

合计 40 例，全部双盲评分。opaque_id = sha256(case_id + seal_salt)[:12]；呈序由 SEED=20261005 洗牌。

## 4. 评分问句（中文；O2 冻结 = 默认值）

> 假设你正在执行下面的【任务】，手头只有这张【方法卡】。该卡对本任务是否适用？
> APPLY = 采纳其指引会实质改变/正确化本任务的执行；SKIP = 不适用。
> 请附一行理由。

## 5. 预注册门槛（数字随本文冻结）

| 门 | 阈值 | 失败动作 |
|---|---|---|
| κ(R1,R2)（原始双盲评分，先于任何裁定；同时报告 raw agreement 与 bootstrap 95%CI） | ≥0.70 PASS；0.55–0.70 HOLD；<0.55 FAIL | HOLD → 单轮指引修订+整表重评；FAIL → 构造器/仪器重做 |
| R1 vs intended 一致率（仅 A/C/D 构造确定 cell） | ≥0.90 | <0.90 → 评分指引歧义，HOLD |
| A / D 认证率 | 各 ≥5/6 | 低 → 报警复核（对照件应近饱和） |
| B 认证率 | ≥12/20（60%） | <12 → 触发 §6 替换轮 |
| C 认证率 | ≥6/8（75%） | <6 → 触发 §6 替换轮 |
| 总分歧率（R1≠R2） | ≤15%（≤6/40） | 超限 → 与 κ 联合判 |
| H⁺（certified B，下一池冻结门同一脚本复用） | ≥2×所需净翻转；现阈值 6 → **≥12** | — |
| H⁻（certified C） | **≥6** | — |

**认证与裁定的边界**：certified 严格要求双评者一致判出 intended，**裁定不救认证**——分歧案仅由 R1 写一行终局理由留痕归因（进分歧清单，不改认证状态）。**替换规则**：仅 B/C 短缺触发；单轮、每格 ≤6 新例、新例同规双盲评；第二轮仍短缺 → 构造器 FAIL。替换全程按偏离登记格式留痕。

## 6. 分析与产物（确定性脚本，零 provider）

- `iq_build.py`：按 §3 构造，产出 iq_candidates.json + iq_sealed.json（公布 sha256）+ iq_sheet.md（盲表，R1/R2 同序）。
- `iq_analyze.py`：κ + raw agreement + bootstrap 95%CI（10⁴ 重采样，seed=20261005）；cell×rater 认证矩阵；分歧清单（含 R1 归因一行）；H⁺/H⁻ headroom 复算；产出 IQ-RESULT.json / IQ-RESULT.md。
- `iq_headroom.py`：独立复用件——任何未来池冻结前跑同一 headroom 门（H⁺ ≥ 2×净翻转需求，H⁻ ≥ 6）。
- 裁决一次性出（Q1∧Q2∧Q3），无期中偷看。

## 7. 与下一轮 SPEC 的挂钩

1. IQ PASS ⇒ 构造器 v2 挂 IQ-CTOR-v2；下一 SPEC 池必须由它产出且冻结前过 iq_headroom.py。
2. promotion 主池必须是 IQ 认证池；老 40 例仅作 regression fixture。
3. SPEC 冻结时另行决策 n（注：n=40/arm 在真实 Δ=+0.15、单侧 α=0.05 下功效仅 ~60%；重算 n 或接受低功效——IQ 不替 SPEC 做此决定）。
4. 评者非独立性与 R2 代理身份随 IQ-RESULT 一并披露，供下一 SPEC 局限节引用。

## 8. 已知局限登记（如实）

1. **R2 非独立**（L/D 归类作者、本设计作者、评前已见 FORENSIC 内容）——盲仅程序性；载重结论挂 R1 与 κ；R2 是带已知偏差的第二双眼，非独立复核。
2. R2 为 LLM 代理而非人类第二评者；"独立双评分者"在零 provider 约束下未达理想形态，operator 已知情选择此构型。
3. n=40，κ 的 CI 宽；门槛判点估计，CI 如实报告。
4. 表面高/低由 bigram 排名带定义，带选择有任意性（具体带已在 §3 定死）。
5. IQ 证标签效度与结构 headroom，**不证效应可检测性**；模型层难度分布要到效能跑才测得。
6. 转化/行为采纳通道仍结构性不可测（沿 SYNTHESIS 局限原文，不追加解释性实验）。

## 9. 冻结流程

operator 回复"冻结"或提出修改 → 定稿 sha256 + git commit → `iq_build.py` 构建并公布封存哈希 → 双盲评分 → `iq_analyze.py` 一次性出裁决。冻结后任何偏离 = 新偏离登记。

## 10. 冻结记录（2026-10-05）

operator 于 22:32 回复"冻结"，O1–O3 全部采用默认值：

- **O1 = 40 例全量双评**（A6 / B20 / C8 / D6，不砍对照件）。
- **O2 = 中文问句**（§4 原文）。
- **O3 = ov_self 带边界定死**：A = 降序 top-6；C = 升序 bottom-8；D = 降序第 9–14 名；降序第 7–8 名 2 卡不入选（缓冲带）。带内并列按 method_id asc。

**实现性登记（构建时发现，如实留痕）**：v1 build_pool.py 的 partner argmax tie-break 实际行为为字典序取 method_id **大**者（代码 `key > (best[0], best[1])`），与 v1 pool.json 自述 "tie-break method_id asc" 相反。IQ 构造器以 v1 **代码行为**为准逐字复刻（B cell 与 v1 配对逐例一致；构建自检 20/20 复现为通过条件）；D cell argmin 为新代码，按本文 tie-break method_id asc。

冻结即生效：本文定稿 commit → `iq_build.py` 构建并公布封存哈希 → R1/R2 双盲评分 → `iq_analyze.py` 一次性裁决。此后任何偏离按 §9 记入偏离登记。
