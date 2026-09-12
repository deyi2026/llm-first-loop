# SMC Browser Phase 1 B-LIVE-PERCEPTION Result — 2026-09-13

> B-PERCEPTION baseline: `e9d3af6a0e2b6c310ad3abb142efb14b88acdd77`
> Live implementation: `37d195500a4264d767c8e24edf5437f4c8ef3a33` (`feat(smc): add live Browser perception host`)
> Browser under qualification: Google Chrome `152.0.7977.84`
> Status: **PARTIAL_PASS — persistent live read-only perception qualified; full-navigation document-generation remains NOT_QUALIFIED in the isolated headless CDP environment.**

## 1. 裁决

B-LIVE-PERCEPTION 已把 B-PERCEPTION 从 deterministic raw fixture 推进到**真实 Chrome DOM + Accessibility Tree 的 persistent read-only host**，但尚不能把 Browser Phase 1 live qualification 写成全绿。

准确结论：

- **factory opt-in activation: PASS**
- **persistent exact-target host: PASS**
- **real CDP DOM+AX capture: PASS**
- **same-document live churn / stable physical identity: PASS**
- **GroundingRef exact hydration across later world changes: PASS**
- **target disappearance → explicit failure / no silent rebind: PASS**
- **full navigation → document generation invalidation: NOT_QUALIFIED_HEADLESS_ENV**
- **overall B-LIVE-PERCEPTION: PARTIAL_PASS**

`PARTIAL_PASS` 不是“差一点可忽略”的 PASS。任何后续材料引用本轮 live 结果，都必须同时保留 navigation/document-generation 未资格这一限定。

## 2. 新增 live host 的边界

新增 `CdpReadOnlyBrowserHost`，只接受显式 opt-in：

```text
LFL_BROWSER_PERCEPTION_CDP_URL=http://127.0.0.1:<port>
LFL_BROWSER_PERCEPTION_TARGET_ID=<exact target id>
```

默认配置为空，因此默认**不注册** `browser_perceive`。

### 2.1 网络/目标边界

- debugger endpoint 必须为 loopback HTTP；
- target websocket 必须为 loopback WS；
- 配置 exact target 时只绑定该 target；
- target 消失后返回显式失败，**不寻找“另一个相似 tab”**；
- 未给 target_id 时，仅 endpoint 恰好只有一个 page target 才允许绑定；
- 同一 target 连续 observation 复用同一 persistent websocket；
- websocket identity 变化不自动重连到新 endpoint，要求显式重建 host。

### 2.2 Production CDP allowlist

生产 host 只允许：

```text
Target.getTargetInfo
Page.getFrameTree
DOMSnapshot.captureSnapshot
Accessibility.getFullAXTree
```

以下类别会在 session 层直接拒绝：

```text
Page.navigate
Runtime.evaluate
Input.*
```

因此 B-LIVE 没有把 navigation、JavaScript execution、mouse/keyboard input 偷渡进 `browser_perceive`。

### 2.3 模型面

模型可见工具仍严格只有：

```text
browser_perceive(action=snapshot)
browser_perceive(action=hydrate, grounding_ref=...)
```

没有 URL、CSS selector、XPath、坐标、CDP node id、AX index、script/code 或 mutation verb。

## 3. Live qualification 方法

本轮没有访问外部网站，也没有调用 LLM。

隔离 qualification harness 启动独立 Chrome headless + remote-debugging。由于该环境的 `Page.navigate` 在 page-level 与 browser-level flattened session 两条路径均超时，harness 不修改 production host，而改用**独立控制连接的 `Runtime.evaluate`**只构造/扰动受控真实 DOM 世界；随后由 LFL factory 注册出的生产 `browser_perceive` 通过另一条 read-only target connection 做 observation。

这个分工刻意保持：

- qualification harness 可以改变测试世界；
- production host 只观察；
- harness mutation 不是 model-facing capability；
- production host 未获得任何 mutation method。

另外，系统现有 MCP Browser Runtime 做了独立 sanity check：新建临时 tab 后可正常导航到本机 LFL Web 登录页并取得真实 Accessibility snapshot；随后该临时 tab 已关闭。这证明机器整体 Browser Runtime 的 navigation/observation 能力正常，但**不能替代**本轮 production `CdpReadOnlyBrowserHost` 的 navigation qualification。

## 4. Live 已通过的机械事实

### 4.1 Factory opt-in

默认 `Settings` 下：

```text
browser_perceive: NOT_REGISTERED
```

显式 loopback CDP endpoint + exact target 后：

```text
browser_perceive: REGISTERED
surface: snapshot | hydrate
```

### 4.2 真实 DOM + AX

真实 Chrome observation 能生成：

- `smc.world_snapshot.v0.1`；
- SemanticObject；
- DOM+AX source fusion；
- canvas blind-spot；
- scope/grounding/completeness；
- exact hydration。

正式成功 run 首次 snapshot 返回 16 个 canonical objects；same-document churn 后返回 19 个 canonical objects。

### 4.3 Same-document churn

外部 harness 对同一真实 DOM node 执行：

- reorder/move；
- `aria-label` 事实修改；
- 新增同名 duplicate node。

随后 read-only host 观察到：

- 原物理 node Semantic ID 保持；
- duplicate 即使同名也得到不同 ID；
- document scope 不因 same-document DOM churn 改代；
- `content_sha256` 随真实 observation fact 改变；
- 世界不再变化时，重复 observation 的 `content_sha256` 恢复稳定。

### 4.4 Grounding

旧 snapshot 的 GroundingRef 在后续世界改变后仍水合到**原 snapshot 内容**，不会重新抓当前状态，也不会自动重绑相似节点。

### 4.5 Target disappearance

外部 harness 关闭 exact target 后，下一次 `snapshot` 返回 observation ERROR，内容明确包含：

```text
bound Browser target disappeared
no silent rebind
```

没有自动选择其它 tab。

## 5. Live 暴露并修复的两个真实-wire问题

### 5.1 `DOMSnapshot.Document.frameId` 是 StringIndex

Deterministic fixture 原先把 `frameId` 当 literal string；真实 Chrome `DOMSnapshot` 使用 `StringIndex`。

旧行为会把整数 index（例如 `2`）错误转为虚构 `frame:2` scope。

修复后：

- production parser 先通过 DOMSnapshot `strings[]` 解 StringIndex；
- 为已有 deterministic fixtures 保留 literal-string compatibility；
- top document DOM nodes 正确归 document scope。

对应测试先 RED 后 GREEN。

### 5.2 snapshot-local AX identity 导致 content hash 假漂移

真实 Accessibility tree 含没有 `backendDOMNodeId` 的 AX-only nodes（例如 InlineTextBox）。合同要求它们的 Semantic ID 为 snapshot-local，不能跨 snapshot 冒充稳定 physical identity。

旧 `content_sha256` 却直接包含这些每次新生成的 local Semantic ID，因此页面完全不变时 hash 仍漂移。

修复裁决：

- **模型面 snapshot-local Semantic ID 继续每 snapshot 改变**；
- 只在 `content_sha256` 的 hash basis 中，把 snapshot-local ID 映射成 deterministic content-local alias；
- 有机械 physical identity 的稳定 ID 不归一化，因此真实 replacement 仍能改变 hash。

新增对抗测试同时要求：

```text
snapshot-local Semantic ID: first != second
same mechanical observation content_sha256: first == second
```

已 GREEN。

## 6. 未通过项：full navigation / document generation

隔离 Chrome 152 remote-debugging 环境里：

- command-line 初始 URL 会出现在 `/json/list` metadata，但 `Page.getFrameTree` 与 DOM 仍停在 blank document；
- `/json/new?...` target metadata 同样不能证明页面实际加载；
- page-level `Page.navigate` 超时；
- browser-level `Target.attachToTarget(flatten=true)` 后 `Page.navigate` 也超时；
- 同环境 `Runtime.evaluate`、DOMSnapshot、AX observation 正常。

因此当前证据只能说明：

> 隔离 headless 环境的 navigation control path 不健康；不能据此宣称 production host 的 full-navigation generation 行为 PASS，也不能据此判定 SMC generation 设计失败。

本轮没有为了拿到绿色结果而：

- 在 production host 增加 hidden navigation；
- 自动重试 `Page.navigate`；
- 自动换 browser target；
- 用 URL 猜 document identity；
- 把系统 Browser Runtime 的导航结果冒充 production host 的资格结果。

要把本项升 PASS，需要下一轮获得一个**可由 exact production host 观察、同时由独立控制面可靠导航的 live target**，然后验证：page scope 保持、document generation 改代、旧 Semantic ID 失效、旧 GroundingRef 仍指向旧 snapshot。

## 7. TDD / deterministic qualification

B-LIVE direct tests：

```text
4 / 4 PASS
```

覆盖：

- default off + env opt-in；
- loopback-only；
- mutation CDP methods blocked；
- exact target persistence；
- no silent rebind；
- factory opt-in registration。

B-PERCEPTION direct 现为：

```text
45 / 45 PASS
```

新增 content-hash adversarial case 包含在内。

组合邻接：

```text
B-LIVE               4
B-PERCEPTION        45
B-SPEC              21
SMC core            15
schema-lazy         14
factory             19
arch guards         14
----------------------
total              132 / 132 PASS
```

## 8. Repository qualification

实现候选与 commit `37d19550...` 内容一致时：

```text
Ruff full: PASS
Env-pin: 538 test files / 0 violations
src Pyright: 0 errors / 0 warnings / 0 informations
pytest tier0: PASS
pytest xdist full: PASS
full ci_gate: exit 0
staged security: 7 / 7 files PASS
git diff --check: PASS
```

实现 commit hook 再次 security PASS。

## 9. Implementation identity

| File | SHA-256 |
|---|---|
| `src/llm_loop/browser/cdp_host.py` | `02f5dc6ed9086434d3a5dbaae1ea6ab101b14aeb4e4870520de98f6eb6fdbf5a` |
| `src/llm_loop/browser/perception.py` | `4eb06f7785072c67ed67c7510b97582708fdd99e816926a4dd16fd2fa7561d14` |
| `src/llm_loop/config.py` | `2e894b53241299bc35a1a9b00d83e4e31314458298ad727a1ead06f1ac067df9` |
| `src/llm_loop/factory.py` | `172e71126b0aafa72db35f1455b0c394d8dda23b75136ae21ac59f245ee94fff` |
| `src/llm_loop/tools/registry.py` | `8b0015eae4128b6ad4a72caddf4e45d847c240ba1f73b03c894b5bb2333027fc` |
| `tests/unit/test_smc_browser_live_perception_v01.py` | `8c0fdea5a973016589a9a7b5a99ac64978640de88c6ba409205d559fd74f2b19` |
| `tests/unit/test_smc_browser_perception_v01.py` | `f98ff8a6bb928ffe5bc9535b9038b42b9c9080199009044613a0bf5b56d34621` |

## 10. Non-claims

本轮**不**声称：

- Browser Phase 1 live qualification 全部通过；
- full navigation/document generation 已通过 production host live test；
- external website ecosystem 已通过；
- mutation/click/fill/select/navigate/scroll 已实现；
- vision-only actionability 已实现；
- native browser chrome/OS UI 已实现；
- `browser_perceive` 应默认开启。

本轮也没有：

- 调用 8901/LLM；
- 重启 8901/8903/Feishu；
- 把 legacy `playwright_exec/test` 暴露为新 SMC 模型面。

## 11. 下一道门

在进入 mutation 前，推荐先关闭唯一 live gap：**B-LIVE-NAVIGATION**。

要求不是给 `browser_perceive` 增加 navigate，而是找到/建立一个可靠的独立 Browser control plane，在 production host 只读观察的前提下机械证明：

```text
same page target
→ external full navigation
→ page scope stable
→ document generation increments
→ old semantic identities invalidated
→ old GroundingRef remains exact old snapshot
```

在这项 PASS 前，B-LIVE 保持 `PARTIAL_PASS`。
