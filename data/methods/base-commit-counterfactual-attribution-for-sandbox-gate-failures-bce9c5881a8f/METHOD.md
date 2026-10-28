---
method_id: base-commit-counterfactual-attribution-for-sandbox-gate-failures-bce9c5881a8f
name: base-commit-counterfactual-attribution-for-sandbox-gate-failures
description: 受限执行环境（沙箱/容器/钉死环境变量）里高成本门禁跑出成片新红时，先用失败输出里已有的环境级物证（errno/权限拒绝/shim 写系统缓存失败）和『失败文件与本次 diff 几乎无交集』两条判据，把第一未知量定性为『环境还是回归』；再用 base commit 的 detached worktree 在同一命令+同一 env 注入下复跑同一批失败文件做决定性对照：失败集合逐条一致即环境问题——如实报告『门禁未通过、非交付缺陷』，拒绝登记完成、文档保留『未运行』，把权威复跑交给非受限环境；集合不一致才是回归。把『逐个修 29 个红』或『盲目重试』压缩成一次对照实验，同时守住『未跑绿不得登记』的诚实口径。
aliases: 门禁红了先拿 base 提交对照复跑, 沙箱里全量测试变红是不是我改坏的, 测试失败集合和基线提交一模一样怎么定性, 环境权限问题导致门禁失败如何排除, 没跑绿之前能不能登记完成
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:2215:cb5c5351205848ebaaee
evidence_refs: learning:learn:03f78edf9b48
created_at: 2026-10-25T11:17:19.786335+08:00
updated_at: 2026-10-25T11:17:19.786335+08:00
---
## Trigger
全量门禁/大测试套件在自己的受限执行环境（沙箱、容器、被注入 HOME/TMPDIR 的 shell）中跑出成片新红（known-reds 对账登记命中为 0、全部判新），且失败签名中已可见环境级错误（如 errno=Operation not permitted、解释器 shim 写工作区外缓存失败），或失败集合横跨本次 diff 未触碰的文件

## Discriminator
写任何修复前就已可见的两条事实：①失败堆栈含环境级物证——权限类 errno 出现在系统目录（/var/folders 等）的缓存写入上，且解释器是 xcrun 之类 shim，错误直接污染子进程 stderr，击穿所有断言『stderr 为空/环境干净』的用例；②失败文件分布（安装脚本、setgid 校验、symlink 越界、子进程 kill、restart 收据）与本次改动文件清单几乎零交集。二者共同把候选空间从『我的 delta 引入了回归，逐个排查』缩成『先做一次归属判定』

## Short path
- 读失败输出，两栏归类：环境级签名（errno/权限/工作区外缓存路径）vs 断言级失败；同时求失败文件集合与本次 diff 的交集——交集为空或近空，环境嫌疑成立
- 单文件隔离复跑：默认 shell 下跑一个失败文件（应绿），再带上门禁注入的 env 复跑（应红），定位翻转变量，成本极低
- 决定性对照：在 base commit 建 detached worktree，用同一命令、同一 env 注入、同一批失败文件复跑，逐条比对失败集合
- 可选单变量 pivot：把嫌疑变量（如临时目录）指到工作区内可写路径，看红数下降后剩余红是否仍与 base 逐条一致
- 集合一致→定性环境：如实报告『门禁未通过、非交付缺陷』，不登记完成、文档口径保留『未运行』，请非沙箱权威终端复跑并等回执；集合不一致→真回归，进入修复

## Stop conditions
- base 与候选失败集合逐条一致（或差异完全可由单一环境变量解释）→停止修码与重试，把权威复跑交给具备该环境的人
- 权威环境（非沙箱终端）复跑回执到手→按实测值更新文档口径并登记完成；在此之前禁止登记完成

## Verification
- 对照实验必须同命令、同 env 注入、同批文件，在 base 与候选各跑一次，对失败集合做逐条 diff，不允许只比红数
- 单独在默认 shell 跑一个失败文件应通过，证明是组合环境触发而非用例本身损坏
- 最终报告须同时给出：失败集合对照结论、被隔离出的环境变量、以及『未在权威环境跑通』的明确声明

## Counterexamples
- base 上不红、仅候选红→真回归，直接修，不要归咎环境
- 交付目标本身就要求在该受限环境内运行→环境红也是交付缺陷，需改代码适配而非交人工复跑
- 失败集中在 diff 触碰的文件且无任何环境级签名→跳过归属判定直接调试
- 自己随时可切换到非受限终端→直接在那里复跑即可，base 对照是多余开销
