# LFL 安装与升级

此文描述安装分发 MVP。只有包含本变更并通过成品验收的 Release 才提供下述成品；
已有源码安装继续使用原入口。当前不承诺桌面安装器、自动更新、包仓库上架或 Windows 运行支持。

## 使用 wheel

安装 uv 后，下载目标 Release 的 wheel 与 SHA256SUMS，核对文件摘要。
将 VERSION 替换为实际下载版本；用户侧不需要 Git、Node 或开发依赖。

~~~bash
uv tool install --python 3.13 ./llm_first_loop-VERSION-py3-none-any.whl
lfl --version
lfl check-install
lfl paths
lfl doctor
~~~

check-install 校验当前资源文件与包内清单一致性；这不是发布者签名或来源可信认证。
uv 会为应用建立独立 Python 环境；wheel 的运行依赖由包管理器安装，
仓库 uv.lock 不自动约束这次安装的全部传递依赖。

选择模型服务后，配置其 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL，
或使用 --config 指定自己的环境配置文件。不要把真实凭证写进安装包。

~~~bash
lfl --config /absolute/path/to/lfl.env chat "你好"
lfl --config /absolute/path/to/lfl.env web
~~~

## 首次使用诊断（P1 doctor）

~~~bash
lfl doctor
lfl doctor --json
lfl --config /absolute/path/to/lfl.env doctor --json
~~~

doctor 是**离线、只读**预检：不装配 Engine、不访问 Provider、不启动/重启服务、
不创建用户目录、不写入环境变量。检查安装包资源清单（源码运行时标明不适用）、
配置文件的存在与可读取性、必需模型配置键是否设置、数据目录和工作目录可用性、
以及自定义技能/文档/界面资源目录是否有效。

JSON 输出遵循 `lfl.doctor/v1`，含 `ready/status/read_only/sources/checks`；
配置项只报告来源（命令行/进程环境/配置文件/默认），**绝不回显配置值、密钥或配置路径**。
每条诊断使用 `pass/warn/fail` 与可执行修复建议；全部通过返回退出码 0，
有任何待配置或失败项返回 1，非法命令参数返回 2。

doctor 不能证明远端密钥有效、模型可调用、Web 正在运行，也不是来源签名验证。
诊断通过后仍需由用户明确选择启动方式；doctor 不自动修复配置或覆盖旧数据。

## 首次使用配置向导（P1 init）

本命令仅在包含 P1 init 功能并完成成品验收的版本中提供。先在本地预览：

~~~bash
lfl init --plan
lfl init --plan --json
lfl init
~~~

`--plan` 始终离线只读、可在脚本/非交互环境运行；`--json` 只与 `--plan` 搭配，
输出配置来源、是否已有文件与需要的键，不输出配置值或绝对路径。`lfl init` 仅在
终端交互时运行，首次输入 `yes` 才开始收集，API Key 通过隐藏输入读取，第二次
明确输入 `yes` 才会尝试写入。默认只新建应用根 `.env`，已存在或为符号链接时拒绝
覆盖；通过 `--config` 可指定**父目录已存在**的新文件。路径上的合法祖先符号链接将先解析成真实父目录，写入前显示实际目标供确认；目标文件自身若为符号链接仍拒绝。配置以 `0600` 模式原子创建，
应用默认新建目录以 `0700` 模式创建。无终端、取消、非法输入或目标竞争失败时
不会覆盖任何已有配置。出现残余临时目录/文件时应停止，切勿自动清空用户数据。

向导不自动验证远端密钥、不启动 LLM、Web、Learning 或 Feishu，也不安装扩展。
完成后仍应自行运行 `lfl doctor`，并明确选择启动 `lfl chat` 或 `lfl web`。

web 复用原有 Web 入口、认证与生命周期清理，默认绑定本机环回地址。
运行目录与用户工作目录分别绑定，身份守卫继续生效。
数据目录与现有业务路径显式分开；这条独立应用启动路径不替代源码工作区的受管发布/重启流程。

## 数据与资源

- macOS 默认应用目录：~/Library/Application Support/LFL。
- Linux 默认应用目录：$XDG_DATA_HOME/lfl；未设置时为 ~/.local/share/lfl。
- LFL_HOME 可显式指定应用目录。默认持久数据在其 data/ 下，默认配置文件为其 .env。
- 全局参数置于命令名之前；命令名之后的参数保持对应子命令原有语义。
- --data-dir 优先于 DATA_DIR/LFL_DATA_DIR 与默认目录；--workspace 优先于 LFL_WORKSPACE_ROOT，
  未指定工作目录时使用调用时的当前目录。
- --config 优先于 LFL_ENV_FILE 与默认配置。进程已有环境变量优先于文件值。
  配置文件内相对路径按配置文件目录解析，命令行相对路径按调用目录解析。
- 应用内部的技能、方法种子、必要规则文档及编译后的界面放在只读包资源区。
  用户可通过 SKILLS_DIR、METHOD_SEED_DIR、DOCS_DIR、UI_V2_DIR 指定自己的资源位置。
- paths 仅展示选定的路径绑定，不展示模型密钥。check-install 不加载用户配置或启动模型。

内置文档只包含 ai_rules、configuration、DEVELOPMENT_REPAIR_SAFETY 和 card-lifecycle；
完整开发设计与历史报告仍查阅源码仓库。运行产生的会话、经验、方法候选与凭证不随应用分发。

## 更新与卸载

对已下载并核验的新 wheel，再执行 uv tool install --python 3.13 <wheel路径>，
然后执行 lfl check-install 与 lfl --version。数据目录在应用虚拟环境之外，更新不搬迁该目录。
本 MVP 不自动迁移数据，不承诺跨不兼容数据格式的降级恢复。

### P1 升级前检查、冷备份与隔离恢复

在提供此 P1 功能且完成安装成品验收的版本中，可以使用以下**离线**工作流：

~~~bash
lfl upgrade --plan --json
lfl backup --plan --json
# 先从运行态核对并停止受影响 Web/Feishu/Learning 与其他持久化写入进程
lfl backup --to /absolute/private/snapshots/before-upgrade --confirm-services-stopped
lfl backup verify --from /absolute/private/snapshots/before-upgrade --json
# 仅恢复到一个从未存在的新位置，不覆盖生产 data 或 .env
lfl rollback --from /absolute/private/snapshots/before-upgrade --into /absolute/private/staged-restore --confirm-services-stopped
~~~

`--plan` 与 `verify` 不读取网络、不修改软件环境、不自动启动模型或服务。冷备份及隔离
恢复必须显式确认受影响服务已停止；**该参数只是操作者声明，程序尚未证明服务真的
停止**，运行中的数据复制可能不一致。先通过现有运维/服务控制通道确认停机并协调
其他写入者，必要时暂缓操作。备份目录和恢复目录必须以前从未存在且父目录可访问，
不会强制覆盖。备份仅包括配置、选定数据及可解析的 Experience/Method 根，
始终标记 `selected_roots`，不自称全量；相应独立根、schema 兼容性及未知写入者
需要管理员额外核对。

快照内的 `.env` 和用户数据为**未加密明文**，权限限制为 `0700` 目录、`0600` 文件；
不得放在公开共享位置、随 wheel 发布、上传不可信平台。SHA256 验证检测快照
意外损坏，并**不能证明备份的真实来源、发布时间或完整信任链**。manifest 只有在
完成备份后才出现；中断时遗留的私有目录不可作为可恢复快照，不会被自动清理。

隔离恢复只建立一个新的可检查副本；不会自行运行 `uv tool install`、删除既有
用户目录、降级数据库、修改 service_control 的期望版本，或重启服务。若确实需要
回退软件，先核验先前 wheel/SHA 与数据格式相容性，再单独批准包安装、恢复目标
切换和受控服务启动；不保证旧程序能读新数据。

uv tool uninstall llm-first-loop 移除应用环境，保留独立数据目录。
用户需要删除数据时，应先备份并明确选择目标目录。

扩展更新按组件类型与名称保留原启停状态。全部组件已禁用的安装，更新新增组件也保持禁用；
部分启用安装中的新组件保持既有默认策略。插件实例数据在更新与卸载安装记录时保留。
本变更不新增插件凭证授权、跨版本依赖求解或完整插件管理界面。

## 构建与验收

构建者需要 Node 与 Python 构建环境：

~~~bash
cd webui
npm ci --ignore-scripts
npm run build
cd ..
uv build
python scripts/verify_install_distribution.py --wheel dist/llm_first_loop-VERSION-py3-none-any.whl
~~~

标准构建同时生成 wheel 与 sdist，sdist 携带已编译界面，重新构建 wheel 不需要 Node。
editable 开发安装保留源码布局，不要求预先构建界面。

成品脚本创建不共享 site-packages 的临时虚拟环境、安装声明依赖，从非 Git 目录验证入口、
资源清单、存储目录和真实 Web health/UI/静态资源。测试禁用 Learning 与 Reflection，
仅使用虚构凭证，Python 网络探针拒绝 Provider 与外部连接；测试只停止自己启动的 Web 进程。
Release 工作流完成这些步骤后，向原有待人工确认的 Release 草稿附加成品、验收报告和校验和。

自动升级执行/原地恢复、桌面安装器、OCI 和生态目录仍为后续执行单元；
冷备份/验证/隔离恢复的 P1 命令不等同于自动生产升级或发布功能。
