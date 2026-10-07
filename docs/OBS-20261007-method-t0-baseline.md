# Method 消费闭环 T0 基线（P0-1 rev 2）

- 性质：纯观测文档，无代码/部署变更。
- 前提核验（详见 AUDIT-20261007 §4.4）：生产 web = generation 195 @ `54fc378c4`（2026-10-07 22:09:02 启动，matches_desired_generation=true）；HEAD `4bd0b9356` 与生产的产品代码差仅为本审计文档。**不存在待部署的 Method 改动，故不做 publish/restart。**
- 生效机制（T0 观测对象）：
  1. `search_records(kind=method)` pull-mode 词法检索（`introspection/search.py::_search_method`；`SEMANTIC_METHOD_ENABLED=0` 仅关语义 RRF 扩展层，不阻断）。
  2. A 面锚点：`tools/registry.py` + `introspection/registry_introspection.py`（5 触发域 + 行为触发）。
  3. `method_manage` 生命周期（save_candidate / record_use / record_qualification / refine）。
  4. Learning reflection 的 related-method advisory。
- **T0 = 2026-10-07 22:09:02（generation 195 启动时刻）**。

## 基线值（2026-10-07 22:5x 采集）

| 指标 | T0 值 | 采集命令 |
|---|---|---|
| method 卡库存 | 677 目录 | `ls data/methods \| wc -l` |
| usage.jsonl 条数 | 6 | `wc -l data/methods/usage.jsonl` |
| kind=method 检索调用（历史累计） | 24 | 见下方脚本 |
| kind=method 检索调用（T0 后） | 0 | 同上，ts 过滤 ≥ T0 |
| method_manage.record_use 调用（历史累计） | 1 | 同上 |
| method_manage.record_use（T0 后） | 0 | 同上 |

采集脚本（精确计数，排除 schema 回显；只统计 payload.tool_calls[].function.name）：

```python
import json, glob
for fp in glob.glob('data/event_logs/*.jsonl'):
    for line in open(fp, encoding='utf-8'):
        if '"search_records"' not in line and '"method_manage"' not in line:
            continue
        e = json.loads(line)
        ts = str(e.get("ts", ""))
        for tc in (e.get("payload") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") == "search_records" and '"method"' in (fn.get("arguments") or ""):
                print("SR_METHOD", ts)
            if fn.get("name") == "method_manage" and '"record_use"' in (fn.get("arguments") or ""):
                print("MM_USE", ts)
```

## T+7d 检查点（2026-10-14 前后）

- [ ] kind=method 调用增量（T0 后累计）：___
- [ ] method_manage.record_use 增量：___
- [ ] usage.jsonl 增量：___
- [ ] 若三项增量均为 0：消费断点不在机制可用性，转向 §4.3 排序 2/3（usage 记录摩擦、触发域覆盖/语义扩展层）。
