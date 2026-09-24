# HEV0-P3 Stage-B 结论（定稿）（run hev0-p3-20260921T024511Z）

状态：**定稿（v2.1）**。2026-09-21 14:13 用户评审：① 草稿 v2 定稿；引擎分型缺陷（GLM 1261 识别）为单列修复项（EVO-20260921-51d12fa6，pending_review），不阻塞本结论。草稿 v2 于 2026-09-21 13:19 收尾批落齐 66 行后重写（v1 于 12:10 收尾项 1+2 产出；12:14 用户授权扩展计划 PLAN_EXTENSION_20260921T1214.json）。裁决规则以 DESIGN-20260921-hev0-p3-three-arm-runtime.md §5 预注册为准；k=10 为授权闭合基准（非预注册）。

## 0. Run 概况
- wire：v6 冻结（per-row DATA_DIR 隔离 + providers.json 种子；manifest active_model = `{"settings_llm_model": "glm/glm-5.3", "settings_max_iterations": 500, "client_resolved": "glm/glm-5.3", "model_fallbacks_count": "glm/glm-5.3-flash,deepseek/deepseek-flash,minimax/MiniMax-M3", "note": "D6 修复: 解析结果落 manifest，不再依赖事后日志推断"}`）
- 行：66/66 落盘 = S2 t4/t5/t6×双臂×k1-10（60）+ S1 t1/t2/t3×b0（3）+ C-1 t1/t2/t3×b1（3）；t3::b0::k1 为 12:19-12:20 授权重跑行（原 v6 行 superseded → rows.superseded.jsonl）
- summary：13:19 终版（rows_done 66/66；arm_aggregate：b0 single_mean_all 31.0 / b1 33.0；job exit=0）
- 哨兵：11:44 一次 FAIL，已裁定误杀（PROD_SPILL_DETECTED.adjudication.json：episode 5693816b 为真实用户会话，非 eval 写入）；收尾批（12:14-13:19）零新触发；隔离零击穿；生产 data/ 相对哨兵基线零新增（复核：期间新增均为本会话 8d524014 自身运行时写入：evidence/audit/tool_execution/interop done 标记）

## 1. 双口径读数（§5）
### 口径 A：预注册 k=3（S2，n=9/臂）
- single_mean：B0 8/9 vs B1 9/9
- pass@3（任务级）：双臂 3/3 任务全过（t4/t5/t6 各至少一次 reward=1.0）
- 符号检验：任务级 t4 差 1 格利于 B1、t5/t6 平 → 不可拒（p>0.125）
- **裁决：reward 臂间差不下结论**（单格差异 + 符号检验不可拒，符合预注册保守规则）

### 口径 B：k=10 授权闭合（S2，n=30/臂，2026-09-21 12:14 授权）
- single_mean：B0 29/30 vs B1 30/30（差异仍为同一单行 t4::b0::k3，见 §5）
- pass@10（任务级）：双臂 3/3；first_attempt：双臂 t4/t5/t6 均 1.0（summary per_task）
- 中间基准 k=5：B0 14/15 vs B1 15/15（v1 草稿口径，仅归档）
- **裁决：扩样至 n=30 不改变口径 A 结论**——全 60 行 S2 中唯一 reward=0 仍是同一行为性失败，臂间 reward 差不下结论

### 副指标（S2 全 30 行/臂，k=10）
- rounds：B0 7.3 vs B1 8.1（+11% < 30% → 不下结论）
- tokens_in：B0 13,309 vs B1 107,374（B1 ≈ 8.1× B0，远超 30% → 按预注册成本规则可下方向性结论：完整引擎〔历史管线/session/anchor〕每轮重发大上下文导致输入 token 显著放大；tokens_out 相当量级：1,545 vs 2,107）
- duration（未预注册，仅记录）：34.1s vs 49.0s（+44%）

## 2. S1 存在性（只记不检验）
- t1_compact_single::b0：reward=1.0（11 轮，completed）
- t2_compact_steady::b0：reward=1.0（23 轮，completed）
- t3_compact_multi::b0：provider_error ×2（v6 原行 + 12:19-12:20 授权重跑，均 0 轮、~4.6s 终止）
  - **t3 1261 定性**（rows/t3_compact_multi_b0_k1/ATTRIBUTION.md，12:22）：同隔离+种子注册表独立重放该行首请求（system+5234 条 seed ≈ 2.7M+ chars）→ GLM HTTP 400 code **1261 "Prompt exceeds max length"**，确定性拒绝。引擎 is_overflow_error() 不识别 GLM 1261 → 误分类为 provider_error（**分型缺陷，单列修复项 EVO-20260921-51d12fa6**）。行记录不回写，仅归因文档。
- B0 物理天花板区间：(1.5M, 2.7M) chars（t1/t2 1.5M 级接受并完成；t3 2.7M 级确定性拒绝）
- 注：B0 在 t1/t2 未触发溢出，与设计预期『确定性溢出 0/3』不符——存在性事实照记

## 3. C-1 三行（12:14 授权补齐；判定规则=B2_REFERENCE.md §判定）
- 规则：0916 冻结库 t1-t3 b1 行 worker sha（40016971/6d1980fe）≠ 143c63d7（220150Z 指定 worker）→ 按 C-1 判『无合格数据』→ 以现行 v6 wire 补跑
- t1_compact_single::b1：reward=1.0（11 轮，627,843 tok_in，680.7s）
- t2_compact_steady::b1：reward=1.0（16 轮，1,307,080 tok_in，674.8s）
- t3_compact_multi::b1：reward=1.0（9 轮，392,446 tok_in，526.8s）
- **判定：C-1 命题成立**——B1（含历史压缩管线）在 B0 物理不可完成的 t3 规模（§2）上完成同任务且 3/3 全绿；t3 b1 tok_in 392k ≪ b0 种子 2.7M chars 请求体，压缩管线收益量化成立

## 4. B2 引用列（B2_REFERENCE.md，20260921T0217Z 冻结库；仅引用，不并入 P3 统计）
- 42 行（21 任务×双臂，k1-3）；wire：0916 双库（无 per-row DATA_DIR 隔离、worker sha 40016971/6d1980fe）
- 该模块结论：B0 7/9（两失败行均为特殊 token 退化，与 §5 同机制）、B1 9/9；B0 退化模式两类：特殊 token 循环 / 明文重复循环
- 用途：机制级旁证（B0 裸会话在受限采样下存在可复现退化模式，跨模块重现）；P3 主结论不依赖 B2 数据；历史 worker 代不同，不参与 C-1 判定

## 5. 唯一 reward=0 行为归因（t4_resume_oplog::b0::k3）
answer_head 全程 `<bos>/<pad>/你好` 特殊 token 循环（rounds=2，143.4s，terminal=completed）：B0 裸会话采样退化进入特殊 token 循环且无护栏可自恢复，行正常终止但 oplog_exact=False → reward 0。属行为性失败而非基础设施故障；k=10 下仍为 S2 全 60 行唯一失败，n=1 不外推为臂级结论，但正是 B0/B1 稳健性对比要捕捉的机制信号（与 §4 B2 旁证一致）。

## 6. 限制与后续项
- 单模型（glm-5.3）；B2 臂未在 P3 v6 wire 下重跑（§4 为 0916 冻结库引用）
- 单列修复项（不阻塞本结论，2026-09-21 14:13 用户裁定）：is_overflow_error() 不识别 GLM 1261（§2）→ **EVO-20260921-51d12fa6**（pending_review；采纳后在引擎侧补 1261→ctx_overflow 分型 + 回归用例，受影响行以归因文档为准不回写）
- k=10 为授权闭合基准（非预注册）；预注册口径仍为 k=3，双口径并列呈报
- 定稿记录：2026-09-21 14:13 用户评审通过（①）；定稿本 = docs/REPORT-20260921-hev0-p3-conclusion.md（取代 docs/REPORT-20260921-hev0-p3-stageA-conclusion.md 草稿）

## 附录 A：F1 披露（2026-09-21T15:32:54+08:00 用户裁决 D-11，勘误注记不回写数据）

- 终跑 B1 臂实际以**引擎默认 anchor ON（pins=2）**运行，与 DESIGN §1 表"B1 强制 off"不符（完整证据链
  与处置见 DESIGN-20260921-hev0-p3-three-arm-runtime.md §9.1 勘误）。全 33 行 b1 锚钉零活动、行为面
  无差异：本报告 §1-§5 全部结论不受影响（anchor 维度未被行使；§1 副指标本就描述为"完整引擎〔历史
  管线/session/anchor〕"）。t1-t3 b1 行 session `history_anchors={"glm":0}`（provider 在压缩域写桩锚）
  为 provider 在线直接证据。anchor 维度的成本形态由 P3.1 Module B（off/on 双臂，v6 wire）另行行使。
