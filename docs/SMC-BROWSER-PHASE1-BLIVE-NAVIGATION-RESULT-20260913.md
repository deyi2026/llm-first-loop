# SMC Browser Phase 1 B-LIVE-NAVIGATION Result — 2026-09-13

> B-LIVE-PERCEPTION baseline: `e7609f850b598320d85639524705c8117cdfaeb5`
> Qualification implementation: `b32b359b4c5aaeb49fad6c9849140a831fd9612f` (`test(smc): qualify live Browser navigation`)
> Browser under qualification: Google Chrome `152.0.7977.84`
> Status: **PASS — same exact page target 的 full-document reload / document-generation 感知失效链已完成真实 live qualification。**

## 1. 裁决

B-LIVE-NAVIGATION 本轮关闭的是 B-LIVE-PERCEPTION 留下的一个窄而关键的未资格项：

> 同一个真实 page target 发生完整文档替换以后，LFL 的只读 Browser perception 是否会保持 page identity，同时改代 document generation，并使旧文档对象 identity 失效；旧 GroundingRef 是否仍能精确回到替换前 snapshot。

正式结论：**PASS**。

本轮真实 live 机械证明：

- exact page target 保持；
- page generation 保持；
- page scope_ref 保持；
- Chrome loader identity 真实改变；
- document generation 增加；
- document scope_ref 改代；
- 新文档中同名物理 DOM 对象没有继承旧 Semantic ID；
- 导航前旧 GroundingRef 在文档替换后仍精确 hydrate 旧 snapshot/object；
- production `CdpReadOnlyBrowserHost` 仍绑定 exact target；
- production Browser 模型面仍只有 `snapshot | hydrate`；
- qualification Chrome 使用 mock keychain，不再触发 macOS SecurityAgent。

## 2. PASS 的准确范围

这里的 `B-LIVE-NAVIGATION = PASS` 指：

```text
same exact page target
    -> external full-document reload
    -> loader/document identity changes
    -> read-only production perception observes new generation
    -> old generation-bound identity is not reused
    -> old GroundingRef still hydrates old immutable snapshot
```

它**不等于**：

- 模型已经获得 `navigate`；
- SMC Browser mutation 已实现；
- cross-URL `Page.navigate` dispatch 已资格；
- click/fill/select/scroll 已资格；
- arbitrary JavaScript execution 已进入 production surface。

尤其是 raw remote-debugging 环境中的 cross-URL `Page.navigate` 仍保留：

```text
NOT_QUALIFIED
```

本轮没有为了把这个环境行为刷绿而把 navigation/retry/rebind 逻辑塞入 production host。

## 3. Control plane 与 production plane 分离

本轮新增的是 qualification-only harness：

```text
scripts/qualification/smc_browser_live_navigation.py
```

它位于 `scripts/qualification/`，并有机器测试保证 `src/llm_loop` 不 import 它。

### 3.1 Qualification control plane

隔离 harness 可以对**测试专用 Chrome**执行：

```text
Runtime.evaluate   # 仅构造受控测试 DOM
Page.reload        # 触发完整文档替换
```

这些能力仅用于资格实验，不注册进 ToolRegistry，不进入模型 schema。

### 3.2 Production perception plane

production `CdpReadOnlyBrowserHost` 仍只允许：

```text
Target.getTargetInfo
Page.getFrameTree
DOMSnapshot.captureSnapshot
Accessibility.getFullAXTree
```

既有模型工具仍只有：

```text
browser_perceive(action=snapshot)
browser_perceive(action=hydrate, grounding_ref=...)
```

并且测试显式锁住以下方法必须被 read-only session 拒绝：

```text
Page.navigate
Page.reload
Runtime.evaluate
Input.dispatchMouseEvent
```

因此 qualification control plane 没有泄漏成 production/model mutation surface。

## 4. 正式 live qualification 方法

formal harness 使用一个隔离 Chrome `152.0.7977.84`：

```text
--headless=new
--remote-debugging-port=<ephemeral loopback port>
--user-data-dir=<ephemeral profile>
--use-mock-keychain
--password-store=basic
```

流程：

1. 取得唯一 exact page target；
2. qualification controller 在该 target 构造一个名为 `Same Name` 的真实 DOM button；
3. production `CdpReadOnlyBrowserHost` 用**另一条只读 websocket**捕获 DOM+AX；
4. `BrowserPerceptionAdapter` 生成第一份 canonical snapshot；
5. harness 用 `Page.reload` 触发真实完整文档替换；
6. 等待 main-frame loaderId 发生机械变化；
7. harness 在新文档再次构造同名 DOM button；
8. production read-only host 再次 observation；
9. adapter 生成第二份 canonical snapshot；
10. 用第一份对象的旧 GroundingRef 在第二份 snapshot 之后 hydrate；
11. `evaluate_navigation()` 只比较 generation/identity/grounding 的机械事实。

整个 formal live run：

- 不访问外部网站；
- 不调用 LLM；
- 不调用 8901；
- 不重启 8901/8903/Feishu；
- 不修改用户正常 Chrome tab；
- 不把 qualification mutation 注册给模型。

## 5. Formal live result

privacy-safe formal result SHA-256：

```text
81168752968887f26dbb741033bf97d6fcbea25730a79d3d8da4e09f9edf0c80
```

### 5.1 Generation / identity / grounding

| Check | Result |
|---|---|
| same exact target | PASS |
| page generation preserved | PASS |
| page scope preserved | PASS |
| loader changed | PASS |
| document generation incremented | PASS |
| document scope changed | PASS |
| same-name identity invalidated | PASS |
| old grounding exact after reload | PASS |

### 5.2 Safety

| Check | Result |
|---|---|
| mock keychain enabled | PASS |
| basic password store enabled | PASS |
| SecurityAgent not spawned | PASS |
| production host exact target bound | PASS |

全部 12 项均为 PASS。

## 6. Live 暴露的资格脚本身份问题

正式 live 首次尝试没有进入 reload 阶段，因为 qualification helper 错误假设：

```text
Same Name 必须只对应一个 canonical object
```

真实 Chrome DOM+AX 实际生成了三个同名 card，其 grounding identity 分别是：

```text
snapshot_local_ax_identity
dom_physical_identity
ax_backend_physical_identity
```

这证明**名称/role 不是 identity**。

修复只发生在 qualification harness：

- 遍历候选对象的 exact GroundingRef；
- hydrate persisted mechanical grounding；
- 仅选择唯一 `identity_basis=dom_physical_identity` 的对象；
- before/after evaluator 使用显式 object id；
- 不把 `identity_basis` 塞进模型 schema；
- 不修改 production adapter 的对象融合逻辑。

修正后正式 live PASS。

## 7. macOS Keychain 安全事件与修正

探索阶段使用 fresh Chrome profile 时曾触发 macOS：

```text
找不到用于储存“Chrome”的钥匙串
```

处理边界：

- 立即暂停 Browser qualification；
- 只关闭本轮测试 Chrome 实例；
- SecurityAgent 只选择“取消”，没有选择“还原为默认”；
- 用户确认弹窗已消失；
- 用户正常 Chrome Browser Runtime / tabs 保持在线。

之后新增两层防回归：

1. formal runner 固定 `--use-mock-keychain --password-store=basic`；
2. 单测要求这两个参数必须存在。

独立安全探针与正式 live run 均确认：

```text
security_agent_not_spawned = PASS
```

## 8. Deterministic / adjacent qualification

新增 B-LIVE-NAV direct tests：

```text
4 / 4 PASS
```

覆盖：

- generation/identity/grounding evaluator positive；
- document generation / identity reuse negative case；
- qualification control plane 不得被 production import；
- qualification Chrome 必须使用 mock keychain/basic password store。

与既有 B-LIVE-PERCEPTION direct 合计：

```text
8 / 8 PASS
```

组合邻接：

```text
B-LIVE-NAVIGATION     4
B-LIVE-PERCEPTION     4
B-PERCEPTION         45
B-SPEC               21
SMC core             15
schema-lazy          14
factory              19
arch guards          14
-----------------------
total               136 / 136 PASS
```

## 9. Static / repository qualification

预提交候选：

```text
Ruff touched: PASS
py_compile: PASS
new script + navigation test Pyright: 0 errors / 0 warnings / 0 informations
git diff --check: PASS
privacy: PASS
git security scan: 3 files PASS
```

`test_smc_browser_live_perception_v01.py` 若单独纳入 Pyright，会在既有 mock monkeypatch 行出现 1 个 `assert_called_once_with` 类型错误；对 committed parent `e7609f85` 原文件使用同一命令可复现完全相同的 1 error，因此本轮新增类型错误为 0。仓库正式门禁只检查 `src` Pyright，仍为 0/0/0。

完整仓库门：

```text
Ruff full: PASS
Env-pin: 539 test files / 0 violations
src Pyright: 0 errors / 0 warnings / 0 informations
pytest tier0: PASS
pytest xdist full: PASS
full ci_gate: exit 0
```

## 10. Implementation identity

Qualification commit：

```text
b32b359b4c5aaeb49fad6c9849140a831fd9612f
```

Parent：

```text
e7609f850b598320d85639524705c8117cdfaeb5
```

| File | SHA-256 |
|---|---|
| `scripts/qualification/smc_browser_live_navigation.py` | `f78e75f4c0266362c58c86b5242447443efa8c5a24ec85b60d57d8db4a019b94` |
| `tests/unit/test_smc_browser_live_navigation_v01.py` | `5e61cdd08ee450392badadbac607045c64d45bf22b6f77d8654e1566b99db820` |
| `tests/unit/test_smc_browser_live_perception_v01.py` | `8fc9a52a7225fe2d7798f779a0248b7e18a921af76c0fac603431951a92cdb09` |

本提交不修改 production `src/llm_loop`。

## 11. 对上一阶段 PARTIAL_PASS 的影响

`B-LIVE-PERCEPTION` 的原结果保留不改；它在当时正确记录：

```text
full-navigation document-generation = NOT_QUALIFIED
overall = PARTIAL_PASS
```

本轮新证据提供了**后续独立资格**：

> same-target full-document replacement 后的 perception generation / identity / grounding 语义现在已 live PASS。

因此当前阶段状态应写为：

```text
B-LIVE-PERCEPTION: historical PARTIAL_PASS（原报告不改写）
B-LIVE-NAVIGATION generation qualification: PASS
cross-URL Page.navigate dispatch: NOT_QUALIFIED
Browser mutation conformance: NOT_STARTED
```

这避免用新结果倒改旧实验，也避免把 perception 资格外推到 mutation。

## 12. 下一道门

本轮完成后，最合理的下一阶段不是直接开放 click/fill/navigate，而是继续沿只读链推进：

```text
live WorldSnapshot
  -> SemanticDiff
  -> Predicate / wait
  -> version/staleness pressure
  -> 再考虑 mutation dispatch + ActionReceipt
```

下一阶段开始前，应继续维持：

- Browser mutation model surface = disabled；
- automatic protocol retry = disabled_v0.1；
- program 只报告机械事实，不替模型选择目标/动作；
- cross-URL Page.navigate 不得因为本轮 generation PASS 被写成已资格。
