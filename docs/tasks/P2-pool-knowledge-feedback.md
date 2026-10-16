# P2 追踪池：任务知识使用反馈与检索闭环（B0→B2 回执汇总）

- 生成：2026-10-16（用户授权「按建议执行」——建追踪载体 + 批次一立项）
- 来源（4 回执 + 1 准入证据）：
  - r0 = docs/governance/receipts/20261015-ac085ab1-knowledge-feedback-loop-code-review.json（REQUEST_CHANGES；P1×3 已修、P2×10）
  - r1 = …-code-review-r1.json（PASS；P1 复检全 FIXED，P2×10 明确不在窄复审范围）
  - B1 = docs/governance/receipts/20261016-e4376979-b1-settlement-wiring-code-review.json（PASS；P2×4）
  - B2 = docs/governance/receipts/20261016-fdc7603b-b2-rule-feedback-p1-code-review.json（PASS；P2×2）
  - ad = ac085ab1 push 准入审查者 P2×7（evidence://v1/056cc06fe267f1eff89da83147274e6f780fa96af71729fce08b979e23e05d2d，原无落盘回执——本文件补齐溯源）
- 去重（3 组）：r0P2-4≡B1P2-3、r0P2-8≡B1P2-1、ad#6≡r0P2-6 → 23 原始 = 20 唯一项
- 总览（2026-10-16 09:0x 更新）：批次一 7（✅ fixed，GOAL-20261016-cf563b27）｜批次二 5（open，+2 新入池见文末）｜批次三 3（open）｜挂账 4（open，+1 新入池）｜销账 1
- 行号均为回执时点，后续以符号重新定位为准。

## 批次一：settlement 口径与幂等（7 项）——本次 goal
| ID | 来源 | 位置 | 问题 | 处置方向 |
|---|---|---|---|---|
| P-SET-1 | r0P2-2 | settlement.py ~652-656 | RuleFeedbackProjection 聚合仅按 submission_hash 去重、忽略 slot：跨工作单元同规则同内容反馈折叠 count=1，违背两层身份「同内容跨 slot 不是重试」 | 去重键补 slot_id（投影计数与两层键一致）+ 测试 |
| P-SET-2 | r0P2-3 | settlement.py ~201-204 | 降级窗口下无 session_id 的回执可抵扣任意会话读取（空值跳过会话比对） | 空 session 回执不参与降级窗口抵扣（legacy 行如需保留则显式标注）+ 测试 |
| P-SET-3 | r0P2-4≡B1P2-3 | settlement.py ~149-178 | experience 回执收集 usage_entries(limit=200) 截断：较旧回执滑出窗口→读取重现待结算清单（诱导重报）；method 侧无界，两侧口径不一 | experience 侧按 session/work_unit 过滤分页读或 store 提供带过滤接口；与 method 侧对齐 |
| P-SET-4 | r0P2-5 | methods/store.py ~1119-1140 | 统计路径 usage_entries 不校验行级 integrity，而 record_use 去重扫描校验：中段篡改行计入统计却对去重不可见，两视图分叉 | 统一校验口径（或统计侧显式标注 unverified 行计数）+ 测试 |
| P-SET-5 | r0P2-7 | settlement.py ~493-513/677-679 | 规则 ref 大小写不对称（投影查询 upper()、事件载荷 ref 未归一、_RULE_REF_RE IGNORECASE 放行小写提交）；SettlementItem.supersedes 对 kind=rule 静默忽略 | 载荷 ref 入投影前归一（或提交时归一）；rule 的 supersedes 显式处理或显式拒绝 |
| P-SET-6 | r0P2-8≡B1P2-1 | settlement.py ~405-432 | 降级模式（无 wu）settlement_calls/settlement_rounds 计入两侧全局账本回执（B1 探针 A6：首笔提交回 calls=5） | ledger 回执按 session_id 过滤（与 _offsets 降级窗口口径对齐）+ 探针场景回归测试 |
| P-SET-7 | B1P2-2 | settlement.py ~346-356 | 规则条目幂等查重只扫当前会话事件：同 (slot,submission_hash) 跨会话重提追加重复 rule.feedback 事件、返回非幂等 committed；与工具描述「同对象同内容重试幂等」无限定表述不符 | 确定任务 slot 跨会话投影查重（优先）；或工具描述明示幂等边界=会话内（降级选择） |

验收：每项有新测试或文档锚定；编码→独立审查闸 PASS→全量门→推送；回执落盘 receipts/。

## 批次二：账本健壮性小修（5 项）——后续 goal
| ID | 来源 | 问题 |
|---|---|---|
| P-LED-1 | ad#1 | revision 解析 int() 未防护（非数字崩溃面） |
| P-LED-2 | ad#2 | 经验侧 append 前 OSError 未包成 ExperiencePersistError |
| P-LED-3 | ad#5 | refs 截断两侧不对称 |
| P-LED-4 | ad#7 | quarantine 崩溃窗口重复字节（与 P-DOC-1 同代码区，可同批） |
| P-LED-5 | r0P2-6≡ad#6 | append 文本模式句柄：Windows '\n'→'\r\n'。二进制写根治，或文档声明 POSIX-only 销账 |

## 批次三：文案/标注（3 项）
| ID | 来源 | 问题 |
|---|---|---|
| P-DOC-1 | r0P2-9 | 隔离后追加 lost 归零语义：文档/回执说明（持久证据在 sidecar+report） |
| P-DOC-2 | ad#3 | doc 缺失时 benefit_counts 全零标注误导 |
| P-DOC-3 | B2P2-1 | threshold_alert 文案统一『声明净分』术语 |

## 挂账（4 项，含理由）
| ID | 来源 | 理由 |
|---|---|---|
| P-DEF-1 | r0P2-1 | 窗口按 task/goal 图事件锚定=设计层重构；等 B3 真实流量证「多任务同会话混入」是实际痛点再动 |
| P-DEF-2 | ad#4 | 每次落账 ≥3 次全文件扫描：账本 22 行无实测瓶颈；B3 复检点后按量级数据评估，先测后修 |
| P-DEF-3 | B2P2-2 | feedback_watermark 同名异型（int vs ts）：无消费方，有消费方时随需处理 |
| P-DEF-4 | B1P2-4 | tests 11 处 pyright 未收窄：本质是「tests 是否纳入 CI 类型检查」的策略决策，**待用户定夺**（纳入=一次性清 11 处；不纳入=挂账） |

## 销账（1 项）
- r0P2-10：批量结算接线——B1 已完成（46a15a79e feat(settlement)），B1 回执探针 A1-A5 独立复检通过（跨 slot 不折叠/幂等/无哨兵/unresolved 不抵扣）。

## 附注（非 P2 计数）
- r1N1(P3)：test_settlement_receipts.py:674 `usage_entries(...)[-1]` 实取最旧（默认倒序最新在前）——当前单行夹具下正确，后续向该夹具追加条目时须改 [0]；批次一顺手改。
- r1N2：unresolved 同内容跨会话按 submission_hash 折叠 idempotent——设计允许的降级语义，备查。
- B1 N1-N4 / B2 cross-checks：非阻断观察，随相关批次顺手处理（N1 failed 回执内嵌 str(exc) 可截断/脱敏、N2 evidence_refs 上限仅 schema 声明、N3 降级窗口接受空 session legacy 行——注意与 P-SET-2 联动）。

规则：本文件是 P2 池唯一追踪载体；每项状态变更（open→fixed/deferred/dropped）须引用完成 goal/提交/回执，不在此口头销账。

## 状态更新（GOAL-20261016-cf563b27，2026-10-16）

- 批次一 P-SET-1..7 全部 **fixed**：编码 subagent_c4f24a5a331c（自报告 docs/reports/GOAL-20261016-cf563b27-b1-settlement-p2-selfreport.md）→ 独立审查闸 subagent_191c6b090506 **PASS**（逐项 FIXED + 探针×5，回执 docs/governance/receipts/20261016-cf563b27-b1-settlement-p2-code-review.json，sha256 8ccb2a8c…）→ 全量门准入 PASS（candidate 85a33047…）→ ci_gate.sh 全链路 exit 0（ruff/env-pin/pyright new=0 + tier0 + 全量 pytest）→ 推送见本 goal 交付。
- r1N1 **fixed**（[-1]→[0]，随批次一）。
- 新入池（T2 审查发现，2026-10-16-cf563b27 回执 P2×2）：
  - P-LED-6（批次二）：跨会话规则查重每次全目录扫描无 TTL 缓存（成本族，与 P-DEF-2 同类，可合并评估）
  - P-DEF-5（挂账）：rule 侧 legacy 空 session 行不进披露计数（实际不可达路径，完整性备注）
- 新入池（编码者如实上报，T2 审查确认范围外）：P-SET-8（批次二候补）：experiences 侧 `_iter_usage_entries` 无行级 integrity 校验（与 P-SET-4 method 侧同族，遗留缺口）。
- 批次二规模更新：5 → 6 项（+P-LED-6；P-SET-8 入批次二候补）。
