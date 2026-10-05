# SPEC-20261005 结果综合（SYNTHESIS）

一次性 provider-free deterministic 分析产出；RESULT.json sha256=6f60fb7057ef4c44580643b2a4b6d121b9c3faa45e444b21e57c1882d65e638a
SPEC sha256=61da4b1557a552e347ecbc45bd2d0190addd7efd7d401115fd1029380182d624 | pool sha256=17bd583c02966791675c54b1c16315d3b4251d502d978c18c0c516df25e16d3f
模型（两臂同一）：deepseek/deepseek-v4-flash | n=40/arm（20 match + 20 mismatch，同案配对）| 执行：交错 C0→C1，seed=20261005 冻结顺序

## 裁决摘要

| 判据 | 数值 | 门槛 | 结果 |
|---|---|---|---|
| M1 主指标（总体正确率差） | Δ=+0.025（0.825→0.850），z=0.30，p=0.381，CI95下界=−0.111 | Δ≥+0.15 且 CI 下界>0 | **FAIL** |
| G1 采纳护栏 | C1=0.00，C0=0.00（record_use 通道结构性为零） | C1 ≥ C0−0.05 | PASS（退化，预声明） |
| G2 成本护栏 | token 比=1.0114；wall 比=1.2529（median 1.953s→2.654s，p90 3.528s→4.288s） | 两项均 ≤1.15× | **FAIL**（仅 wall 分量） |
| 安全性 | 分层 Δacc：match +0.00 / mismatch +0.05；OTHER 0/0；重跑 40/40 对称 | 分层≥−0.10 等 | PASS |

**最终标签（按预注册映射）**：GUARDRAIL BREACH - NARROW EXPOSURE（G2 wall 分量触发优先分支）
**实质结论**：机制可见性成立（前置门 C0 5/5 MISSING、C1 5/5 VISIBLE），但**效能未获资质**——M1 主指标远低于 +0.15 阈值且无统计信号；代价护栏 wall 分量超限（token 分量正常）。维持实验 canary 现状，不升级、不回滚。

## 读数

- match 层 20/20 双臂全对（天花板）：正确 Method 配正确触发场景对该模型零难度，该层无判别力。
- 全部信号只能来自 mismatch 层：0.65→0.70，即 20 例中多对 1 例。binding 提示在该陷阱强度、该模型下未产生可测的判断改善。
- 这不是递送失败（前置门已证可见性），也不是安全失败；是**效应量失败**。

## 偏离登记（全量披露）

1. **D1（数据前）** harness 接口实测修正：DATA_DIR env 才能覆盖 data_dir（LFL_DATA_DIR 被 toml 显式值压制）；LLM_MODEL 需喂裸名 deepseek-v4-flash。模型与协议未变。
2. **D2（数据前）** 池构造规则三次确定性迭代（最终：overlap_coefficient(trigger_j, description_i) 最大化 + 孪生排除），全程未接触任何模型输出；池冻结 sha256=17bd583c…，git 提交 d3eecad26/8077691ec。
3. **D3（数据前）** smoke 提示改为仅英文大写 YES/NO + 语义化门解析（曾因中文"是"被字面解析误拦）。
4. **D4（执行中）** orchestrator healthy() 以裸名比对 canonical model_used，致每 cell 双跑（160 行正式数据）；analyzer 按 (case,arm) 取最新行；重跑对称 40/40、由机械误判统一触发且发生在任何结果解析之前——非 outcome-driven。此为 harness 缺陷，不影响 cell 内协议同一性。
5. **D5（数据后、冻结前）** analyzer 重跑计数实现与计划文本不符（总量≤2 vs 计划原文"C1≤C0+2"），按计划文本修正；v1 输出留档 RESULT.v1.json（sha256=a23666a30b8123a4a46933268d8a4dbe17b3820d244239fa4b4db801f8bb2423）。

## 局限（如实）

- 单轮裁决设计：无行为采纳通道，"decision vs behavioral adoption"与"Adoption→Outcome Conversion"结构性不可测——对外部建议的诚实闭合：**不追加解释性实验**。
- 陷阱强度受机械生成约束（高重叠配对存在真双适用标签噪声；paired 设计保护 Δ，绝对正确率为下界）。
- wall 比值受顺序 API 延迟混杂（已交错但未控载）；token 比 1.0114 表明真实负载差异极小，wall 超限大概率传输方差，但按冻结判据仍记 FAIL。
- 单模型（deepseek-v4-flash）；capability-aware（弱臂开关）策略不在本设计可判定范围。

## 对四个预注册问题的回答

M1 效应量≥+0.15？**否**（+0.025，p=0.38）。G1 Method 被采纳？**通道退化**（record_use 0/0，PASS 无信息量）。G2 成本≤15%？token 是（+1.1%），wall 否（+25.3%）。安全回归？**无**（全分量不劣化）。

## 下一步（按冻结结果，不追加解释性实验）

1. subject-binding 维持 gen177 canary 现状：不升级为 qualified capability，不回滚（无伤害信号）。
2. 停止 binding 文本优化——瓶颈不在递送，在 Method 本身的质量/适用性判别强度。
3. G2 wall 分量若未来重议升级，需在配对分批设计下重测；本次不作改判依据。
4. 弱臂 capability-aware 与 behavioral-adoption 通道需要新的预注册实验，与本次结果解耦。
