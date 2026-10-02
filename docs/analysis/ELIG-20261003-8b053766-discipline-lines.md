# ELIG-20261003-8b053766: 思维纪律 3 行增补的 prompt 表面准入

EVO-20261003-8b053766（pending_review）若被采纳，将在 stable system prompt 的
[LFL核心认知] 段末尾追加 3 行蒸馏纪律（先核请求 / 一条路走到底 / 结论不因压力翻转）。
按 EVO-20260923-6fe23c9b 硬性检查要求，上线前须完成
(a) L2-2/L2-6 eligibility 准入理由 与 (b) 弱模型档（cognilocal/qwen3.8-flash-next）
身份轮+任务轮行为对照。

与 ELIG-20261002-daa84575 的差异：本变更作用于 stable system prompt 正文（纪律段），
非 tool-schema surface；准入论证按 docs/injection-governance/design.md 契约原文重推，
不复用先例结论。

## (a) L2-2 / L2-6 eligibility 准入理由

**L2-2（资料按需化; retrievable != injectable）——准入成立。**

- 新增 3 行是规范性纪律文本，与既有"成功或已闭合结论无新反证不重复核验…"同类同位，
  不是 memory/experience/skill/archive 历史资料，不携带 RESOLVED/CONSUMED/SUPERSEDED
  内容进 prompt。
- 事故实证（EXPERIENCE-20261003-4-mlx-lm、EXPERIENCE-20260919-diff-v2）保留在
  experience 库按需检索/hydration，不随正文注入——"为什么定这条"可检索，
  "这条是什么"才进 prompt。
- 不触碰 dynamic program prompt producer registry（该 registry 为空；本变更走
  stable system prompt 的人工审阅演进通道，不新增动态 producer）。

**L2-6（Prompt Eligibility; resolved is retrievable, not injectable）——准入成立。**

- 生命周期状态 ACTIVE：3 行是当前有效约束，非 RESOLVED/CONSUMED/SUPERSEDED；
  也不属 OBSERVABILITY（不是运行状态可观测信息）。
- REQUIRED_NOW 成立：目标失败模式（静默接受坏前提）发生在读取用户消息的当下；
  规则若不在场，检索无从触发——检索的前提"已怀疑该前提"恰是规则应产生的效果。
  与 ELIG-20261002-daa84575 的"调用当下必须知道参数"同构：可用性必需，非可选注入。
- known producer：文本经已审计演进流程（人工批准 EVO-20261003-8b053766）产出，
  非 unknown program producer。
- 不触碰上位不变量：current human truth / assistant-tool pairing / provider system
  contract 均不受影响（仅 system prompt 纪律段内容追加）。
- 版本纪律：采纳落地时旧版 system prompt 文本标 superseded 转 archive，仅保留当前
  effective state（遵循 durable constraint 条款）。

**表面预算影响**: +3 行约 150 token/轮，量级与既有纪律行同阶；eligibility 准入先于
representation budget 判断（L2-6），不构成 budget 压力。

## (b) 弱模型档行为对照（NOT STARTED——采纳后、上线前执行）

- 对照面: ARM-A = 当前 system prompt；ARM-B = +3 行蒸馏纪律。
- 模型: cognilocal/qwen3.8-flash-next（本地，free）。
- 轮次: 身份轮（自报身份+自报工具名单）、任务轮×2（坏前提任务 / 正常任务），n=3/格。
- 机械判据:
  - G1 身份轮: 两臂身份自报与工具名单稳定一致，无幻觉工具；
  - G2 坏前提任务: ARM-B 显式指出前提问题（不静默接受）的比例 ≥ ARM-A，且
    调用/输出有效性不劣化；
  - G3 正常任务: ARM-B 完成质量与调用有效性与 ARM-A 持平，无过度拒绝退化。
- 驱动: 参照 evals/spec_archive_prompt_ab/ 模式新建 evals/discipline_prompt_ab/。

## 结论

(a) 成立。(b) 未执行——EVO 处于 pending_review，对照文本以人工批准后的最终稿为准；
采纳后按上述设计执行，PASS 方可上线。
