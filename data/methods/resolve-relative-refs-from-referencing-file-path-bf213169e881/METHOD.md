---
method_id: resolve-relative-refs-from-referencing-file-path-bf213169e881
name: resolve-relative-refs-from-referencing-file-path
description: 复核文档内引用资源（图片/附件/链接文件）是否存在或未被覆盖时：若引用以相对路径出现且引用文件自身路径已知，则 dirname(引用文件)+相对引用 联结即唯一候选位置，应直接探测解析结果，不要先猜资产目录。本集 grep 已给出 ../../img/fig1-loop.png 且文件位于 docs/promotion/revisions/20261010/，直接联结即得 docs/promotion/img/；实际却先误探 docs/img/ 产生一次失败调用后才走对。路径联结是纯机械操作，可脚本化；模型只保留『解析 miss 本身是否构成 REVISE blocker』的裁决。（本集开头两次 workdir 参数错误属环境噪声：被拒后应先 pwd/ls 确立有效根再重试。）
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:87454a3c-2a7c-4282-974a-24e435f8ebcb:111:d0c660658034fc77b882
evidence_refs: learning:learn:f0e1ef4bbd10
created_at: 2026-10-11T01:50:29.817877+08:00
updated_at: 2026-10-11T01:50:29.817877+08:00
---
## Trigger
需核验某文档/稿件中引用的资源（图、附件、被链接文件）存在性或未被覆盖，且引用呈相对路径形式（如 ../../img/x.png），引用文件自身路径已确认。

## Discriminator
引用文本本身就是相对路径 + 引用文件路径已知：二者联结确定性地给出资源存放位置，无需枚举或猜测资产目录。knowledge-at-time 成立：本集 grep 步已暴露 ../../img/ 引用、ls -l 步已确认文件路径，均早于后来失败的 docs/img 探测；当时直接 ls 联结结果即可零失败完成图存在性核验。

## Short path
- 先核目标文件身份：按用户给定路径 ls+wc+sha256sum 对照声称值
- diff 锁定相对基线（r2→r3 及原稿累计）的改动范围是否与声明一致
- grep 提取全部图/链接引用，得到相对路径与引用行号
- 用 引用文件目录+相对引用 做路径联结，对解析出的路径直接 ls/sha256sum 验证存在与未覆盖
- git status 确认引用资源与旧稿均未被改动、旧 REVISE 关键字 0 命中后，输出唯一裁决并停止

## Stop conditions
- 用户核验清单各项（身份/diff/资源存在/阻塞解除/未覆盖）均有可查证据回执，立即给出 PASS/REVISE 与 remaining blocker 并停止
- 用户明确限定范围（如不重跑其他稿审查），完成清单后不扩大复核面
- 解析 miss 且确认是引用本身失效时，如实记为 REVISE 事实即停止，不得继续换目录猜测以『挽救』

## Verification
- 实测 SHA256 与声称值一致；diff 局限在声明的改动集内
- 新稿引用资源集合与声明保留集一一对应，且在『联结解析出的路径』上验证存在、哈希/ git 状态未变
- 旧 REVISE 原因关键词在新稿 0 命中，删除点上下文无悬空指涉（如『如图/上图』）

## Counterexamples
- 引用是绝对 URL、web 锚点或由构建脚本分配的 ID，不具备文件系统相对路径语义——直接联结必然错位，应改为解析构建配置或 URL
- 站点存在 baseurl/symlink 布局，盘上相对路径与运行时解析路径不一致——须按部署布局解析，不能裸联结
- 本次 diff 同时删除了资源与其引用（一并移除），存在性 miss 是预期结果，不构成未解除的 blocker，不应据此判 REVISE
- 文中没有任何显式相对引用、资产目录完全未知——此时才应退回目录枚举式发现，本方法前提不成立
