---
method_id: numstat-fingerprint-reconcile-before-loss-forensics-fe0e96a92220
name: numstat-fingerprint-reconcile-before-loss-forensics
description: 当先前结论或交接记忆声称一批已暂存(staged)内容『消失/去向不明/需找回』，且该声称带可机械核对的量化指纹（文件清单＋行数，如 8 文件 +1576、单文件 579）时，第一未知量不是『谁清了暂存区/内容还能不能恢复』，而是『该指纹能否在某笔提交的 numstat 里精确对上』。在权威仓（以状态快照 workspace 字段为准，不按默认工作区猜）对涉事路径跑完整窗口的 git log --numstat：文件集合与 insertions 逐项吻合 ⇒ 暂存集已被提交，index 变空由 commit 自身解释，零丢失；只有对账不闭合才进入 stash/fsck/并发写者等丢失取证。窗口必须覆盖声称内容产生之时，不能只看最近 HEAD 附近（本集此前误判正源于只查了 10:05 之后的提交）。
aliases: staged 文件说没就没了 先对 numstat 账, 暂存区被清空 先查是不是已经提交了, 说改动消失 先按行数指纹对账提交史, git 暂存内容去向不明 要不要 fsck 找回, index 空了 不一定有人动过 可能就是 commit
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:2429:621b0c3c854f0747559b
evidence_refs: learning:learn:e96356cc7a7c
created_at: 2026-10-29T12:00:03.226214+08:00
updated_at: 2026-10-29T12:00:03.226214+08:00
---
## Trigger
先前轮次/交接记忆声称某批已暂存或未提交内容『消失、去向不明、需要找回』，且声称中带有可核对的量化指纹（具体文件清单＋新增行数），需要裁决『真丢失还是已被某笔提交吸收』并决定是否做恢复取证

## Discriminator
声称指纹（文件集合、各文件 insertions、合计行数）是否与某笔提交的 git log --numstat 输出精确一致。这一可观察事实把『谁清空了 index／blob 还在不在／要不要 fsck』整族问题折叠为『commit 本身清空了 index』。且 task_state 回执的 workspace 字段在动手前已钉死权威仓路径，无需按默认工作区猜测

## Short path
- 从最新 task_state/回执的 workspace 字段钉死权威仓路径，不做默认工作区猜测
- 在该仓对涉事路径集跑 git log --numstat，窗口自声称内容产生之时起而非只看 HEAD 附近几笔；未知量：是否存在一笔提交吸收了该文件集
- 逐项对账：文件集合、各文件 insertions、合计行数 vs 声称指纹；未知量：指纹是否闭合
- 若闭合，做祖先链验证（merge-base --is-ancestor 吸收提交 → 当前发布 HEAD），确认内容已入目标线；结论『已提交、零丢失、无需找回』，停止
- 仅当对账不闭合（缺文件/行数不符/无命中）才展开丢失取证：stash 时间戳、fsck unreachable blobs、事件流并发 git 操作考古

## Stop conditions
- 指纹完全对上且吸收提交在目标发布线祖先链上 ⇒ 判『已提交、零丢失』，停止一切恢复取证，也不再寻找『清空暂存区的人』
- 对账发现实质缺口 ⇒ 转入 blob 级丢失取证分支，不再重复 numstat 对账

## Verification
- sum(吸收提交 numstat insertions) == 声称合计（本集 1576 分毫不差）且逐文件计数一致
- merge-base --is-ancestor <吸收提交> <发布/当前 HEAD> 通过
- 若判『已提交』，对发现的并发 restore/reset 只需说明其作用对象不含指纹文件即可归档，不必再深挖

## Counterexamples
- 声称无量化指纹（只说『一些改动不见了』）⇒ 无法对账，应先从回执/状态快照重建文件清单再裁决
- 暂存内容从未被提交且工作区已被清理 ⇒ numstat 无从命中，对账法失效，直接进 fsck/stash 恢复
- 同路径同日多笔大改提交 ⇒ 行数可能跨提交重叠，必须对『单笔完整文件集合』对账而非只比总数
- 涉事仓未钉死（多 worktree/多镜像并存）⇒ 先钉权威仓再对账，否则在错误仓对不上会被误判为丢失
