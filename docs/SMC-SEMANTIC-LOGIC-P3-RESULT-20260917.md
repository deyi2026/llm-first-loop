# SMC Semantic Logic P3 Shadow Qualification Result — 2026-09-17

## 结论

**P3 Shadow Qualification：PASS。**

- Formal-main 基线：`ddd108a2e05897cf4d72cd920e1d7c00a5786a7e`
- Fresh P0–P2 replay：`dc344a1669cfa1954019e6677bceba7701c54db3`
- P3 qualification anchor：`1891c7e1b2959abfdeb9a064e54916de26c54c1a`
- P2 RulePack：`5809347c62aa8a8b1856eff1bab0f11b9d98a57b0aedaef103e8ee2470f776a3`
- Machine result JSON SHA256：`51d5a3dd90d73d27c83a2394d625f76f8a8fb9e3770f554fc3e7882b1f4acb0a`

P3 保持 **shadow-only**：Semantic Logic 没有 production consumer，没有 Factory/runtime wiring，没有改变 provider-visible surface，也没有取得 dispatch、retry、admission、task/goal completion 或 mutation authority。

## Fresh-main 重建资格

P0–P2 的 21 个 SMC commits 已从正式 `lfl/main@ddd108a2` fresh replay。强树证明：P2 的 56 个路径与旧资格树字节一致，同时 current-main-only 的 28 个路径保持 main 字节不变。

Fresh replay 资格：

- P1/P2 broad：**252/252 PASS**
- 可精确重建的 Browser/P1 + P2 focused：**298/298 PASS**
- production Semantic Logic consumer：**0**
- Ruff / Pyright / syntax / diff / security：PASS
- fresh replay full `scripts/ci_gate.sh`：PASS，env-pin **603 / 0**，xdist 全绿

历史 P2 报告记录过 expanded adjacency **299/299**，但没有冻结那一轮 exact command / 第 299 项 identity。本轮没有伪造这一项，而是重跑可机械重建的 298 项，并在 P3 实现后使用更强的 **375/375** 联合回归覆盖。

## P3 Shadow 结果

- cases：**14/14 equivalent**
- false closure：**0**
- silent rebind：**0**
- unknown → false collapse：**0**
- proof coverage：**100%**
- 每个 case：`oracle_result_hash == shadow_result_hash`
- mismatch paths：全部为空

| Fixture | Gate | 类别 | Verdict | Oracle/Shadow SHA256 | Derivation rules |
| --- | --- | --- | --- | --- | --- |
| `P3-grounding-exact-compile` | `P3-GROUNDING-01` | grounding | PASS | `4cc806f25d2e7a35e08f4ec29fd17f3db86d9485610cc682d4db2fc370b339fa` | browser.action.fixed-contract@0.1<br>browser.grounding.exact-binding@0.1 |
| `P3-reorder-object-continuity` | `P3-VERSION-REORDER` | reorder | PASS | `a1bc5c2d4c2787238c720f79ad7d63cdf4dbcf22772d8eacc93f47fbd6777b42` | core.version.assess-precondition@0.1 |
| `P3-replacement-no-rebind` | `P3-VERSION-REPLACEMENT` | replacement | PASS | `dfa21e2ad397e0755984085e6739447a2d2f96798b29063ab75d41ecb12c6ee7` | core.version.assess-precondition@0.1 |
| `P3-duplicate-identity-no-fusion` | `P3-IDENTITY-AMBIGUOUS` | duplicate_identity | PASS | `2618be3510fe68390079673cbcd71feb53aa88b7ce644460bc5f7715a64a4a41` | core.identity.ambiguity-no-fusion@0.1 |
| `P3-navigation-document-generation` | `P3-VERSION-NAVIGATION` | navigation | PASS | `1eec75357b07c3dda759d3833f915e271a2b620856c243948c1dbd8081a0eea9` | core.version.assess-precondition@0.1 |
| `P3-frame-generation-no-continuity` | `P3-SCOPE-FRAME-GENERATION` | frame_generation | PASS | `6d9632ebbdf0a38f66c6ad8a0643b5eacc36b555090ef61c2c283e315c0cf449` | core.scope.target-relation@0.1 |
| `P3-dom-ax-conflict-unresolved` | `P3-CONFLICT-DOM-AX` | dom_ax_conflict | PASS | `592ca93757448cc01dda86b62f3dd49158a7ae88343f210b6ed079962fc92c40` | core.conflict.canonicalize-unresolved@0.1 |
| `P3-partial-coverage-absence` | `P3-PREDICATE-PARTIAL-ABSENCE` | partial_coverage | PASS | `865afe955b6d203ad94ae75b51a8eec089cb77a76b466ffc27ac8f313f4f6afb` | browser.predicate.evaluate@0.1 |
| `P3-virtualized-lower-bound-count` | `P3-PREDICATE-LOWER-BOUND` | virtualized_list | PASS | `485cdee8db609fdfd5e06b4b348afab6ecb7d6d39b908469fe0ba41bf557c30f` | browser.predicate.evaluate@0.1 |
| `P3-stale-grounding-expired` | `P3-GROUNDING-EXPIRED` | stale_ref | PASS | `c8d76e4d75f70c2f23941f4eeeb4d57d3f658a001d2bce9eda3d8fc4c393fcb2` | browser.grounding.exact-binding@0.1 |
| `P3-version-target-changed` | `P3-VERSION-MISMATCH` | version_mismatch | PASS | `18c107caf782efecb6845245ba9cdcabef95a50179066fef5106dd7de123dac3` | core.version.assess-precondition@0.1 |
| `P3-duplicate-action-single-dispatch` | `P3-RECEIPT-DUPLICATE` | non_idempotent_mutation | PASS | `bb88f28132b11fc024bf5fc8f8cd25245d863471ca397d1f12fd536a40ecba39` | core.receipt.validate-dispatch-invariants@0.1<br>core.receipt.validate-sequence@0.1 |
| `P3-receipt-running-terminal` | `P3-RECEIPT-REVISION` | receipt_revision | PASS | `bf83b9fa44770e8eb0b22fd60396c3534bbbfc0c6d1bdeb3f0b894abdd1ae832` | core.receipt.validate-dispatch-invariants@0.1<br>core.receipt.validate-sequence@0.1 |
| `P3-transport-ambiguity-no-retry` | `P3-RECEIPT-AMBIGUITY` | non_idempotent_mutation | PASS | `2e317cff12df2e823f4f43a4f19e054616c5f3d47a038354b8aa11353e385359` | core.receipt.validate-dispatch-invariants@0.1<br>core.receipt.validate-sequence@0.1 |

## 比较方法

P3 qualification helper 位于 `tools/semantic_logic/p3_shadow_qualification.py`，不在 production `src/llm_loop` 内。

每个 case 先调用当前 Browser production Python 机械 oracle 产生/读取 observation、version 或 receipt；随后仅将**同一批已经观察/持久化的事实**投影到 frozen P2 RulePack。Shadow 计算不会为了比较而重新抓取世界状态，也不会改变 native Browser 的结果。

比较面只允许 protocol 明确声明的 opaque runtime identity 字段退出 comparable hash。semantic values、reason code、completeness、version relation、receipt sequence/status 都不得被“归一化掉”。任何 mismatch 都是 RED。

## 覆盖面

14 个 deterministic case 覆盖：exact grounding、reorder、replacement、duplicate identity、navigation、frame generation、DOM/AX conflict、partial coverage、virtualized/lower-bound object count、expired stale GroundingRef、version mismatch、duplicate non-idempotent mutation、running→terminal receipt revision、transport ambiguity/no-retry。

## Qualification Gate

P3 implementation anchor `1891c7e1` committed-state：

- P3 focused：**4/4 PASS**
- Browser + P1 + P2 + P3 combined：**375/375 PASS**
- Ruff：PASS
- qualification helper/test Pyright：**0 errors / 0 warnings**
- `src` Pyright：**0 errors / 0 warnings**
- production Semantic Logic consumer：**0**
- whole-tree security：**1994 files PASS**
- full `scripts/ci_gate.sh`：PASS
- env-pin：**604 files / 0 undeclared**
- xdist：**全绿**

RESULT docs commit 后按协议对 exact result HEAD 再跑 committed-state 375 + static/security + full `ci_gate`。该 post-result 验收作为提交后的外部证据保留，不再回写本报告，否则会形成“写回结果 → 新 commit → 再验收”的递归身份循环；本文件因此固定记录 qualification anchor，而最终 result-HEAD 验收以同轮 committed-state Gate 回执为准。

## Authority / non-effects

仍维持四层权责：LLM 负责语义选择、策略与任务完成判断；Semantic Logic 只负责 deterministic bounded mechanical closure；Adapter 负责物理 observation/grounding/actuation primitives；Runtime 负责 permission/session/effect authority、reservation、duplicate fencing、physical dispatch、retry 与 durable receipt。

本阶段没有部署、没有重启 Web/Feishu/8901、没有启动或切换模型、没有合并 main、没有 P3 remote push，也不需要人工产品测试。

## 下一阶段边界

P3 到此只证明 **shadow equivalence**。下一阶段 **P4 Semantic Compiler A/B** 必须单独获得 owner 指令；P4 仍不等于 production authority。真正 selective authority cutover 从 P5 才开始，mutation precondition 仍应最后处理。
