---
method_id: pin-execution-target-when-workspace-vends-source-snapshots-6cf68b27939c
name: pin-execution-target-when-workspace-vends-source-snapshots
description: 工作区内存在与 live 树同路径的完整源码快照（发布镜像、构建副本、vendored 依赖）时，"读过的代码"与"执行的代码"会静默分叉：裸解释器可能把包解析到旧快照，行为探针的红绿于是对错目标，且不报任何错误。方法：以搜索回执中同路径多副本的命中分布为早期信号；锚点核验只读 live 前缀；任何 import 本项目的探针/测试先一行确认模块 __file__ 落点（或用 PYTHONPATH 钉住），落点对上被审 HEAD 后才把探针结果当裁决。可省去：对旧副本跑出的红绿反复归因、探针与源码矛盾时的宽泛重查与重复运行。
aliases: 跑探针前先确认 import 的是哪份代码, 别把行为测试跑到旧副本上, 探针结果和源码对不上先查执行落点, 仓库带源码快照时钉住 PYTHONPATH, 确认测试跑的是当前源码不是历史版本
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:3319adeb-e84e-4f85-ae10-8306e3d98fb1:832:a60f1df5f344c196db79
evidence_refs: learning:learn:fc3be54ccee1
created_at: 2026-11-06T17:31:44.329864+08:00
updated_at: 2026-11-06T17:31:44.329864+08:00
---
## Trigger
需要用行为探针/测试裁决『当前工作区源码』的断言（如核验外部审查报告的 bug 主张），而仓库内存在同源代码的多份完整副本（.releases/<sha>/、dist、vendored 快照）；或文件名/内容搜索回执显示同一路径在 live 前缀与快照目录下各有一份命中。

## Discriminator
搜索/定位回执中同一文件路径出现多份命中（1 份 live src/ + N 份快照目录），这一事实在跑任何探针之前就已可见；或探针结果与刚直读的 live 源码相矛盾。任一事实都把搜索空间缩成一个未知量：探针实际执行的是哪份副本。

## Short path
- 开局定位时若回执出现同路径多副本命中，记下 live 树精确前缀（如 src/），此后锚点核验只读该前缀，快照命中仅作历史参考
- 运行任何 import 本项目代码的探针/测试前，先执行一行命令打印目标模块 __file__（或以 PYTHONPATH=<live前缀> 固定），确认解析落点
- 落点与被审 HEAD 的 live 树一致后，才把探针红绿、回执行号作为对该代码的裁决依据；测试套件在同一钉扎环境下运行
- 若探针输出与刚读过的 live 源码矛盾，第一反应是复查执行落点，而不是重读源码、换探针写法或扩大搜索

## Stop conditions
- 落点已确认指向 live 树（或与审查对象一致的指定副本），且探针输出与所读源码版本一致，即可采信结果并停止环境排查

## Verification
- 探针前打印的 __file__/sys.path 前缀与 git rev-parse HEAD 及本次所读文件属于同一份代码
- 结论中引用的行号、断言对象与实际执行的副本逐一对应，无跨副本混引

## Counterexamples
- 任务本身就是审计某个历史 release 快照——真值是被审快照而非 live 树，落点应钉在快照上，live 树反而是干扰
- 工作区以 editable 安装单一指向 src 且无快照目录——一次落点确认即可，无需每次钉扎
- 快照目录只含构建产物、无可 import 的包结构——import 解析不过去，静默分叉风险不存在，不必预检
