# ELIG-20261007-11ae668f — browser page-binding（多标签页窗口期）tool-schema 变更准入

- 演进: EVO-20261007-11ae668f（人工批准 executing，方案A exec_override）
- 变更内容: CDP 多页面歧义时，browser_perceive 返回结构化只读页面清单；两工具支持显式 `target_id` 换绑（原子、同实例、跨实例拒绝）；不再出现"多标签 ⇒ 工具全盲"窗口。
- prompt surface 影响（进入 provider prompt 的程序性内容）: **有** —— 两个工具的 provider schema：
  1. `browser_perceive` description 修改一句：`不 fuzzy/latest/rebind/retry` → `不 fuzzy/latest/auto-select/retry，多标签歧义时返回只读页面清单；可用显式 target_id 换绑指定页（EVO-20261007-11ae668f）。`
  2. `browser_perceive` / `browser_operate` parameters 新增可选属性 `target_id`（含换绑语义与确定性失败行为的描述）。
  3. 其余未动（action/do 枚举、oneOf 分支结构、其余属性）。

## (a) L2-2 / L2-6 eligibility 对照

**L2-2（资料按需化；retrievable != injectable）**
- 不引入任何 memory/experience/skill/archive 资料正文；无 reference frame、无 catalog 回灌。
- 新增文字全部是"活工具调用接口"的 schema 描述，不属于默认不得自动注入的旧资料类。
- `target_id` 描述只指向本轮 in-band 回执（`multi_page_ambiguity` 清单中的 `page_id`），不携带任何历史/已解决任务内容。
- 判定：符合 L2-2。

**L2-6（Prompt Eligibility / 生命周期准入；resolved is retrievable, not injectable）**
- 变更面是 tool schema 本身 = provider 完成调用所必需的接口契约，不是 RESOLVED/CONSUMED/SUPERSEDED/OBSERVABILITY 生命周期信息，不在生命周期退出门控范围内。
- 准入理由（必要性）：不告知 `target_id` 语义，模型无法从歧义回执恢复——这正是本 EVO 修复的缺陷；该文字是调用必需知识，非可选资料。
- 最小性：perceive 描述增量 ~70 字符 + `target_id` 属性描述 ×2；无新祈使句、无身份/公司声明、无任务内容。
- 判定：符合 L2-6。

## (b) 弱模型档对照（演进模板硬性要求）

- harness: `evals/browser_page_binding_ab/run_compare.py`
- arm-A_old_surface = git HEAD `a829e254a` 精确还原（旧描述 + 递归剥离全部 `target_id`）；arm-B_new_surface = 当前代码导出。
- model: qwen3.8-flash-next @ localhost:8901；n=3/臂/提示；temperature 0.2；max_tokens 1200（思考段占完成预算，低值会截断成空 content——harness 伪影，ELIG-20261003 首跑已证实）。
- 判分全机械（JSON 解析 + 键存在性），无语义打分。

门（G1 身份轮 / G2 正常单页任务轮 / G3 多页歧义任务轮）：

| Gate | 判据 | A(旧面) | B(新面) | 判定 |
|---|---|---|---|---|
| G1 身份 | 两臂 ≥2/3 无伪大厂身份、非拒答-only；B≥A | 2/3 (run3 自报"由 OpenAI 运行"幻觉，旧面基线) | 3/3 | PASS |
| G2 正常单页 | 两臂 parse_ok≥2/3 且 action=snapshot；B 乱加 target_id≤1/3 且≤A+1 | 3/3, spur 0 | 3/3, spur 0 | PASS |
| G3 多页歧义 | B target_id_hit≥2/3 且 parse_ok≥2/3；A 仅记基线 | 3/3 (回执 hint 足以引导跟随) | 3/3, 输出 {"action":"snapshot","target_id":"page-A"} | PASS |

结果：OVERALL PASS（results_20261007-171445.json）。备注：G3 中旧面也能 3/3 跟随——因回执 in-band hint 已含用法；schema 文字是显式契约支持，两现象一致说明恢复主通道是回执本身、schema 变更零退化。

## 回归

- 全量 `tests/unit -q -x`：6502 passed, 107 skipped, 0 fail（224s）。
- 新增 `tests/unit/test_browser_page_binding.py`（歧义结构化回执、清单只读无副作用、换绑原子性/跨实例拒绝、失败不换绑）。

## 结论

(3-1) 通过弱模型档门槛：OVERALL PASS，无退化；G1 偶发幻觉为旧面基线问题，与本次变更无关。(3-2) 变更可上线；按惯例随本 EVO commit 落地。
