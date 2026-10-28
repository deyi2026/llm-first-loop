---
method_id: editable-restart-deploys-worktree-escalate-uncommitted-riders-c831e0694bd8
name: editable-restart-deploys-worktree-escalate-uncommitted-riders
description: 共享工作区中服务经 editable 安装（.pth→src）直载源码时，『提交并重启生效』里的路径限定 commit 并不限定部署面：重启加载的是当前整棵工作树快照，兄弟会话未提交、未批准的改动会一起静默上线。先按出处把脏树分组成 changeset，只提交获批批次并跑其回归；确认服务代码加载方式后，若存在搭车批（非噪音、属等待审批的正当产物，可用 pending 投影+mtime 稳定性核实），把『现在重启=两批同时生效』作为 A/B 裁决交给用户，而不是单方面重启或单方面 stash/清理。与『desired 绑定过期需选 update』不同：这里代码会生效，问题是生效范围过大且含未批内容。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7f2be023-db54-4395-9854-c784b5295062:401:1d1ffb78823cfcc28138
evidence_refs: learning:learn:6151c18a6bf5
created_at: 2026-10-20T12:57:39.848497+08:00
updated_at: 2026-10-20T12:57:39.848497+08:00
---
## Trigger
用户指示『提交 X 并重启服务生效』，且仓库为多会话共享工作区、目标服务通过 editable 安装（site-packages 存在指向 src 的 .pth）直接加载工作树源码运行。

## Discriminator
最早一次 git status/diff --stat 已显示脏树远超目标修复文件集（本例 12 个修改+多个新增文件，修复只占 2 个）；随后 site-packages 列表出现 __editable__*.pth 指向 src、且 ps 显示服务正用该 .venv 运行——这两条当时已知事实即可判定：commit 范围 ≠ 重启部署范围，未提交的他批改动会随重启一起上线。

## Short path
- 1) git status + diff --stat：把脏树按出处分区（目标修复文件集 / 其他批次 / 保留本地的未跟踪目录），未知量=树里是否只有用户获批的改动。
- 2) 确认服务代码加载方式：查 .venv site-packages 的 *.pth 或 status 回执的 code_root/git_head 字段，未知量=重启的部署单元是已提交 HEAD 还是当前工作树。
- 3) 若部署单元=工作树且存在他批改动：用 status 的 pending 投影与文件 mtime+短等待核实该批出处与稳定性（是否兄弟会话等待审批的产物、是否仍在被写入）。
- 4) 路径限定 git add 只提交目标修复文件，用项目 .venv 解释器（勿用裸 python）跑该批回归测试，pre-commit 扫描确认无夹带。
- 5) 停在裁决点：向用户呈现『A 现在重启=两批一起生效 / B 等他批审批后再一次重启』，不单方面重启也不 stash/清理他批产物；提示重启回执异步（waiting_for_requester_exit），生效核验留到下一会话。

## Stop conditions
- 用户对搭车批作出明确裁决（批准一起上线 / 等待审批后再重启）
- 除已提交修复外，工作树中不再有会被服务加载的源码改动
- 确认服务加载的是已发布工件而非工作树（editable 耦合不成立，直接重启）

## Verification
- 提交后 git status 只剩他批改动与保留目录：无夹带、无暂存残留
- 重启动作可追溯到用户的显式选择，而非对『提交并重启』的字面默认执行
- 下一会话核服务身份（git_head/generation/started_at）与被裁决的 changeset 一致

## Counterexamples
- 服务以打包/发布快照部署（非 editable）：重启加载已发布工件，脏树不影响部署面，无需裁决，直接重启。
- 单会话工作区且用户要求提交全部改动：脏树本身就是获批 changeset，全量提交并重启即可。
- 脏树中他批内容只是源码树外的噪音（备份/日志/未跟踪文档）且用户已批准目标批：清理或忽略后直接重启，不必升级为 A/B 裁决。
