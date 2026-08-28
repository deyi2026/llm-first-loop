# glm-minimax-3 Cognitive Activation A/B 报告 (2026-08-29)

矩阵: 2 models × 3 tasks × 2 reps × 2 phases = 24 runs（workers=2 并行, control 全部先于 shadow 契约保持）
数据: data_ab/glm-minimax-3/summary.json（24/24 exit=0）
driver: commit 8f89369（smoke3 预验证 PASS: recovery=3/pc=rounds/goal_ok）

## 四层 Gate 判定

### A. Safety Gate —— PASS
- 24/24 exit=0；action attribution 干净（shadow 12 runs goal 归因 11/12 True，唯一 F=mini evid r2 rb=0 属模型行为差异非归因缺陷）
- rebuild 链正常（checkpoint-driven rb 0-2/run）；无跨会话/revision 异常信号

### B. Activation Gate —— FAIL（实验设施缺口，非任务未触发）
- packet_compile/rounds = 24/24 100% ✓（quiet 轮全覆盖持续成立）
- **warm_active=0 / cold_active=0 全 24 runs** —— mem（save_experience→tip 槽）/interop（pending 种子→每轮注入）形态均未激活 tier 投影
- 根因（代码证据 build.py L887-888, L1017）: `if _cog_mode != "enforce": _tier_on=False` → shadow 下 tier 投影不编译 → warm/cold 恒 0
- 即 CR-R1 审查清单第 6 项（shadow 同构编译）未实施——header 编译在 shadow 跑（pc=rounds 证明），tier 编译没有
- evid 形态 recovery 通路验证 PASS（smoke3 recovery=3；全量 evid rec 1-6/run）

### C. Quality Gate —— PASS（表面）
24/24 最终回答非空（665-2780 chars）；内容抽验留待深评。

### D. Efficiency Gate —— 方向性积极，n=2 不定论
| 指标 | control 合计 | shadow 合计 | 方向 |
|---|---|---|---|
| duplicate_tool_calls | 48 | 35 | shadow 少 27% |
| rounds（glm interop） | 24 | 8 | shadow 少 67% |
| rounds（glm evid） | 14 | 17 | shadow 略多 |
| recovery calls | 19 | 16 | 相当 |
- shadow 不改 prompt，差异仍属模型方差（用户上轮口径）——但 dup 下降方向跨 4/6 任务组一致，值得批次 D 后重跑确认

## CR_VALIDATED = INCONCLUSIVE

理由: Activation Gate 被实验设施缺口（shadow tier 编译未实施）阻断，本轮无法测量 WARM/COLD 投影的正确性与收益。CR 无效证据为零（Safety/Quality 全过），但有效证据也未产生。

## 下一步（唯一阻塞项）
1. 实施批次 D（审查项 6）: shadow 与 enforce 完全同构编译（load/barrier/compile/tier 全跑，仅不替换 prompt）——build.py L887-888 分支修正
2. 重跑 glm-minimax-3 同矩阵 → Activation Gate 复判
3. Activation PASS 后按用户判据评审 shadow→enforce

---

## 3b 复判（批次 D 后重跑，HEAD=f650dad，24 runs 同矩阵）

### Activation Gate 复判: 设施 PASS（部分激活）

| 形态 | shadow warm_active | 3（修复前） | 3b（修复后） |
|---|---|---|---|
| interop | GLM r1/r2 + MiniMax r1/r2 | 0/4 | **4/4 激活（warmS=53）** |
| mem | 4 runs | 0/4 | 0/4 |
| evid | 4 runs | 0/4 | 0/4（recovery 1-3 正常） |
| control 对照（12 runs） | — | 全 0 | **全 0 ✓**（对照成立） |

- interop 形态 4/4 激活 + control 全 0 = 批次 D 生效的直接证据（shadow 可测 WARM 投影）
- mem 形态 0 的归因：单测（test_shadow_packet_covers_persisted_memory，2 passed）已证
  memory_snapshot→packet 投影路径通；生产 0 = driver 场景上游未产生该类注入
  （A/B 隔离 data_dir 下 turn 快照/经验检索触发条件未满足），非 CR 设施缺陷
- goal 归因 12/12 True（3 为 11/12）

### Safety / Quality: 保持 PASS
24/24 exit=0、ans 全非空（793-1896）。

### Efficiency（n=2 方差大，仅记录）
dup: control 33 vs shadow 31（3: 48/35）；rounds 总体相当。

### CR_VALIDATED = YES（设施级）/ Activation 覆盖 PARTIAL

- shadow 度量设施完整性验证通过：批次 D 后 shadow 编译输入面=真实注入面、
  warm 可测、control 对照成立、单测回归锁在库
- Activation 完全覆盖（mem 形态）依赖 driver 侧任务设计改进（触发 turn 快照/
  经验检索注入），不阻塞 shadow→enforce 评审的设施前提
- 下一步：向用户提交 shadow→enforce promotion 评审（附 3/3b 数据）
