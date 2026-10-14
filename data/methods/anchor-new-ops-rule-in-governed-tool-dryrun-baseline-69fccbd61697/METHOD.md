---
method_id: anchor-new-ops-rule-in-governed-tool-dryrun-baseline-69fccbd61697
name: anchor-new-ops-rule-in-governed-tool-dryrun-baseline
description: 设立新运维/清理规则文档时的三步事实锚定：(1) 检索确认无既有规范、从仓库规则命名家族对齐前缀，避免另起炉灶；(2) 当前状态基线直接用被治理工具自身的 dry-run/清单模式测（其发现逻辑即权威口径），不要手搓限深 find 后再补一致性验证；(3) 条款中的唯一入口、保护边界、参数从工具源码/help 提取；实测基线与预期相反时如实重新定性（本集基线为 0，规则被定性为预防性制度而非清理遗留）。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:2d3fd645-2639-44ec-9f14-2a96c1c807fe:65:df19eb3903857c248b5d
evidence_refs: learning:learn:76723ce362f7
created_at: 2026-10-14T12:30:25.986004+08:00
updated_at: 2026-10-14T12:30:25.986004+08:00
---
## Trigger
需要新设一条清理/运维/流程类规则文档，且该规则将治理仓库中一个既有脚本/工具、并会断言当前状态或引用工具行为时

## Discriminator
两个当时已知事实可提前收窄搜索：(a) docs/ 已存在规则命名家族（SMC-RULE-* / ai_rules 等），新文档命名与结构可对齐而非另起炉灶；(b) 被治理脚本自带 dry-run 清单模式且其发现逻辑（rglob 全深度）就是规则将采用的权威口径——用手搓限深计数会制造『是否代表真实分布』的新未知量，迫使二次核实

## Short path
- search_docs 查既有清理/规则规范；未命中即确认无重复，回执中的最近文档参考已足够，不换措辞重搜
- 模式 grep（RULE|OPS|MAINT 等）定位规则命名家族，确定新文档前缀与结构
- 直接运行被治理脚本的 dry-run 取全深度权威基线（含占用跳过、保护路径行为），替代手搓限深 find
- 读脚本源码/help，把唯一入口、两步流程、保护边界、参数名（--apply/--min-age-hours 等）提取为条款事实
- 成文写入实测基线；若基线为 0 或与预期相反，明确定性为预防性制度并核正用户预期
- present_files 交付并附诚实核正说明

## Stop conditions
- 规则中每个事实断言（基线计数、参数名、保护路径）均有本仓库工具输出或源码支撑
- 命名已对齐既有规则家族，且检索确认无同主题重复规范
- 基线已按被治理工具自身口径测得，必要时仅加一个独立口径交叉验证

## Verification
- 重跑 dry-run 与一次独立 find 双向核对计数一致
- 条款引用的每个参数/保护路径在脚本 help 或源码中真实存在
- 新文档文件名能被既有规则家族的模式 grep 命中

## Counterexamples
- 规则为纯流程/行为约定、不治理任何既有工具时，无 dry-run 基线可测，检索+对齐命名后直接成文
- 基线探测本身有破坏性或高成本（需重跑 eval、重建环境）时，应以只读账本/元数据为准而非运行工具
- 仓库已有同主题权威规则文档时，应修订其版本而非另设新 v1，防止规则碎片化
