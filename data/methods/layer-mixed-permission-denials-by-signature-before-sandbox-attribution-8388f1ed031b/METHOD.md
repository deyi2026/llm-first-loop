---
method_id: layer-mixed-permission-denials-by-signature-before-sandbox-attribution-8388f1ed031b
name: layer-mixed-permission-denials-by-signature-before-sandbox-attribution
description: 多种权限拒绝症状并存（或用户问『是不是沙箱』）时，第一个未知量是『有几层机制』而不是『哪条证据能解释全部』。按错误签名分区：带沙箱横幅的 shell EPERM → workdir 参数锚定的写白名单层；工具级 scope 错误码（非 shell 输出）→ 工具的 workspace 根绑定层，治理根在 workspace-root 类 env 变量里一查即得，换措辞搜 evidence 搜不到；stderr 的 can't create 落在 $TMPDIR → 临时目录恒拒层，与目标路径可写性无关。每层分别路由修复通道：workdir 重锚、TMPDIR=/tmp、scope 属架构配置只能建议交用户；无 [安全硬阻断] 标记的 EPERM 不走提权/审批接口。与 workdir 探针卡互补：那张解单层写边界，本卡管多签名分层归因与通道路由。
aliases: 是不是沙箱怎么判断, 权限拒绝先分层再归因, 写不进去和读不到是不是一回事, 提权申请什么情况才该提, 临时文件创建被拒怎么办
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:6e7b4358-a1b8-4e23-a99c-931d6e86bee2:389:be205affe9a7fcf49723
evidence_refs: learning:learn:955ed0fdd270
created_at: 2026-10-28T11:13:27.343748+08:00
updated_at: 2026-10-28T11:13:27.343748+08:00
---
## Trigger
多种权限拒绝症状同时出现（shell EPERM+沙箱横幅、工具级 scope 错误码、指向系统临时目录的 can't create），或用户用『是不是沙箱/权限问题』对既往失败要求单一归因时

## Discriminator
三条签名在当时回执里即可区分：(1) shell 输出里的 Operation not permitted 且回执带沙箱横幅 → 沙箱写白名单；(2) 工具级错误码（如快照/读写工具的 scope mismatch）不是命令输出 → 工具根绑定，其定义在 workspace-root 类 env 变量；(3) 失败路径落在 $TMPDIR 而非目标文件 → 临时目录恒拒。签名不同即机制不同，不能互相解释，也不能共用一个修复通道。

## Short path
- 先列签名清单：从已有回执/证据提取全部失败形态并按三分法分区，不急于合并成一个『沙箱』解释
- 每层读一手治理根：env 中的 workspace 根变量、工具调用的 workdir 参数、回执横幅声明的允许面；对工具级错误码不再换措辞搜 evidence（工具层错误不是命令观测，存不进证据库）
- 一次有界探针矩阵验证两个假设：唯一变量 workdir，路径覆盖 目标目录/$TMPDIR//tmp 三类
- 按层路由修复：workdir 重锚解决 shell 写；TMPDIR 重定向解决 patch/mktemp 类临时文件失败；工具 scope 覆盖面是架构配置只能提变更建议交用户；EPERM 不带硬阻断标记时提权/审批接口不适用
- 回答用户时按层命名机制，显式纠正把两层揉在一起的表述，并把每层修复与授权边界一一对应

## Stop conditions
- 每个失败签名都有机制解释且对应修复通道已明确，即停止补充探针
- 探针矩阵每格结论（翻转/恒拒）已取得，不再重复同类路径探测

## Verification
- 同一目标目录在两种 workdir 下可写性翻转 → 证明白名单锚定 workdir 参数
- $TMPDIR 在全部 workdir 下均 DENIED 且 mktemp 复现同样失败 → 证明临时目录恒拒独立于目标可写性
- 工具 scope 错误与 env 显示的根未覆盖目标路径相一致 → 证明是根绑定而非沙箱拒绝

## Counterexamples
- 仅单一签名（纯 shell EPERM、无工具级错误码、无临时目录路径）时不必分层，直接用单层 workdir 探针方法
- stderr 的 can't create 路径就是目标文件本身而非系统临时目录 → 是目标可写性问题，不引入 TMPDIR 层
- 工具报 scope 错误但 env 根实际覆盖目标路径 → 是路径拼写/相对化错误，不是分层架构问题
- 回执明确带 [安全硬阻断] 标记 → EPERM 归因失效，提权/审批通道才是正确路由
