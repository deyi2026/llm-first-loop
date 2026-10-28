---
method_id: uniform-enoent-on-repo-skeleton-resolve-checkout-root-before-network-fal-bb034a612b71
name: uniform-enoent-on-repo-skeleton-resolve-checkout-root-before-network-fallback
description: 核验文档引用的仓库相对路径时，若整批目标跨 .github/、docs/、scripts/、src/ 等互不相关顶层目录同时报 No such file or directory，而同 cwd 下已知文件（如刚读取成功的被审文档）确实存在，应判为 cwd 是多项目工作区容器、真实 checkout 在下一层：先枚举容器顶层定位含 repo 骨架的目录，再在其中一轮并行核验本地可裁决断言；仅本质上网络侧的事实才走远端查询。避免把根错位误当文件不存在而转向换词重试或网络回退。
aliases: 文件全找不到先确认进没进错目录, 整批路径缺失先找仓库根, 多 checkout 工作区定位真实仓库, 路径全 ENOENT 别急着抓远端, 工作区根不等于仓库根, 核验文档引用先落地真实 checkout
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:0:dee60a80f799bff03f6c
evidence_refs: learning:learn:9a43997fc50b
created_at: 2026-10-27T17:32:24.399494+08:00
updated_at: 2026-10-27T17:32:24.399494+08:00
---
## Trigger
对文档/报告中引用的仓库相对路径做存在性或内容核验（ls/grep/sed 批量探测），回执显示整批目标跨多个互不相关顶层目录同时 ENOENT，但同一 cwd 下已有文件确实存在（如本 run 刚读取成功的文档）

## Discriminator
失败回执的形状本身：整批跨目录全缺（repo 骨架整体不在）+ 同树内已知存在文件 → cwd 是容器而非仓库根；唯一先决未知量是『权威 checkout 在哪个子目录』，不是『这些文件去哪了』，更不该由网络抓取代替本地核验

## Short path
- 用一次 ls 批量探测被引路径；未知量：断言路径能否从当前 cwd 解析
- 回执呈整骨架 ENOENT 而同 cwd 有已知文件 → 假设根错位；枚举 cwd 顶层一层目录，锁定含 .github/ 等骨架的真实 checkout 子目录
- 在真实 checkout 内一轮并行核验全部本地可裁决断言（规则正文、workflow 触发条件、脚本内容、回执计数），每项带 file:line
- 仅把本质上网络侧的事实（如线上 Release 资产在否）留给远端查询；403/超时不回退为本地断言的替代核验
- 证据落定即修订文档并停止，不再对同批路径换词重试

## Stop conditions
- 每条会改结论的断言已在真实 checkout 内 confirm，或显式标注『待复核』并说明缺的证据
- checkout 根已确认而被引路径仍不存在 → 判为文档断言虚构/过时，停止路径层重试

## Verification
- 最终引用的 file:line 是否全部位于同一真实 checkout 根下
- 后续本地核验回执不再出现整骨架 ENOENT
- 文档中被网络侧失败（403/超时）触及的断言是否已降级为『待复核』而非被静默当作已核验

## Counterexamples
- 仅个别文件缺失而同级兄弟路径可解析 → 是真实改名/删除，做定点搜索而非找根
- cwd 确为仓库但被引路径从未存在（文档引用幻觉路径）→ 根枚举证明根正确后，问题在文档断言不在环境
- 目标事实本质上只在远端（线上资产状态、外部服务实时状态）→ 网络查询是正确工具，本地根解析帮不上
- 稀疏/部分 checkout 或 git exclude 造成『存在但看不见』→ 属快照镜像类情形，另循对应方法
