---
method_id: deploy-hook-runs-as-pusher-gate-on-served-artifact-44ae02621429
name: deploy-hook-runs-as-pusher-gate-on-served-artifact
description: git post-receive 类『推送即部署』钩子以推送者身份执行，且其失败不会让 push 报错；若再用保留属主的拷贝（cp -a）写入 root 侧创建的 webroot，非 root 推送会静默失败，站点停留在旧内容。写钩子前即可预判：钩子身份=推送用户、post-receive 非零退出不能拒绝 push、跨身份的属主保留拷贝必败。因此直接选身份安全的流式解包（git archive|tar -x）、把 webroot 调整为推送用户所有、显式输出钩子错误；完成判据只认最终用户可见工件——用最小权限账号推带唯一标记的内容并 curl 断言返回该标记，而不是看 push 退出码。本集该缺陷由『推了 v3 页面仍显示旧内容』暴露，改为 tar 解包+属主调整后实时生效。
aliases: git push 成功但网页还是旧的, post-receive 钩子静默失败, 推送部署后 curl 不到新内容, git 钩子 cp -a 权限失败, push 到线上没生效怎么排查, webhook 部署以谁身份执行
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:tb-task:38:5d36a5c41841e0555c40
evidence_refs: learning:learn:dc94b3823409
created_at: 2026-10-23T13:13:58.734506+08:00
updated_at: 2026-10-23T13:13:58.734506+08:00
---
## Trigger
在 git 服务器上配置 post-receive 类『推送即部署』钩子，把被推分支内容发布到 web 服务器根目录，且存在非 root 推送账号、或 webroot 由 root 侧创建

## Discriminator
三条写钩子前已知的事实合并即可预判静默失败：钩子以推送用户身份运行；post-receive 的失败不会使 push 失败（错误再被重定向吞掉则完全静默）；保留属主的拷贝跨身份必败。这把『部署机制怎么选』从多种缩成『流式解包+目标属主对齐+错误显式化』一条

## Short path
- 写钩子前先答一个未知量：钩子以谁的身份执行？由已知事实（多账号可推送、webroot 为 root 所建）得出=推送用户
- 据此选身份安全的部署机制：git archive <被推分支> | tar -x -C webroot（产物归钩子用户所有），并把 webroot 属主调为推送用户、目录 755/文件 644
- 钩子不吞错误：执行结果 echo 进 push 输出或落日志，任何失败必须显式可见
- 验收只测端到端工件：用最小权限账号推带唯一版本标记的文件，curl 服务端 URL 断言返回的正是该标记，而非 push 退出码

## Stop conditions
- 非 root 账号完成一次带唯一标记的真实 push，且 curl 返回的正是该标记内容
- 钩子输出/日志中部署结果可见且无被吞错误

## Verification
- 推含唯一标记（如版本号字符串）的文件后，curl 必须返回新标记而非旧内容
- 检查 webroot 内文件属主为推送用户、权限可被 web 服务器读取
- 人为让钩子失败一次，确认失败在 push 输出/日志中可见而非静默

## Counterexamples
- 仅 root 推送且 webroot 属 root 的单用户环境：cp -a 不会跨身份失败，身份维度问题不存在
- pre-receive 钩子：非零退出会拒绝 push，失败会传播到推送方
- 部署系统已把部署结果回传触发方（如 CI webhook 返回体含部署状态）时，触发成功即已含部署真值
- 部署目标需要保留属主或特殊权限位（如 setuid）时，以推送用户身份解包会改变语义，需另行处理
