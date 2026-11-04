---
method_id: pin-import-source-and-assert-module-file-before-trusting-equivalence-gre-c93b0e441b92
name: pin-import-source-and-assert-module-file-before-trusting-equivalence-green
description: 仓库存在同一源码树的多份完整副本（如 .releases/<sha>/、快照、vendored fork）时，靠 import 项目包做的新旧对拍/golden 等值验证可能静默加载镜像旧代码：全绿只是旧对旧的假绿。验证脚本第一步是把导入钉到工作树 src，并断言每个 arm 的 module.__file__ 实际路径；两 arm 必须落在不同树，否则比较无效。开局一次文件名检索/git status 已足以暴露副本存在，无需额外探测。
aliases: 对拍假绿 导入了镜像旧代码, 等值验证加载错源码树, sys.path 钉到 src 再对拍, 测试全绿但比的是旧对旧, release 快照目录污染 import, 断言 __file__ 再信绿
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80a9ad77-9a07-4f8b-9da4-49adb180bd96:920:24db346e23e7939d276e
evidence_refs: learning:learn:73719d3494c6
created_at: 2026-11-04T14:46:12.439898+08:00
updated_at: 2026-11-04T14:46:12.439898+08:00
---
## Trigger
在含多份完整源码树副本的仓库里，用临时脚本 import 项目包执行新旧实现对拍、golden 等值或行为回归验证，并准备采信“全等/全绿”结果时。

## Discriminator
开局可见事实：git status 或文件名检索已显示同一 src/<pkg>/... 路径存在 N 份版本化副本。副本存在 ⇒ import 解析到哪份树由 sys.path 顺序决定，而绿色回执不携带“加载了哪份树”的信息——绿不能自证加载的是新代码。

## Short path
- 盘点仓库时若见同一包路径多副本，把“验证脚本会导入哪份树”列为先决未知量
- 脚本开头 sys.path.insert(0, str(worktree/'src'))，把解析顺序钉到工作树
- import 后立即断言 module.__file__ 落在预期树内；新旧两 arm 各断一次，断言失败即证明本次绿无效
- 对拍两 arm 的 __file__ 必须指向不同树；若相同则判结果无效，修路径后重跑
- 断言全过后才执行等值比较并采信绿色

## Stop conditions
- 所有被比较模块的 __file__ 均解析到预期树，且新旧 arm 路径确实不同、比较完成
- 仓库确认只有单一源码树（无镜像副本），可直接采信普通 import 的结果

## Verification
- 采信任何绿色结果前，回显/断言全部被比较模块的 __file__ 实际路径
- 故意注入一个已知差异（改一行新实现），确认对拍会变红——证明比较真的加载了两份不同代码

## Counterexamples
- 仓库只有单一源码树、无任何版本化副本——路径钉住与断言是多余仪式
- 验证不经过 import（显式路径 subprocess、文件级哈希对比）——本方法不适用
- 镜像副本不含 __init__.py 且任何情况下都不可导入——风险不存在，但一行断言成本近零可保留
