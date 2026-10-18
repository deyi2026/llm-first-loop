# LFL 安装与升级

此文描述安装分发 MVP。已有源码安装继续使用原入口。当前 macOS `.pkg` 仍是本地
未签名候选，**尚无可公开发行的签名/公证安装包**；不要安装内部候选或绕过 Gatekeeper。

## 普通 macOS 用户：保持安装简单

正式签名版发布后，正常用户只需要：

1. 下载单个 `LFL-VERSION-macos-arm64.pkg`，双击打开 macOS 安装器。
2. 按系统安装器提示点“继续/安装”完成安装；不需要自己准备 Python、uv、Git 或 Node。
3. 双击 `/Applications/LFL Start.command`，在终端向导中填写模型服务地址、模型名（可留空）和隐藏输入的 API Key。最后只需确认一次 `yes`；配置通过本机诊断后，向导会启动 Web。

这条路径不要求用户手动运行升级、备份、签名或验收命令。若下载页尚未提供正式签名版，
请暂缓公开安装，不要把下方的 wheel/开发者流程当作普通用户安装步骤。安装器默认
只安装应用，不自动删除用户数据；卸载应用也保留独立用户数据目录。

## 高级/临时备用：使用 wheel（需 Python 3.13 和 uv）

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

**首次启动建议直接运行 `lfl start`**：如果尚未配置，先调用现有 `lfl init`
交互向导；随后调用 `lfl doctor` 复核，就绪后使用原有 Web 启动入口。
`start` 仅在最后写入前要求一次明确确认，不自动联网验证密钥，也不新建服务控制平面。
再次运行 `lfl start` 可复用现有配置；Web 仍遵循原有认证、地址和工作目录绑定，
按 Ctrl+C 退出。`lfl start --plan` 或 `lfl start --plan --json` 可离线只读预览，
不会启动模型或 Web。非交互环境缺配置时明确拒绝，绝不静默生成密钥。

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
终端交互时运行，先填写模型服务地址、可选模型名和隐藏输入的 API Key，再查看摘要，
只在最后输入一次 `yes` 才会尝试写入。默认只新建应用根 `.env`，已存在或为符号链接时拒绝
覆盖；通过 `--config` 可指定**父目录已存在**的新文件。路径上的合法祖先符号链接将先解析成真实父目录，写入前显示实际目标供确认；目标文件自身若为符号链接仍拒绝。配置以 `0600` 模式原子创建，
应用默认新建目录以 `0700` 模式创建。无终端、取消、非法输入或目标竞争失败时
不会覆盖任何已有配置。出现残余临时目录/文件时应停止，切勿自动清空用户数据。

单独运行 `lfl init` 只配置，不自动验证远端密钥、不启动 LLM、Web、Learning 或 Feishu，
也不安装扩展。通过安装器启动的 `LFL Start.command` 使用 `lfl start`：配置写入后先做
本机诊断，只有就绪才启动 Web；若只想配置而不启动，请直接运行 `lfl init`。

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
lfl upgrade --plan --candidate /absolute/private/llm_first_loop-0.6.33-py3-none-any.whl --expected-sha256 SHA256 --json
lfl upgrade --plan --candidate /absolute/private/llm_first_loop-0.6.33-py3-none-any.whl --expected-sha256 SHA256 --require-trust --json
lfl backup --plan --json
# 先从运行态核对并停止受影响 Web/Feishu/Learning 与其他持久化写入进程
lfl backup --to /absolute/private/snapshots/before-upgrade --confirm-services-stopped
lfl backup verify --from /absolute/private/snapshots/before-upgrade --json
# 仅恢复到一个从未存在的新位置，不覆盖生产 data 或 .env
lfl rollback --from /absolute/private/snapshots/before-upgrade --into /absolute/private/staged-restore --confirm-services-stopped
~~~

`--plan` 与 `verify` 不读取网络、不修改软件环境、不自动启动模型或服务。

升级 `--candidate` 检查仅读取本地 wheel、核对 SHA256、包身份和版本，且始终
报告 `stage_eligible=false`、`candidate_trusted=false`；即便完整性通过也**绝不
证明可信发布者来源、数据格式兼容、服务已停止或允许安装**。`--require-trust`
和 `--require-data-compatibility` 在没有独立权威证明时必定安全拒绝，不会执行
`uv`、访问网络、创建 staging 或切换应用程序。正式自动升级的 `prepare`、
`commit`、`abort` 尚未实现，不能使用这些命令开展生产切换。

**可用的升级前隔离候选管理（无需停机）：**

~~~bash
lfl upgrade --stage --candidate /absolute/private/llm_first_loop-VERSION-py3-none-any.whl --expected-sha256 SHA256 --json
# 记录输出的 24 位 stage_id：
lfl upgrade --verify-stage --id STAGE_ID --json
lfl upgrade --abort --id STAGE_ID --json
~~~

`--stage` 只将通过完整性检查的 wheel 复制到应用私有 `upgrade-staging`，
`--verify-stage` 只读重新计算复制品摘要，`--abort` 仅删除结构和字节均经过复核的
本应用暂存候选；有新增文件、内容篡改、目录非私有或非本应用交易时**拒绝删除**。
这三项不启动候选代码、不安装软件、不读取真实密钥、不影响活动版本或用户数据，
也不要求暂停 Web/Feishu/Learning。它们**不代表自动升级已经执行**：暂存文件仍
是未获来源认证的隔离字节，不承诺用户已安装到目标版本。`--require-trust` 和
`--require-data-compatibility` 用于隔离暂存时也会安全拒绝，因为当前没有可信签名
和完整数据 schema 兼容性证据。

`--prepare`、`--commit` 保留明确的安全阻断：没有权威服务停机和所有外部写入者
退出证明时只报告拒绝，不改版本指针或生产环境；`--abort --id` 只撤销**未执行过
切换的隔离候选**，不能恢复已经切换的生产代码。需要实际恢复用户数据时继续使用
上面的 `backup verify` 和 `rollback --into NEW_DIR`，绝不覆盖原 data 目录。

冷备份及隔离恢复必须显式确认受影响服务已停止；**该参数只是操作者声明，程序尚未证明服务真的
停止**，运行中的数据复制可能不一致。先通过现有运维/服务控制通道确认停机并协调
其他写入者，必要时暂缓操作。备份目录和恢复目录必须以前从未存在且父目录可访问，
不会强制覆盖。备份仅包括配置、选定数据及可解析的 Experience/Method 根，
始终标记 `selected_roots`，不自称全量；相应独立根、schema 兼容性及未知写入者
需要管理员额外核对。

如果默认 Method 目录嵌套在 data 内，快照只保存一次 `data/methods`，
manifest 用 `sources.methods="alias"` 和 `aliases.methods` 记录原始角色。
显式配置的外部 Methods 目录仍单独备份，先前旧版 manifest 中的双份实体目录仍
可以通过验证并隔离恢复。恢复时如有别名，应查看 manifest 确定真实文件所在的
`payload` 子目录，不能将别名误认为额外恢复了一份数据。

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

### 本地扩展管理入口（P1）

~~~bash
lfl extensions list
lfl extensions list --json
lfl extensions inspect /absolute/local/plugin-directory
lfl extensions install /absolute/local/plugin-directory
lfl extensions disable demo-plugin
lfl extensions enable demo-plugin
lfl extensions update /absolute/local/plugin-directory
lfl extensions remove demo-plugin
~~~

`inspect` / `list` 只读；变更类命令在交互终端要求输入 `yes`，非交互运行
需要显式添加 `--yes`。只支持**本地已取得的扩展目录**，不会自行下载远端包
或执行安装 hook。安装前可 `inspect` 查看组件兼容性，MCP Server 后续是否运行
继续遵循现有启动和权限规则。管理入口复用 `DATA_DIR/extensions` 的安装记录、
修订号 CAS、禁用状态及实例数据目录。`remove` 只移除安装记录，**不删除插件数据**。

## 构建与验收

### Apple Silicon 原生 `.pkg` 候选（免用户安装 Python/uv）

构建者可在 **macOS arm64** 上，从已经完成代码审查、完整测试及来源核验的
wheel 离线构建带 Python 3.13 运行时的自包含安装包。`pkgbuild` 只在私有临时
目录工作，生成的 `.pkg` 默认**不签名、不公证、不执行系统安装**。安装包包含
`/Applications/LFL.app` 和双击打开终端向导的 `LFL Start.command`，不用用户
自行准备 Python、uv、Git 或 Node；内部仍复用 `lfl start` 和原有服务权限。

~~~bash
python scripts/build_macos_cli_pkg.py --wheel /absolute/private/llm_first_loop-VERSION-py3-none-any.whl --expected-sha256 WHEEL_SHA256 --out-dir /absolute/never-before-existing/pkg-output
python scripts/verify_macos_cli_pkg.py --pkg /absolute/pkg-output/LFL-VERSION-macos-arm64-unsigned.pkg --expected-sha256 PKG_SHA256 --report /absolute/private/pkg-smoke.json
~~~

验证器会**仅解包到临时目录**、检查应用结构、跨目录独立 Python 可执行、
`lfl --version`、`check-install`、首次启动只读预览，以及模拟配置下真实 Web
health/UI 200；只停止验证时由它启动的服务。不得以此替代真实系统安装测试。

**正式面向公众发行的阻断条件：**需经过经授权的 Apple Developer ID
代码签名、Installer 签名、公证和 Gatekeeper 验证，复核安装目标碰撞、卸载后
用户数据保留及签名成品真实安装；没有签名密钥时，此 `.pkg` 仅是本地验收候选，
**禁止声称已上架、已公证或已公开发布**。当前仅 arm64；Intel、Windows
和其他架构未验收。

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

### 从精确 Git 提交构建可信候选

日常开发工作树可能有尚未提交的源码（包括其他 Agent 正在处理的模块）。
**不得从这样的工作树直接 `uv build` 并发布产物**：setuptools 会扫描 Python 包
目录，可能把未提交代码带入 wheel，即使对应 Git commit 本身不包含它。

请使用干净提交态构建入口；即使调用处存在未提交文件，也只读取指定 Git 提交：

~~~bash
python scripts/build_committed_distribution.py \
  --ref HEAD --out-dir /absolute/new/private/release-candidate
~~~

该入口先从指定 commit 创建短命 detached Git worktree，只复用本机已安装的
`webui/node_modules` **依赖二进制**，在隔离工作树重新执行源码绑定 WebUI build，
再使用 `uv build --offline` 生成 wheel 和 sdist。它逐项比对 wheel 内 Python 模块
与该 commit 跟踪的 `src/llm_loop/*.py`，并在新目录写入 `provenance.json`（源
commit、WebUI 来源 SHA、wheel/sdist SHA）。目标目录必须从未存在，不覆盖旧产物。

这只证明**代码来源于指定已提交快照、构建未用调用者未提交源码**；复用的
本机 Node 依赖不等于独立证明软件供应链来源和版本锁闭合，构建回执也不等于
发布者签名。Release 仍须完成受管代码审查、原版完整 R9、依赖哈希资格、
隔离虚拟环境安装和人工批准；不能直接推送、发布或重启生产。
