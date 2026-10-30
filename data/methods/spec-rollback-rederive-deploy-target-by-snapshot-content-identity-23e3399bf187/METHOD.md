---
method_id: spec-rollback-rederive-deploy-target-by-snapshot-content-identity-23e3399bf187
name: spec-rollback-rederive-deploy-target-by-snapshot-content-identity
description: 并发写者发来口径/规格变更通知（明确声明旧口径作废、点名承载变更的 commit 与新增机制文件）时，任何把部署目标 pin 到具体 commit/代的既有决策菜单条目都可能已失效。先从通知+git 链重推『哪个最新产物物理包含点名的机制文件』，再用 live 发布快照的内容身份（模块文件存在性）与 live git_head 裁决：缺失 ⇒ 必须 publish 新代，单 restart 无效；在冻结副本上独立验收后才发布，不采信并发会话自述数字。
aliases: 别的会话改了口径还能按原方案上线吗, 线上到底跑的哪个版本的代码, 发布前先看发布目录里有没有那个新文件, 别按旧菜单直接重启到旧版本, 怎么确认新加的拦截在正式环境真的生效, 规格回退后之前的 A/B 选项还算数吗
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:cbda67c5-6cd8-421e-b4df-f59d74b4f2cc:1521:dd23993676eb417f83f2
evidence_refs: learning:learn:4fdf0b0dcc85
created_at: 2026-10-30T17:17:55.180634+08:00
updated_at: 2026-10-30T17:17:55.180634+08:00
---
## Trigger
收到并发会话的口径/规格变更通知（含旧口径作废声明、点名承载 commit/新增模块文件/设计文档节），而手头存在先前生成的部署决策菜单或既定候选 commit，且需把变更发布到 live/多服务。

## Discriminator
通知自带的当时已知三元组——作废口径名、现行口径名、变更承载 artifact（commit id + 机制文件路径）——加上 git log 显示既有菜单候选 commit 与新 commit 的时间先后。三者合用即可把『部署什么』从菜单枚举缩到『包含点名机制文件的最新 commit 线』；再用 live 发布快照中该文件的存在/缺失机械判定机制当前是否生效、publish 是否必要。

## Short path
- 从变更通知提取三元组：作废口径、现行口径、承载 artifact（commit/机制文件/文档节）——未知量：现行口径由哪个产物体现
- git log 确认点名 commit 存在并取该线上最新一代（含后续 REVISE 修复）——未知量：最终验收候选是谁
- 读 live 各服务当前 git_head 的发布快照，机械检查点名机制文件是否存在——未知量：机制现在是否已生效；缺失 ⇒ restart 单独无效，必须 publish 新代
- 把候选复制到独立 worktree 冻结，跑聚焦测试+绕过矩阵+否定面+闸自证伪——未知量：候选真实现行口径且守得住，不采信并发会话自述数字
- publish 新 desired 代，按回执 action_id 键控核对各服务重启终态；live git_head==候选且端到端越界写被拦即收口；异步未终态者排哨兵并如实标注未完成

## Stop conditions
- live 各服务 git_head == 候选 commit，且端到端探针：越界写回 write_scope_violation 且目标文件未产生、scope 内写不被误杀
- 异步服务未到终态（如等待本会话退出才重启）：哨兵已排、完成判据已定义即停，不宣称完成
- 候选不含通知点名的机制文件，或通知与 git 链不符：停止发布，先与并发写者对账

## Verification
- 发布快照与候选 commit 的机制文件身份一致（存在且内容对应）
- 各服务 live git_head 与发布回执 git_head 一致
- 留档上线前快照检查结果，作为机制此前未生效、publish 必要性的证据
- 独立重跑的测试与绕过矩阵数字来自冻结副本，非继承自述

## Counterexamples
- 纯配置开关类变更（无新增文件）：快照文件存在性判别失效，应查配置值/环境端点
- 通知未经 artifact 证实（点名 commit 不存在或 diff 不含所述变更）：不能据此作废旧选项，先对账再动
- live 服务不从发布快照加载而是就地 import 工作区代码：快照检查不代表实际生效面，须查进程真实加载路径
- 无并发写者、无作废声明的单会话常规发布：直接按既定候选走验收，无需重推
