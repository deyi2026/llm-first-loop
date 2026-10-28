---
method_id: filter-vendor-tree-hits-and-pin-source-layout-before-reads-41c79a675c78
name: filter-vendor-tree-hits-and-pin-source-layout-before-reads
description: 仓库内按文件名/内容检索定位项目自身实现时，若回执被 .venv/site-packages/node_modules 等依赖树副本淹没，先按路径前缀分流：依赖命中当噪声排除，只沿项目源码根的命中走；把检索回执的相对路径拼成绝对路径之前，先用符号级内容检索或一次目录列举钉死源码布局（如 src-layout 与磁盘路径的映射）再 read；一旦收到显式『路径不存在且已登记』的失败回执，立即换定位方式而非重试原路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cfb48927-c4d8-44fb-9dd3-cd89bb5523c9:94:7e0dd2c59bfd0f392bb8
evidence_refs: learning:learn:4bc84c996623
created_at: 2026-10-19T00:31:18.393234+08:00
updated_at: 2026-10-19T00:31:18.393234+08:00
---
## Trigger
在代码库任务中检索目标文件/符号，回执大量命中第三方依赖目录（.venv、site-packages、node_modules 等），或准备按检索回执给出的相对路径拼接绝对路径读取文件时

## Discriminator
两条当时即可见的事实：①检索回执的路径字符串本身含依赖目录段——这些是第三方 SDK 副本而非待改源码，且任务上下文（完善自家实现）已排除它们是目标；②read 失败回执显式登记『该路径不存在且此前已登记、建议停止该路径搜索』——这是权威否定证据而非 transient 错误，不应重试同一分支。

## Short path
- 先读定义本轮改动范围的设计文档/任务描述，提取被点名的文件与符号，把『全库找某关键词』缩成『查这几个符号』
- 对检索回执做路径分诊：凡命中路径含 .venv/site-packages/node_modules 等依赖段的按第三方副本排除，只保留项目源码根下的命中
- 用符号级内容检索（搜具体函数名/装配入口）取得带真实磁盘路径的命中，或列一次源码根目录，钉死相对路径→磁盘路径映射（如 src-layout）后再 read
- read 一旦收到显式『不存在且已登记』回执，立即改用布局/符号定位，不在原路径上重试或换措辞
- 按点名文件的相关区段读码核对现状，随后进入实现与测试

## Stop conditions
- 目标符号已在可直接解析成功的磁盘路径下取得定义与调用点，且与设计文档点名一致
- 检索回执已全部归属项目源码根，或依赖副本命中已被显式排除并说明理由

## Verification
- 构造出的绝对路径被 read_file 直接解析成功（无『不存在』回执）
- 最终引用的代码事实（文件、函数、行号）与符号检索回执中的 path:line 一致

## Counterexamples
- 任务目标就是依赖库本身的行为（如确认某 SDK 的类型定义或版本兼容性）时，site-packages 命中正是权威目标，不得当噪声排除
- 检索工具返回的路径可直接解析且首次读取成功，或仓库为扁平布局/单文件任务时，额外布局探针是多余开销
- 失败原因是权限或 transient 超时（回执未显式登记不存在）时，应排查读通道而非立刻怀疑路径映射
