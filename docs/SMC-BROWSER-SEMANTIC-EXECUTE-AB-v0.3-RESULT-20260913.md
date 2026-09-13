# SMC Browser Semantic Execute A/B v0.3 — Result — 2026-09-13

## 裁决

**Smoke Gate：FAIL。**

因此当前正式状态是：

- `browser_semantic_execute` **机械执行层：PASS**；
- Ornith model-facing usability：**NOT_QUALIFIED**；
- 默认启用：**NOT_QUALIFIED**；
- 云端 GLM / MiniMax / DeepSeek canary：**NOT_RUN_BY_GATE**。

这不是把新工具判成“无效”。相反，本轮证明它已经把一个明确的旧故障类消掉：模型不再需要手工维护 `target_id / scope_ref / expected_version / version_scope / action_id`。但三项真实任务里 treatment 只通过 1 项，且 delayed-wait 仍超时，所以还不能进入默认启用或跨 provider 扩展。

## 冻结身份与证据

- implementation：`b313f9bb5e689aa935cdc081d83f5dca7d7af3a7`
- mechanical live report：`abf97bb6c2f7b9495cfd2ed588ffa6aa0959f1e6`，12/12 behavior + 7/7 safety PASS
- A/B protocol：`0e79a9857a3cbcc90a7b192843a958994005704a`
- frozen plan SHA256：`8f3bab36fdd4836a1bc5e27a1256b944d43c17ce3d51e3678924af2cf10dc8d0`
- measured results SHA256：`41340d60a1a4501296ea74979175fcfdbf520d1faaaa22af086994ee7142c1e1`
- gate SHA256：`37dfa458d3a5bda2b8db48c4b784ab5f8c3a5bb8c43cf50af828412a2ebeda1b`
- execution manifest SHA256：`9035d155e50e4acbcd14af913b01e9487da1d2017956e947fbf852a2e3acbcb6`
- offline analysis SHA256：`037473868e94d3cdc324d40896e94ddd23428eb8c0e9556a2be195e2f91b1182`

实验保持同一 Ornith、Thinking ON、temperature 0、184K input / 16K output、prompt/decode concurrency=1、fresh session/data/Chrome profile，逐行串行执行；没有第二个本地模型，没有 fallback，没有 SecurityAgent 弹窗。

## Frozen gate

| 项 | 结果 |
|---|---:|
| 完整 rows | 6/6 |
| infra valid | FAIL（两条 delayed-wait 240s TIMEOUT） |
| no fallback | PASS |
| SecurityAgent | 0 |
| full_action SMC adoption | 2/3 |
| semantic_execute SMC adoption | 2/3 |
| full_action task pass | **0/3** |
| semantic_execute task pass | **1/3**，门槛 2/3 |
| semantic_execute object `ok` receipts | 2，门槛 ≥1 |
| semantic_execute navigate `ok` receipts | 2，门槛 ≥2 |
| semantic_execute old scope/version blockers | **0**，要求 0 |
| automatic retry | **0**，要求 0 |

`surface_exact=false` 来自 timeout rows 没有 terminal worker payload，**不是观测到 surface 漂移**。正式模型请求前的 committed-state preflight 已确认两臂 exact surface，且共享的 `browser_perceive + get_tool_schema` 哈希一致。

## 三个 paired task

### 1. `click_commit`

**semantic_execute：PASS；full_action：TASK_FAIL。**

Treatment 用 `resource_ref` 完成真实 navigate，再用 object GroundingRef 完成 click；外部 oracle 精确记录一次 Commit。它用了 10 rounds / 9 tools / 95,950 input tokens，0 个旧 scope/version blocker。

Control 第一次 navigate 成功后连续出现 3 个 `resource_scope_mismatch`，即使读取完整 tool schema 后仍继续重复 navigate，12 rounds 内一次 object action 都没有发出。该行使用 13 tools / 111,341 input tokens，最终 commit_count=0。

这一对是本轮最强的方向性证据：**物理执行器健康，旧 13 字段模型合同本身会诱发 scope/version 维护错误；把机械编译放进工具后该故障类消失。**

### 2. `fill_submit`

**两臂都 TASK_FAIL，但失败边界不同。**

Treatment 最终真实完成了 navigate + fill，`scope_blockers=0`；但它一开始在没有 snapshot/ref 的情况下把非 GroundingRef 当 `target_ref`，被工具正确拒绝，之后又把多轮消耗在 wait/snapshot/hydrate，直到第 12 轮才完成 fill，已经没有下一轮去点击 Save，因此 external save_count=0。

Control 同样先成功 navigate，随后再次出现 3 个 `resource_scope_mismatch` 并反复 navigate，始终没有到 fill。也就是说 treatment 已经把失败位置从“不会正确构造动作合同”推进到了“Observe / Wait / Act 轨迹与轮次效率”。

### 3. `delayed_wait`

**两臂都在 frozen 240s worker limit TIMEOUT。** 两条都没有外部 ready-click side effect，且都没有 replay。

Control 的 durable session 有 9 个工具调用：1 次 full `browser_action(navigate)` + 8 次 perception，其中 wait×4；唯一 ActionReceipt 是 navigate 在 dispatch 前因 `expected_version_unavailable` 被拒，automatic retry=false。

Treatment 的 durable session 有 7 个工具调用：最初 1 次 semantic navigate 使用非 GroundingRef，被 `target_ref_unavailable:invalid_ref` 在工具编译层拒绝；之后 perception×5（wait×3、snapshot×2）+ get_tool_schema×1；**0 个 ActionReceipt**，说明在 timeout 前没有形成可 dispatch 的 semantic action。

## 机械层的净变化

对有 terminal worker telemetry 的两行/臂做描述性汇总：

| 指标 | full_action | semantic_execute |
|---|---:|---:|
| task pass（全部3行） | 0/3 | 1/3 |
| receipt `ok` | 2 | 4 |
| object `ok` | **0** | **2** |
| rejected receipts | 6 | 1 |
| old scope/version blockers | **6** | **0** |
| mean rounds（2条有终态telemetry） | 12.0 | 11.0 |
| mean input tokens | 111,969 | 92,520 |
| mean output tokens | 3,160 | 1,897.5 |

round/token/wall-time 只做描述，不做显著性或普遍性能声明。

## 新暴露的 First-Call-Ready 缺口

现在的主要短板已经不是“缺少执行程序”，而是**工具局部机械用法还没有强到足以让 Ornith 首调稳定正确**：

1. `target_ref`：两条 treatment 轨迹都先尝试了非 GroundingRef，真实错误为 `target_ref_unavailable:invalid_ref`。应在 lazy 参数局部明确：`target_ref` 只能来自当前 `snapshot` 返回的 exact GroundingRef；URL、名称、文字都不是 target_ref。
2. `browser_perceive(wait)`：真实出现 `scope predicate target must equal its exact scope_ref`。这个 scope target 合同应在 wait 的 compact parameter facts 中首调可见。
3. `interval_ms`：真实出现超出机械范围，工具返回“必须是整数 1..5000”。这个上限也应进入 lazy parameter-local contract。
4. 多步动作：工具内 worked example 应继续保持 `snapshot -> exact ref -> execute -> receipt -> re-snapshot`，并用一个极短的 fill/save 例子说明：非时间条件不要先泛化成 wait；navigate 后重新观察，再操作当前 object ref。

这些都属于**工具描述中的机械事实**，与此前 63-tool First-Call-Ready 修复属于同一类；不需要恢复程序语义路由。

## 下一轮建议

下一轮应做一个小型 v0.4，只改 model-facing **tool-local mechanical contract**，不动执行语义：

- 给 `browser_semantic_execute.target_ref` 增加 compact 参数局部说明；
- 给 `args` 保留 verb-specific closed shapes；
- 给 `browser_perceive wait` 的 scope predicate / `interval_ms=1..5000` 增加已被真实失败证明 load-bearing 的参数局部事实；
- 保留“先 Observe，再 Ground，再 Execute，Receipt 后重新 Observe/Verify”的 canonical example；
- 重新跑相同 3 对任务，仍以 external oracle 为唯一 task pass。

明确不采用：自动 target selection、自动 snapshot/latest、自动 retry/replay、自动 rebind、程序侧 task completion、扩大 universal prompt、强制 Method search。

只有 v0.4 本地 smoke 过预设 gate，才重新开放 GLM / MiniMax / DeepSeek cloud canary。
