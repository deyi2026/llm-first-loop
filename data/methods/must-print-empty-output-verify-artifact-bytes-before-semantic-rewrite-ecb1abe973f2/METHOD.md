---
method_id: must-print-empty-output-verify-artifact-bytes-before-semantic-rewrite-ecb1abe973f2
name: must-print-empty-output-verify-artifact-bytes-before-semantic-rewrite
description: 落盘脚本首跑回执 success/退出码0 却零输出，而脚本顶层含无条件 print（要么打印要么抛错）时，先按『制品传输/执行不一致』处理：核对落盘文件实际字节并裸跑看真实退出码与 stderr，再考虑改脚本语义。本集：heredoc 经执行包装器落盘被污染（.py 内混入 shell 命令行致 SyntaxError），却先按『架构前缀猜错』重写了一遍脚本，属绕远；后换 printf 逐行传输一次成功。另 python -I 隔离模式会排除 site-packages，制造假性 ModuleNotFoundError，与解释器选择无关。
aliases: 脚本执行成功但没任何输出, 落盘文件内容和写的不一样, cat 重定向写脚本不可靠换什么, 一行行拼脚本文件的写法, 换个方式跑就导入不了库
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d7d570d1-4d88-404b-9c9e-79d8afafaeed:199:45bf7aec0a7a6175ba09
evidence_refs: learning:learn:f132efbeafac
created_at: 2026-11-15T12:26:34.965510+08:00
updated_at: 2026-11-15T12:26:34.965510+08:00
---
## Trigger
需要『生成脚本→落盘→用解释器执行』取数据（如读二进制制品元数据），首次执行回执为 success/退出码0 但无可观测输出，且脚本逻辑保证必有输出（无条件 print 或必抛异常）。

## Discriminator
回执形态与脚本语义的当场矛盾：must-print 脚本 + 空输出。该矛盾在改脚本前已可见，足以把『换键名/改脚本内容』的候选空间压缩为『核文件字节 + 裸跑看 exit/stderr』两个动作，而不是先枚举语义假设。

## Short path
- 按守卫要求先落盘脚本后，紧接着的下一次调用即裸跑：python3 script; echo exit=$?，不吞 stderr——未知量：脚本是否真被完整执行、真实退出码
- 空输出或 exit≠0 → 用 head/nl/wc 查看落盘文件实际字节——未知量：文件是否等于意图内容（本集发现 .py 内混入了 shell 命令行）
- 证实污染 → 换字节透明传输重写：printf '%s\n' 逐行写文件，且不加 -I——未知量：干净文件能否一次通过（所需模块先前已在无标志解释器验证可导入）
- 脚本输出与预期键值一致即取数完成，停止，不再改写脚本

## Stop conditions
- 裸跑输出与预期一致（拿到目标元数据/数据）即停
- 文件字节核对与意图一致、exit=0 仍无输出 → 排除传输问题，才回到语义假设（如输出被同链管道吞掉）

## Verification
- 落盘后立即 wc -c + head 比对文件与意图内容；执行时退出码与 stderr 必须同时可见
- 同一解释器无标志时可导入所需模块、加隔离标志后报 ModuleNotFoundError → 判定是标志所致而非环境，去掉标志复跑

## Counterexamples
- 脚本本身允许零输出（结果写文件、grep 无匹配 exit 1、条件分支未触发）→ 空输出是语义结果，直接修正内容假设，不必核字节
- 空输出由同一命令链的管道/重定向吞掉（如 | head -0、>file）→ 先审命令链，再查文件
- 回执已含真实 traceback 且未加隔离标志（如默认解释器缺依赖）→ 是环境选择问题，走『先定项目权威运行环境』路线，与制品传输无关
