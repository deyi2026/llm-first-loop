---
method_id: escaped-name-verbatim-enumeration-before-exact-read-d876e624f1d3
name: escaped-name-verbatim-enumeration-before-exact-read
description: 目标文件名只在转义显示里出现过（git status 双引号+八进制转义、JSON \uXXXX、URL 编码）时，把『逐字真实名』当第一未知量：先用能原样返回名字的枚举（ls/glob，按最长相邻 ASCII 片段过滤）拿到字面名，再做精确路径读取。不要手工解码转义序列去猜名字——按语义『读个大概』的解码几乎必错字节，失败的 read 还会把错误路径登记进不存在缓存。本集：从转义串手推出错经验卡文件名→read 失败→绕道 docs 搜索、无关 fetch、被拒 search_files 数次，最后一条 ls|grep 才拿到真名。
aliases: git status 中文文件名乱码怎么读, 八进制转义文件名还原错了, 转义路径别手敲先ls, quotepath转义名定位真实文件, 按英文片段grep目录拿准确文件名, 猜文件名失败后改ls
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:ce8b88af-7349-4903-91ab-b37a329e0489:406:44b298deec2f73ea8976
evidence_refs: learning:learn:bf51b836a8d1
created_at: 2026-10-28T15:30:39.647013+08:00
updated_at: 2026-10-28T15:30:39.647013+08:00
---
## Trigger
需要按精确路径读取一个文件，但其名字此前只在转义/加引号的显示形态中出现（如 git status/log 的 core.quotepath 八进制转义、JSON unicode 转义、百分号编码）；或 read 回执报『文件不存在』并附带『停止该路径搜索、改用枚举定位或向用户求证』的显式改道提示。

## Discriminator
显示串外层有引号且内含反斜杠转义序列——这一形态本身即证明该串不是可直接寻址的字面名，任何手推解码都只是猜测；同时失败回执往往原样给出改道建议。任一事实都足以把『再猜一个解码』缩成『先枚举拿字面名』。

## Short path
- 发现目标名只以转义形态出现在先前输出中 → 定第一未知量为『逐字字面名』，不发起任何基于猜测路径的读取
- 对父目录做原样枚举（ls/glob），用最长相邻 ASCII 片段（日期 slug、英文词）过滤，取回字面名
- 把枚举原样返回的字符串直接用于读取，不再重敲或二次解码
- 若枚举类工具被策略拒绝，降级 shell ls 或直接向用户求证；绝不迭代下一个手推解码

## Stop conditions
- 枚举输出中出现与上下文（日期/主题/清单行）一致的字面名且读取成功
- 枚举与求证均不可用时向用户升级，停止猜测迭代

## Verification
- 成功读取所用的路径与枚举返回串逐字节一致，且去转义后能对上权威清单行（如 git status 的 untracked 条目）

## Counterexamples
- 文件名纯 ASCII 且未加引号显示 → 直接读，枚举跳是浪费
- 此前某回执已原样打印完整字面路径 → 直接复用，不必枚举
- store 采用不可枚举的哈希/规范化命名 → 应走读命名方案设计文档的路线，本方法不适用
- 任务本身就是模式匹配任一命中文件皆可 → 枚举即是任务本身，无此摩擦
