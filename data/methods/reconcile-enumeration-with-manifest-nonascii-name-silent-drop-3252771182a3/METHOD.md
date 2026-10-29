---
method_id: reconcile-enumeration-with-manifest-nonascii-name-silent-drop-3252771182a3
name: reconcile-enumeration-with-manifest-nonascii-name-silent-drop
description: 用筛选式文件枚举（如『含某模式的文件清单』）去更正先前结论或放行某文件（『它不含敏感串，可直接入库』）之前，先做计数对账：命中集＋逐项核查过的未命中集必须等于权威清单总数（git status 已列出的 untracked 全集）。任何差额都意味着枚举管道在静默丢文件，而不是文件真的未命中。典型丢失源：非 ASCII 文件名被 git 默认 quotepath 转成带引号的八进制串，任何经 shell 词分割或 [ -f ] 测试的管道都会无声跳过它，把『管道表示不了』伪装成『未命中』。改用 NUL 管道（ls-files -z | xargs -0）与 core.quotepath=false 重跑，对账通过后才下否定结论，否则会出现错误更正→撤回→换基线重算的整段返工。
aliases: grep 计数比 git status 少一个文件, 中文文件名 八进制转义 漏检, 文件清单对不上总数先查管道, git quotepath 非ASCII路径丢失, 更正上一轮结论前先对账文件数, 别用漏文件的清单说没命中
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:6e7b4358-a1b8-4e23-a99c-931d6e86bee2:478:d41a3351d49480389da0
evidence_refs: learning:learn:5fff99507577
created_at: 2026-10-28T13:16:22.407507+08:00
updated_at: 2026-10-28T13:16:22.407507+08:00
---
## Trigger
对一批文件跑模式筛选/计数，并准备据此宣布否定结论（某文件不含 X、可直接入库）或更正上一轮说法；且同一上下文已有权威全集清单（git status / ls-files 输出）可对账

## Discriminator
枚举计数 < 权威清单计数（如 14 vs 15），且差额文件的名字在权威清单里以带引号的八进制转义形式（"docs/\345..."）出现——转义名字本身就是当前管道无法忠实传递该文件名的可见证据，而非该文件未命中模式

## Short path
- 取权威全集（git status / ls-files）并记下总数与所有以转义形式显示的文件名；未知量：全集多大、哪些名字可能管道不兼容
- 用 NUL 安全管道枚举命中集：git -c core.quotepath=false ls-files -o --exclude-standard -z | xargs -0 grep -l '<模式>'；未知量：哪些文件真命中
- 对账：命中数 + 逐项核查过的未命中数 = 全集数；有差额先修管道（quotepath/编码/词分割），对账不过不下结论、不发更正
- 对差额文件或转义名文件不经管道直接 grep 文件本体，二次确认命中与否
- 对账通过后才宣布更正/放行，并沿用同一 NUL 管道做后续备份、替换与校验，避免二次踩同一坑

## Stop conditions
- 命中集与全集完成对账，差额文件的命中性已直接核查
- 权威清单本身带 pathspec/.gitignore 过滤或过期时，先取真正全集再对账
- 无版本控制、无权威清单的目录，先用确定序枚举（如 find -s）生成清单作为对账基准

## Verification
- 修正管道后重跑同一枚举，计数应与权威清单一致，并与备份目录独立计数交叉验证（本集：15 文件 / 56 处）
- 含非 ASCII 名的文件不经文件名管道单独 grep 本体，确认命中与否
- 无损改写的期望计数必须包含自身新增注记引入的替换词（如约定行里的 `$HOME`），否则会把正确数据误判 FAIL

## Counterexamples
- 文件名全 ASCII 且计数已相等：对账退化为一次零成本比较，无需改造管道
- 用 grep -r 直接扫目录、不经文件名中转的管道不产生此类静默丢失（但其输出侧转义仍可能坑下游 [ -f ] 判断）
- 权威清单本身被 pathspec 限制或已过期：先补全量，否则对账空转
- 二进制文件或超大目录逐名管道不经济：只在用户点名的候选文件上直接核查本体
