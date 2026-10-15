# B3 观察报告：真实流量后统计面基线（GOAL-20261016-fdc7603b / TASK-fdc7603b-005）

观察时间：2026-10-16 06:55（B2 部署 generation=269 / 进程 25491 / 3bd871709 之后）

## 1. 链路连通（部署面）

- learning 服务 publish gen 269 → restart succeeded → 运行时清单核验：pid 25491、git_head=3bd871709、started 06:52:52 ✅
- 新代码功能面在 B2 全量门（exit=0 / 319 passed）与审查回执（PASS，渲染取证）双重覆盖 ✅

## 2. 真实数据面基线（只读观察，样本量如实披露）

| 观察项 | 现状 | 说明 |
|---|---|---|
| methods usage 账本 | 24 行，**全部 legacy v1 schema**（无 schema 字段），6 个去重 method_ref | 由 B1 收口会话经旧进程写入（合法 legacy 桶，v2 上线后按既有归桶语义处理） |
| methods 水位 | count=24，ts=2026-10-16T00:07:21 | B1 收尾结算时刻 |
| experiences usage 账本 | 文件不存在 | 尚无经验侧使用记录流量 |
| EventStore `knowledge.read` 事件 | **全库 0 条** | 新打点通道尚未承载真实会话 |
| EventStore `rule.feedback` 事件 | **全库 0 条** | 规则反馈提交通道尚未被真实使用 |
| 净分渲染（真实数据） | usage_net(6 refs) 正常渲染（各 net=1/applied=1，legacy_entries=1） | 声明净分标注位于检索注释层，渲染正确性由 B2 审查回执的真实渲染取证背书 |

**为何新通道零流量**：B1/B2 部署只更新 learning 服务进程；B1 部署（00:40）以来的真实会话（含执行本报告的会话）仍由旧代码进程承载（本会话事件文件中可见 review_admission_qualified/service_action_terminal 等新事件，但无 knowledge.read——与承载进程版本一致）。属部署-流量时滞，非通道故障。

## 3. 观察结论与后续

- 统计面（账本/水位/渲染/待结算）在真实数据上行为正确；新口径（声明净分/双水位/待结算计数）代码与测试就绪。
- **首次真实流量条件**：任一由 gen≥268 运行时承载的会话做一次精确水合（产生 knowledge.read）或收尾结算（产生 v2 账本行/回执）即开始积累。
- 建议复检点：下次新运行时会话收尾后，观察 ①knowledge.read→pending→submit 全链计数 ②v2 schema 行进入账本 ③规则反馈提交后 _search_rule 注释三件套呈现。本次不预设自动唤醒，由后续任务按需安排。

## 4. 遗留项盘点（不阻断，用户已指示挂账）

- P2 总池 ≈23 项：r0 审查 ×10、B1 准入审查 ×7、B1 审查 ×4、B2 审查 ×2（含 registry 工具 schema 口径措辞未同步）。
- 位置：docs/governance/receipts/ 各回执 findings 节。

## 5. 证据

- 部署核验：runtime_manifest.learning.json（pid 25491 / 3bd871709）
- 数据面探针：本报告 2 节各数字均来自 2026-10-16 06:53-06:55 只读探针真实输出（event_logs 全量类型统计、usage.jsonl 逐行解析、usage_net 真实渲染）
- 审查/门禁：20261016-fdc7603b-b2-rule-feedback-p1-code-review.json（PASS）；ci_gate exit=0 / 319 passed
