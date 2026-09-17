# 设计：规则/经验/技能注入分层与使用统计闭环（2026-09-17）

> 状态：提案（已过一轮 grill 自答拷问，待人工审阅 + P0 数据先行）
> 关联：Method Learning 优化补充；取代已退役的记忆全文自动注入路径。

## 一、实测基线（408 会话全量轨迹扫描，2026-09-17）

| 通道 | 实测 | 说明 |
|---|---|---|
| execute_command | 22,605 | 流量主体（对照组） |
| search_records 卡片 | 711 | memory 131 / episode 105 / experience 69 / method 27 / rule 20 / lesson 8 |
| skill_load / skill_list | 30 / 29 | 稀疏但真实 |
| search_docs | 195 | 文档检索活跃 |
| 工具失败回执内嵌指针 | 每次 failure 必现 | `[RULE-AI-02/07]…按需 search_records`（registry.py:1435），**无登记** |
| 记忆全文自动注入 | 0 | **已退役**（build.py:543 del memory_msgs；engine.py:682 agency-first） |

结构性结论：按需水合非零但占比极低（rule 2.8% / experience 9.7% of search_records）；实际注入流量由 **schema 内嵌描述 + 失败回执指针 + 静态系统提示** 承担；最大既有注入面（回执指针）恰好在统计盲区。

## 二、四层模型

- **L0 常驻系统提示**：不变行为宪法（安全/诚实/证据纪律），保持极小。已有，不动。
- **L1 发现层（新）**：时机点注入**标题级指针**（≤3 条：标题+ref+一句话）。时机仅两个：任务首 turn（基于首条 user 指令相关性检索）、工具失败回执（现雏形扩展）。全文决策权在模型。
- **L2 按需水合（已有）**：search_records 卡片 → read_evidence / skill_load / search_docs。
- **L3 登记与归因闭环（新）**：见四。

## 三、拷问六问（自答，摘要）

1. **归因标准**：双口径。A 级=注入 ref 字面出现在后续 tool args/答案（机械、低误报、时序约束 ts_inject<ts_use）；B 级=行为一致（语义，仅模型在 reflection 标注，不进自动决策）。已知风险：用而不引 ref 会低估——报告必须双列，决策取保守方向（宁高估帮助不误杀）。
2. **与退役路径的本质区别**：①标题级 vs 全文；②时机触发（首turn/失败）vs 每 run 无条件；③带自证闭环（连续零归因自动退场）vs 无统计。分层单向：内容只能从 L1 降级/摘除，升格常驻必须走 method qualification 正规晋级。
3. **小样本置信**：计数制门槛（注入≥K=10 且 A 级归因=0 才降频；再连续才摘除）；摘除仅影响指针不影响 L2 检索（可逆）；复用率只作 qualification 参考输入，判定权在模型（既有原则）。
4. **防隐性干扰**：预算硬上限（每 run ≤1 块、≤400 chars、≤3 条）；时机白名单（首turn+失败，禁中间轮追加）；surface 级低命中整时机降级；配置可关；轨迹带可审计标记。
5. **与 Method Learning 接口**：reuse_stats（ledger 聚合）作为 qualification 证据之一，与 episode 溯源/独立评估并列，不单独构成 promotion 依据；归因数据天然异源（后续任务 ≠ source episode），不自证。反向：qualified method 自动进 L1 候选池——产出→发现→归因→资格证据闭环。
6. **成本**：ledger 每 run ≤2 条 JSONL 追加（与 event log 同量级）；A 级归因 O(注入×后续调用) post_run 一次 fail-open；聚合离线批处理；唯一新增模型成本=首 turn 检索 embedding +1 次/任务（可配置降级关键词/跳过）。

## 四、新盲点（拷问产物，进设计约束）

- 回执内嵌指针先补登记（P0），否则最大注入面继续无统计；
- embedding 不可用时 L1 首 turn 检索降级路径必须先定义；
- 归因窗口按 run_id 划分，防跨 run 误归因；
- "用而不引"低估风险 → 双口径报告 + 宽松降权门槛。

## 五、分期

- **P0 纯观测（零行为变化）**：injection ledger 事件 + 回执指针登记 + 聚合脚本（复用基线扫描）→ 跑 2 周拿数据；
- **P1 归因**：A 级机械归因 + per-ref/per-surface 报告（self_evaluate/维护任务输出）；
- **P2 L1 发现层**：首 turn 标题级指针 + 预算 + 自适应降频/摘除；
- **P3 接口**：reuse_stats 进 method qualification 证据与 save_experience 验证状态（长期 unverified 降权）。
