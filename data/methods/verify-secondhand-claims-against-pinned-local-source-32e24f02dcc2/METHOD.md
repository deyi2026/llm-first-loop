---
method_id: verify-secondhand-claims-against-pinned-local-source-32e24f02dcc2
name: verify-secondhand-claims-against-pinned-local-source
description: 当文档中关于外部项目的特征被明确标注为二手来源且存在待核验对比项时：一次裸专名检索确认既有 provenance → 一次定位 canonical 上游 → 一次本地获取（clone）并立即 pin commit → 只在本地副本逐条核验断言，不重复抓取已持有文件的远程镜像页。本集摩擦：clone 回执已枚举 README.md 后仍 web_fetch 仓库页取同一内容并引入代理 fake-ip 异常分支；search_evidence 因附加'source code repository'意图后缀落空，随后裸名即命中。两条浪费均可由当时回执避免。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7c2d2cfd-aeec-4302-9540-d52110cadd7a:21:59ad5d539f9ab93e21e8
evidence_refs: learning:learn:006a6f510152
created_at: 2026-09-24T17:29:21.035782+00:00
updated_at: 2026-09-24T17:29:21.035782+00:00
---
## Trigger
待核验文档/任务：外部项目的机制描述被标注为二手来源（如'来自二手讨论，需核验'、对比表列'待拉源码核验后填写'），需要取得一手材料后填表或做决策

## Discriminator
获取类工具的回执已枚举本地持有的文件清单（clone 输出列出 README.md 与 src/*.ts）——该清单在场时，关于此 artifact 的后续事实来源应是本地 pinned 副本，远程镜像页不提供新增核验点；同时检索回执可证：evidence/归档 store 用裸专名即可命中，意图性后缀导致 miss

## Short path
- 读待核验文档，抽出断言清单与其标注的来源状态（二手/待核验），未知量=要核验什么、依据什么
- 用裸专名一次检索 evidence/归档，确认二手 provenance 是否已在库（勿加'source code repository'类意图后缀）
- 一次 targeted 检索定位 canonical 上游（stars/命名一致性判 canonical，忽略同名 fork），未知量=一手材料在哪
- 一次本地获取（浅 clone），从回执文件清单直接规划要读的承载断言的文件，并立即 git log pin commit
- 只读本地副本中与断言对应的文件，逐条映射断言→代码/README 行；不从 web 镜像重复取已克隆内容
- 产出中记录 pinned 版本，逐项表填实即停

## Stop conditions
- 全部待核验断言均已映射到本地 pinned 副本的具体代码/README 证据
- commit hash 已取得并写入产出，分析锚定到不可变版本
- 二手来源的每处过誉/偏差已有一手对照结论（如'无损压缩'→阈值边缘仍删、永久无回滚）

## Verification
- 核验引用是否全部指向本地 clone 的具体文件与行，而非二手文章或 web 镜像
- commit hash 在 clone 后立即取得，与分析对象一致，而非事后另取 default branch
- 对比表每一格都能给出代码级证据（默认值、问题措辞、存在/缺失的机制环节）

## Counterexamples
- clone 是 partial（shallow 缺子模块/LFS）或目标内容本不在 repo（releases、渲染文档站、issues 讨论）→ 远程页面是必要来源，仍需抓取
- 任务要核实'当前线上/default branch 实时态'（访客看到的 README、最新 release）而非某个 pinned 快照 → 此时沿用 fresh-read-authoritative-record 方法重读，本方法不适用
- 上游无代码库（纯论文/纯托管服务）→ 一手材料是论文或官方文档，clone-本地核验流程整体不适用
