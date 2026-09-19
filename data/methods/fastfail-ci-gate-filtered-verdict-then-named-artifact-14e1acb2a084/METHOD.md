---
method_id: fastfail-ci-gate-filtered-verdict-then-named-artifact-14e1acb2a084
name: fastfail-ci-gate-filtered-verdict-then-named-artifact
description: 当 PR/CI checks 表中某 gate 以秒级时长失败时，把它当作该 gate 自身机械检查脚本输出的确定性一行判定：先用只读失败步骤的方式（gh run view --log-failed，或按 ##[error]/checker 错误前缀过滤）拿到这行判定，再沿判定中点名的确切 artifact 路径去读 checker 的 schema 段与一份最近通过的样例，据此构造修复物并用与远端相同的 base/diff 语义本地复跑验证。不顺序分页原始日志，不重跑碰运气。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:855926d8-3b7a-4a6d-9c5e-34631b59df2b:685:2e28dcaf12033e2f75c8
evidence_refs: learning:learn:3c11ceda6c5a
created_at: 2026-09-19T10:56:23.836665+00:00
updated_at: 2026-09-19T10:56:23.836665+00:00
---
## Trigger
远端 PR/CI checks 表出现 fail 项且完成时长为秒级（远短于任何测试/构建，如 <60s），并行长任务仍 pending/pass，需要定位失败根因并准备修复。

## Discriminator
checks 表中失败项的完成时长（本例 6s，对照安全扫描 40s pass、门禁 pending）在拉取日志之前就已可见——秒败意味着失败发生在 gate 自身的前置机械检查脚本内，其输出是一行确定性判定，且通常点名期望的确切路径/文件；gh CLI 提供 --log-failed 只取失败步骤日志。

## Short path
- 从 checks 表确认失败项与秒级时长 → 未知量：该 gate 到底拒绝了什么？
- 只读失败步骤日志（gh run view --job <id> --log-failed，或 grep '##[error]'/'expected' 等错误标记）→ 一次取得一行判定，其中点名确切 artifact 路径（如 expected exactly one manifest under docs/.../submissions/, found 0）
- 沿判定点名的路径：列出该目录 + 读 checker 脚本的 schema/required-keys 段 + 读一份最近通过（已合入）的样例 → 未知量：合规格式与覆盖要求
- 按 schema+样例构造修复物（如覆盖精确变更路径全集的 manifest），以与远端相同的 base 与 three-dot 语义本地复跑同一 checker，确认 PASS
- 停在授权边界：原授权为 exact-SHA 且不含新提交时，报告根因与已备好的修复，等待授权后再 push

## Stop conditions
- 已取得 checker 的一行判定且其点名具体 artifact 路径（机械确认，非猜测）
- 本地以相同参数复跑同一 checker 结果 PASS，且修复物逐字段对照 schema 与既有通过样例一致
- 修复动作超出当前授权字面范围（如 exact-SHA push 不覆盖新增提交）→ 停止并请示，不自行扩大授权

## Verification
- 提取的判定行包含具体可执行期望（如 expected exactly one X, found 0: []）而非泛化/基础设施错误
- 本地复跑同一 checker、同一 base 与 diff 语义（three-dot），结果可复现地在加入修复物后翻转为 PASS
- 最终报告的根因与远端失败日志中的判定行逐字对应，且修复物路径与判定点名的路径一致

## Counterexamples
- 失败项运行了数分钟（真实测试/构建套件）：失败可能藏在多行 traceback 中，单行过滤会丢失上下文，应改用带邻域的日志阅读
- 秒败源于 runner/infra（checkout/setup 之前退出、网络或配额问题）：判定是基础设施错误，正确动作是重跑或换 runner，而非研究仓库 schema
- 判定点名的路径不在仓库内（环境变量、外部服务、secret）：无法沿路径本地跟进，需改从配置来源或文档取证
