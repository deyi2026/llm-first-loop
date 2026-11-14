---
method_id: interpreter-resolves-imported-module-path-and-mutation-scope-273efd38b676
name: interpreter-resolves-imported-module-path-and-mutation-scope
description: 要读或改一个已被本仓库代码 import 且先前成功运行过的模块（框架基类/store/dispatch 层）的权威语义时，不要把 dotted import 名拼成猜测的仓库相对路径去 read/grep。用已成功运行该模块的解释器（项目 venv 优先）执行一次 import 并打印 __file__/find_spec，把『真实文件在哪』一次钉死；即使 import 因解释器版本失败，traceback 打印的 File 行本身就是答案。解析出的位置还同时决定修改落点：若在共享只读安装且任务禁改全局语义，则在 worktree 内做 scoped 子类 override，绝不编辑共享源。
aliases: 为什么仓库里搜不到要改的包, import报错堆栈里已经印了文件在哪, 被pip装走的依赖源码去哪读, 框架基类不在工作树里怎么定位, 路径不存在已被登记还换姿势继续猜, 改不动共享安装里的实现就在树内重载
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:568:9304962ebc6ff105290f
evidence_refs: learning:learn:11555637531d
created_at: 2026-11-13T21:57:01.497120+08:00
updated_at: 2026-11-13T21:57:01.497120+08:00
---
## Trigger
需要理解或修改某依赖模块的生产语义；该模块已被刚读过的树内文件顶部 import，且有冻结回执/测试通过记录证明这些文件此前真实运行成功；其源码位置未知或疑似不在当前工作树（工作树里只有调用方没有被调方）。

## Discriminator
刚读的脚本/测试顶部 import 已给出模块名，且回执证明这些文件曾成功运行——即模块在某个运行环境里可解析，dotted 名不等于仓库相对路径；同一条 python -c 的失败回执（版本级 ImportError）也会在 traceback 中打印解析后的真实文件路径，失败回执即位置答案。

## Short path
- 识别目标模块 M 已被树内文件 import 且该文件曾成功运行 → 唯一未知量是 M 的真实文件位置，不是『仓库里哪个目录像』
- 用该运行环境的解释器执行 `python -c "import M; print(M.__file__)"` 或 find_spec；版本级 ImportError 也算成功——traceback 的 File 行已给出路径
- 直读解析出的真实文件中目标符号（如 settle/reserve）的完整生产语义
- 若解析路径落在可写 worktree 之外（共享安装/release 目录）且任务禁改全局语义 → 修改落点改为树内子类/override，共享源保持只读
- 若任何解释器都 ModuleNotFoundError → 先把未知量切成『项目权威 venv 在哪』解决后回到第 2 步

## Stop conditions
- 已从解释器解析出的真实文件读到目标符号完整生产语义，且修改落点已确定（树内或明确不改）
- 共享源确认只读禁改，本地 override 已被测试实际调用并生效

## Verification
- 打印的 __file__（或 traceback File 行）与此前运行回执中出现的安装路径一致
- 改动后共享安装源文件内容/哈希未变；测试断言走的是 override 类而非原类

## Counterexamples
- 仓库 vendored 了同模块源码且任务要求改本分支副本：环境安装副本 ≠ 分支副本，应以分支内路径为准而非 import 解析结果
- 目标没有可 import 的名字（按文件名/布局找产物）：应走目录 ls/scoped search，import 解析无从下手
- 只需知道某符号在哪些调用点出现：scoped grep 即可，无需解析模块安装位置
