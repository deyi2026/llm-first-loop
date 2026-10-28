---
method_id: interpreter-resolve-source-and-config-paths-under-relocated-installs-0e82fcc12b3d
name: interpreter-resolve-source-and-config-paths-under-relocated-installs
description: 当一个 CLI 包能通过 venv / `python -m pkg.mod` 成功启动（产出应用级输出而非 ModuleNotFoundError），但你却找不到它的源码或配置时：不要先做 cwd 相对 grep 或全盘文件搜索，先用同一解释器 `python -c "import pkg; print(pkg.__file__)"` 一步定位真实源码路径（发布快照、site-packages、非 editable 安装下源码常不在 cwd）。同理，若启动门槛报缺少必填 env 变量、而项目 .env 中该键值实际非空存在，嫌疑不在配置内容而在 loader 的默认路径推导（常按 __file__ 向上 N 级解析，在快照布局下指向不存在的位置）：读 loader 代码确认根因后，用其公开 API 显式传正确路径绕过，不改代码、不反复重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a997d0bf-003d-4335-ade1-4f3981aa79e1:213:ff44768dda6c0a094c25
evidence_refs: learning:learn:edb008812429
created_at: 2026-10-17T09:03:40.116080+08:00
updated_at: 2026-10-17T09:03:40.116080+08:00
---
## Trigger
需要查看或调用一个已验证可运行的 Python 包的源码/CLI 子命令语法，但 cwd 下没有该包目录（发布快照、.releases/<sha>/src、site-packages 等重定位安装）；或 CLI 启动门槛报缺少必填 env/config，而项目 .env 中该键确实存在且值非空。

## Discriminator
两个当时即可观察的事实各自缩窄搜索空间：(1) 启动命令产出的是应用级错误而非 ModuleNotFoundError → 解释器能 import 该包 → 真实源码路径距一条 pkg.__file__ 查询仅一步，cwd 假设和全盘搜索都是错方向；(2) 进程环境变量为 UNSET 而项目 .env 中该键值长度 > 0 → 缺的不是配置本身，而是 loader 的默认查找路径（按 __file__ 推导，在重定位布局下指错位置）。

## Short path
- 需要源码/子命令语法时，第一步用运行它的同一解释器解析 pkg.__file__ / os.path.dirname(pkg.__file__)，锁定真实源码根（未知量：源码在哪）
- 在解析出的真实路径上 grep/sed 子命令分发处与实现函数，取确切拼写和参数顺序（未知量：语法契约）
- 若被启动门槛挡：先只读验证项目 .env 中该键存在且非空（如打印 value 长度），再直接读 loader 的默认路径推导代码定位根因，而非重试或怀疑配置内容（未知量：配置为何未被加载）
- 绕过而不改代码：调用 loader 自身 API 显式传正确路径（或临时 export 该变量），并先用一个只读子命令（如 list 类命令）确认门槛已过
- 执行状态变更命令前，从权威存储只读核对目标记录 ID 与当前状态；执行后重读同一存储确认状态迁移完成

## Stop conditions
- 源码路径已由 import 解析且子命令语法已从分发代码原文确认
- 配置未加载的根因已在 loader 代码中定位（默认路径指向不存在的位置），且显式路径绕过后只读命令成功
- 状态迁移已通过重读权威存储确认，而非仅凭命令自身 stdout

## Verification
- 解析出的 pkg 路径与启动所用的 venv/解释器同属一个 import 体系（同一环境查询所得）
- 显式路径绕过后，先跑一个只读子命令验证不再报缺失 env，再做状态变更
- 最终结果以权威存储（audit/record 文件）重读为准，与命令回执相互印证

## Counterexamples
- 普通开发检出、源码就在 cwd：cwd grep 本来正确，import 解析是多余一步
- 该 env 变量在 .env 中确实为空或缺失：门槛报错是对的，应补配置值而非追查 loader 路径 bug
- 解释器报 ModuleNotFoundError（包对该环境不可 import）：此时目录/全盘搜索才是合理发现手段
- 一次性脚本未打包安装：没有 pkg.__file__ 可解析，方法不适用
