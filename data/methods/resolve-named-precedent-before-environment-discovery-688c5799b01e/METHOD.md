---
method_id: resolve-named-precedent-before-environment-discovery-688c5799b01e
name: resolve-named-precedent-before-environment-discovery
description: 执行已批准的合并/发布/promotion 时，若任务记录已给出同类操作的命名先例（目标线+参考提交）且被批准任务的结果文档引用了流程协议，先用当前仓库内一条命令的窄检查解析该先例（目标分支存在性、祖先关系、带入区间、越界未提交改动），并直接读被引用协议章节按其执行；只有命名路径解析失败时，才枚举全部分支/worktree/外部目录去重新发现部署机制。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:1192:f8949e33ee868aeb1b67
evidence_refs: learning:learn:e17eb8e90e1a
created_at: 2026-09-18T15:28:24.608565+00:00
updated_at: 2026-09-18T15:28:24.608565+00:00
---
## Trigger
用户批准执行一次 promotion/合并/发布，且任务或目标状态中已存在同类操作的先例记录（写明目标线与参考提交），或被批准任务的结果文档引用了流程协议

## Discriminator
第一个工具结果中的先例行（如“P0-A …合入 main（cf8288822）”）加上当前仓库内一条命令即可验证的事实（本地是否存在该目标分支、HEAD 是否含参考提交、remote 列表中并无独立主区仓库）——这些在探测任何猜测的外部主区路径之前就已可见，足以把“部署机制未知”缩成“验证本地目标线的合并路径”

## Short path
- 读任务/目标状态：提取批准对象提交号、先例（目标线+参考提交）、任务自身结果文档指针；未知量=要执行的确切操作
- 读该任务的结果文档及其引用的流程协议章节：取得正典步骤、合并方式、指定 worktree、禁止触碰的越界改动；未知量=程序与边界
- 当前仓库窄验证：git status 识别越界未提交改动；目标分支存在性、is-ancestor、<target>..HEAD 带入区间（发现已部署提交与已知红随车）；必要时一次运行时来源检查（进程版本/import 解析）确认“合并≠部署”
- 按协议执行：正典环境定向测试复验 + 指定 worktree 内 --no-ff 合并到目标线
- 验证 merge commit 祖先关系并记账；披露边界（不重启、随车已知红、不 push 远端）

## Stop conditions
- merge commit 已落在目标线且同时以批准对象提交与旧 tip 为祖先，定向测试复验与任务记账完成、边界已披露即停止
- 命名先例无法解析（本地无目标分支、协议文档缺失或权威线在外部/远端）时停止复现路径，转为显式机制发现并说明理由

## Verification
- 合并前 log <target>..HEAD 确认带入区间与最终披露一致（含已部署提交、已知红）
- 合并后 merge-base/log 验证批准提交与既有 tip 均为新 merge commit 的祖先
- 在正典环境重跑结果文档中的定向测试+lint，确认与批准时的验证结论一致

## Counterexamples
- 没有同类先例（首次发布）或先例指向的外部/远端仓库才是权威线时，照抄本地先例会合错线，必须先确认权威目标
- 本次批准范围包含部署/重启而先例只是代码合并时，仅复现合并不充分；协议文档缺失或已过期时也不能照抄
- 当前 clone 为单分支、无本地目标分支时，窄检查本身失败，此时分支/worktree/目录枚举式发现才是正当起点
