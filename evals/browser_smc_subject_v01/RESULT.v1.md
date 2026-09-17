# browser_smc_subject_v01 — 首个 subject-facing smoke 结果（v01）

Receipt（冻结，surface-as-was）: `results/run_20260917T231757Z/summary.json`
（git a3a790c3b；plan/pro协议 5a3075d9f，fixture v1.1 + runner cbf6efc34/18da9900）

## 1. Gate 与表面结论

预声明门全过：`infra_valid` 5/5（无 WORKER_ERROR/TIMEOUT/fallback/surface mismatch）、
`judge_executed` 5/5、`oracle_pass` 1/5 ≥ min 1 → **gate PASS**。

表面记分 1/5（ambiguity_halt PASS，其余 4 族 oracle FAIL）。**该记分是退化记分，不构成
subject 能力结论**：5 行 `ok_count=0`——subject 全程没有成功执行过任何一个动作。
ambiguity_halt 的"通过"是零动作退化满足零事件 oracle（浏览器从未离开起始页，
fixture 零 GET）。

## 2. 根因（已修复，见 §3）：工具层机器署名缺失

证据链（row 01-name_pollution，`rows/01-name_pollution/data/observability/tool_reachability.jsonl`）：

- rounds 3/6/9/11/12 共 5 次 `browser_action`，payload 全部 13/14 字段精确正确
  （schema/domain/scope_ref/action_id/verb/target_id/args/operation_class/
  idempotency_class/atomicity_class/expected_version/version_scope=resource/
  version_precondition=required），唯一缺 `args_normalization`；
- 模型在 rounds 4/7 两次调用 `get_tool_schema` 求解——工具 schema（`src/llm_loop/tools/
  builtin/browser_action.py` L34-61）诚实声明 13 字段且 `additionalProperties: false`，
  按广告面**不可能发现**也不允许代交该字段；
- 运行时校验器（`src/llm_loop/browser/action.py` L276-293）要求含 `args_normalization`
  的 14 字段精确集合，且拒因 `semantic_action_fields_mismatch` 不指名字段——模型只能
  在无辜的 `args` 形态上盲试（4 种变体，均非病因）。

分层意图本身是冻结且自洽的：`args_normalization` 是机器署名 receipt 字段
（`action.py` L36-44 docstring："Machine-authored receipt field; never part of the
model-owned surface"；adapter 14 字段契约有显式测试
`test_missing_normalization_field_is_rejected`）。兄弟工具
`browser_semantic_execute.compile_request` 在编译期机器自注入该字段
（`browser_semantic_execute.py` L112-121）。缺的一环在 `BrowserActionTool.execute`：
把模型裸 kwargs 直通 adapter，漏了机器署名步骤。**层间矛盾，任何模型必然全灭。**

dry-judge 为何没抓住：competent-subject 是 Playwright 驱动，动作由控制器侧组装
（14 字段直连 adapter），不经过模型面 schema——矛盾只在真模型行暴露。

其余 4 行同根因（rejected navigate 合计 30 次，全部 `semantic_action_fields_mismatch`；
fixture 零 GET，`/state` 全空）。fixture 本身零缺口（本轮根本没打到它）。

## 3. 修复（71ce26740）

`BrowserActionTool.execute` 注入 `args_normalization={"applied": false, "rule": null}`
（passthrough，同 semantic_execute 的机器署名语义）；模型越权代交则原样透传，
adapter 照旧 fail-closed（`args_normalization_mismatch`）。adapter 契约、模型面
schema、工具描述全部不动（均为冻结面）。

回归锚定 `tests/unit/test_smc_browser_action_tool_authorship_v01.py`（3 用例：
13 字段 click/navigate 不再 fields_mismatch 且回执记 passthrough；hand-authored
仍 fail-closed）。相关面 43/43 绿（含既有 adapter 冻结测试）。

## 4. 修复后复测

（运行中，收尾时填）

## 5. 转入 v02 的杠杆（本轮不做）

1. **拒因指名**：`semantic_action_fields_mismatch` 应返回缺失/多余字段集合——fc2c
   已验证的 required-set 机械杠杆；但拒因文本是 subject 可见面，改动属 surface
   变更，须 v02 冻结后配对评估。
2. **零事件 oracle 的退化通过**：ambiguity_halt 无法区分"正确 halt"与"从未动作"。
   v02 建议把"至少一次 route GET"（visits 非空）作为该族 oracle 前置——fixture v1.1
   的 visits log 已支持。
3. typed_wait_param / scoped_scroll / cross_route_navigate 三族在真 subject 下尚无
   有效测量（本轮全被 navigate 堵死），复测后才有首批数据。
