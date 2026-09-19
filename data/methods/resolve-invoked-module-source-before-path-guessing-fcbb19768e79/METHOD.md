---
method_id: resolve-invoked-module-source-before-path-guessing-fcbb19768e79
name: resolve-invoked-module-source-before-path-guessing
description: 需要审查一个刚成功执行过的模块/工具的内部逻辑时，把调用命令本身当作源码定位的 provenance edge：先用同一解释器机械解析 dotted module 到源文件（importlib/__file__），再做关键词 grep 与定点阅读。不要凭目录布局直觉猜物理路径；猜错一次后也不要立即升级为仓库级文件名枚举——'调用成功'本身就是该模块可导入的证据，一次解释器查询可同时消解'路径不存在'与'多个同名文件'两类歧义。猜测+搜索的候选空间是整个仓库，模块解析是确定性的单步。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e8e83cd1-6d33-4a6b-b29b-56131638f5d7:761:8303b189a425067e75c4
evidence_refs: learning:learn:b04978e4cfb6
created_at: 2026-09-19T02:04:16.644349+00:00
updated_at: 2026-09-19T02:04:16.644349+00:00
---
## Trigger
需要读取一个刚通过 `python -m <pkg>.<mod>` 或已知入口成功执行过的命令的源码/校验逻辑，而其确切文件路径尚无任何 provenance 支撑。

## Discriminator
第一条输出里 `.venv/bin/python -m llm_loop.runtime.service_control` 刚在 code_root 下执行成功——该 dotted module 在此解释器中可导入，源文件路径可由一次 `importlib`/`__file__` 查询机械确定；相对地，凭布局直觉猜出的路径是未经验证的假设，其 'No such file or directory' 回执是精确否定而非瞬时故障。

## Short path
- 明确未知量：publish 为何接受非预期 HEAD，校验逻辑在哪个文件哪些行。已见事实：`python -m llm_loop.runtime.service_control` 刚用该 venv 成功执行。
- 用同一解释器机械解析：`.venv/bin/python -c "import llm_loop.runtime.service_control as m; print(m.__file__)"` → 得到精确源文件路径（单步消解路径不存在与同名歧义两类问题）。
- 在解析出的路径上 grep 目标关键字（git_head / rev-parse / porcelain / def publish）取行号。
- read_file 只读命中的行区间（如 1131-1225）。
- 以 file:line 引用陈述真实校验清单，机制确认即停止；不重试路径猜测、不做仓库级枚举。

## Stop conditions
- 已从机械解析出的源文件读到目标逻辑，并能给出可核对的 file:line 引用。
- 解析查询失败且错误明确（如装为无源码 wheel、解释器不一致）时，只转一次精确文件名搜索后即收敛，不重复路径猜测。

## Verification
- 解析出的 `__file__` 对应的模块限定名与调用串一致（llm_loop.runtime.service_control）。
- grep 在该文件命中目标关键字后才进入阅读；最终结论附 file:line，用户可独立核对。

## Counterexamples
- 模块在当前解释器不可导入，或安装为无源码 wheel（`__file__` 指向 site-packages 而非仓库源码）——方法失效，应回退文件名搜索或 `pip show -f`。
- 目标本就是全仓库发现（'所有与 X 相关的文件'，或需比较多个同名候选）——文件名搜索是正确工具，不应被本方法替代。
- traceback、日志或配置已直接给出精确文件路径——直接 grep/read，解析一步多余。
