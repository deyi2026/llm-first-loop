# SPEC-20261005 执行计划与预注册（数据采集前冻结）

- SPEC: docs/SPEC-20261005-method-binding-efficacy-preregistration.md
- SPEC sha256: 61da4b1557a552e347ecbc45bd2d0190addd7efd7d401115fd1029380182d624（不得修改其研究问题/判据/阈值/样本量/停止规则/分析计划）
- Pool: pool.json sha256=17bd583c02966791675c54b1c16315d3b4251d502d978c18c0c516df25e16d3f（40 例：20 match + 20 mismatch；选择规则=生命周期等级 qualified>active>candidate>hold>retired、method_id 升序取前 20；配对规则=在全部非 retired/hold 卡中，argmax overlap_coefficient(bigrams(trigger_j), bigrams(description_i))，约束 J(trigger_j,trigger_i)≤0.35 排除同题孪生，平局取 method_id 升序；顺序 seed=20261005 shuffle）
- 标签噪声声明：mismatch 高重叠陷阱存在真双适用噪声；paired 同案双臂下 M1 差值不受影响，绝对正确率按下界解读
- 臂定义：C0 = LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL 缺省；C1 = =1。实证（本仓库、2026-10-05）：load_env_file+load_settings 后 toml tools.method_subject_binding_experimental=true 不投影进进程 env，registry 实测 C0 缺省=无 binding、C1=有 binding；无偏离登记需要
- 模型登记（两臂同一）：deepseek/deepseek-v4-flash（LLM_MODEL env 覆盖；providers.json 固定采样参数）
- 隔离：两臂同用 DATA_DIR=evals/method_binding_efficacy_v1/run_data（绝对路径；实证：LFL_DATA_DIR env 被 toml 显式 lfl_data_dir 压制，DATA_DIR env 优先生效——预数据修订）；生产 gen177 冻结——实验窗口内不 publish/restart/改 runtime.toml 与 providers.json
- 前置门（任一失败即中止，不得开正式 80 例）：(1) 两臂 lazy 工具面 diff 仅限 save_experience；(2) C0 smoke n=5 全 MISSING；(3) C1 smoke n=5 全 VISIBLE（headless 载具复证）
- 执行顺序：按 pool.run_order（seed 已定），每例内两臂交错 C0→C1；worker 断言 binding 态与臂一致、model_used=登记模型、data_dir=隔离路径
- 技术失败处理：异常/超时/fallback 换模/truncated → 记 OTHER，该例允许恰好 1 次重跑并标记 rerun_of；禁止 outcome-driven 重跑
- 无期中分析：80 例+smoke 完成前不解析裁决、不聚合任何结果；仅允许进程存活与行数增长的运维检查
- G1 实现说明（非判据修改）：按 SPEC 原文统计 trace 中 method_manage record_use(use_decision=applied)；本单轮裁决设计下该通道大概率结构性为 0，若如此将在报告如实标注 G1 退化并说明其护栏作用由 M1 的 APPLY 侧正确率承载
- G2：mean(tokens_in+tokens_out) 与 mean(wall_s) 均 ≤ 1.15×C0
- 安全性操作化（预注册）：两分层 Δacc ≥ −0.10 且 OTHER_C1 ≤ OTHER_C0+3 且 C1 重跑数 ≤ C0 重跑数+2
- 探索性登记（不进判据）：完整 trace 落盘；外部建议的两层采纳（decision/behavioral）与本设计的 Conversion Rate 在单轮裁决设计下无行为通道可测，作为局限如实记录，不追加解释性实验
- 判决映射：M1&G1&G2&安全全过=QUALIFIED；M1 FAIL 且 G1/G2 过=MECHANISM VISIBLE, EFFICACY NOT QUALIFIED；G2 FAIL 或安全回归=GUARDRAIL BREACH（收窄暴露）；其余组合按 SPEC §4 原文优先级
