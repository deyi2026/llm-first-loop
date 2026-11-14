---
method_id: worktree-carries-tracked-tree-scope-own-root-before-release-path-guess-ef76c70cf0cb
name: worktree-carries-tracked-tree-scope-own-root-before-release-path-guess
description: 续跑/交接回执声称框架源码『不在当前 worktree』而钉在外部 release/venv 时，不要把该笔记直接拼成确切路径读取：git linked worktree 必含全部 tracked 文件，该说法只描述运行时 import 解析口径。先对 worktree 根做 scoped 文件名/内容搜索定位父类与 store 定义（默认搜索常排除 .worktrees，已知符号零命中是范围伪影而非缺席）；仅当本树确无该文件或需与 pinned 运行版本逐字一致时，才一次探针确认外部目录布局再精确读取，或用解释器解析实际模块路径，并 diff 两份拷贝标注版本口径。
aliases: 源码不在 worktree 里去哪找, release 目录猜路径提示文件不存在, worktree 里的文件搜索搜不到, 状态回执说依赖源码在 releases 目录, 核对父类实现该读哪个拷贝, 搜出一堆 release 命中不知道用哪个
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:730:e21c0430e942fa8e9158
evidence_refs: learning:learn:17853c5b0474
created_at: 2026-11-13T22:18:27.243654+08:00
updated_at: 2026-11-13T22:18:27.243654+08:00
---
## Trigger
续跑/状态回执把生产或框架源码（父类、store、契约层）钉在外部工件目录（.releases/<hash>、venv、site-packages）并称『源不在当前 worktree』；任务需读该源码裁决缺陷报告或修改子类；或默认工作区搜索对已知存在的符号返回零命中。

## Discriminator
回执已给出 worktree 路径+分支+基线 main：linked worktree 必然物化全部 tracked 文件，因此『源不在 worktree』只能是运行时解析口径、不是文件缺席；且默认搜索范围排除 .worktrees，对已知符号零命中应先怀疑范围伪影而非存在性。

## Short path
- 从状态回执取 worktree 绝对路径；对缺陷符号/文件名做 root=worktree 的 scoped 搜索（零命中先怀疑搜索范围排除，不怀疑文件存在）
- 在 worktree 内定位父类/store/契约文件并直读定义区间，逐项裁决缺陷报告：属实给行号证据，不属实或已被上轮改净则如实回执
- 仅当本树确无该文件（untracked/运行时生成/仅装于 site-packages）或需与 pinned 运行版本逐字一致时：一次 ls/文件名搜索确认外部目录真实布局后再精确读取，或用已成功运行的解释器解析模块 __file__ 拿到权威拷贝
- 两份拷贝并存时 diff 并在结论中显式标注版本口径，避免拿仓库拷贝验证另一个版本的签名/行为

## Stop conditions
- 每个待裁决断言均已对照定义面（直读的签名/schema 行号）得出结论并逐项回执
- 外部工件布局已由一次探针确认；不再对工具已登记『不存在』的路径换拼写重试

## Verification
- 命中文件位于回执声明的 worktree/分支内；涉及运行时行为时与解释器解析路径或 pinned release 比对版本一致性
- 缺陷报告逐项有行号级证据（例如父类方法实为 -> None 时明确回执『该缺陷当前不存在』，而非默认接受报告）

## Counterexamples
- 框架源确实未被仓库 track（运行时注入、生成物、或仅安装在 site-packages）：worktree scoped 搜索必 miss，外部/解释器解析才是唯一路径
- 任务要求与 pinned release（由不同提交构建）逐字一致的运行语义：读 worktree 拷贝会对照错误版本，应以运行解析出的拷贝为准
- 单树仓库且目标目录布局已由先前回执列明：直接精确读取即可，无需前置 scoped 搜索或布局探针
