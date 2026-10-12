# SMC Browser Semantic Execute FCR A/B v0.4 — Result — 2026-09-13

## 裁决

**预声明 Smoke Gate：FAIL。** 但这次必须把“gate 失败”和“treatment 表现”分开写：

- `browser_semantic_execute` treatment 的外部任务 oracle：**3/3 PASS**；
- treatment SMC adoption：**3/3**；
- treatment 机械回执：navigate `ok`=**3**、object `ok`=**4**、old scope/version blocker=**0**、automatic retry=**0**；
- 机械 live qualification 仍为 **12/12 behavior + 7/7 safety PASS**；
- v0.4 tool-local FCR 假设：**DIRECTIONALLY SUPPORTED**；
- 但按本轮冻结 gate，默认启用状态仍是 **NOT_QUALIFIED_BY_CURRENT_GATE**；
- GLM / MiniMax / DeepSeek cloud canary：**NOT_RUN_BY_GATE**。

Gate 失败的直接原因不是 treatment task failure，而是 `full_action` 控制臂有两条 frozen 240s TIMEOUT，导致 `infra_valid=false`、timeout rows 无 terminal worker surface 因而 `surface_exact=false`，且 full-action SMC adoption 只有 1/3。**不能在看到 treatment 3/3 后事后修改 gate。**

## 身份与证据

- v0.4 FCR implementation：`62a3b50a7a4f50ac8c3e8d42cb0f010435f33cfd`
- v0.4 protocol：`b516f08b4abb754583dd5f8c794bffe937b31220`
- FCR surface preflight guard：`ea282591eba846b8e1ebc9743618d73479dd5ff0`
- measured HEAD：`ea282591eba846b8e1ebc9743618d73479dd5ff0`
- semantic execute implementation：`b313f9bb5e689aa935cdc081d83f5dca7d7af3a7`
- mechanical live harness/report：`fd812123a8ad0fe5e844a2fc7f0d2e17ceccd3be` / `abf97bb6c2f7b9495cfd2ed588ffa6aa0959f1e6`
- frozen protocol plan SHA256：`8f3bab36fdd4836a1bc5e27a1256b944d43c17ce3d51e3678924af2cf10dc8d0`（与 v0.3 相同）
- measured results SHA256：`20137b426fb2903e22e8f0ed02f0ea2ba0b5b93a3e1aa66a840b27824cfce624`
- gate SHA256：`f0aa2f90029d0e33dfa09bc67bea02b74eb2a82cdcfc724566eb9787765b25a5`
- execution manifest SHA256：`594acdc2c25da9f4fee346cfbd8c8a21cbe88f52eb5314efad5d7a1cba03d482`
- offline analysis SHA256：`796a5cacbdb4363bd208e56edb7aebeda0dda92af189d3905d3fb54a093a6c73`

模型和运行参数保持 Ornith / Thinking ON / temperature 0 / 184K input / 16K output / max iterations 12 / prompt+decode concurrency=1；每行 fresh session/data/Chrome profile，严格串行，无 fallback，无第二个本地模型。正式执行前 committed-state surface preflight 已确认两臂共享 `browser_perceive + get_tool_schema` 哈希相同，v0.4 wait FCR 在两臂均可见；semantic mutation 面仍只有 `verb + target_ref + args` 三字段。

## v0.4 只改了什么

implementation `62a3b50a` 只改 3 个 model-facing 描述文件和 2 个测试文件；未改 Browser 执行控制流：

- `semantic_execute.target_ref`：强调**先 snapshot 取得 exact GroundingRef/resource_ref**；URL、名称、scope_ref 不能冒充 `target_ref`；
- `semantic_execute.args`：保留 verb-specific closed shapes；
- `browser_perceive(wait)`：强调 wait 只用于真实时间条件；scope predicate 必须 `target=scope_ref=当前 observation 的 exact scope_ref`；`interval_ms` 为整数 1..5000；
- lazy schema 通过参数局部 compact facts 保留上述 load-bearing 事实。

没有扩大 universal prompt，没有自动 route/target selection/latest/snapshot/retry/replay/rebind/completion，也没有 provider-specific rewrite。

## Frozen gate

| 项 | v0.4 结果 |
|---|---:|
| 完整 rows | 6/6 |
| infra valid | **FAIL**（full_action row2/row5 TIMEOUT） |
| surface exact | **FAIL by timeout telemetry absence**；正式 preflight exact PASS |
| no fallback | PASS |
| SecurityAgent | 0 |
| full_action SMC adoption | **1/3**，门槛 ≥2 |
| semantic_execute SMC adoption | **3/3**，门槛 ≥2 |
| full_action task pass | **0/3** |
| semantic_execute task pass | **3/3**，门槛 ≥2 |
| semantic object `ok` receipts | **4**，门槛 ≥1 |
| semantic navigate `ok` receipts | **3**，门槛 ≥2 |
| semantic old scope/version blockers | **0** |
| automatic retry | **0** |

`surface_exact=false` 与 v0.3 一样，是 timeout rows 没有 terminal worker payload 造成，不是观测到 provider surface 漂移；formal preflight 已在模型请求前硬校验 exact surface 与 FCR markers。

## 三个 paired task

### 1. click_commit

- **semantic_execute：PASS**，external `commit_count=1`；11 rounds / 10 tools / 88.813s；navigate `ok`=1、object click `ok`=1、scope blocker=0。
- **full_action：TIMEOUT**，240s，external oracle=false；partial durable receipts 显示 `navigate_page_target_mismatch` 与 `args_contract_mismatch`，均在 dispatch 前拒绝、automatic retry=false。

Treatment 仍在第一个工具调用把非 GroundingRef 当 `target_ref`，被 `target_ref_unavailable:invalid_ref` 安全拒绝；随后 snapshot→resource navigate→object click→verify 成功。两次 wait 均使用合法 contract 并成功，v0.3 该任务的 wait contract failure 未复现。

### 2. fill_submit

- **semantic_execute：PASS**，external `save_count=1` 且值精确匹配 `AB-7319`；11 rounds / 10 tools / 85.452s；navigate `ok`=1、fill/click object `ok`=2、scope blocker=0。
- **full_action：TASK_FAIL**；12 rounds / 14 tools / 194.343s；两个 mutation receipt 都因 `expected_version_unavailable` 在 dispatch 前 rejected，object/navigate `ok` 均为 0。

这是 v0.4 相比 v0.3 最直接的改善：v0.3 treatment 只做到 navigate+fill，12 轮耗尽后没有 Save；v0.4 在同一任务/行序/模型/轮次上限内完成 navigate→fill→Save click→外部验证。仍有一条 invalid target_ref 首调和一条 `scope predicate target must equal its exact scope_ref` wait failure，因此不能声称 FCR 缺口完全消失。

### 3. delayed_wait

- **semantic_execute：PASS**，external `ready_click_count=1`、`early_click_count=0`；9 rounds / 8 tools / 101.533s；navigate `ok`=1、object click `ok`=1、scope blocker=0。
- **full_action：TIMEOUT**，240s，external oracle=false；partial durable receipt 为 `expected_version_missing`，pre-dispatch rejected、automatic retry=false。

Treatment 轨迹为：首个无 ref navigate 被安全拒绝 → snapshot → exact resource navigate → **合法 wait success** → snapshot → exact object click → verify。v0.3 treatment 在该任务 240s TIMEOUT、无 ActionReceipt；v0.4 已真实完成时间条件与后续动作。

## v0.3 → v0.4 的方向性变化

| semantic_execute 指标 | v0.3 | v0.4 |
|---|---:|---:|
| task pass | **1/3** | **3/3** |
| infra-fail/timeout rows | 1 | **0** |
| receipt `ok` | 4 | **7** |
| object `ok` | 2 | **4** |
| navigate `ok` | 2 | **3** |
| rejected receipts | 1 | **0** |
| old scope/version blockers | 0 | **0** |
| median tool calls | 11 | **10** |
| median wall time | 123.621s | **88.813s** |
| median input tokens | **92,520** | 110,258 |

这只支持方向性判断，**不支持统计显著性或“全面更高效”声明**：尤其 input-token median 反而增加。最强证据是三项 external task oracle 从 1/3 提升到 3/3，且所有成功都由真实页面 side effect 判定，而不是由 receipt 或模型自报完成判定。

## 仍未解决的 FCR 缺口

1. **3/3 semantic treatment 行都仍在第一个工具调用用非 GroundingRef 调 navigate。** 工具均以 `target_ref_unavailable:invalid_ref` 在编译层安全拒绝，没有 dispatch。说明“必须先 snapshot”的文字已经存在，但对 Ornith 的首调纪律仍不够稳定。
2. `fill_submit` 仍出现 1 次 `scope predicate target must equal its exact scope_ref`。因此 wait FCR 明显改善，但尚非零错误。
3. v0.4 没有引入任何自动补救；这些错误之所以没有造成错误物理动作，是现有 exact ref / stale-version / single-dispatch 边界在工作，不是程序替模型选了正确下一步。

## 正式裁决

**机械架构方向成立，v0.4 tool-local FCR 的 real-model 证据显著优于 v0.3；但当前这次预声明 gate 仍然 FAIL，所以不能把“3/3 treatment PASS”改写成“正式默认启用资格已通过”。**

当前应记录为：

- Semantic Action Compiler / `browser_semantic_execute`：**机械资格 PASS**；
- Ornith treatment usability：**3/3 real-task PASS，强方向性正证据**；
- v0.4 frozen smoke qualification：**FAIL（control TIMEOUT / infra gate）**；
- 默认启用：**NOT_QUALIFIED_BY_CURRENT_GATE**；
- 云端 provider canary：**NOT_RUN_BY_GATE**。

下一步不应事后放宽本轮 gate。若继续，应另行冻结一个新的确认性资格化设计，再决定是否开放 cloud canary；本报告不预先改变该下一阶段的标准。
