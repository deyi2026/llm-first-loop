---
method_id: scope-search-surface-before-scanning-large-workspace-8ab6d7e7de27
name: scope-search-surface-before-scanning-large-workspace
description: 在含多个大型 checkout 的工作区做内容检索前，先把检索面收敛到文档/元数据层，并对代码下钻限定子目录与文件名模式
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:4:b732016ee4384ffcad2d
evidence_refs: evidence://v1/1511954dba92506dc7ffcbe1744a5f6f0054056426cb1295713de48f53bc0e64
parent_ref: method:method-self-distill
created_at: 2026-10-21T23:11:34.080405+08:00
updated_at: 2026-10-21T23:11:34.080405+08:00
---
来源：2026-10-21 DeepInfer × research 对照任务中的真实摩擦（按 method:method-self-distill 六步蒸馏）。

## 1. Friction（最早扩散点）
在 `$HOME/Project/research` 上执行整树内容检索 `grep -ril "deepinfer" .`（排除 .git/node_modules），命令超过 60s 超时（execute_command 返回「执行超时」）。此前一次 `find . -maxdepth 2` 已经暴露出工作区含多个大型子项目（StateBraid/、FreeToken/、llama.cpp fork、.archive/），说明体量已知，却仍走了全树扫描。

## 2. Discriminator（当时已可见的事实）
顶层清单已显示存在大体量子目录（vendored/fork/build/archive）。可用判别事实：目标事实大概率在**文档与清单层**（`docs/`、`analysis/`、`design/`、`README.md`），代码层检索应下钻到具体子目录。knowledge-at-time 成立。

## 3. Counterfactual 最短可信路径
1) 列顶层清单（一次，已完成）；2) 改用 `search_files(root=<docs|analysis|design>, pattern='*.md', content=<kw>)` 之类的受限检索；3) 若文档层不足，再逐个下钻到具名子目录并用文件名模式限定；4) 取得权威事实后停止。

## 4. Generalize（只抽象一层）
对"在含多个大体积 checkout 的工作区里找 X"这类需求，**先把检索面收敛到文档/元数据层，不要对整棵树做内容全量扫描**；需要代码证据时，下钻到具名子目录 + 文件名模式。

## 5. Falsify（反例）
目标事实只存在于代码或构建产物里（例如"这个 llama.cpp fork 到底改了哪个函数"），文档层必然不足——此时必须下钻到代码子目录，但仍要限定范围，而不是整树。另一反例：工作区很小（<1k 文件），直接 grep 无成本。

## 6. Compress（Method Card）
```yaml
name: scope-search-surface-before-scanning-large-workspace
status: candidate
trigger:
  - 需要在含多个大型 checkout/构建产物的工作区做内容检索
discriminator:
  - 顶层清单是否已显示大体量子目录（vendored/fork/build/archive）
short_path:
  - 先列顶层清单
  - 只对文档/清单层（*.md、索引文件）做受限检索
  - 文档层不足时，下钻到具名子目录并用文件名模式限定
  - 取得权威事实即停
branch_on_evidence:
  - observation: 文档层已命中权威来源
    next: 停止检索，进入分析
  - observation: 文档层无命中且目标在代码里
    next: 下钻该子目录 + 文件名模式
stop_conditions:
  - 已从权威来源取得目标事实
verification:
  - 检索命令在 60s 内返回且结果可读
anti_patterns:
  - 未经范围收敛直接对整棵树 grep/find
counterexamples:
  - 工作区很小，直接 grep 无成本
  - 目标事实只存在于代码/构建产物中
programizable:
  - 默认对 content 检索加 root + 文件名 pattern 约束
model_owned:
  - 判断目标事实位于文档层还是代码层
why_shorter: 用已知体量把"整树扫描"先缩成"文档层检索 + 具名下钻"两个小面。
```
