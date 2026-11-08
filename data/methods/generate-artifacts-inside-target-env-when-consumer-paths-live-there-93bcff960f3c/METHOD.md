---
method_id: generate-artifacts-inside-target-env-when-consumer-paths-live-there-93bcff960f3c
name: generate-artifacts-inside-target-env-when-consumer-paths-live-there
description: 跨平台验收（目标行为在 Linux VM/容器等目标环境内执行）且被测产物须用仓库真实代码生成时，把生成步骤放进目标环境执行，而不是在宿主机（如 macOS）生成后搬运。判据：产物的绝对路径引用与加载/消费点是否全部位于目标环境——是则宿主侧生成只增加一次搬运与语义漂移风险（macOS /tmp 为 symlink，会被真实代码的 install-root 校验拒绝），且被测的正是目标平台行为，在目标环境内生成反而更真实。生成中的校验拒绝按目标平台语义裁决：平台差异就迁移执行点，代码缺陷就停下留最小复现。仅当目标环境跑不了生成代码时才回退宿主生成+目标侧重验。
aliases: 在VM里用真实代码渲染unit, 宿主机/tmp软链被安装根校验拒绝, 跨平台验收产物在哪边生成, macOS生成Linux部署产物被拒后搬进虚拟机, 目标平台内执行渲染再验收
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:1633:d668f1e685d674665154
evidence_refs: learning:learn:043bf4779a5c
created_at: 2026-11-08T00:46:46.805069+08:00
updated_at: 2026-11-08T00:46:46.805069+08:00
---
## Trigger
验收/测试必须在另一个平台环境（VM、容器、另一 OS）内执行，且需要用仓库真实代码（含其自身防御性校验逻辑）生成被测产物（unit 文件、部署布局、配置等），产物随后要在该目标环境内被原生机制加载消费。

## Discriminator
产物的路径语义与消费点归属：若产物的绝对路径（install root、ExecStart、unit search path 等）全部解析到目标环境内部，而宿主与目标平台的文件系统语义存在已知差异（如 macOS /tmp→/private/tmp 为 symlink、Linux /tmp 为真目录），则宿主侧生成注定要二次搬运、且可能被真实代码的平台校验拒绝——唯一合理生成点是目标环境本身。任务书若已写明路径全在目标侧（/tmp 假数据、$XDG_RUNTIME_DIR），这一判据在动手前即可成立，无需先撞一次失败。

## Short path
- 只读短探针确认目标环境可用（VM 响应、systemctl --user/runtime、目标名称无冲突），不把宿主侧观察当作目标实况
- 把真实生成代码（模块+最小驱动脚本）打包传入目标环境，在目标环境内执行生成，install root 用目标平台的真实路径
- 生成中触发的任何校验拒绝按目标平台语义裁决：平台差异→迁移执行点了事，不视为被测代码缺陷；代码缺陷→停住、留最小复现再汇报
- 产物直接在目标环境加载并跑验收断言；结束按清单清理并核实无残留

## Stop conditions
- 产物已在目标环境内由真实代码生成、并被目标环境原生机制（如 systemd-analyze verify / systemctl show）加载验证通过
- 确认目标环境无法运行生成代码（缺运行时、只读）时停止迁移方案，显式改走宿主生成+目标侧重验并记录该回退

## Verification
- 生成产物中的每个绝对路径都能在目标环境内解析且语义正确（未经宿主路径翻译）
- 若宿主侧生成曾被拒，确认拒绝换平台后消失（平台差异）而非换参数后消失（代码缺陷）

## Counterexamples
- 被测对象就是宿主平台行为本身（如『宿主 symlink 根路径必须被拒绝』是验收项）→ 必须在宿主执行，搬进目标环境反而测不到
- 生成是纯文本模板、路径全由目标侧参数注入，且宿主生成有明确收益（构建缓存、工具链只在宿主）→ 宿主生成可接受，但搬运后必须在目标侧重新 verify
- 目标环境无法执行生成代码且无法安装运行时 → 只能宿主生成，本方法不适用
