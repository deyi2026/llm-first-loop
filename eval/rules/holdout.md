# held-out 隔离规则

> 版本：v1 ｜ 生效日期：2026-10-23 ｜ 状态：**生效**（决策来源：用户 2026-10-23 拍板 D-3）
> 配套：`docs/EVAL-PLAN-LFL-20261023.md` §5-P2、§4-D3、§4-D5

---

## 1. 规则

**held-out 任务集不得进入任何用于"改进"的语料或索引。** 具体禁止项：

| # | 禁止项 | 说明 |
|---|---|---|
| 1 | 不入 **method / experience / lesson discovery** 检索语料 | `search_records` 的 method/experience/lesson/episode 语料不得包含 held-out 题面、题解、失败轨迹或任务 id |
| 2 | 不入 **memory 写入** 语料 | 任何写向 `memory` / `memory_extract` 的内容不得含 held-out 信息 |
| 3 | 不入 **promotion 论证**语料 | held-out 之外的证据用于提出改进；held-out 只用于**事后一次性验证** |
| 4 | 不入 **method_manage 候选**的 evidence_refs | 候选方法的证据链不得引用 held-out 任务 id |
| 5 | 不入 **报告的归因细节** | 对外报告中 held-out 失败只报聚合数与失败模式类别，不报题面/逐例轨迹 |

**唯一允许用途**：在改进方案冻结后，**一次性**跑 held-out 并报告 Δpass@1（可重复跑以取 CI，但每次跑都不得回流为改进输入）。

---

## 2. 隔离强度

- **强隔离**：held-out 题面与 solution 在改进期对优化循环不可见（默认档）。
- 题面、test_patch、solution 分文件存放；`solution` 目录在改进期不进入任何索引。
- 每次检索/写入前用**索引排除清单**过滤（见 §4），而非依赖模型自觉。

---

## 3. 污染判定（发现即作废该轮）

| 情形 | 处置 |
|---|---|
| 改进期读取了 held-out 题面/solution | 该轮 held-out 结果作废，重新冻结新版本 |
| 改进期读了 held-out 的 gold patch / 官方 commit | 同上 |
| held-out 结果被用于继续调优 | 结果作废；且该轮**不得计入 promotion 论证** |
| 题面在冻结后被修改 | 视为新版本，旧结论不自动迁移（D2 / §2 统计纪律） |

---

## 4. 索引排除清单（机制）

`evals/heldout/v1/manifest.json` 必须包含：

```json
{
  "version": "v1",
  "created_at": "<ISO8601>",
  "tasks": [
    {"task_id": "<id>", "statement_sha256": "<sha256>", "test_patch_sha256": "<sha256>",
     "solution_sha256": "<sha256>"}
  ],
  "exclusion": {
    "record_kinds": ["method", "experience", "lesson", "episode", "memory", "memory_extract"],
    "index_paths": ["evals/heldout/v1/"],
    "forbidden_task_ids": ["<id>", "..."]
  }
}
```

- 任何写入 `record_kinds` 列举载体的操作，**必须**先对照 `forbidden_task_ids` 与 `statement_sha256` 过滤。
- 过滤器实现落 `evals/heldout/v1/filter.py`（P2 交付），提供 `assert_not_heldout(text, manifest) -> None | str`。
- 自检命令（每轮收尾必跑）：

```bash
python3 evals/heldout/v1/filter.py --selfcheck
```

- 违反时的处置：记录为 **known-red**（`docs/known-reds-20260909.md` 新增小节），并把该轮结论降级为 C 级（不得 promotion）。

---

## 5. 与证据分级的关系

- held-out Δpass@1 > 0 且同预算 → **A 级**，可进入 promotion 论证。
- 无 held-out，只有域内激发任务提升 → **C 级**，**不得据此 promotion**。
- 任何被判定为污染的轮次 → 该轮结论**作废**，既不是 A 也不是 C，而是"无结论"。
