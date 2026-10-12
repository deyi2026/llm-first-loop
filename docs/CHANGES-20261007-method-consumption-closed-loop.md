# CHANGES 2026-10-07: Method 消费闭环（A 面触发锚点 + B 面检索联动）

## 背景与问题

Method 供给侧健康（652 张卡，词法/语义检索 top-3 命中实测通过，semantic scope=method
已于 10-06 生产激活 gen 181），但全库仅 5 条 use 回记。5/652≈0.8% 是事件数与卡数之比，
不是消费率；当前缺少检索机会、候选曝光和实际采用的完整分母。
检索 smoke 证明能力可用，尚不能证明所有任务都能查到适用方法；本轮工作假设是
schema 触发词过于抽象（"复杂/高摩擦/重复型任务"），使模型难以想起检索，需实测验证。

对照证据：skill_list 用具体场景锚点（"格式转换/PDF、特定站点抓取、运维诊断"）+
行为触发（"准备自己探测或拼装流程前先发现候选"），同处一个 schema 面而消费实际发生。

## A 面：schema 触发锚点（上午已实施）

`search_records` 描述（registry.py compact + registry_introspection.py full 两处）：
抽象触发词 → 五个实测命中域（失败重试/换源、编辑冲突、超时判定、浏览器定位、
验证纪律）+ 行为触发（动手前先做有界 method 搜索 limit<=5）。
保留防滥用条款与 method:<id> 不猜测条款。

## B 面：记忆检索附带 Method 候选（本轮新增，用户提议）

用户提议"只要检索相关记忆，就一并检索方法"。评估采纳，边界如下：

### 与 09-24 被否决形态的本质区别

method_injection.py:7-11 记录：会话开场**无条件常驻**注入 ACTIVE 卡列表已被实验否决
（弱模型注意力挤占：身份轮用训练先验答题，session 6aec21cb vs 对照 f66027f9；
L2-2"可检索≠可注入"）。B 面三个特征全部相反：

- **条件触发**：仅当记忆检索（kind=experience/lesson/memory）已发生，非开场
- **query 对齐**：附带候选与主检索同 query，用既有词法/语义 RRF 召回；召回不证明任务适用性
- **单次尾注、空结果静默**：method 零命中时尾注消失；不在开场无条件列出卡片。
  命中时仍增加回执内容，是否带来噪声或注意力成本尚待评估；历史回执也可能进入后续上下文。

### 实现

- `RecordSearcher.search()`（introspection/search.py）：special 分支短路前调
  `_maybe_collect_related_methods`——开关开 + kind∈{experience,lesson,memory} +
  query 非空且非 exact-ref 形态时，`_search_method(query, 2)` 附带；fail-open；
  **保存/恢复语义诊断**（附带检索不得污染主结果诊断透传——_search_method 会写
  `_last_semantic_diagnostics`，实测确认后加 finally 恢复）
- `related_methods` property；factory.py 适配器 duck-typing 透传（与 last_diagnostics
  同模式）
- `tools_status.py::_format_related_methods_hint`：回执尾注（命中路径尾部 + 零命中
  路径）。工具层读取经 `__self__` 兼容 bound-method 注入形态（与
  _read_last_diagnostics 同构）。文案纪律：`task_applicability=not_evaluated`，
  不替模型选方法，采用需先 exact method:<id> 水合
- `config.py`：`method_related_hint_enabled`（默认 True；env METHOD_RELATED_HINT_ENABLED）
- 描述两处各加一句"记忆类检索回执附带 [Method 候选提示] 尾注"

### 零命中也渲染

经验零命中但 method 有候选时尾注仍渲染——这正是消费缺口的典型场景
（经验库没有、方法库有）。

## 护栏与教训

1. **compact 描述 80 字增量预算**（test_rule_presence_contract）在实施中暴露超支：
   A 面（+95）+ B 面（+48）合计远超预算。且**上会话 A 面单独已超支**——当时验证
   子集未含 rule_presence_contract，属验证盲区。本轮全量回归暴露后压缩文案至
   Δ=67（A 面锚点从五域展开压为紧凑列举，B 面去掉 kind 括号列表）。教训：
   描述文案改动必须跑 rule_presence_contract 全量，而非自选子集。
2. **路径可关联，因果归因尚未隔离**：action_trace 与 method ledger 可核对主动
   kind=method discovery，以及尾注候选 ref → exact 水合 → record_use 的时序。
   同时启用 A/B 时，尾注也可能诱发后续 discovery，两路可能重叠；无明确来源证据的
   采用记为来源未知，不把时序关联当因果证明。独立效应需要单路对照，非本轮新增机制。

## 验证

- tests/unit/test_method_related_hint.py 7/7：命中尾注、零命中尾注、method 空
  零噪声、非记忆 kind 不附带且重置、exact-ref 不附带、开关关闭、诊断不污染
- test_rule_presence_contract.py 20/20（含 80 字预算契约）
- test_method_learning.py + test_experience_learning_record_contract.py 全过
- 全量 tests/unit：用户提供本轮终态 `6458 passed, 107 skipped, 0 failed`，EXIT:0。
  这是功能回归结果，不构成消费收益或默认上线资格。

## 提交与运行态边界

- 本轮最初 staged 的 11 文件（+369/-8）同时含独立 TOOL_GUARD_ENABLED 配置回收；
  它与 A/B 消费改造应分开提交。回收经验、pipeline 注释和 evidence pipeline 测试
  属回收项；config.py/factory.py 需按 hunk 分离，避免混合回滚。
- 本候选尚未 publish/restart；`method_related_hint_enabled=True` 仅是候选默认值，
  不代表生产已启用。FR-1 仍按原授权观察；本轮收尾不扩大生产变更范围。

## 闭环观察（以 A/B 实际生效时刻起算）

- 10-13 是 FR-1 A3 的 T+7d 复核日，可同时做本候选状态检查，不能称为未上线 A/B 的 T+7d。
- A/B 的 T0 取生产实际生效时刻并记录 generation、commit、开关与模型身份；
  T+7d 从该 T0 起算。上线前只能做功能验证，不能计为消费观察期。
- 在 T0 重新快照 usage.jsonl 基线（本轮历史基线为 5），统计增量及唯一 method ref；
  use 回记不等于任务收益，缺少回记也不证明从未使用。
- A 面：统计普通 query 的 kind=method discovery，排除 exact 水合；
  B 面：统计符合条件的记忆检索、候选尾注曝光、水合、record_use 关联链，来源不明单列。
- 零增量时先核对生效、有效任务机会、检索命中、provider-visible 尾注与回记覆盖。
  无曝光/无适用机会则证据不足；确认有机会和曝光仍无转化时，仅支持触发/采用机制
  尚未奏效的结论，再考虑模型侧调用纪律，不能据此断言供给侧机制已证伪。
