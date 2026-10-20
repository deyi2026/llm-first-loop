# ASSESS: 方法池漏斗盘点（2026-10-21 实测）

- 日期：2026-10-21 ｜ 状态：实测盘点 ｜ 触发：用户指令（三项任务之三）
- 数据源：`data/methods/*/METHOD.md`（1290 张）、`data/methods/usage.jsonl`、各卡 `qualification.jsonl`
- 方法：glob + json 直接读盘，无口径转换；下列每个数字均可用 §7 脚本复现
- 与 `DESIGN-20261017-method-in-loop.md` 的关系：该文档 D2/D4 诊断成立，但本盘点发现一个**更上游**的事实（§5），会改变处置顺序

## 0. 结论

1. **不是漏斗窄，是三条流水线并联。** 生成（1290 张）、评估（68 张）、使用（42 张）三段几乎不相交：三者交集仅 7 张；1188 张（92.1%）既没被评估过也没被使用过。
2. **评估流水线在 2026-09-23 之后停摆。** 73 条 qualification 记录中 63 条集中在那一天（62 not_evaluated + 1 pass），此后仅在 10-12 补了 1 条；同期（10-12 至 10-20）卡片新增 440 张。生成是连续流，评估是一次性批处理，两者速率差一个数量级。
3. **`verdict=not_evaluated` 不等于“没评估”。** 9-23 那 62 条的 `mechanism`、`promotion`、`task_benefit` 三个字段全部为 `pass`，note 写着“qualify”；`verdict` 记 `not_evaluated` 的原因是 `evaluator: model`（自评、无独立证据）。真正的缺口是**证据等级**，不是评估动作。
4. **晋级与使用解耦。** 24 张已晋级卡（active 23 + qualified 1）中 22 张（91.7%）从未出现在 usage；反过来，42 张在用卡中 36 张（85.7%）仍是 `candidate`。准入判据没有约束执行路径。

## 1. 逐层实测

| 层 | 指标 | 实测值 |
|---|---|---|
| 生成 | 卡片总数 | **1290** |
| | status 分布 | candidate 1236 / hold 28 / active 23 / retired 2 / qualified 1 |
| | 有 created_at | 1287（3 张缺失） |
| | 10-12→10-20 新增 | **440**（约 49/天） |
| 评估 | 有 qualification.jsonl 的卡 | **68**（5.3%） |
| | 记录条数 | **73** |
| | verdict | not_evaluated 62 / pass 11 |
| | 三维字段 | mechanism/promotion/task_benefit 绝大多数为 pass（含 62 条 not_evaluated） |
| | evaluator | `model`（自评），未见独立评估器 |
| 使用 | usage 记录 | **54** |
| | 覆盖卡数 | **42**（3.3%） |
| | decision | applied 40 / adapted 8 / not_applicable 6 |
| | 使用时 method_status | candidate 47 / hold 4 / active 3 |
| | application_proven | True 48 / False 6 |
| 晋级 | active + qualified | **24** |

## 2. 时序：评估是一次性事件，不是流程

生成（created_at）：

```
10-12  25    10-16  32    10-20  42
10-13  85    10-17  65    10-21   9（当日未完）
10-14  60    10-18  44
10-15  50    10-19  37
```

qualification（ts）：

```
09-12   1 pass
09-17   4 pass
09-20   1 pass
09-23  62 not_evaluated + 1 pass   ← 单日 63 条
09-29   3 pass
10-12   1 pass                      ← 此后归零
```

usage（ts）：

```
10-12  2   10-16  9   10-19  5
10-13  2   10-17  8   10-20  6
10-14  1   10-18  4
```

**读法**：09-23 那天对存量卡做了一次批量“过一遍”，之后评估动作基本消失；而生成和使用都保持连续。用“漏斗太窄”描述会误导处置方向——真正的问题是**评估没有常驻**。

## 3. 字段语义修正：not_evaluated 的真实含义

`verdict=not_evaluated` 的一条样例：

```json
{"evaluator":"model","mechanism":"pass","promotion":"pass",
 "task_benefit":"pass","verdict":"not_evaluated",
 "note":"……qualify。","ts":"2026-09-23T15:57:39Z"}
```

三个判据维度都判 pass，唯独 `verdict` 记 not_evaluated。合理解释：`verdict` 是**证据等级**字段（要求独立评估），而 `evaluator: model` 不满足该等级，于是整体降级为“未评估”。

这个区分很重要：

- 若按 `verdict` 读 → “68 张卡只有 11 张过关”，结论是评估覆盖率太低；
- 若按三维字段读 → “68 张卡实质上都判了 pass，但全是自评”，结论是**准入缺独立验证**。

后者才是与 P3（准入资格）和 §7.3（禁止自评闭环）对得上的问题。`DESIGN-20261017` 里“verdict=not_evaluated 53/60”的表述应按此修正。

## 4. 交汇矩阵（最关键的一张表）

| 集合 | 张数 |
|---|---|
| 被使用 ∩ 有 qualification ∩ 是卡 | **7** |
| 只用过、无 qualification | 1（另有 1 条 usage 指向非卡对象） |
| 有 qualification、没用过 | **61** |
| 既没用过也没 qualification | **1188** |

被使用卡的状态分布：

| status | 张数 |
|---|---|
| candidate | 36 |
| hold | 3 |
| active | 1 |
| qualified | 1 |
| 非卡对象 | 1 |

有 qualification 的卡的状态分布：

| status | 张数 |
|---|---|
| candidate | 60 |
| hold | 5 |
| active | 2 |
| qualified | 1 |

**两条结论**：

1. 有 qualification 的 68 张里 60 张仍是 candidate —— 判了 pass 也没触发状态流转；
2. 在用的 42 张里 36 张是 candidate —— 执行路径根本不看准入状态。

也就是说：**准入状态对“会不会被用”没有解释力**。这解释了为什么 `DESIGN-20261017` 的 D2（评估与晋级语义割裂）在真机上表现为“改了也不动”。

## 5. 与 DESIGN-20261017 的差异

该文档把堵点定位在 D4（生成无准入，18 天 555→1156）与 D2（评估/晋级语义割裂），并提出 §9 的检索/可见性/排序改动。

本盘点同意这两条，但认为**顺序应当反过来**：

- 生成无准入之所以是问题，是因为**没有任何下游环节会消化它**；在评估停摆、使用不看准入的情况下，收紧生成的准入只会让库存增速变慢，不会让存量变好；
- 先恢复评估的**常驻性**和**证据等级**，再谈准入收紧，才可能改变分子而不只是分母。

## 6. 三个候选动作（按依赖排序，不并做）

**A. 题库重建（阻断项，必须先做）**
S0 与 PREREG-20261019b 的 M0 都指向同一件事：现有 held-out 题库上，原卡通过率 0.846–1.0，天花板压住了一切效应（S0 v1.3 D=28<30；M0 判 `M0_INSUFFICIENT_SENSITIVITY`）。在不换题库的前提下，任何预筛或准入实验都会得到“无差异”这个唯一结果。判据：先筛出 no_card 基线落在 0.3–0.6 的题，不足 N 题就扩库。

**B. 在用卡移除消融（Harness² 的库消融，可直接移植）**
对象取 42 张在用卡（而非 1290 张库存）。每张卡做 `给卡 vs 不给卡` 配对，题从 A 的新题库取。这是**唯一能回答“这些卡到底有没有用”的实验**，也是论文里被证明能检出差异的设计（它靠移除条目看分数是否下降）。成本：42 × 2 × 每题题数。

**C. 复活 qualification，但换证据源**
把 `evaluator: model` 换成外部判分器，`verdict` 才有资格从 not_evaluated 变成 pass/fail；同时给 `pass` 加一条状态流转规则（pass → active，或 pass → 指定观察期）。否则 B 的结论无处落地。

不建议现在做的：继续对 1290 张做批量 qualification（分母太大、题太简单、判据是自评，三重无效）；或按 `DESIGN-20261017` §9 继续调排序权重（在评估停摆下，排序只改变“先看到哪张卡”，不改变“卡有没有用”）。

## 7. 复现脚本

```python
import json,glob,os,collections,re
cards={}
for m in glob.glob("data/methods/*/METHOD.md"):
    c=os.path.basename(os.path.dirname(m))
    t=open(m,encoding="utf-8",errors="replace").read()[:3000]
    mm=re.search(r"^status:\s*(\S+)",t,re.M)
    cards[c]=mm.group(1) if mm else "<none>"
qcards={f.split("/")[2] for f in glob.glob("data/methods/*/qualification.jsonl")}
urecs=[json.loads(l) for l in open("data/methods/usage.jsonl") if l.strip()]
used={r["method_ref"].split("method:")[-1] for r in urecs if "method_ref" in r}
A,B,C=set(cards),used,qcards
print(len(A),len(B),len(C),"triple:",len(A&B&C),"neither:",len(A-B-C))
print(collections.Counter(cards.values()).most_common())
```

## 8. 数字口径声明

- 卡片总数以 `METHOD.md` 计数（1290）；`ls -d */` 曾得 1289，差 1 为目录/METHOD.md 不一致，以 METHOD.md 为准。
- usage 的 `method_ref` 有 1 条指向非卡对象，交叉统计时单列，未强行归并。
- `verdict` 与 `mechanism/promotion/task_benefit` 是两套字段，本盘点不合并二者，只指出语义差异。
