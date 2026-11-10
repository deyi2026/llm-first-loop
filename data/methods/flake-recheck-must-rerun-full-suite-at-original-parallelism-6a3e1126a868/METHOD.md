---
method_id: flake-recheck-must-rerun-full-suite-at-original-parallelism-6a3e1126a868
name: flake-recheck-must-rerun-full-suite-at-original-parallelism
description: 并行测试套件出现失败、需判定 flake 还是真回归（尤其门禁要决定豁免/阻断）时，判别力只来自『保持原调度条件的同构复跑』，不来自 diff↔失败用例的 import 耦合启发式，也不来自缩小复跑：--dist loadfile 下同文件用例在单 worker 内串行执行，只复跑失败文件/用例改变了产生失败的全局并发条件，『串行绿』对负载相关回归无判别力。正确复核：先做廉价 serial/单用例复跑定位，再以完全相同的并行参数复跑一次全量套件——再红即真回归阻断，绿才可按 flake 记录条件放行。判定器上线前用应拦/应放双探针验收。
aliases: 串行过了并行还是红怎么判, 只复跑挂掉的文件算不算复现, flake和真回归靠什么判别, xdist同文件其实在单worker串行, 假红豁免前再跑一次全量, 复现并发失败别改调度条件
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:1895:31e9de8f4cfe6edd6d25
evidence_refs: learning:learn:228653b51f27
created_at: 2026-11-10T22:05:23.140926+08:00
updated_at: 2026-11-10T22:05:23.140926+08:00
---
## Trigger
并行测试套件（pytest-xdist / -n / --dist loadfile 等）出现失败，需要判定 flake vs 真回归并决定门禁豁免或阻断；或正在设计/加固 flake 自动判定器，且倾向用『diff 与失败用例的代码耦合』启发式或『只复跑失败文件』来节省时间。

## Discriminator
跑套件的命令行/配置当时已写明调度分配模式：--dist loadfile ⇒ 同文件用例在单 worker 内串行执行、并发只存在于跨文件的全局调度。由此在动手设计判定器之前即可推出：产生失败的最小保真复现单位是整个并行套件；任何缩小到失败文件/用例的复跑都必然改变被检验的条件，串行绿不构成『假红』证据。

## Short path
- 读门禁/CI 命令行拿到调度参数（-n、--dist）——未知量：产生这次失败的最小保真复现单位是什么？
- 由分配模式直接推出保真单位（loadfile ⇒ 全量并行套件），复核方案定为：先廉价 serial/单用例复跑做定位，再以逐字相同的并行参数复跑一次全量套件。
- 同构全量复跑再次出现同一失败 ⇒ 负载相关真回归，阻断并修复；复跑绿 ⇒ 才可按 flake 记录种子/条件后放行。
- 不构建 diff↔失败用例 import 耦合类代理判据：代码邻域 ≠ 运行时并发邻域，调度耦合是全局的。
- 判定器落地前双探针验收：应拦探针（仅全局并发下失败的用例）必须让门禁 exit=1；应放探针（无注入）全链路 exit=0。

## Stop conditions
- 一次同构全量并行复跑后即出判定（再红=阻断，绿=flake 放行并记录条件），不追加 N 次全量复跑
- 单用例或 serial 复跑已稳定复现同一失败（确定性失败）时，在定位步即终止，无需全量复跑

## Verification
- 应拦探针：注入仅在全量并行下才会失败的用例，最终门禁 exit=1——旧的『serial 绿即放行』判据必须在此输入上被推翻
- 应放探针：无注入树全链路门禁 exit=0，正常路径不误伤
- 复核命令与首轮逐字同参（同 -n/--dist，种子可得时同种子），否则复跑不构成同构证据

## Counterexamples
- 确定性逻辑失败：单用例复跑稳定红，直接定位修复即可，数百秒级的全量并行复跑纯属浪费
- 两个特定用例间的端口/临时文件冲突：最小复现单位是这两个用例的组合，全量套件因调度随机性反而不稳定复现
- 套件本身串行或单 worker 运行：不存在可被缩小复跑破坏的并发条件，缩小复跑无损
