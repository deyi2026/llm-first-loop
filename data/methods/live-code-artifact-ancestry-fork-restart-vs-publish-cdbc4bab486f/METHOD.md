---
method_id: live-code-artifact-ancestry-fork-restart-vs-publish-cdbc4bab486f
name: live-code-artifact-ancestry-fork-restart-vs-publish
description: 长驻宿主上刚提交的门/规则改动不生效、且已重启过（或重启脚本实际未重启任何进程）时，不迭代重启方式、不枚举『宿主 import 自哪里』的嫌疑清单：先用同参最小探针确认失败串仍是同一旧规则签名，再用服务所用解释器跑零副作用 import 探针一步定位活进程加载的代码工件（工作区 editable / .releases 类部署快照 / 旧 site 副本）。若落在部署快照，对 fix commit 与快照 SHA 做祖先判定（merge-base --is-ancestor）并直接 grep 快照内规则常量交叉验证——快照不含修复则任何重启结构性无效，唯一杠杆是 publish 新 release。publish 的脏树门禁常只看 tracked（--untracked-files=no），只需回退可再生 tracked 输出即可解锁，untracked 一律不动；publish 后以 desired generation / live.git_head 回执验收，accepted 不等于生效。
aliases: 重启了还是走老逻辑怎么办, 先查进程跑的是哪份代码再谈重启, 线上跑的是快照不是工作区, fix 不在运行 release 里, publish 脏树门禁看不看 untracked
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c5f52ba4-0dd0-440d-ab8e-d4b02bb2ed41:2478:cd0b019d4daa0f3b6491
evidence_refs: learning:learn:bb0aa5c9db21
created_at: 2026-10-26T14:20:38.866016+08:00
updated_at: 2026-10-26T14:20:38.866016+08:00
---
## Trigger
HEAD 已含某门/规则文件改动（git log --name-only 可证），但长驻宿主的同参探针仍返回与改动前完全一致的旧规则签名，且已执行过一次重启或重启脚本输出表明它未真正重启任何常驻进程；下一步倾向换方式再重启、或按旧断点里的嫌疑清单逐一排查宿主 import 位置

## Discriminator
『HEAD 确含该门文件改动 + 探针失败串逐字不变』这对已观察事实把假设空间缩到单一未知量：活进程实际加载哪个代码工件。在服务解释器下跑 import 探针（print(module.__file__)）一步定址；若结果是 .releases/<sha> 类部署快照，则 git merge-base --is-ancestor <fix-commit> <snapshot-sha> 的 NOT IN 直接证明重启结构性无效，杠杆从 restart 切换为 publish

## Short path
- 用门的最小同参探针确认失败串仍是同一旧规则签名；若失败原因已变，按新原因重新诊断，不走本路径
- 在服务所用的解释器/运行身份下跑 import 探针拿 module.__file__，把候选（工作区 editable / 部署快照 / 旧 site 副本）缩成一条确定路径
- 若为部署快照：git merge-base --is-ancestor 判定 fix 是否在快照内，并 grep 快照内的规则常量（如豁免前缀元组）交叉验证；NOT IN ⇒ 停止一切重启迭代，转入 publish
- 读 publish 门禁源码的真实脏树口径（常为 git status --porcelain --untracked-files=no，仅 tracked 脏挡路），不要想当然清理 untracked
- 只处置 tracked 脏：确认文件为可再生运行产物（测试报告/记账账本）后 checkout -- 回退；含手稿则 stash/commit 而非回退
- publish 绑定 HEAD → 托管 restart；以 desired generation / live.git_head==desired 回执验收，不再对旧进程重复探针
- 活代码工件已含 fix 时：grep 常量比对确认；若常量由配置外置驱动，转配置更新路径

## Stop conditions
- import 探针落在工作区/repo editable 且宿主进程启动时间早于 fix 提交 → 本方法退出，转入『重启即加载』路径（self-hosted-gate-stale-until-host-restart 场景）
- 快照已是 fix commit 后代（ancestor 成立）而门仍旧行为 → 因素在配置外置或多进程未换代，另开诊断，不再碰 publish
- publish 回执绑定新 release（git_head==HEAD）且 restart 受理/终态按协议核对完毕 → 停止处置，进入验收

## Verification
- merge-base 祖先判定 + 直接读快照内门常量双重确认，不依赖单一信号
- 回退 tracked 脏前逐文件核对确为可再生输出，无人工手稿
- publish 后以 live.git_head/desired generation 回执核对生效；accepted 只证明 desired 绑定，不证明执行完成

## Counterexamples
- 宿主本就 import 工作区 editable（module.__file__ 指向 repo src），只是进程早于提交：重启即够，无 publish 概念，套本方法会绕远
- 门行为由配置文件/外置常量驱动：改代码+publish 也不生效，应改配置并触发 reload
- 两次探针失败串不同（新规则新原因）：说明新代码可能已加载，应按新失败串重诊而非跳去 publish
- tracked 脏文件含人工手稿/不可再生产物：checkout -- 会毁工作，必须 stash/commit 而非回退
