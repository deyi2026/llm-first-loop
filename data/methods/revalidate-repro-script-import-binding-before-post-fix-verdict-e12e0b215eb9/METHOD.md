---
method_id: revalidate-repro-script-import-binding-before-post-fix-verdict-e12e0b215eb9
name: revalidate-repro-script-import-binding-before-post-fix-verdict
description: 修复落进主仓后重跑旧复现脚本，若判定与直接断言修复行为的回归单测相矛盾（测试绿、脚本仍报漏洞复现），第一未知量不是『修复无效』而是『脚本加载哪份代码副本』。含发布快照镜像/部署副本/vendored 树的仓库里同一模块常有多份拷贝；复现脚本创作时的 sys.path/绝对路径钉子仍指向当时的验证对象（如上一版发布快照）。先有界读脚本头部确认 import 绑定，改钉到修复所在树再跑；也可有意双跑（快照在下次发布前本就该仍红）。只有绑定确认无误仍矛盾，才重开根因诊断。
aliases: 修完还报复现 先查脚本 import 哪份代码, 复现脚本钉在旧 release 副本上, 测试绿脚本红 是不是 sys.path 指错树, 多副本仓库 验证脚本绑的是哪棵源码树, stale repro pin false alarm after fix
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:1961:e3c001240ba0244673e1
evidence_refs: learning:learn:e92d2aeea573
created_at: 2026-10-29T08:49:11.832556+08:00
updated_at: 2026-10-29T08:49:11.832556+08:00
---
## Trigger
修复后用先前保存的复现/验证脚本确认修复是否生效，其判定与直接断言修复行为的新增回归单测相矛盾；或仓库存在同一模块的多份副本（发布快照、部署副本、vendored site-packages），而复现脚本是独立入口（自管 sys.path/解释器）

## Discriminator
单测经 pytest 从修复所在树导入并已跑绿（直接证明该树上修复行为生效）；而独立复现脚本的 import 目标在创作时被钉到当时的验证对象（sys.path.insert 指向发布快照等），从未与修复落点核对。两绿一红且工作区可证地存在多份模块拷贝时，『加载了不同副本』是首要假设，一次读脚本头部即可裁决

## Short path
- 修复 + 直接断言修复行为的回归测试并跑绿（它们定义『所导入树』上的真值）
- 重跑旧复现脚本前，有界读其头部：sys.path/路径/解释器钉住哪份代码副本？（唯一未知量：验证工件的绑定）
- 钉子≠修复所在树 → 改钉重跑；或有意双跑：快照副本在下次发布前应仍红、主树应转绿，两侧各自成立
- 脚本确认绑定到含修复的树后，应拦被拦/应放被放 → 修复验证成立，进入提交流程
- 仅当绑定无误且仍矛盾时，才回到修复面/根因重诊断

## Stop conditions
- 复现脚本经确认绑定到含修复的代码树后，其判定与回归单测一致
- 双跑模式下『快照红+主树绿』的差异本身即绑定正确的证据，可停止

## Verification
- 读脚本头部确认 import 钉子指向修复所在树，或在脚本内打印所导入模块的 __file__ 回执
- 修复文件的写入回执（diff/sha）与脚本导入路径属于同一棵树

## Counterexamples
- 脚本无显式钉子、隐式从仓库根导入主树：矛盾另有原因（.pyc 缓存、错解释器/错 venv），查绑定无收益
- 单测本身跑的是已安装包而非工作树（editable 安装缺失）：绿的才是陈旧侧，不能默认单测代表修复树
- 复现是一次性内联命令而非保存工件：不存在陈旧绑定，矛盾即真实修复缺口
- 修复目标就是快照/部署副本本身：脚本钉住快照是正确的，不应改绑
