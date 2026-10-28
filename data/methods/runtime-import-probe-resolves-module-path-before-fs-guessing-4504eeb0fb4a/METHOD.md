---
method_id: runtime-import-probe-resolves-module-path-before-fs-guessing-4504eeb0fb4a
name: runtime-import-probe-resolves-module-path-before-fs-guessing
description: 已读源文件给出目标实现的包级 import 语句（如 from llm_loop.tools import review_host_admission）后需要物理路径时，不要按目录布局猜：本集先猜缩写目录 /lfl、再拼仓库根 llm_loop/，两次工具失败后又通配符 ls/find 遍历 $HOME/Project，最后才用解释器探针一步命中 src/ 布局。import 路径是语言运行时的模块标识符而非文件系统路径；物理位置的权威解析者是解释器本身。在已知 workspace 跑一次零副作用 import 探针（print(m.__file__)）即可把『src根/平铺/editable安装/缩写目录』所有布局假设缩成一条确定事实，后续 grep/读段全部锚定该文件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:152:701d85f613e53c7b87d3
evidence_refs: learning:learn:fe83a651a4e3
created_at: 2026-10-21T12:55:32.466796+08:00
updated_at: 2026-10-21T12:55:32.466796+08:00
---
## Trigger
已读 artifact（测试/调用方源码）明确给出目标实现的 import 路径，且需要定位其物理文件；workspace 已知但项目布局未知（src 布局、平铺、editable install、缩写目录都有可能），或已出现一次按布局猜路径失败的回执

## Discriminator
import 语句是运行时可解析的模块标识符，而判别物理位置的真值机制（解释器 import 解析）在猜路径之前就已可用——任何目录布局猜测都是在无判别信息下枚举可能性

## Short path
- 读到 import 语句后，把第一未知量收窄为一个：该模块名解析到哪个物理文件
- 在已知 workspace 用一次零副作用运行时探针：python3 -c 'import <pkg.module> as m; print(m.__file__)'
- 核对返回路径落在当前 workspace 内（如 src/llm_loop/...）：在，则 grep/读段全部锚定该文件（本集 grep merge-base 一次命中第448行）
- 探针失败（ModuleNotFoundError）或解析到 workspace 外副本时才升级：项目权威环境定位或读 pyproject 声明的包布局，而不是换目录布局再猜一次

## Stop conditions
- 探针返回的 __file__ 位于当前 workspace 内：已获权威路径，停止一切目录枚举，进入读码
- 探针解析到 site-packages 等非 workspace 副本：运行副本≠仓库源码，显式区分后按该事实分支，不再枚举
- 无 shell/解释器可用：改读构建配置声明的包布局，属读配置而非猜测

## Verification
- 探针输出路径须能被后续 read_file/grep 直接命中（无 No such file or directory）
- 最终修改的文件与探针解析文件为同一路径，证明改的是运行时真实加载的实现

## Counterexamples
- 仅持 exact-path 读工具、无 shell 时无法跑探针：应读 pyproject/setup 的包布局声明，而非盲猜目录
- import 的是第三方/stdlib 模块，__file__ 落在 site-packages：那不是待改的项目源码，探针结果只证明『不可改副本』这一事实
- identifier 不是可 import 模块（文档引用、字符串常量、伪路径）：运行时解析不适用，回到 provenance/文档定位
