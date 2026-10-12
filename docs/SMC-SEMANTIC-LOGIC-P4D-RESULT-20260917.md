# SMC Semantic Logic P4-D Deterministic Compiler Result — 2026-09-17

**Status: PASS — P4-D ONLY.**

P4-D 已按冻结协议完成 deterministic RED→GREEN。结论只限于：**P4 Arm-B typed minimal declaration 可以在隔离 qualification harness 中机械翻译为现有 Arm-A `BrowserSemanticExecuteTool.compile_request` 的完全等价 canonical SemanticAction，同时保留 exact-ref、stale/version、single-dispatch 前的 fail-closed 边界。**

这不是 P4-FCR、P4-LIVE 或 production authority 的资格结论。

## 身份

- P4 protocol anchor：`ff735cfac4c905e4c0de0bd7ce933b311eecea41`
- P4-D implementation anchor：`aed762f2c9596c9f07251e67783119bb076d80b5`
- implementation parent：`ff735cfac4c905e4c0de0bd7ce933b311eecea41`
- protocol SHA256：`d39a34053c9762ae6760e6bc65a43375ac6f4023966621963918890af78ab9f6`
- helper SHA256：`682829616f3d511518b2719753c4372972092c28c99fc61b26e15c93fb57fed5`
- test SHA256：`39c7ea518aaa735cad7e2b6730fe6aa828c89d7a72f5b7840e256c6e29355a48`

Implementation commit 精确只有两个 qualification 文件、`+407`：

```text
tools/semantic_logic/p4d_typed_compiler.py
tests/unit/test_smc_semantic_logic_p4d.py
```

没有修改 `src/`、Factory、production registry、Browser adapter、Runtime 或 provider-visible production surface。

## RED → GREEN

第一轮 pytest collection 暴露了一个**测试设计错误**：参数名 `request` 是 pytest 保留 fixture 名。它先被改成 `payload`，这次 collection failure 不作为 P4-D RED 证据。

修正测试设计后，真正 RED 收敛为单一原因：

```text
P4-D typed compiler helper is not implemented yet
```

冻结 protocol 的独立断言已通过；所有实现相关 case 都因为 `tools/semantic_logic/p4d_typed_compiler.py` 不存在而失败。

随后只新增 qualification-only helper。它：

1. 读取 frozen P4 protocol 的 Arm-B schema；
2. 严格验证 typed request 的 required fields / primitive type / minLength / enum；
3. 将模型已声明的 typed call 机械映射为 Arm-A `verb + target_ref + args`；
4. 委托现有 `BrowserSemanticExecuteTool.compile_request` 完成 exact hydrate 与 canonical SemanticAction 机械派生；
5. 不包含 execute/dispatch、Factory 注册、retry、recovery、target selection 或 completion logic。

GREEN：**19/19 PASS**。

## 五类正向 parity

P4-D 对以下五类 typed declaration 均证明：在**同一 exact observed ref 和相同 semantic values** 下，B 组产出的 canonical SemanticAction 与 A 组 `compile_request` **dict 全等**：

| Arm B declaration | Arm A canonical request |
|---|---|
| `browser_semantic_click(object_ref)` | `click + target_ref=object_ref + args={}` |
| `browser_semantic_fill(object_ref,text,mode)` | `fill + target_ref=object_ref + args={text,mode}` |
| `browser_semantic_select(object_ref,value)` | `select + target_ref=object_ref + args={value}` |
| `browser_semantic_scroll(object_ref,delta_pages)` | `scroll + target_ref=object_ref + args={delta_pages}` |
| `browser_semantic_navigate(resource_ref,url)` | `navigate + target_ref=resource_ref + args={url}` |

因此 `schema/domain/scope_ref/target_id/expected_version/version_scope/operation_class/idempotency_class/atomicity_class/version_precondition/action_id` 等 authority-bearing mechanical fields 没有第二套 P4-D 语义实现；它们仍由已经资格化的现有 compiler 派生。

## Fail-closed / no-dispatch

确定性 adversarial cases 证明：

- resource ref 错用于 object action：reject；
- object GroundingRef 错用于 navigate：reject；
- cross-session ref：reject；
- malformed/non-grounding ref：reject；
- expired ref：reject；不 refresh、不 rebind；
- extra/missing fields、错误 enum/type、未冻结 tool 名称：reject；
- 所有 compile rejection 下 dispatch sentinel：**0**；
- 同一 typed declaration 重复 compile：canonical result 与 `action_id` 稳定一致。

P4-D 没有执行任何 Browser mutation。

## 隔离环境说明

fresh P4-D worktree 初始没有 gitignored 的 restricted-EYE `node_modules`，所以第一次相邻 P2-G1 回归统一报：

```text
pinned_backend_not_installed
```

这不是语义回归。P4-D 与已资格化 P3 worktree 的 validator `package-lock.json` SHA256 均为：

`83d2ee38f112bea8929751a5a2c31dede5aec07312eb696ce660537d288c71be`

在确认 lock 完全一致后，从已资格化 P3 环境复制同一 gitignored pinned validator dependency tree；**tracked tree 零变化**。随后 N3 邻接恢复全绿，没有跳过或放宽 Gate。

## Qualification

在 implementation anchor `aed762f2...` 上：

- P4-D focused：**19/19 PASS**
- P4-D + immediate adjacency：**64/64 PASS**
- Browser + P1 + P2 + P3 + P4-D combined：**394/394 PASS**
- Ruff：PASS
- `py_compile`：PASS
- helper/test Pyright：**0 errors / 0 warnings**
- `src` Pyright：**0 errors / 0 warnings**
- production typed compiler consumer：**0**
- whole-tree security：**2000 files PASS**
- full `scripts/ci_gate.sh`：**PASS**
- env-pin：**605 test files / 0 undeclared COMPACT_RATIO dependents**
- xdist：**全绿**

现有 41 个 test-side-effect review warnings 仍是仓库既有 nonblocking scanner 输出，不是 P4-D 新缺陷。

## Authority / non-effects

P4-D 没有改变四层权责：

- LLM 仍选择对象/资源、verb、semantic args、wait/re-observe 策略和 task completion；
- Compiler 只做 frozen typed declaration → existing canonical compiler 的机械翻译；
- Adapter 仍拥有物理 grounding / observation / actuation primitive；
- Runtime 仍拥有 permission、session/effect authority、reservation、duplicate fencing、physical dispatch、retry 与 durable receipt。

本阶段没有 model call、没有 Browser 物理 mutation、没有 production consumer/Factory wiring、没有 push/merge、没有部署、没有 Web/Feishu/8901 restart，也没有模型启动或切换。

## 裁决边界

**P4-D deterministic typed compiler parity：QUALIFIED。**

这只证明 B 组声明面可以在机械意义上无损编译到现有 A 组 canonical action。它**没有**证明模型在 B surface 上 First-Call-Ready 更好，也没有证明 full-task 成功率提升。

下一阶段 **P4-FCR 40-row declaration-only A/B** 仍为 `NOT_STARTED`。在进入任何模型调用前必须单独跨越阶段 checkpoint。

本 result docs commit 完成后会再次对 exact result HEAD 做 committed-state requalification；该 post-result 证据不回写本文件，以避免“写回结果 → 新 commit → 再验收”的递归身份循环。
