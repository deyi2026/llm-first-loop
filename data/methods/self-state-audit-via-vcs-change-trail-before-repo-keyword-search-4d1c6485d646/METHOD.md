---
method_id: self-state-audit-via-vcs-change-trail-before-repo-keyword-search-4d1c6485d646
name: self-state-audit-via-vcs-change-trail-before-repo-keyword-search
description: 当用户问'你在修什么/有没有跑偏/进度如何'这类关于本会话自身工作状态的元问题时，不要先做仓内关键词检索——通用词（如 receipt）会命中跨子系统同名实现，全是噪声。先读 VCS 变更迹：git status + 最近提交 + 提交引用的 spec/验收清单，它们唯一权威地记录'改了什么、为何改、验收到哪'；再对待声明的验证结论做一次最小复核（如重跑点名的测试类）；最后与用户字面点名范围逐项对比，显式标出超范围项并附干净回退选项后停止。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:451:66807e1ac9d4a3edc247
evidence_refs: learning:learn:d4d8b9bddf57
created_at: 2026-09-22T17:32:00.228766+00:00
updated_at: 2026-09-22T17:32:00.228766+00:00
---
## Trigger
用户提出关于本会话自身工作产品的元问题（在修什么/是否跑偏/完成了哪些），或需要快速重建'我做到哪了'的上下文，且工作发生在有提交记录的代码仓库

## Discriminator
问题对象是'本会话已产生的改动'，其权威记录是 VCS 状态与最近提交（含其引用的 spec 验收清单）；而候选搜索词在仓内是跨子系统通用词，search 命中的多为其他子系统的同名实现，无法定位本次工作

## Short path
- git status --short + 最近提交列表（log/diff --stat）：枚举本会话工作产品的权威集合（spec 文档、源码改动、测试、提交 hash），解决'改了什么'
- 从提交信息或未跟踪文档定位本次修复的 spec，读修复项清单与验收勾选状态：解决'在修什么、修到哪'
- 仅对答案中要声明的验证结论做一次最小复核（只跑点名的测试文件/类），不扩大枚举
- 把已落地项与用户字面点名范围逐项对比，显式区分 范围内/超范围/未动，超范围项给出独立提交边界与回退选项，把范围裁决抛回给用户

## Stop conditions
- 已从 spec/提交记录取得'修什么+落地状态+范围对比'，且声明的测试结果来自本次实际运行
- 用户字面范围之外的项已明示并附回退方案，等待用户裁决
- git 变更迹显示无本会话产物时，才转宽检索或直接询问用户

## Verification
- 每个'已落地'声明对应可见 commit hash，工作区状态与声明一致
- 测试通过数来自本次实际运行输出，而非记忆或旧报告
- 范围结论逐条对应用户原话点名的项，无擅自扩项被包装成范围内

## Counterexamples
- 问题问的是概念或机制（'X 怎么工作'）而非会话状态 → 文档/源码检索才是正道
- 搜索词是仓内罕见唯一 token（专有文件名/ID）→ 一次 filename/content 检索即命中，比读 git 历史更便宜
- 无 VCS，或改动全部未提交且无 spec/清单 → 需回退到文件 mtime、会话日志或结果工件审计
- 共享仓库中最近提交混杂他人工作 → 必须先按作者/时间过滤，否则会把别人的改动当成自己的工作产品
