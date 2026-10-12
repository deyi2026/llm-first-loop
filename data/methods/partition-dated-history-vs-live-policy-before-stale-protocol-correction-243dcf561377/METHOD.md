---
method_id: partition-dated-history-vs-live-policy-before-stale-protocol-correction-243dcf561377
name: partition-dated-history-vs-live-policy-before-stale-protocol-correction
description: 当用户宣布某拓扑/策略已变（如“主区退役，镜像即唯一区”）并要求纠正系统中残留的旧协议表述时，先把搜索命中按生命周期分区：带日期的 append-only 记录（DECISION/REVIEW/CHANGELOG/CALIBRATION/governance）原样保留；仍在生效的规则面（每轮注入的规则、协议文档、README 活章节、脚本/.env 注释、git remote）才改写；代码注释里的历史事故防御理由保留机制、仅加历史标注。改写语义前先用物理事实（目录已不存在、remote 自指）验证新拓扑，并补齐文档之外的纠正面，最后 grep 复核+测试收尾。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1523846-ee16-4c78-9f53-7abf782eac2b:1142:e5e2202d0365b8fcdc5f
evidence_refs: learning:learn:0d82d898ecfe
created_at: 2026-09-30T00:35:21.225259+08:00
updated_at: 2026-09-30T00:35:21.225259+08:00
---
## Trigger
用户指出旧协议/旧拓扑表述成为“干扰项”（如‘按镜像协议待审批后应用到主区’），要求全库纠正；搜索命中同时混杂历史记录与现行生效规则，无法全改也不能只改一部分。

## Discriminator
命中文件当时可观察的生命周期特征：文件名/正文带日期的记录类（DECISION-*、REVIEW-*、CHANGELOG、CALIBRATION-SEEDS、governance JSON）= 历史记录，不改；无日期或被运行时/每轮注入加载的规则与配置面（README 活规则章节、ai_rules.md 门禁段、协议文档、脚本操作注释、.env 注释、git remote）= 活面，改。且改写语义前先验证使旧表述失效的物理事实：ls 旧主区目录不存在、git remote mainrepo 指向镜像自身（自引用）。

## Short path
- 对旧术语做一次内容搜索，按文件路径收集全部命中，不强求首轮过滤
- 一次遍历完成分区：带日期 append-only 记录→保留；活规则/协议/配置/注释面→待改；同词异义（如 UI 布局语义的‘主区’）→排除
- 对驱动语义改写的拓扑断言做物理验证（目标目录存在性、remote/ref 指向），未验证前不动协议语义
- 按影响优先级编辑活面（每轮注入的规则最先）；改名用 git mv 并同步全部入边（扫描白名单/引用）；运行时绑定链路上的名字不改
- grep 复核活文件面无残留旧流程表述 + 跑针对性测试/语法检查，汇报‘已改/保留’分区清单

## Stop conditions
- 活面 grep 复核无残留‘审批后跨区应用’类流程表述，历史记录零改动
- 针对性测试与语法检查通过，改动无行为影响（或已按协议处理重启）
- 出现与用户指示冲突的未知拓扑事实（如目录又出现/双区恢复迹象）→ 停止改写并上报

## Verification
- 写后复读一致 / 快照 sha 校验（file contract）
- grep 复核全区活文件无旧表述残留，且带日期历史文档未被触碰（git diff 只含活面文件）
- 测试套件与 bash -n / 安全扫描通过；改名文件的入边引用（白名单、跨文档指针）全部更新

## Counterexamples
- 用户明确要求连历史/文档本身一起改（纠正范围覆盖带日期记录）→ 分区翻转，按显式指令范围执行，不套用‘历史保留’
- 拓扑断言未经验证或可能回退（双区未来可能恢复）→ 不把协议改写成单区语义，只上报差异待确认
- 带日期的文档实际仍被运行时或每轮 prompt 注入加载 → 它是活面；‘有日期’不是充分判据，判据是‘是否仍被加载生效’
- 同词异义命中（webui 的‘会话主区/本地镜像’是 UI 布局概念）→ 与拓扑纠正无关，不改
