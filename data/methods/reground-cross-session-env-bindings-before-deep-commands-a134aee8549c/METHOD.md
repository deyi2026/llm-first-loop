---
method_id: reground-cross-session-env-bindings-before-deep-commands-a134aee8549c
name: reground-cross-session-env-bindings-before-deep-commands
description: 跨会话/记忆携带的环境绑定（绝对路径、主机名、系统数据目录位置）在本会话首次使用前是假设而非事实：先用一次廉价观察（pwd、ls 仓库根）重接地；需要定位系统真实数据目录时，沿代码中构造该路径的解析模块（config/paths）这条边走，而不是按顶层目录名猜测。本集首条命令直接复用先前会话的他人 home 绝对路径，连败两次后升级为全盘 find /（返回误导性临时克隆），又按目录名误猜 methods/ 并触发一次 60s 超时；而这些都可用一次 pwd + 调用点追踪避免。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:72:8235e0691e3ecabede11
evidence_refs: learning:learn:f1e0b2521b82
created_at: 2026-10-17T23:28:13.970404+08:00
updated_at: 2026-10-17T23:28:13.970404+08:00
---
## Trigger
准备在命令中使用来自先前上下文/记忆的绝对路径、主机名或数据目录位置，而本会话尚未做过任何文件系统观察（连 pwd 都没有）；或目标目录位置未知、存在多个同名/相似顶层目录可供按名猜测

## Discriminator
待用事实的 provenance 在发出命令前即可判别：该路径/位置字符串携带与本会话无关的绑定（网络挂载点、他人 home、与当前用户或机器不符的布局），属跨会话记忆而非本会话观察；而当前 shell 的 cwd 与仓库根从未被观察过——一次 pwd;ls 就能把『环境完全未知』缩成『已知根 + 相对路径可达』，无需任何深层命令或全盘枚举

## Short path
- 发出任何深层命令前先 pwd; ls 仓库根：解决『当前环境在哪、目录布局如何』这一未知量
- 相对已知根定位目标代码（ls 目标子树; grep 关键函数/构造器行号），路径参数只消费上一步已暴露的事实
- 需要系统真实数据目录时，grep 该 store/客户端的构造调用点，读 paths/config 中的解析逻辑，再 ls 解析出的目录并直接统计（卡数、覆盖文件分布）
- 沿已定位代码读准入门与调用注入点，取得用户问题所需全部事实后立即停止；接地已暴露目标结构时不升级为全盘 find，也不按目录名重猜

## Stop conditions
- 真实仓库根已确认且相对路径可达目标代码/数据目录
- 用户问题所需事实（准入条件、真实规模、注入机制）均已从定义处读到
- 仅当 pwd 后目标结构确实不存在时，才升级为限定范围（子树+maxdepth）的 find，而非全盘枚举

## Verification
- 每条深度命令的路径参数都能追溯到本会话已观察到的目录、或解析代码明确给出的目录
- 对数据规模的断言（卡总数、qualification 覆盖数）来自对真实 store 目录的直接统计，而非顶层同名目录或记忆中的数字

## Counterexamples
- 路径在本会话内由工具回执刚刚给出：属 session provenance，直接使用，重接地是浪费调用
- 任务本身就是要核验外部路径/主机是否存在（如审计远端配置）：接地即任务本体，没有可先做的替代步骤
- 环境由 CI/容器配置钉死且路径来自权威配置文件而非模型记忆：配置即真值，无需 pwd 探测
- 纯知识型问题无需执行命令时，不应为『接地』发起无关节点观察
