---
method_id: derive-exact-paths-from-observed-layout-not-noisy-search-hits-2ebfcc30d385
name: derive-exact-paths-from-observed-layout-not-noisy-search-hits
description: 在仓库内定位权威源文件（契约/模块/配置）时，不要把噪声检索命中（全部落在 .venv/site-packages）或记忆印象提升为确切路径后直接精确读取。第一未知量是仓库路径布局：用一次根目录/父目录 ls，或复用已有回执里的真实路径形状（如 porcelain 输出的前缀）锚定布局，再拼路径并做廉价存在性检查。精确读取返回确定性『路径不存在』时，先从已观察布局证据重推导路径重试一次；排除自身推断错误后，才构建分支分叉/未提交本地工作等复杂叙事——否则会产出『该文件从未在此历史中存在』这类错误中间结论并污染后续判断。
aliases: 路径不存在先怀疑自己拼错前缀, venv 搜索命中全是噪声怎么办, not-found 别急着查分支分叉, 读文件前先确认目录布局, 凭记忆报路径翻车
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:168:3b3c657a42d63427aba3
evidence_refs: learning:learn:8b2ee2e5591b
created_at: 2026-11-13T20:26:44.595610+08:00
updated_at: 2026-11-13T20:26:44.595610+08:00
---
## Trigger
需要在仓库内定位某权威文件的确切路径，而检索命中集中在依赖目录（.venv/site-packages）或仅有间接引用；或基于推断路径的精确读取返回确定性『路径不存在』

## Discriminator
所断言的确切路径是否在任一已观察回执中有直接出处：若检索仅命中 vendor 目录而项目源码树零命中，且 ls/git status 等回执已展示真实路径前缀（如 src/ 布局），则路径推断未经证实，仓库布局才是第一未知量

## Short path
- 按命中分布分流：项目树零命中、仅 .venv/site-packages 命中 ⇒ 视为噪声，下一未知量定为『仓库布局』，用一次根目录 ls 或复用已有回执中的路径形状确定前缀
- 用布局修正后的路径先做廉价存在性检查（ls 父目录），确认后再精确读取
- 精确读取返回确定性 not-found 时，先从已观察回执（porcelain 路径、父目录 ls）重推导路径并重试一次
- 修正路径后仍不存在，才用 git log/merge-base 等证据检验分叉或未提交工作假设
- 一旦目标文件在预期工作树中确认存在且可读，停止定位，进入契约阅读

## Stop conditions
- 存在性检查确认目标文件在预期工作树中存在且内容可读
- 修正路径后仍 not-found 且 git log 证实该路径在基线历史中确无记录——此时才转向分叉/缺失结论

## Verification
- 每个被断言的确切路径都能在某个已观察回执（ls/porcelain/搜索命中的完整路径）中找到出处
- 采纳『文件不存在/分支分叉』结论前，复盘已先排除自身路径推断（前缀/布局）错误

## Counterexamples
- 搜索已直接给出项目树内的完整路径命中——直接使用，无需布局探查
- 路径由用户指令或早前工具回执逐字给出——not-found 即真实缺失/移动，分叉检查是正当的下一步而非过度叙事
- 扁平布局仓库（无 src/ 前缀）——方法核心是从回执推导布局，而非假设任何特定前缀
- 文件确实只存在于另一工作树的未提交改动中——此时 not-found 与分叉叙事同时成立，但仍需先确认路径本身拼写正确
