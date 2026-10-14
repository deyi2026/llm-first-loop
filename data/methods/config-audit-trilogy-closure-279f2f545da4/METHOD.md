---
method_id: config-audit-trilogy-closure-279f2f545da4
name: config-audit-trilogy-closure
description: 配置文件死配置盘点与遗留处置的标准闭环：判死证据→三问收口→三重护栏删除→报告附录收口，含双层配置对账与必填校验反例。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:2d3fd645-2639-44ec-9f14-2a96c1c807fe:218:7da11495bea72136de23
created_at: 2026-10-14T14:15:48.909758+08:00
updated_at: 2026-10-14T14:15:48.909758+08:00
---
## Trigger
配置文件（.env / providers.json / providers.local.json 等）的死配置盘点、遗留项用户裁决执行、配置面审计收口。

## Discriminator
适用于「判断配置项生死 + 安全删除/改值 + 可回滚收口」的任务。不适用于：代码逻辑改造（如移除必填校验）、运行中服务参数热调（用 adjust_strategy）、纯文档清理。

## Short path
1. **判死证据先行**：宽松字面量全库 grep（py/sh/yaml/toml/md；排除 .releases/.worktrees/evals/backup 旁路副本），零命中才可判死；命中即保留并标注消费点。
2. **三问收口**（每个删除项）：谁消费（grep 实证）？何时读（启动装配/热重载/按需）？删了会怎样（零读取=零差；值变更=重启生效；必填校验项=禁删）？
3. **三重护栏**：删前 sha256 快照 + 独立备份文件（字节一致校验）→ 逐项唯一匹配删除（禁模糊批量）→ 删后反断言（被删变量零残留 + 行数差=预期 + JSON/py 语法校验）。
4. **报告即收口**：报告逐项记「变量=值 | 代码默认(读取点) | 用途/依据 | 验证 | 回收条件」；后续裁决以附录追加（处置结果+终态 sha256）。
5. **双层配置对账**：存在 providers.json + providers.local.json 等覆盖层时，生效源以优先级最高层为准；与 registry/catalog 实际内容对账后再判空壳。

## Stop conditions
- 任何删除项的三问有一问答不清 → 停，列为「需用户确认」不擅动。
- 发现必填校验/启动硬门消费该配置 → 停删，改注释修正并在报告如实记录冲突。
- registry/catalog 与文件内容对不上 → 停，先溯源真实注册源再动。
- 全库 grep 超时 → 停，缩小目录范围（maxdepth/排除大目录）后重试，不放宽判定标准。

## Verification
- 删后断言：`grep -c <被删变量>=0`、行数差=预期、`python -m json.tool` PASS、sha256 记录报告。
- 热重载验证：refresh_config 无报错；model_catalog 与配置文件逐 provider 对账（模型数求和=目录总数）。
- 回滚保障：备份文件 sha256 与原文件字节一致；编辑走 snapshot precondition。

## Counterexamples
- 字面量 grep 零命中≠安全删除：config.py:808-828 必填校验通过 missing 机制消费 LLM_API_KEY/LLM_BASE_URL，test_m50:622 注释「缺二者走重载失败」是高价值线索——tests 注释必须纳入扫描面。
- 空壳判定不看覆盖层会误判：providers.json 的 cognilocal（models={}）看似可删，实际 registry 的 cognilocal（2 模型）来自优先级更高的 providers.local.json 活条目——直接「清理 cognilocal」会误删弱模型对照档；须区分「遮蔽的空壳副本」（可删）与「覆盖层活条目」（不可删）。
- 值语义变更（EVOLVE_LOCAL_EXEC 2→0）受 Settings 启动装配冻结约束，不得声称「已生效」——生效点=下次重启，报告必须写明。
