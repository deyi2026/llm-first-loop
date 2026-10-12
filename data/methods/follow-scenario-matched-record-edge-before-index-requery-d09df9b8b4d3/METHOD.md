---
method_id: follow-scenario-matched-record-edge-before-index-requery-d09df9b8b4d3
name: follow-scenario-matched-record-edge-before-index-requery
description: 定位某项已完成工作（评测结论/运行结果/计划落点）的物理位置时：先用项目代号+产物类型查记录库；一旦出现 scenario/tags/时间戳精确匹配且可取 full_record 的命中，立即沿其 evidence 字段内嵌的产物路径直读数据，而不是向另一个索引（如 docs 全文检索）换词重查。'首个索引未命中 + 记录库精确命中'的组合已把全域搜索缩成一条可验证路径；记录无精确命中或路径过时，才升级到目录/docs 宽搜。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:192:e995904daa6c45aacbc4
evidence_refs: learning:learn:b0190e755e5e
created_at: 2026-09-21T02:10:14.139694+00:00
updated_at: 2026-09-21T02:10:14.139694+00:00
---
## Trigger
需要定位某次已完成工作的结论、数字或计划的物理落点；且此刻已发生（或即将发生）一次索引未命中后的换词重试——尤其当另一来源（记录/experience 库）已经返回与目标场景精确匹配的条目时

## Discriminator
记录库命中中已存在精确匹配条目：scenario 含同项目代号+同产物类型（判别力预检），时间戳为当天，且用户要找的另一个未知量（48 行全量决策、亿级 token 成本）也已出现在该 scenario 文本里；representation=full_record 可取，其 evidence 字段通常内嵌产物精确路径。这一事实在换索引重查之前就已把'结论在哪/计划是什么'缩为一条可跟随的 provenance edge。

## Short path
- 读 goal 状态与最新 checkpoint，锁定要找的事实及其声称的支撑物（如'字节级归档的运行产物'），据此判断结论大概率在运行产物而非 docs
- 用项目代号+产物类型查记录库；检查命中条目的 scenario/tags/时间戳是否与目标精确匹配
- hydrate 精确匹配记录的 full_record，从其 evidence 字段提取产物目录/文件路径（未知量：结论数字的物理位置）
- 按时间戳选最新产物目录，读注释文档并聚合原始 rows（未知量：结论数字+结论未覆盖的维度信号）
- 数字与 goal 完成声明核对一致后停止，进入建议生成；不再向 docs 等其它索引发变体查询

## Stop conditions
- 已从记录 evidence 指向的最新产物取得用户所需事实，且与 goal/checkpoint 声明一致
- 记录库无精确场景命中，或其路径已被更新产物取代且无法定位——此时才升级 docs/目录宽搜

## Verification
- 确认最终读取的产物目录时间戳/冻结版本是最新（如 ls -dt），与 goal 声明的最终基线一致
- 结论数字可由原始 rows.jsonl 重算复现；结论未覆盖的维度（tokens/轮数等）已另行核对过

## Counterexamples
- 团队约定结论只发布在 docs SoT 且记录库滞后时：docs 检索是正确首选，记录命中不代表当前落点
- 命中记录较旧，evidence 路径指向已被 supersede 的运行目录：必须比对时间戳取最新，不能盲跟路径
- 用户只需要 goal 状态本身：hydrate goal 证据即应停止，无需追记录与产物
- 记录库零命中时，向 docs/目录宽搜是正确升级而非弯路，本方法不适用
