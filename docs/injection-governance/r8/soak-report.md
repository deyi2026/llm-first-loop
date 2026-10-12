# R8.3 Bounded Live Shadow Soak Report

日期：2026-08-30

## 1. 结论

**R8.3 Shadow Soak = PASS。Behavior canary = NOT STARTED。R9 = NOT STARTED。**

本阶段没有实现新的 prompt/profile 行为，也没有修改 `src/` 生产代码。目标仅是让 mirror 真实运行态加载已审核的 9/9 capability metadata，并验证 `injection.profile.shadow` 在真实 primary provider call、长历史以及 deterministic fallback/1210 路径上持续正确归因。

权威 gate：`soak-gates.md`。脱敏 live evidence：`soak-evidence.json`。

## 2. Live registry 激活

R8.2/R8 metadata 配置完成后，mirror 8903 做了受控 web 单服务 restart。健康检查通过，代码基线为当时生产 HEAD `16fdb5d`；R8.3 后续 tracked 变更仅是 evidence/tooling/docs/tests，不改变运行中的生产 `src/`。

restart 后 `GET /api/v1/models`：

```text
active models = 9
mxnook present = false
```

运行时 metadata inventory：

```text
models_total=9
metadata_complete=9/9 = 100%
strong=1
weak=8
unknown=0
profiles: full=1, minimal=8
registry_degraded=false
metadata_gate_ready=true
```

未调用 behavior profile apply；`mode=shadow, applied=false` 不变。

## 3. Bounded live primary soak

为了不污染用户共享会话，创建了三个临时、非 shared 的隔离 session：

1. strong-short：`local/qwen/qwen3.8-27b`，3 次真实 provider call；
2. weak-short：`deepseek/deepseek-v4-flash`，3 次真实 provider call；
3. weak-long-history：预置 40 条短历史后再调用 `deepseek/deepseek-v4-flash`，1 次真实 provider call。

全部 7 次请求都走 mirror 8903 production engine/provider path 并得到 HTTP 200。`soak-evidence.json` 仅保存 profile/event 派生字段，不保存 session id、prompt、raw answer、endpoint、API key/env name 或 Authorization header。

结果：

```text
request.usage events             = 7
injection.profile.shadow events  = 7
unattributed primary attempts    = 0
unexpected non-primary attempts  = 0
profile churn models             = 0
attribution/mode/source violations = 0
```

具体 profile：

```text
local/qwen/qwen3.8-27b       strong -> full    3/3
DeepSeek V4 Flash short      weak   -> minimal 3/3
DeepSeek V4 Flash long hist  weak   -> minimal 1/1
```

7/7 事件均同时满足：

```text
attempt_kind=primary
attempt_index=0
mode=shadow
applied=false
source=provider_registry
observed tier/profile/reason == current ModelSpec recommendation
```

因此 live primary attribution accuracy = **100%**，profile churn = **0**。

### 非 gate 的回答诊断

临时 prompt 使用了“逐字返回 marker”作为方便的 smoke diagnostic。严格 byte-equal marker 为 4/7；没有把它作为 R8.3 quality gate，也没有据此评价模型能力。原因是本阶段 `applied=false`，没有 treatment/control 行为差异，回答文本不可能构成“profile 应用收益”的因果证据。真实行为收益必须留到 behavior canary。

## 4. Fallback / 1210 / zero-behavior 路径

不为了制造异常去污染 live provider。复跑 production engine deterministic E2E：

```text
test_shadow_profile_change_is_provider_payload_byte_identical  PASS
test_fallback_attempts_get_exact_shadow_attribution            PASS
test_err1210_retry_gets_shadow_attempt_event                   PASS
```

**3/3 PASS**。

这些测试锁定：

- capability metadata 改变推荐 minimal/full 时，实际 provider `messages+tools` byte-identical；
- primary + 每个真实 fallback provider call 都有独立且精确的 profile event；
- 1210 retry 产生独立 `err1210_retry` attempt，不被 primary 遥测吞掉；
- resolve failure 不冒充 provider attempt。

## 5. 长历史与结构正交

40-message long-history live case 仍稳定推荐 weak/minimal，说明历史长度没有污染 capability/profile attribution。

R8.3 没有触碰 production `src/`，因此没有引入新的 prompt/build/budget/recovery/user-wire 行为变量。原 R8 的 R2×R4×R5×R6 15/15 orthogonal matrix 仍是生产行为基线；本轮另外复跑相邻 focused suite：

```text
err1210 recovery              63
identity summary              11
injection budget               7
injection profile shadow      12
R8 inventory                   3
R8.3 soak evaluator            4
program recovery boundary     10
reference integration         15
reference policy              11
user truth wire                9
TOTAL                         145
```

**145/145 PASS**。

静态门：

```text
pyright: 0 errors / 0 warnings / 0 informations
py_compile: PASS
git diff --check: PASS
```

仓库既有 21 条 provider URL 人工复核 warning 仍是 non-blocking、非本轮新增。

## 6. R0 frozen gate

R0 analyzer 再执行：

```text
R0=PASS
R0-1_data_completeness=PASS
R0-2_baseline_measurable=PASS
R0-3_deterministic_reproduction=PASS
R0-4_parameter_candidate_gate=PASS
```

`docs/injection-governance/r0` 全目录逐文件 SHA 前后相同，tracked diff **0 byte**。

## 7. 临时运行态清理

三个 soak session 在脱敏 evidence 生成后通过正式 `DELETE /api/v1/sessions/{sid}?confirm=true` 清理：

- active session JSON 已删除；
- event-log sidecar 已删除；
- `.identity/<sid>.json` 删除 tombstone 按 SessionStore 设计保留，防 SID 复用；
- `shared_current_session.json` 删除前后 byte-identical，未改变用户共享当前会话。

## 8. Detached clean checkout

R8.3 candidate commit 在 detached clean worktree 中复验：

```text
focused 145/145: PASS
pyright: 0 errors / 0 warnings
py_compile: PASS
current 9/9 inventory reproduction: PASS
R0 canonical relative-path reproduction: PASS / 0-byte
status before/after: clean
```

首次 clean R0 验证若使用绝对 `--data-dir/--out-dir`，只会让 `baseline-manifest.json` 的 path 字符串变为绝对路径；`baseline.jsonl`、fixtures、report 和四个 R0 gate 均未变化。改回 canonical 相对路径（临时 Git-ignored `data` symlink，只读指向 frozen runtime data）后，manifest 也恢复 byte-identical。该现象是验证命令路径语义，不是 R0 内容漂移。

## 8. Gate 判定

| Gate | Result |
|---|---|
| metadata complete 9/9 | PASS |
| unknown=0 / registry non-degraded | PASS |
| strong + weak live primary | PASS |
| long-history live primary | PASS |
| mode=shadow 100% | PASS |
| applied=false 100% | PASS |
| attribution matches ModelSpec 100% | PASS |
| profile churn=0 | PASS |
| unattributed primary attempt=0 | PASS |
| fallback exact attribution | PASS |
| err1210 retry attribution | PASS |
| capability-only payload byte identity | PASS |
| adjacent R2/R3/R4/R5/R6 focused 145/145 | PASS |
| R0 frozen 0-byte | PASS |

因此 **R8.3 PASS**。

这只把下一阶段从“metadata 尚未验证”推进为“可以设计小范围 behavior canary”。它**没有**授权：

- 全局应用 minimal/full；
- 修改 default shadow；
- 进入 R9 主区应用。

下一阶段如获 owner 明确指令，应单独立项 behavior canary，并用 session allowlist / 两端代表模型 / 明确 rollback 进行因果验证。
