# R8 按模型能力分档注入（Shadow）验证报告

日期：2026-08-30
状态：**SHADOW PASS；R8.3 SOAK PASS；behavior canary NOT STARTED**

## 1. 范围

R8 只实现 `minimal / standard / full` 的**推荐计算与逐 provider-attempt 审计**。本阶段不允许推荐值影响：

- prompt build / message ordering；
- R2 `INJECTION_BUDGET_CHARS`；
- R3 `REFERENCE_AUTO_TURNS`、seen-set、pointerization；
- R4 program recovery；
- R5 identity summary filtering；
- R6 exact user-truth tail / provider wire normalization；
- tool schema、provider 参数、model routing。

因此 R8 的第一验收问题不是“哪个档位效果最好”，而是：**能否在完全不改变 provider payload 的前提下，准确、可审计地算出未来推荐档位。**

## 2. 单一能力事实源

R8 不维护模型名 allowlist，也不根据 `context / thinking / cost_tier / provider id` 猜强弱。唯一事实源是当前路由绑定的不可变 `ProviderRegistry/ModelSpec` 快照。

沿用仓库既有能力枚举：

```text
capability_tier = strong | weak | unknown
```

不新增 `standard` 模型 tier。`standard` 只是 injection profile：

```text
weak                         -> minimal
unknown / unresolved         -> minimal   # 保守
strong + reasoning=false     -> standard
strong + reasoning=true      -> full
```

这与既有 `unknown=保守视为弱模型` 契约一致，同时避免 R8 再造第二套模型能力状态机。

实现：`src/llm_loop/core/injection_profile.py`。

## 3. 为什么不用 request.meta 承载 R8

最初可选落点是给 `request.meta` 增字段，但代码审查发现：`request.meta` 是**round 级快照**，同一 round 主模型失败后可能同步 fallback 到另一模型。若把 profile 只写在 `request.meta`，实际 fallback provider 会被归到主模型。

因此 R8 新增独立事件：

```text
injection.profile.shadow
```

每个**真实 engine-level provider call**写一条：

- `primary#0`；
- `fallback#1..N`，resolve 失败不计 provider attempt；
- `err1210_retry#1..N`，覆盖 blind / strip / aggregate/raw retry 的真实重发。

事件包含 model、tier、recommended profile、reason、attempt kind/index，并强制：

```text
mode = shadow
applied = false
```

事件写失败 fail-open，不阻断 LLM；推荐计算只读 registry snapshot，不回写 Session 或 provider config。

## 4. 零行为证明

专项测试构造两份 registry，保持：

- model id 相同；
- user/system/tools 相同；
- build 路径相同；

只把能力元数据从 `weak` 改为 `strong + reasoning=true`。shadow recommendation 从 `minimal` 变为 `full`，但 FakeLLM 捕获的 `messages + tools` 经确定性 JSON 序列化后**逐字节一致**。

这直接证明：

```text
recommended profile changed != provider payload changed
```

R8 没有把 profile 偷接进 prompt。

## 5. Provider attempt 归因覆盖

专项集成验证：

```text
primary/m   -> minimal  -> primary#0
fb1/m1      -> standard -> fallback#1
fb2/m2      -> full     -> fallback#2
```

第一 fallback 真实超时、第二 fallback 成功，事件顺序与真实调用顺序一致。另有 1210 blind retry E2E：

```text
primary#0 -> err1210_retry#1
```

恢复成功后两条事件 model/profile 一致，证明 1210 的隐藏重发不再漏归因。

## 6. 当前 runtime shadow inventory

证据：`docs/injection-governance/r8/shadow-inventory.json`。该文件由 `scripts/injection_r8_shadow.py` 从运行时 `data/providers.json` 读取后生成，输出只保留脱敏派生字段与源 SHA，不包含 base_url、api_key_env、凭证或本地路径。

当前结果：

```text
models_total=11
capability_tier: unknown=11
recommended profile: minimal=11
classified_models=0
classified_coverage=0.0%
metadata_complete_models=0
canary_ready=false
canary_block_reason=capability_metadata_incomplete
```

关键解释：**11/11 minimal 不是“11 个模型已验证为弱”**。事实是当前 provider config 没有显式填 capability tier；parser 按既有契约回退 `unknown`，R8 再保守推荐 minimal。

因此 R8 shadow infrastructure 可以验收，但行为 canary 不能开始。进入 canary 前至少需要：

1. 运维/owner 对实际模型显式填写并审核 `capability_tier`；
2. strong 模型显式填写/审核 `reasoning`，否则不能判断 standard vs full；
3. 重新生成 shadow inventory，`metadata_complete_coverage=100%` 后再讨论行为 canary。

R8 **没有修改 `data/providers.json`**。

### 6.1 Post-R8 capability audit（R8.1）

R8 验收后按 owner 指令执行 metadata audit；详见 `capability-audit.md/json`。只对有受控实测证据的模型补 metadata；随后 owner 明确退役不用的 Qwen3.6。当前 inventory 更新为：

```text
classified=4/10 = 40.0%
strong=1, weak=3, unknown=6
recommended profile: full=1, minimal=9
canary_ready=false
```

R8.1 修改了 Git-ignored `data/providers.json` 的 5 个 metadata 字段，但没有调用 `refresh_config`，live registry 未热重载；R8 `mode=shadow, applied=false` 不变。剩余 unknown 不按厂商/模型名猜档，R9 继续未开始。

R8.1 验证：runtime registry parse PASS；R8/provider/event focused 112/112 PASS；inventory byte-reproduction PASS；pyright 0/0；R0 四门 PASS 且 0-byte diff。

### 6.2 Post-R8 remote capability completion（R8.2）

R8.2 新增 credential-safe `scripts/injection_r8_remote_ab.py`：凭据只通过项目正常 `.env -> ProviderRegistry -> LLMClient` 路径在一次性子进程内解析，证据不保存 key、endpoint、raw HTTP body 或 raw answer。72/72 A/B prompt hash 与冻结 R7 fixture 当前重算一致。

受控 A 臂 + 独立 T3/T4 dominance 复跑支持把 DeepSeek V4 Flash/Pro、GLM 5.3/5.3 Flash、MiniMax M3 五个模型标记为 `weak`。`LLMEmptyResponseError` 按仓库定义属于“正常流结束但无 final content/tool”的完成失败，不按 transport error 处理。`mxnook/glm-5.3-flash` A/B 12/12 HTTP error，简单请求 thinking on/off 也均 HTTP 502，因此保持 `unknown`。

当前 runtime inventory：

```text
classified=9/10 = 90.0%
strong=1, weak=8, unknown=1
recommended profile: full=1, minimal=9
canary_ready=false
```

R8.2 当时仍未调用 `refresh_config`，live registry 未热重载，`mode=shadow, applied=false` 不变。完整远端证据见 `r8/remote-ab.json` 和 `r8/capability-audit.md`。mxnook provider 持续 HTTP 502；owner 随后明确允许忽略，因此从 active inventory 退役。当时 metadata gate 达到 9/9=100% READY；后续 R8.3 已完成，见 §6.4。

R8.2 最终门：117/117 focused PASS；remote-runner evaluator 5/5；pyright 0/0；py_compile/diff-check PASS；inventory byte-reproduction PASS；72/72 remote prompt hash PASS；R0 四门 PASS 且 0-byte diff。
Detached clean checkout 同口径复验 PASS，测试前后 `git status` 均 clean。

### 6.3 Owner exclusion of mxnook（current）

R8.2 结束时 `mxnook/glm-5.3-flash` 因持续 HTTP 502 保持 unknown。owner 随后明确表示可以不再考虑 mxnook，因此本轮将该 provider 从 Git-ignored `data/providers.json` active catalog 删除；没有把 502 猜成 weak，也没有调用 `refresh_config`。

当前 active inventory：

```text
classified=9/9 = 100.0%
strong=1, weak=8, unknown=0
recommended profile: full=1, minimal=8
canary_ready=true
```

这表示 **metadata gate READY**，不是 behavior canary 已启动。当时下一阶段为 R8.3 shadow soak；现已完成，见 §6.4。R9 继续未开始。

### 6.4 R8.3 bounded live shadow soak — PASS

权威门：`r8/soak-gates.md`；详细报告：`r8/soak-report.md`；脱敏证据：`r8/soak-evidence.json`。

Mirror 8903 已受控加载当前 9-model registry；active metadata 9/9 complete、unknown=0、registry non-degraded。隔离 live soak 覆盖 strong-short 3 calls、weak-short 3 calls、40-message weak long-history 1 call：共 7 个真实 primary provider calls，对应 7 个 `injection.profile.shadow`，unattributed=0、nonprimary=0、profile churn=0、attribution/mode/source violations=0。strong 始终 `full`，weak 始终 `minimal`，全部 `mode=shadow, applied=false`。

Production-path deterministic gate 再验 payload byte-identity + fallback exact attribution + err1210 retry attribution 3/3 PASS；R8.3/R2/R3/R4/R5/R6 focused 145/145；pyright 0/0；R0 frozen 再次 0-byte。Detached clean checkout 同口径复验 PASS（145/145 + static + inventory reproduction + canonical R0 0-byte，status before/after clean）。三个临时 soak session 在证据脱敏后经正式 DELETE API 清理，shared current 指针 byte-identical。

**结论：R8.3 PASS；behavior canary NOT STARTED；R9 NOT STARTED。**

## 7. 结构/预算正交门

在 production-shape fixture 上复跑：

```text
off/shadow/enforce × 512/700/900/2000/8000 = 15 points
```

15/15 同时满足：

```text
recovery_count == 1
tail_user_run == 1
exact user suffix == true
recovery slot consumed == true
generated_program_chars <= R2 used_chars <= budget
```

代表值：

```text
off      512 used= 463 generated= 331
shadow   512 used= 463 generated= 331
enforce  512 used= 463 generated= 351
off     8000 used=2374 generated=2089
shadow  8000 used=2374 generated=2089
enforce 8000 used=2374 generated=1493
```

结论：R8 shadow 不改变 R2/R4/R5/R6 组合不变量。

## 8. R0 frozen gate

R0 analyzer 重新执行：

```text
R0=PASS
R0-1_data_completeness=PASS
R0-2_baseline_measurable=PASS
R0-3_deterministic_reproduction=PASS
R0-4_parameter_candidate_gate=PASS
```

`docs/injection-governance/r0` 全目录逐文件 SHA 前后相同，tracked diff **0 byte**。

## 9. 测试与静态门

### 9.1 R8 / adjacent focused

覆盖 R8 profile/event/inventory、event log、err1210、fallback、model routing/pool/providers、R2/R3/R4/R6：

```text
268/268 PASS
```

另有一次未排除环境依赖的首跑，`test_model_attribution.py` 4 个 Web/飞书 import 用例因当前 MCP Python 缺 `pypdf` / `lark_oapi` 失败；失败发生在 import，未进入 R8 代码。为避免改变环境，本阶段没有安装依赖，也没有把这 4 项冒充为 R8 PASS。

pytest 仍打印仓库既有 21 条 `audit_test_side_effects` provider URL 人工复核 warning；非 R8 新增、非阻断。

### 9.2 Static

R8 touched production + 新测试/脚本：

```text
py_compile: PASS
pyright: 0 errors / 0 warnings / 0 informations
git diff --check: PASS
```

`tests/unit/test_event_log.py` 只增加新 event constant 到既有 exact-registry 集合；差分静态验证显示：父提交与 R8 提交都恰为 **6 个**相同 `reportOptionalMemberAccess`，仅因 R8 新增两行导致报错行号整体 +2。故该文件的 6 个 pyright 债是 pre-existing，不把它伪装成 R8 新 clean 文件；pytest contract 已通过。

### 9.3 Detached clean checkout

在不使用当前工作区任何 untracked/dirty overlay 的 detached worktree 中验证最终源码形态：

```text
checkout status before = clean
R8/adjacent focused = 268/268 PASS
R8 production + new tests/script pyright = 0/0
py_compile = PASS
checkout status after = clean
```

这证明 R8 提交自包含，不依赖主工作区中现存的 Web/Cognitive/scheduler 等未提交改动。

## 10. 文档一致性修复

审查中发现 `requirements.md` 总览仍残留旧编号：把“模型分档”写成 R7、“A/B”写成 R8；但同文件后文与 `tasks.md` 已是 R7=A/B、R8=model tier。R8 收口同步修正该自相矛盾，不改历史 R7 证据。

## 11. 结论

R8 达成当前阶段目标：

- capability 来源单一；
- minimal/standard/full 推荐确定、保守、可审计；
- primary/fallback/1210 retry 归因完整；
- profile 变化不会改变 provider payload；
- R0/R2/R4/R5/R6 不变量继续成立；
- 当前真实 catalog 的元数据缺口被显式暴露，未被“自动猜档”掩盖。

因此状态是：

```text
R8 shadow = PASS
R8 behavior canary = NOT STARTED（R8.3 已通过，具备另立 canary 设计条件）
R9 = NOT STARTED
```

下一阶段若要做行为 canary，应先补齐并审核 provider capability metadata，再另立目标；不得从当前 0% classified coverage 直接升级到 enforce。
