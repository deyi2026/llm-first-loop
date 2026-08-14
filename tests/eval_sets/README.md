# 评测集（Evaluation Set）

> B7(2026-08-14) 开源化：场景可扩展——外部贡献者按本文件 schema 新增场景即可，
> 无需改判定代码（判定注册表按名分派）。

## 文件布局

```
tests/eval_sets/
  scenarios_v1.json    # 场景定义（版本化；新增场景不动既有版本，开 v2 或追加同版本条目）
tests/scripts/test_eval_suite.py   # 判定/统计/链路测试（防漂移：场景 schema 校验）
scripts/run_eval.py                # 运行器（真实 LLM / --dry）
src/llm_loop/eval/verdicts.py      # 判定函数注册表（VERDICTS）+ Wilson CI
```

## 场景 schema（scenarios_v1.json）

顶层：`{"version": 1, "name": ..., "created": ..., "baseline_ref": ..., "scenarios": [...]}`

每个场景对象：

| 字段 | 必填 | 说明 |
|:---|:---|:---|
| `id` | ✅ | 唯一标识（snake_case，如 `rule07_tool_first_read`） |
| `name` | ✅ | 人类可读名称（中文描述） |
| `prompt` | ✅ | 任务文本（发给引擎的用户消息） |
| `samples` | ✅ | 样本数（建议 6，统计功效参考 Wilson CI） |
| `verdict` | ✅ | 判定名（必须已在 `VERDICTS` 注册，否则 schema 测试报错） |
| `params` | ✅ | 判定参数（如 `{"tool": "read_file"}`；无参数用 `{}`） |

## 新增场景步骤（约 30 分钟）

1. 在 `scenarios_v1.json` 的 `scenarios` 数组追加对象（按上述 schema）。
2. 若需要新判定：在 `src/llm_loop/eval/verdicts.py` 加判定函数并用
   `@_register("name")` 注册（输入统一为 `(trace, answer, **params)`，返回 bool；
   判定必须纯函数、确定性、可单测）。
3. 加单测：判定函数行为（tests/scripts/test_eval_suite.py 或新测试文件）。
4. 本地验证链路：`python scripts/run_eval.py --dry --samples 2`（零 LLM 管道检查）。
5. 真实基线：`python scripts/run_eval.py`（需 key；CI nightly 也会跑）。

## 纪律（沿用内部实证口径）

- **不引入程序强制**：评测是"度量"不是"闸门"——场景失败不阻塞发布，如实记录即可。
- **统计约束**：结论用 Wilson 95% CI；区间重叠即不宣称统计显著；N 小时如实标注。
- **负结果同等呈现**：新增场景的负结果与正结果一样有价值（记录原因，不美化）。
- **防漂移**：场景 schema 由 `test_scenarios_json_valid_and_schema` 校验
  （id/prompt/samples/verdict 必填 + verdict 必须已注册）——改了判定名忘了场景会挂。
