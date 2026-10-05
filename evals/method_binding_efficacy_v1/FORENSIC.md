# SPEC-20261005 Mismatch-Layer Forensic（事后、探索性、单评分者）

**性质声明**：provider-free 事后分析，仅读已冻结工件（pool 17bd583c / matrix / RESULT 6f60fb70）；不重开 M1 冻结裁决；单评分者（分析代理本人）归类，结论为下一轮预注册的假设生成，非确证。数据底稿：FORENSIC-DATA.json（forensic_v1.py 确定性产出）。

## 1. Paired transitions（n=40，同案双臂）

| 层 | 双对 | 双错 | C0错→C1对 | C0对→C1错 |
|---|---|---|---|---|
| match (20) | 20 | 0 | 0 | 0 |
| mismatch (20) | 13 | 6 | **1** | **0** |

## 2. 焦点 7 例（C1 全部判错案）逐例归类

判类口径（按本设计可测性收敛后）：
- **L 标签噪声/真双适用**：陷阱卡与呈现 trigger 同域（trigger 源方法与陷阱卡是同域 sibling），卡对任务实质适用，expected=SKIP 在实质上不成立；
- **D 判别失败（binding 可修）**：卡与任务在 subject/purpose 上实质分歧，APPLY 属真误判；
- 转化类（判断对但未落实行动）：单轮裁决设计**结构性不可测**，不参与归类（预注册局限原文）。

| case | 陷阱卡 ← trigger源方法 | 转移 | 归类 | 依据（一行） |
|---|---|---|---|---|
| mb-030 | anchor-and-derive-environment-parameters ← mechanical-identity-resolution-then-receipt-narrowed-retry | 双错 | **L** | 两卡同域（环境/身份参数无权威观察值→先锚定），呈现 trigger 是卡片 Trigger 的同义改写 |
| mb-028 | anaphora-artifact-first-context-recovery ← followup-questions-route-to-recent-artifact-first | 双错 | **L** | 同域 sibling（代词指代+近期工件→先恢复上下文），双臂 APPLY 理由实质成立 |
| mb-032 | anchor-background-job-polling-to-duration-prior ← timed-harvest-instead-of-interim-polling | 双错 | **L** | 同域且互为对策的两卡（停等 vs 轮询）；场景事实两边都覆盖，属裁定级分歧非判别失败 |
| mb-038 | anchor-declared-worktree-root-before-commands ← verify-declared-runtime-deps-in-fresh-execution-root | 双错 | **L** | 同域（新执行根+复用冻结契约），卡 Trigger 与呈现 trigger 语义重叠 |
| mb-026 | ambiguous-timeout-verify-landed-before-rerun ← compound-timeout-bounded-local-probe-first | 双错 | **L** | 同域（复合链超时/状态未知→先幂等观察），双臂理由均实质成立 |
| mb-018 | adjudicate-from-alert-payload-audit-claims-before-write ← guard-fail-attribution-before-broad-forensics | 双错 | **L(弱)** | 主域同（告警 payload 裁定）；卡附加"claim 审计"条件在 trigger 中缺席，严格判别者可 SKIP——单评分者边界案 |
| mb-024 | allowlist-names-from-authoritative-definition ← zero-hit-from-indexed-search-is-not-absence-proof | C0错→C1对 | **D，binding 修复** | 唯一 purpose 级分歧：卡面向"写工件前取名集"，任务只"核验标识符存在"；C1 用 subject 视角识别用途差并 SKIP（C0 误 APPLY） |

13 例双对全部为 SKIP/SKIP：两臂无 binding 也已正确拒绝。

## 3. 聚合与读数

- **L 占 C1 判错案的 6/6（弱案 1），D 可修案 1/7 且已被 binding 修复；候选 Method 质量、能力天花板：0 例；转化通道：不可测。**
- **噪声地板 ≥ 6/20 = 0.30 > M1 阈值 0.15**：按 L 归类，本池Mismatch 层最高实质正确率 = 14/20 = 0.70，**C1 恰好命中 0.70**。
- **Δ=+0.025 是本池的结构上限**：match 层双臂 20/20 饱和（+0 余量）；mismatch 可判子集 14 例中 C0 已取 13，C1 取满 14 → 净余量恰 +1 例 = +1/40 = +0.025 = 实测值。**M1 要求 +6 例净翻转，而池只提供 1 例可赢余量**——本实验在跑之前就在结构上不可能通过 M1，无论 binding 真实效应多大。
- 机制一致性：binding 按 subject 匹配运作；同域陷阱 subject 匹配 → binding 按设计指向 APPLY（对 6 例 L 中性）；唯一 purpose 分歧案 → binding 正确翻转、零反向翻转（C0对→C1错 = 0）。

## 4. 对下一轮的含义（假设，待独立裁定）

1. **第 0 前置（新发现，先于原四分支）**：仪器效度。陷阱标签须在冻结前经独立双评分者做双适用裁定（分歧即剔除/换卡），且陷阱构造须从"词汇重叠排除孪生"升级为"**purpose 级分歧**的近失卡"（同词汇、不同 subject/purpose）——否则任何机制的真实 +0.15 效应都不可分辨（噪声地板已超阈值 2 倍）。
2. 若仪器修好后判别仍饱和（C1≈100% 可判集）→ 才轮到 capability-aware 分支；候选 Method 质量/检索排序分支本轮 0 证据支持。
3. 转化（行为采纳）通道需带行动通道的新设计，与本 forensic 解耦（预注册局限原文）。
4. 本归类为单评分者；L 判定的独立复核已并入下一轮池构造的第 0 前置，不在此追加解释性实验。

## 5. 附：D4 与 G2 wall 的澄清（两笔不同的账）

D4 双跑使**矩阵总 provider 成本 2×（160 行 vs 80 行）**；但 G2 的 wall 比 1.2529 只在 latest 行上计算，与双跑无关，属交错顺序下的 API 传输方差（SYNTHESIS §局限）。修复 D4（runner v2）消除的是前者；后者要么配对分批重测、要么按传输噪声记。
