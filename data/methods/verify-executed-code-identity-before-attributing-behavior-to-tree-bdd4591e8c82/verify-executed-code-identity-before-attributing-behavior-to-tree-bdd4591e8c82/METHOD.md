---
method_id: verify-executed-code-identity-before-attributing-behavior-to-tree-bdd4591e8c82
name: verify-executed-code-identity-before-attributing-behavior-to-tree
description: 在把复现/运行的异常行为归因为『某棵树、分支或快照里的代码缺陷』之前，先核验被执行代码的身份：打印模块解析路径（__file__、spec origin 或 traceback 中的绝对路径）。仓根共享 venv、editable 安装、site-packages、release 部署目录都会让 import 身份偏离 cwd 所在的树。路径指向别处（如旧 release 快照）说明此前复现跑的全是别的代码，须用显式路径覆盖重跑再归因；被诊树判定正确则结论改写为环境/发版问题。『源码看似正确、行为却错』的矛盾本身就是首要信号。
aliases: 跑的不是读的那份代码, 行为和源码对不上, debug 时跑错版本, 复现结果怪不到这个分支, 改了代码行为没变
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:ef19b98b-a401-41d3-9bc9-31d5cd6ff0e1:1170:23d24e7fefd8b0b3ad47
evidence_refs: learning:learn:1f0e7daf7479
created_at: 2026-11-20T14:24:01.106837+08:00
updated_at: 2026-11-20T14:24:01.106837+08:00
---
## Trigger
要把一次复现的异常行为归因为『被诊树（worktree/分支/快照）内的代码缺陷』，且执行所用的解释器或 venv 位于被诊树之外；或诊断中途已出现『读到的源码逻辑正确、复现行为却错』的矛盾。

## Discriminator
命令行可见的解释器路径不在被诊树内（如 .venv 挂在仓根而 cwd 在 worktree）——此时包身份由 site-packages 的 .pth/安装记录决定，与 cwd 无关，行为证据的归属尚未核验。这一事实加一次解析路径打印，即可把『解析器哪里坏了』的形态×分支枚举折叠成『路径一致/不一致』二分支。

## Short path
- 复现一次拿到异常行为（如判定 target 异常），同时记录所用解释器路径与 cwd 的关系
- 先不做命令形态分解：打印被执行模块的解析路径，解决唯一先决未知量『这次跑的是哪棵树的代码』
- 路径指向其他树（release 快照/安装包）→ 身份错位成立，用显式路径覆盖指向被诊树重跑同一复现
- 被诊树判定正确 → 结论改写为『无代码缺陷，宿主跑的是旧快照』，修复路径转向合并/发版，停止解剖源码
- 被诊树判定同样错误 → 身份假设成立，此时才进入常规 bug 定位（形态分解/读分支代码）

## Stop conditions
- 解析路径已核实指向被诊树且复现仍异常——身份假设成立，转入常规 bug 定位
- 身份错位已证实且被诊树判定正确——诊断闭环，缺陷归属改写为运行环境/发版链问题，不再枚举解析器形态

## Verification
- 用 __file__ / spec origin / traceback 打印的绝对路径核对被执行文件确实位于被诊树内
- 显式覆盖后重跑，前后各打印一次解析路径并对比判定输出，确认结论由被诊树代码产生

## Counterexamples
- 诊断目标本来就是部署/线上环境本身（如查『线上守卫为何误判』）：release 快照就是被诊对象，解析到它是正确身份，复现无需重定向
- venv 为被诊树本地所有（worktree 自带环境）：身份天然绑定该树，不存在此摩擦点
- 以显式文件路径直接执行的脚本：身份由命令行路径唯一决定，无解析歧义，可跳过身份核验步骤
