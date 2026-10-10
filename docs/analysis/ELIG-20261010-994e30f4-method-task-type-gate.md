# ELIG-20261010-994e30f4 — method_manage task_type 表面与 activate 跨任务门

- 建议编号: EVO-20261010-994e30f4（人工已批准，human_exec_override=true）
- 变更性质: 工具 schema 面（method_manage 增 `task_type` 属性描述）+ 程序面（MethodStore activate 校验）
- 本文目的: EVO-20260923-6fe23c9b 规定的上线前硬性检查——(a) L2-2/L2-6 论证与 (b) 弱模型档对照

## 1. 变更内容

程序面（不进 prompt）:
- `store.py::_normalize_task_type`: 模型声明的任务域归一（casefold/空白/下划线折叠，缺省 unknown）
- `store.py::record_qualification` / `_record_qualification_locked`: 新 keyword-only 参数 `task_type="unknown"`，写入 qualification.jsonl 条目（旧条目读作 unknown）
- `store.py::_update_status_locked`: `->active` 且当前非 active 时，校验 verdict=pass 条目的 task_type 去重数 ≥2；不满足则 `_blocked(cross_task_type_qualification)` 并抛 ValueError。存量 active 卡不回溯（重申 active 幂等仍允许；离开 active 再进入则适用新门）
- `registry_experience.py::_run_record_method_qualification`: 线程化 task_type 进 store 调用、审计与回执

prompt 面（本次 ELIG 审查对象）:
- method_manage schema properties 增 1 行:
  `task_type`: string ≤64，"仅 record_qualification 消费：本 qualification 所属任务域的模型声明（如 browser/code-edit/diagnosis/writing；大小写与空白归一，不校验真伪）。activate 门（EVO-20261010-994e30f4）要求 verdict=pass 条目覆盖 ≥2 个不同 task_type 才能转 active；缺省 unknown 不计数。存量 active 卡 grandfather 不回溯"
- 工具回执文本增 `task_type=<值>` 片段（仅 record_qualification 成功路径）

## 2. L2-2/L2-6 准入论证

- 检索面（L2-6 可检索性）: 无新增待检索内容——task_type 不是知识，是声明字段；不进 METHOD.md、不进注入面、不占 method 检索预算。
- 注入面（L2-2）: 不新增任何注入路径。method 注入内容仍来自 METHOD.md 正文（本 EVO 明确不加字段）；task_type 只存在于 qualification.jsonl 与工具 schema 描述。
- 覆盖面核算: schema 增量 1 属性 + 回执尾部 1 字段，均位于弱模型可见表面，故按 (b) 做对照。
- 不可由程序核验的边界（如实声明）: task_type 是模型声明，程序不校验任务域真伪；同一 episode 声明两种类型可伪造成"跨域"。噪声底线: 该门防的是"单域蒸馏直接激活"的系统性风险，不防蓄意伪造——与 qualification 其余 verdict 字段同一认识论层级（evaluator=model），未降低、也未提升声明面。

## 3. 弱模型档对照

- 模型: cognilocal/qwen3.8-flash-next（本地端点，thinking 模式）
- 对照臂: ARM-A=剥离 task_type 的旧 schema；ARM-B=当前新 schema（其余字节相同）
- harness: `evals/method_task_type_prompt_ab/run_compare.py`（机械判据，无语义评分）
- 判据: G1 身份轮（自报工具集合两臂一致且无幻觉）；G2 域已知任务轮（两臂 parse/valid 不劣化，B 臂产出良构 task_type，无臂外参数）；G3 域未指明任务轮（两臂 parse/valid 不劣化，B 臂 task_type 缺省或字符串均可，无类型违规）

### 结果

（首轮 compare_evo-994e30f4-premerge: max_tokens=500 时 thinking 耗尽预算致 content 空，A/B 两臂均大面积空输出，判据无法评估——判 harness 功率不足，max_tokens 提至 2000 重跑；首轮 JSON 留档不作为通过证据。）

v2（compare_evo-994e30f4-premerge-v2, temp=0, 3 reps, max_tokens=2000）: **verdict=PASS**

- G1 身份轮: 两臂自报工具集合完全一致（均为 method_manage），无幻觉工具名，均自认 llm-first-loop 运行环境
- G2 域已知任务轮: B 臂 3/3 parse_ok + valid_call + task_type 良构（均给出 `"task_type": "code-edit"`，正确取自场景声明）+ 0 臂外参数；A 臂 0/3——原始输出为 content 空且 ~120s/次（2000 token 预算被 thinking 全额耗尽，temp=0 下 3 次同构），属模型×预算交互而非 B 臂回归；B 严格不劣于 A
- G3 域未指明任务轮: 两臂各 3/3 parse_ok + valid_call + 0 臂外参数；B 臂 3 次均省略 task_type（域未指明时的合法行为），无类型违规
- 如实声明: G2 的 A 臂空输出使该轮"两臂对称比较"不可得；判据本身（B 不劣于 A + B 正确使用新表面）成立，但不应解读为"B 使弱模型变聪明"——结论是 B 臂可用且无劣化，样本 3 reps

## 4. 结论

上线判定: **通过**。
- 程序面: activate 跨任务门按批准范围实现，存量 grandfather 语义有测试锁定；全量单测 0 失败
- prompt 面: 弱模型档对照 G1-G3 全过；schema 增量对弱模型无劣化，新参数可被正确发现与使用
- 已知限制（第 2 节）随建议记录，不阻塞本次上线

## 5. 测试与回归

- 单测: tests/unit/test_method_learning.py（契约更新 2 处 + 新增 test_activation_task_type_gate_counts_and_grandfather_semantics）、tests/unit/test_method_store_durability.py（适配新契约）
- 全量: tests/unit 7354 passed / 108 skipped / 0 failed（2026-10-10）
- 存量 dry-run（只读）: 2 张 active 卡 distinct=0——grandfather 生效（不回溯不拦截重申），如离开 active 再进入将按新门要求补跨域 qualification；唯一 qualified 卡（schedule-cadence）distinct=0，当前尝试 activate 会被拦（即本 EVO 预期效果）
