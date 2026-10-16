# K-Rate 知识打分闭环

评分层 → 聚合层 → 索引层 → 消费 → 处置 → 回流。本地 27B scorer（127.0.0.1:8091，
27B-Instant-MLX-8bit）只产概率分布不产叙述；使用叙述与自报收益来自 settlement 回执。

```
任务收尾 settlement_submit (decision/benefit/evidence_level/note/evidence_refs)
        │  落盘 data/methods/usage.jsonl (method-use/v2, 现有 LFL 原生流程)
        ▼
① python3 tools/krate/krate_score.py        # 对未打分事件调 scorer, 追加 scores.jsonl
        ▼
② python3 tools/krate/krate_index.py        # 聚合→composite→index.json/md + dispositions.md
        ▼
③ 接入模型消费 (见"消费契约")               # 索引=排序器, 不是检索器
        ▼
④ 按 dispositions.md 建议, 由模型走原生工具执行状态变更 (脚本永不改知识库)
   method_manage / refine_experience / submit_evolution
        ▼
   被优化/复活的知识回到 ①, 新使用事件继续积累 → 闭环
```

## 消费契约（其他大模型接入 LFL 时）

1. **检索照旧**：`search_records`（method/experience/lesson/rule）或 `search_docs` 拿候选 ref。
2. **排序看索引**：读 `data/knowledge_index/index.json`，按 ref 匹配：
   - `composite` 降序 + `n_valid≥3` → 优先加载，先读该条目 Trigger 段
   - `disposition=STALE_*` 或卡龄大 → 降优先级，除非检索词强命中
   - `disposition=INVALIDATE_CANDIDATE` → 不加载（除非持有新反证，此时应反驳而非照用）
   - `disposition=REFINE_TRIGGER_*` → 条目仍可用，但 Trigger 有召回噪声，靠 Discriminator 二次确认
3. **开局 priming**：可读本任务领域 top-N（≤5 条）做预热，不得用它替代检索。
4. **分数不是真值**：执行前必读条目正文（METHOD.md / EXPERIENCE-*.md / ai_rules.md）。
   跨 `prompt_hash` 的分数不可比较（见 index header）。
5. **回报**：任务收尾正常走 settlement 回执即可，事件自动进入打分管线。

## 评分语义

- 五档 usefulness：0 无帮助 / 1 轻微 / 2 中等 / 3 显著 / 4 决定性（含反事实考量：
  "不用它会怎样"，照做无差异=0-1 档，防安慰剂）。
- `p_suff`（证据充分性）：<0.35 insufficient 不计分只计数；[0.35,0.65) borderline 计分×0.5；
  ≥0.65 全权。空 note/无回执引用的事件天然落在低权区（自评偏置控制）。
- 聚合：`E_shrunk=(2·2.0+Σw·e)/(2+Σw)`，w=evidence_level 权重(model_declared 0.6 /
  observation_linked 1.0 / independently_evaluated 1.2)×borderline 折减。单次满分只到 2.67。
- `composite = E_shrunk − 0.5×hindered自报次数 − 卡龄衰减(30d 免衰, 后线性, 封顶 0.6)`。

## 处置标准（数值门槛 → 建议动作；执行走原生工具，脚本只建议）

| 建议 | 触发条件 | 动作（原生工具） |
|:--|:--|:--|
| QUALIFY_CANDIDATE | composite≥3.0 ∧ n_valid≥3 ∧ 30d 内有使用 | `method_manage record_qualification` |
| DEMOTE_HOLD_OR_ARCHIVE | n_valid≥3 ∧ E_shrunk<1.5 ∧ hindered=0 | method→`transition hold`；experience→`refine_experience archive` |
| INVALIDATE_CANDIDATE | hindered≥2 ∨ (hindered=1 ∧ 证据refs非空) | `refine_experience invalidate` / method invalidate（保留尸体供检索避坑） |
| REFINE_TRIGGER_RECALL_MISMATCH | 0档占比≥70% ∧ n_valid≥3 | `method_manage refine` 改写 Trigger/Discriminator（是召回错配不是知识坏） |
| STALE_DEMOTE_OUT_OF_RECOMMENDED | n=0 ∧ 卡龄>45d | 不删，仅出推荐位（索引自动降权） |
| RECEIPT_QUALITY_FIX | n_insufficient 占比≥60% | 不动条目；改进使用方回执质量（settlement note+evidence_refs） |
| REVIVE_CANDIDATE | hold/archive 状态 ∧ 新事件 top≥3 | `refine_experience restore` / method reopen |
| RULE_INDEX_ONLY | rule 类任意低分 | **只走 `submit_evolution` 建议，永不弃用**（规则属治理层） |

处置原则：低分先诊断原因（不对题→改写；无效果→降级观察；有害→失效；太老→降权），
**默认可逆**（archive/hold 可 restore），只有 hindered 证据充分才 invalidate。

## 事件 schema（experience/rule 手动补事件时）

`krate_score.py --events <file>.jsonl`，每行兼容 method-use/v2 字段：
`record_ref`(experience:<id> 时指向 experiences/EXPERIENCE-*.md)、`decision`、`benefit`、
`evidence_level`、`note`、`evidence_refs[]`、`ts`、`submission_hash`(幂等键)。
rule 事件目前不落 ledger，按 RULE_INDEX_ONLY 处理。

## 自动闭环（EVO: settlement 后自动 score+index）

- **触发点**：`src/llm_loop/introspection/registry_experience.py::_run_settlement_submit`，
  `committed>0` 时 fire-and-forget spawn `tools/krate/autorun_after_settlement.py`
  （分离进程组、不等待；任何失败只 audit `krate_autorun/failed`，绝不影响结算回执）。
- **串行化**：脚本内 flock `data/knowledge_index/.autorun.lock`；锁忙则等待上限
  `KRATE_AUTORUN_WAIT_S`（默认 300s）后放弃——score(event_id)/index(全量重建) 均幂等，
  下次触发或手动运行自动补齐漏网事件。
- **守卫**：`LFL_KRATE_AUTORUN=0` 一键关闭；pytest 环境（`PYTEST_CURRENT_TEST`）跳过，
  防单测向真实 data/ 落子；脚本缺失（部署未携带 tools/krate）静默跳过。
- **日志**：`data/knowledge_index/autorun.log`（超 2MB 截尾保留 256KB）。
  scorer 不可达（krate_score exit 2）是 pending 状态，autorun 恒 exit 0。
- **手动等价**：`python3 tools/krate/autorun_after_settlement.py`（行为与自动触发完全一致，
  含锁）。**不要绕过 autorun 直接跑 `krate_score.py`**：锁在 autorun 层，直跑与 autorun
  并发时锁不互斥，虽有 event_id 幂等兜底，仍可能重复调用 scorer 浪费配额。
- **测试**：`tests/unit/test_krate_autorun_hook.py`（守卫矩阵 + 脚本锁语义，tmp 树隔离）。

## 边界与已知限制

- scorer 不可达 → 事件留 pending，退出码 2，**绝不造默认分**。
- 幂等：event_id=submission_hash；重跑跳过已打分。
- 索引可随时全量重建（幂等）；scores.jsonl 为 append-only 真值源，损坏行被容忍跳过。
- 冷启动：多数条目 UNRATED 是常态；索引不替代检索，只是给"加载优先级"提供证据。
- 分数跨 scorer 版本/prompt 版本不可比较（index header 带 prompt_hash）。
