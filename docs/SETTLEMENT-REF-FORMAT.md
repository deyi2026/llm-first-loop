# 知识结算的 ref 口径（2026-10-31 补记）

## 为什么需要这份文档

`settlement_submit` 的 `ref` 字段在不同 kind 下对应**不同的真实 key**。2026-10-31 实测：
同一张 experience 卡，用带前缀的 stable ref 提交失败、用裸文件名提交成功——看起来像通道坏了，
实际是口径不一致。

## 各 kind 的 ref 真实 key

| kind | 提交用的 ref | 底层 key | 备注 |
|---|---|---|---|
| `experience` | **文件名去掉 `.md`** | 同左 | 例：`EXPERIENCE-20261031-审查门禁的材料上限应按资产类别分级-有界投影-而非全局放宽` |
| `method` | stable ref | 同左 | 例：`method-root-cause` |
| `rule` | `RULE-AI-xx` | 同左 | 例：`RULE-AI-35` |

**带 `experience:` 前缀的形式**（如 `experience:EXPERIENCE-20261031-xxx`）是检索/展示用的
stable ref 形态，**不是**结算通道的 key。2026-10-31 已修复校验侧口径不一致的代码缺陷
（`src/llm_loop/introspection/settlement.py`：校验侧按 kind 归一，与写入侧 `record_use`
一致），修复后带前缀形式也能通过；但**裸文件名形式最稳**，因为它就是底层 key。

## 提交顺序（避免盲试）

1. 先建 `work_unit_id`（本轮任务标识，建议 `wu-<日期>-<主题>`）。没有它，提交会落到
   `unresolved`，无法抵扣确定性任务。
2. `settlement_pending(work_unit_id=…)` —— 先看清"精确水合读取事件 − 已回执"的待结算清单。
   它反映的是**你真正水合读过的**知识卡片，不是全部接触过的。
3. 按清单逐条 `settlement_submit`，`decision` 取实际效果（applied/adapted/not_applicable/rejected），
   `evidence_level` 取可支撑的档位（有观测链接用 `observation_linked`，纯自报用 `model_declared`）。
4. 回执里的 `failed` 要逐条看 reason：`self_reported ref not found` 是 ref 形态问题，
   不是卡片不存在。

## 失败排查表

| 回执 | 真实含义 | 处理 |
|---|---|---|
| `self_reported ref not found` | key 形态不对（最常见） | 按上表换成裸文件名 / stable ref |
| `unresolved`（无 work_unit_id） | 无法归到确定性任务 | 补 `work_unit_id` 重提 |
| `pending` | 缺 read_version 或版本不匹配 | 补齐 `read_version`（精确水合时的版本哈希） |
| 计数 `committed=0` 且无 per-item reason | 批量被上限或 schema 拒绝 | 拆小批重提，核对字段名 |

## 与"精读抵扣"的关系

`settlement_pending` 的清单来自**统一检索工具的精确水合成功路径**。它**不**覆盖
`read_file` 直读知识文件、附件内嵌摘录、泛查询命中。这是**事件源可观测范围**，
不是全部知识接触——模型可以用 `self_reported=true` 补充自报条目，但那样就没有读版本抵扣，
只能按自报证据等级记账。

## 尚未落地的改进建议

1. **工具描述补口径**：`settlement_submit` 的 schema description 应写明上表的 ref 形态。
   （2026-10-31 未做：`src/llm_loop/introspection/registry_experience.py` 正被并发改动，
   避免冲突未动。）
2. **错误信息分级**：`self_reported ref not found` 应回显"已尝试的 key"，并区分
   「卡片不存在」与「形态不对」——当前两者同码，只能靠猜。
3. **卡片短 id**：`save_experience` 回执宜带一个稳定短 id，避免人工核对长中文标题。
