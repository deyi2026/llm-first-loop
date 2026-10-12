# SMC v0.1 Conformance Baseline — 2026-09-12

> 合同：`docs/SMC-CONTRACT-v0.1.md`
> 基线代码：`226a9010143013bf085a6c2b681910332a0f4aac`
> 分支：`feature/smc-contract-v0.1-20260912`
> 性质：**观察性基线**。本报告记录当前实现与合同之间的距离，不为追求全绿修改 SMX frozen implementation。

---

## 1. 总结

本轮把 SMC v0.1 的首批机械探针落到了真实现行 API/CLI 上：

- R1 / Domain-0：P0–P8；
- R2 / LFL precedents：L1–L5；
- R3 / Browser：本轮未实现，也不伪装成 implementation conformance。

结果：

| 层 | PASS | GAP | FAIL | NOT_APPLICABLE |
|---|---:|---:|---:|---:|
| R1 / SMX P0–P8 | 3 | 6 | 0 | 0 |
| R2 / LFL L1–L5 | 5 | 0 | 0 | 0 |
| 合计 | **8** | **6** | **0** | **0** |

这里的 `GAP` 不是测试失败，而是：**合同要求已经明确，但当前 pre-contract implementation 尚未提供相应 canonical capability / wire fact。**

本轮最重要的结论不是“SMX 只有 3 项 PASS”，而是：

> **SMX 已经稳定证明了 Domain-0 的若干关键机制（完整 diff 的正向忠实、盲区显式、running 非终态）；同时新合同成功暴露了 6 组此前容易被“功能可用”掩盖的 epistemic / identity / wire gaps。**

这正是 SMC conformance 的用途：不让工程实现成熟度被误写成合同成熟度。

---

## 2. R1 — SMX Domain-0 实测矩阵

| Probe | 状态 | 实测事实 | 合同意义 |
|---|---|---|---|
| P0 contract surface | **GAP** | provider surface 只有 `wait/snapshot/diff/receipt`，无 command/cmd/exec/策略 key；但 snapshot 输出仍是 pre-SMC wire | Program Authority 静态面通过；canonical wire 尚未 conform |
| P1 complete diff fidelity | **PASS** | 完整双快照的 create/delete/modify 均真实出现于结构结果/显示行 | complete comparable snapshot-pair 的正向 diff 机制成立 |
| P2 incomplete diff fidelity | **GAP** | `created/deleted/total_changes=null`、± 行抑制已成立；但 `modified` 仍是未标注 lower-bound 的整数 | 06738a22 修复是正确但尚未完成字段级 completeness |
| P3 blind-spot honesty | **PASS** | missing root、budget truncation、注入式 EACCES/walk error 均显式出现 | “不可达 ≠ 空集”成立 |
| P4 Predicate honesty | **GAP** | satisfied / timeout / non-loopback gate 正常；但 observer error 仍折叠成 false，8MiB cap 后 negative 仍为 false，sampling facts 未结构化 | 三态、否定覆盖、polling semantics 尚未 conform |
| P5 hydrate + integrity | **GAP** | snapshot_id 能回到落盘 observation；模型面 snapshot 没有独立 content-integrity/version token | identity 可水合，但 immutable grounding integrity 尚缺 |
| P6 running honesty | **PASS** | CLI background 仍 running 时 `running=true`，note 明示，且无终态 diff | “进行中 ≠ 已完成”成立 |
| P7 diff comparability | **GAP** | 两张不同 roots 的 snapshot 可直接 diff，并被解释成 create/delete；无 `comparable/scope_relation` | scope change 仍可能伪装成 world change |
| P8 canonical vs raw hydrate | **GAP** | 截断 run 的 raw CLI receipt 仍含 numeric counts；`receipt(full=true)` 原样暴露且无 `canonical=false` | raw grounding 可绕过 canonical completeness 纪律 |

### P0 — 结构面通过，但 canonical wire 未开始

机械检查确认：当前模型面没有把 SMX `exec/bg/collect` 暗中塞进 `smx_perceive`，也没有 `recommended_action / best_candidate / priority / completion` 一类已知策略字段。

这支持原先的安全裁决：

> `smx_perceive` 仍是感知面；世界修改执行继续走 LFL 的现行安全执行通道。

但当前 payload 仍使用：

- `schema: 1`
- `snapshot_id`
- `entries`
- `roots_meta`
- `store_path`
- `smx_sha`

而不是 SMC v0.1 的 self-describing `schema/domain/scope/completeness/projection/grounding_version`。因此状态必须是 `GAP`，不能因为行为接近就算 wire PASS。

### P1 — complete diff 正向语义稳定

同一 root 的完整快照前后制造：

- 新文件；
- 删除文件；
- 文件内容/大小变化。

当前实现正确返回 create/delete/modify 事实，且显示行与真实路径变化一致。

这证明 Domain-0 的 snapshot-pair net diff 在**完整、可比场景**下已经是可靠机制。

### P2 — 完整性纪律已经进步，但只完成一半

用 111 条目与 budget=100 复刻截断场景：

- `diff_complete=false`；
- `created=null`；
- `deleted=null`；
- `total_changes=null`；
- `+/-` 显示行被抑制。

这些都证明 06738a22 的修复方向正确。

剩余 GAP：

```text
modified = len(d["modified"])
```

在一侧不完整时，这个数字可以代表“真实观察到的 modified 下界”，但不一定 exhaustive。当前 payload 没有：

```text
field_completeness.modified = false
```

所以它还不满足 SMC 的字段级完整性纪律。

### P3 — blind-spot honesty 已经成立

本轮分别验证：

1. root 不存在 → `note=not_found`；
2. budget 不足 → `truncated=true`；
3. `os.scandir` 机械注入 `EACCES` → `walk_errors` 显式出现。

没有出现“观察失败后返回空集合，模型误以为什么都没有”的行为。

### P4 — Predicate 是下一批最值得修的合同面

已有正确行为：

- `file_exists` 满足 → `satisfied=true`；
- 有效 polling 到 deadline 仍未命中 → `satisfied=false`，工具调用本身仍成功；
- non-loopback `port_open` → 安全拒绝。

三个真实 GAP：

1. **observer error 与 false 混合**：对目录做 `file_contains` 产生读取错误，但最终仍 `satisfied=false`；
2. **partial negative 与 false 混合**：目标文本放在 `FC_CAP=8MiB` 之后，detail 已写 `capped ... 尾部未检`，但最终仍 `satisfied=false`；
3. **sampling semantics 不结构化**：回执没有统一 `evaluation_mode / interval / sample_count / observer_error_count`。

因此当前 wait 很好用，但还不能说 SMC Predicate honesty 已通过。

### P5 — hydrate 可达，但 grounding integrity 不足

当前 `snapshot_id` 可以：

- 定位 `.json` 快照；
- 重新读取相同 observation。

但模型面 snapshot payload / stored doc 没有独立内容 integrity token，例如：

- `snapshot_sha256`
- `content_sha256`
- `grounding_version`

CLI 的 `smx.py::write_snapshot` 已有 sha12，但不能把 CLI 能力冒充成模型面已经具备。

### P6 — running / terminal 边界正确

真实启动短后台进程后立即 collect：

```text
running=true
note=进程仍在运行；稍后再次 collect。未取 diff...
```

回执没有终态 diff。这条可以正式记 PASS。

### P7 — diff 必须先证明可比

建立两个完全不同 root：

```text
left/left.txt
right/right.txt
```

分别 snapshot 后请求 `diff(left, right)`，当前实现：

- `diff_complete=true`；
- 把 left 内容当 deleted；
- 把 right 内容当 created；
- 没有 `comparable`；
- 没有 `scope_relation`。

这对 Browser Phase 1 尤其关键：页面跳转、iframe 切换、多 tab 切换都不能被解释成“上一屏全部 deleted + 下一屏全部 created”。

### P8 — raw 回验不能穿透 canonical 纪律

CLI 在截断场景仍保存：

```text
diff.counts.created/deleted/modified
changed.json
scope.truncated_any=true
```

随后模型面：

```text
smx_perceive(action=receipt, full=true)
```

会把 raw receipt 原样返回，没有 `canonical=false` 区分。

所以当前状态是：

> raw grounding 可取是优点；但 raw grounding 与 canonical SMC interpretation 尚未分层。

---

## 3. R2 — LFL Cross-domain Precedent Anchors

R2 不宣称“LFL 文件域已经是 SMC adapter”。它只验证 SMC 抽象并非 Browser 特化想象，而是已经有可工作的同构机制。

| Anchor | 状态 | 实测事实 | 对 SMC 的意义 |
|---|---|---|---|
| L1 EvidenceRef hydration | **PASS** | 精确 range hydration + `next_start` + `blob_sha256` + `range_sha256` | GroundingRef / projection / integrity 已有成熟先例 |
| L2 file expected version | **PASS** | 即使文件 size/mtime 伪装相同，只要完整 bytes 已变仍 `VersionConflict`，且不覆盖当前内容 | 乐观并发不是纸面概念 |
| L3 model-authored synopsis | **PASS** | summary verbatim 保存；绑定 source SHA/range；`task_applicability=not_evaluated` | 程序存取事实、模型拥有语义解释的先例 |
| L4 evidence currentness | **PASS** | stale 显式；默认阻断历史正文；`allow_stale=true` 才显式读取；task applicability 仍由模型判断 | 时效与任务适用性可拆开 |
| L5 explicit incompleteness | **PASS** | 部分读取 `complete=false + next_start`；不存在 ref 显式失败 | 不完整/不可用不静默 |

R2 的结果支持一个重要判断：

> SMC v0.1 的 GroundingRef、版本前置、projection completeness、currentness/applicability 分离并不是为了 SMX 强行发明的新抽象；它们已经在 LFL 其它机械域里证明可实现。

---

## 4. 当前合同 G1–G16 与本轮探针覆盖关系

P0–P8 并不声称一次测完全部 G1–G16。

### 已被本轮直接机械化的 GAP

| Contract GAP | 对应 probe |
|---|---|
| G6 模型面 snapshot 无内容 integrity token | P5 |
| G7 Predicate observer error 无三态 | P4 |
| G9 diff scope comparability 缺失 | P7 |
| G10 canonical SemanticDiff wire 尚未 conform | P0 |
| G12 Predicate sampling facts 缺失 | P4 |
| G13 partial coverage negative 仍当 false | P4 |
| G14 modified lower-bound 无 field completeness | P2 |
| G15 observation vs projection 尚未 canonical 分层 | P0 |
| G16 raw receipt hydrate 可绕 canonical diff | P8 |

### 本轮未冒充已验证的合同面

以下仍保留在合同 §6，不因为没写 probe 就视为不存在：

- G1 physical object identity continuity；
- G2 canonical SemanticAction mutation wire；
- G3 object-level multi-sensor coverage；
- G4 high-frequency stale/identity pressure；
- G5 spatial relations；
- G8 async receipt append-only history；
- G11 model-facing `diff_semantics`。

其中 G1/G2/G3/G4/G5 很大程度上要到 Browser Phase 1/2 才能真正施压；G8/G11 可以在后续 SMC-ADAPT-SMX 机械补齐。

---

## 5. 实验冻结治理事实

SMC conformance 与 SMX focused A/B 必须分线处理。

当前三项 SMX 核心文件仍与 **SMX focused v1.1 30-run** frozen spec 一致：

- `tools/smx/smx.py`
- `src/llm_loop/tools/builtin/smx_perceive.py`
- `src/llm_loop/tools/registry.py`

但当前 convergence `226a9010` 已修改：

```text
evals/pilot/analyze.py
```

它同样属于 SMX focused v1.1 的 18 个 `source_sha256` frozen files。因此：

> **当前 convergence HEAD 不可直接执行并称为原 frozen SMX focused v1.1 30-run。**

以后只有两条诚实路径：

1. 原 v1.1：从精确 frozen worktree/revision 运行，并在首个模型请求前验证全部 source hashes + plan hash；
2. 当前 convergence：重新冻结成新的 SMX focused protocol version，再运行新矩阵。

本轮没有运行任何模型，也没有运行 SMX 30-run。

---

## 6. 验证记录

### 新探针

```text
tests/unit/test_smc_contract_v01_conformance.py
15 / 15 PASS
```

15 个 pytest case = 14 个 P0–P8/L1–L5 参数化 probe + 1 个完整矩阵复算。

### 邻接回归

组合执行：

```text
tests/test_smx_perceive.py
tests/unit/test_evidence_phase8.py
tests/unit/test_file_service_versioning.py
tests/unit/test_source_synopsis.py
tests/unit/test_smc_contract_v01_conformance.py

61 / 61 PASS
```

### 探针静态质量

```text
Ruff: PASS
py_compile: PASS
Pyright: 0 errors / 0 warnings / 0 informations
```

### Whole-tree security

```text
bash scripts/git_security_scan.sh --tree
PASS — 1613 tracked files
```

### Full repository gate

```text
bash scripts/ci_gate.sh
exit 0

Ruff full gate: PASS
env-pin: 535 test files scanned / 0 undeclared COMPACT_RATIO dependents
src Pyright: 0 errors / 0 warnings / 0 informations
tier0: PASS
xdist full suite: PASS
```

上述测试均不调用 8901，不依赖外部模型。

---

## 7. 准入裁决

### SMC Contract v0.1

**准入：可以进入独立 docs commit 候选。**

原因：

- 合同已经能在真实 Domain-0 中产生有区分度的 PASS/GAP，而不是所有实现都能“解释成符合”；
- R2 证明关键抽象已有跨域工程先例；
- 合同没有为了让 SMX 过线而弱化 Predicate / Grounding / Diff / Identity 纪律。

### 当前 SMX 作为 `smc-perception-v0.1`

**准入：NOT YET CONFORMANT；保持 pre-contract / experimental adapter。**

但它已经有足够好的机械基础进入后续 `SMC-ADAPT-SMX`：

- complete diff fidelity 已工作；
- blind-spot honesty 已工作；
- running honesty 已工作；
- 核心安全边界没有倒退成第二执行通道。

真正阻止它宣称 conformant 的不是“功能不够多”，而是：

- canonical schema；
- grounding integrity；
- Predicate epistemic honesty；
- diff comparability / semantics；
- raw/canonical 分层。

### SMC-ADAPT-SMX

**现在不实施。**

原因不是技术阻塞，而是实验治理：修改 `smx.py` / `smx_perceive.py` 会改变 SMX focused treatment。必须先完成/放弃原 frozen A/B，或显式 re-freeze 新协议版本。

### Browser Phase 1

**设计准备可以继续；实现不应抢在 Contract + Domain-0 probe baseline 收口之前。**

Browser Phase 1 的第一批实现测试应优先打在 Domain-0 无法证明的地方：

1. stable Semantic ID 与 ambiguity；
2. `scope_ref` / multi-tab identity；
3. action dispatch 前 TOCTOU / expected version；
4. canonical ActionReceipt revision；
5. DOM/AX coverage conflict；
6. navigation/scope-change diff comparability。

这比继续给 SMX 增加更多 shell predicate 更符合 Semantic Manipulation Framework 的主目标。

## Revision provenance

- The first uncommitted `docs/SMC-CONTRACT-v0.1.md` draft contained 338 lines.
- Adversarial contract review expanded the normative contract to the committed 515-line form (`docs(smc): define semantic manipulation contract v0.1`).
- A later 516-line untracked copy in the main worktree was mechanically compared with the committed form: after trimming trailing newlines the contents were identical; the only difference was one extra EOF newline. That untracked duplicate was deleted before convergence integration.
- This history is provenance only; the 338-line draft is not reconstructed or treated as a competing normative contract.
