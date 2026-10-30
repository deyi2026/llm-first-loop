# Method 独立评审队列 — Round 4（2026-10-30）

口径：全库机械证据扫描（`method_mechanical_evidence.py collect --select methods`，1641 张卡，url-phase=skip）产出的 `fail` 全部 + 分层抽样的 `manual_review`（local_path 与 tool_existence 各 4，步长抽样、不挑样本）。
目的：(A) 事实轴那 1 条是否成立；(B) 量化 manual_review 的真实率——机械抽取器把 body 里的示例路径/标识符当成了存在性主张（疑似过召），若成立则批量处置的机械基础不成立。
生成：`python3 scripts/qualification/method_mechanical_evidence.py collect --select methods --methods <全库> --url-phase skip --out-json reports/qualification-r4/mech-all-sample.json --out-md reports/qualification-r4/mech-all-sample.md`
入库：`reports/qualification-r4/mech-findings.json`（175 条发现子集，312KB）。全量清单（1641 张逐卡条目，1.28MB）**未入库**——超过仓库 git 安全扫描的单文件 1MB 上限；由上条命令按当时的库状态复现。
表格第 2 列放卡目录名（`pack` 的 `_selected_names` 只认 ascii kebab，且按 frontmatter name/dir 名精确匹配）；标题另列。

| method_ref | 卡目录名 | 标题 | 分组 | status | 机械发现（待核主张） | 机械判定 |
|---|---|---|---|---|---|---|
| `method:subagent-three-layer-diagnose-and-spawn-playbook-87273b2b3118` | `subagent-three-layer-diagnose-and-spawn-playbook-87273b2b3118` | subagent-three-layer-diagnose-and-spawn-playbook | A-fact-axis | candidate | [anchor] frontmatter.freshness_refs 声明仓库路径 docs/SUBAGENT-PLAYBOOK-20261025.md 存在 | fail |
| `method:adjudicate-prior-claims-via-definition-surface-not-keyword-discovery-b840be51dc0e` | `adjudicate-prior-claims-via-definition-surface-not-keyword-discovery-b840be51dc0e` | adjudicate-prior-claims-via-definition-surface-not-keyword-discovery | B-path-mention | candidate | [mention] body 声明仓库路径 evals/docs/experiences 存在 | manual_review |
| `method:inventory-driven-salvage-commit-5b505795e3f4` | `inventory-driven-salvage-commit-5b505795e3f4` | inventory-driven-salvage-commit | B-path-mention | candidate | [mention] body 声明仓库路径 docs/evals 存在 | manual_review |
| `method:reconcile-durable-task-store-before-labeled-work-2f4267d25ece` | `reconcile-durable-task-store-before-labeled-work-2f4267d25ece` | reconcile-durable-task-store-before-labeled-work | B-path-mention | hold | [mention] body 声明仓库路径 docs/frontier/goal/evidence 存在 | manual_review |
| `method:stem-cluster-filename-search-before-generic-token-sweeps-a3df5a76b805` | `stem-cluster-filename-search-before-generic-token-sweeps-a3df5a76b805` | stem-cluster-filename-search-before-generic-token-sweeps | B-path-mention | candidate | [mention] body 声明仓库路径 docs/S4-RESULT- 存在 | manual_review |
| `method:candidate-a80acb208b99` | `candidate-a80acb208b99` | 会话级知识层双向同步（开局检索·使用裁决·收尾结算） | C-tool-mention | hold | 正文以反引号提及工具/命令 `record_qualification` | manual_review |
| `method:exact-identifier-first-search-with-subsystem-split-b2d923262868` | `exact-identifier-first-search-with-subsystem-split-b2d923262868` | exact-identifier-first-search-with-subsystem-split | C-tool-mention | candidate | 正文以反引号提及工具/命令 `stable_prefix` | manual_review |
| `method:mutation-verify-consumption-protocol-9adee5230506` | `mutation-verify-consumption-protocol-9adee5230506` | mutation-verify-consumption-protocol | C-tool-mention | candidate | 正文以反引号提及工具/命令 `method-semantic-operation` | manual_review |
| `method:resolve-invoked-module-source-before-path-guessing-fcbb19768e79` | `resolve-invoked-module-source-before-path-guessing-fcbb19768e79` | resolve-invoked-module-source-before-path-guessing | C-tool-mention | candidate | 正文以反引号提及工具/命令 `importlib` | manual_review |
