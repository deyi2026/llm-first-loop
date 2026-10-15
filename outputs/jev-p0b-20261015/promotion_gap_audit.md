# 经验卡晋升空窗与 record_use 账本失真审计（只读）

- 生成脚本：`outputs/jev-p0b-20261015/promotion_gap_audit.py`（可复算）
- 机器产物：`outputs/jev-p0b-20261015/promotion_gap_audit.json`
- 权威口径：`ExperienceDocument.from_md`（代码解析器）。**不使用正则扫描 front matter**——本审计首轮用正则产生过假阴性（125 张被误判为"无 front matter"）。
- 边界：只读。未改任何经验卡、未改 usage 账本、未改 producer、未新建采样。

## 1. 卡片验证态分布（463 张 = 464 个 md − README.md）

| verification_state × record_kind | 数量 |
|---|---|
| verified / experience | 160 |
| verified / lesson | 111 |
| legacy_unclassified / experience | 176 |
| unverified / lesson | 16 |

按"是否显式标注"拆分（关键：区分标注与默认值回填）：

| verification_state | explicit 显式标注 | defaulted 默认值回填 |
|---|---|---|
| verified | 271 | 0 |
| unverified | 16 | 0 |
| legacy_unclassified | 11 | **165** |

## 2. 晋升空窗的真实规模是 165，不是 176

176 张 `legacy_unclassified` 是两种性质完全不同的东西，不能合并记账：

**A. 11 张显式标注（不是空窗，是"已晋升后归档"路径）**
- `status` 全部 = `archived`（11/11）
- `promoted_to_rule` 非空：**6 张**（RULE-AI-02 ×2、RULE-AI-23 ×4）
- `last_verified_at` 非空：9 张
- 判定：这批卡是走到晋升/验证后归档，遗留 `legacy_unclassified` 是标签未同步，不是"从未分类"。

**B. 165 张 defaulted（真正的空窗人群）**
- `verification_state` 字段从未写入，`legacy_unclassified` 是解析器默认回填
- `status`：active 128 / archived 37
- `evidence` 非空：**142/165**
- `promoted_to_rule` 非空：5；`last_verified_at` 非空：2

> 修正声明：本审计过程中我曾口算"explicit legacy 中 8 张已 promoted_to_rule"，实为 **6 张**，以脚本输出为准。

**结论**：真正从未被验证态分类的是 **165 张**（其中 128 张仍 active），且其中 **142 张卡内已带 evidence 文本**——即素材存在、缺的是分类动作，不是缺证据。这属于分类欠账，不能由本轮只读审计代偿（改 165 张卡的验证态是写操作，且需要逐张判断证据是否足以支撑 verified）。

## 3. record_use 账本核查（experience 20 条 + method 22 条）

### 3.1 experience 侧：零漂移、零截断
- 20 条声明逐条比对"账本内嵌 verification_state/status"与"卡当前值"：**漂移 0 条**
- `store.usage_net()` 实算：**截断 0 条**，每条都被完整计入
- `use_decision`：applied 16 / adapted 4，**负面 0 条**（无 not_applicable、无 rejected）
- 账本内嵌 `verification_state`：verified 8 / unverified 9 / legacy_unclassified 3
  → 即 **12/20（60%）的使用声明落在非 verified 卡上**：声明"用了"与"卡被验证过"目前完全脱钩

### 3.2 method 侧：2 条漂移，且均被 D3 重锚点截断为 net=0

| method | 声明时 status | 当前 status | 账本条目 | usage_net 计入 | net |
|---|---|---|---|---|---|
| `resume-continuation-via-named-provenance-and-git-delta-948a229d7f50` | candidate | active | 1 | 0 | 0 |
| `self-execute-review-contract-on-degenerate-tool-output-c1088a737f27` | candidate | qualified | 1 | 0 | 0 |

机制：D3 重锚点只累计"声明时 status == 卡当前 status"的条目。这两张卡在声明后发生了 lifecycle 晋升（candidate → active / qualified），于是**历史正向 applied 被排除出净分**。

这是设计内的语义（"修正后从修正点重新累计"），但副作用值得记档：**卡片晋升成功，其晋升前积累的正向证据被清零**。与第 2 节的"从未分类"构成镜像缺口——一端是 165 张从未分类，另一端是 2 张分过类却在晋升后归零。

- `decision`：applied 18 / adapted 3 / not_applicable 1，**rejected 0**
- 全库 42 条声明中仅 1 条负面，且是 not_applicable（按 RULE-AI-31 只记账、不构成弃用依据）

## 4. 与 P0a §13 项 2 的关系：同一 gap，不重复记账

- `task_benefit`：experience 侧 20/20 `not_evaluated`，method 侧 22/22 `not_evaluated`，合计 **42/42**
- 与 P0a v0.6 已记录的"`task_benefit` 40/40 not_evaluated、机会分母不可从现有事件构造"是**同一缺口**，本轮把计数从 40 精确为 42（P0a 统计对象为 EventStore 事件，本轮为两侧 usage 账本，口径不同）
- 该字段只能由 producer 侧新增才能测，属实施项，本轮只读审计不补造

## 5. UNMEASURABLE 项（如实标注，不推测）

1. **165 张 defaulted 卡中究竟多少张的证据足以支撑 verified**——需逐张人工/模型判断证据质量，只读审计不做（且判定即写操作）。142 张"有 evidence 文本"不等于 142 张"证据合格"。
2. **绝对晋升遗漏量**——无"应该被晋升"的独立清单，无法算出遗漏率，只能给出未分类存量。
3. **2 条被截断声明对真实净分的影响方向**——已知是正向证据被清零（低估），但低估量在 42 条样本上无统计意义。

## 6. 结论

- 观测基础可用、可复算；**分类欠账（165 张）与账本截断（2 条）是两个独立的、已定位的具体缺陷**，不再是"可能存在缺口"的模糊判断。
- 全库 42 条使用声明近乎全正向（41 正 / 1 中性 / 0 错误引导），**这不构成任何卡有效性的证据**：无独立事实标签、无曝光分母、`task_benefit` 42/42 not_evaluated、零对照。沿用 P0a 结论——收益/校准评估仍不可做。
- 建议的两个实施项（均非本轮只读范围）：① 对 165 张 defaulted 卡做分批分类并补齐 `verification_state`；② 评估 D3 重锚点是否应对"晋升"方向保留历史正向证据（当前语义下晋升即清零）。
