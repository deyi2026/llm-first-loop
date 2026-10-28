---
method_id: pin-import-site-and-fixture-invariants-before-probing-63acb70a94fb
name: pin-import-site-and-fixture-invariants-before-probing
description: 在含归档快照副本（.releases/、temp、备份目录）且存在多个解释器（系统 python 与 .venv）的工作区里，对刚编辑的代码跑性能/行为探针或 before/after 对比之前，先用压测实际调用的那个解释器回显目标模块 __file__，钉死『这次测的是哪份代码』；再对合成夹具做结构不变量断言（如父子索引无自环、不越界）；基线取自 VCS 只读快照而非工作树。三项任一未钉死，探针 delta 不得归因给代码改动，异常结果先怀疑解析环境或夹具，而不是来回修改实现。
status: active
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:80246fde-e7ed-4d85-a591-1327907b29de:946:ea8f60113c54f7d57965
evidence_refs: learning:learn:3fc487c92ab9
created_at: 2026-10-18T13:37:02.718017+08:00
updated_at: 2026-10-18T23:31:37.840908+08:00
---
## Trigger
工作区同时存在同一包的归档快照副本目录（.releases/、temp、备份）与多个可用解释器（系统 python / venv python），且即将对刚编辑的活跃树代码运行性能或行为探针、before/after 对比，其结果将驱动后续代码决策

## Discriminator
两条当时已可观察的事实：(1) 关于『压测解释器本次 import 哪份代码』尚无任何已观察证据——sys.path 顺序只是从被截断的回执推断出来的，而开场检索已经命中『PYTHONPATH 指向 .releases 快照导致修复无效假阴性』的同型教训，说明该陷阱在本仓库真实存在过；(2) 压测用的是手工合成结构数据（如 parentIndex 数组）且未对其结构不变量（无自环、父索引合法）做过任何断言。任一为真，就先证真测量装置，再相信数值。

## Short path
- 探针前用与压测完全相同的解释器（含相同 venv/PYTHONPATH）执行 `python -c "import 目标模块 as m; print(m.__file__)"`，断言路径落在活跃树 src/ 而非快照副本目录——未知量：这次到底测的哪份代码
- 基线数据从 VCS 只读快照（git show HEAD:path）生成，不读工作树，避免未提交改动或临时文件混入基线
- 对合成夹具加结构前置断言（parentIndex[i] < i、无自环、索引不越界），断言不过先修夹具，不进入实现分析
- 三项钉死后才跑探针并采信 delta；此时若结果仍异常，解析与夹具已被证真，才进入对实现本身的根因分析
- 若第 1 步发现 import 的是快照副本：换解释器/修环境后重跑，此前全部 delta 作废，不据此改任何代码

## Stop conditions
- 压测解释器回显的模块 __file__ 指向活跃树文件，且夹具不变量断言 0 违例，且基线内容与 VCS 快照一致——测量装置已证真，归因成立，停止元验证，进入正常分析
- 已确认工作区无快照副本且仅一个解释器（解析歧义不存在），只需保留 VCS 基线一项后即可直接探针

## Verification
- 用压测 harness 实际调用的同一解释器回显模块 __file__ 并留档；修复前后各回显一次，确认两次都指向同一活跃树文件
- 夹具结构校验输出 0 违例（自环/越界/孤儿计数为 0）
- 基线文件 hash 与 git show HEAD: 产物一致
- 结论回写时注明：归因仅在 import-site、夹具、基线三项证据齐备后成立

## Counterexamples
- 单解释器、无快照副本的干净仓库：无解析歧义，import-site 预检可省，只保留 VCS 基线项
- 探针框架自身 banner 已打印实际加载的源文件路径：该事实已被直接观察，无需另跑回显命令
- 纯只读代码调研（不编辑代码、不做 before/after 归因）：没有 delta 需要归因，整套预检不适用
- 夹具来自真实生产捕获而非手工合成：结构不变量由数据来源保证时，夹具断言降级为可选
