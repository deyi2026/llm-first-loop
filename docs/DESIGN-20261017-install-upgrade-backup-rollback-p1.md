# P1 安装包升级、冷备份与隔离回滚（设计/验收契约 v0.1）

状态：Stage A（需求和 RED）；未授权执行生产更新/回滚。本文件不是“已上线”回执。

## 权威事实及机制边界

- `lfl` 安装入口由 `llm_loop.cli.application_main` 分发；`check-install` 校验本地 wheel 资源清单，**不是来源签名**；`doctor` 离线、只读。现有 `lfl init` 只允许新建配置，不会覆盖 `.env`。
- wheel 更新由 `uv tool install --reinstall <受信且独立核验SHA的wheel>` 等包管理操作完成；现有 `service_control` 的 release known-good rollback 属**运行时控制平面**，不能替代 wheel 的版本回退，也不保证数据 schema 降级兼容。
- `RuntimePaths.data_dir` 是权威数据目录，`infer_state_root()` 会为 `<root>/data` 派生 `<root>`，Experience 可在 `<root>/experiences`，Method 常在 `<data>/methods`，显式 `EXPERIENCES_DIR` / `METHODS_DIR` 还可能位于独立根。扩展实例数据位于 `<data>/extensions`，必须保留。`.env` 应根据 `--config > LFL_ENV_FILE > 应用根/.env` 解析来源，进程非空/空配置覆盖优先级不应被静默改变。
- **不能假定只复制 `<data>` 就是完整备份；更不能备份仓库 `.env`、临时目录或运行中 SQLite/JSONL 后直接宣称一致快照。**

## P1 MVP 对外接口

| 命令 | 性质/返回 |
|---|---|
| `lfl upgrade --plan [--json]` | 离线只读；输出当前安装版身份、受控升级前置项及兼容性未知项，不下载、不执行包管理器、不影响任何服务；0=预览有效，1=阻断，2=命令格式错误 |
| `lfl backup --plan [--json]` | 离线只读；列出将检查的配置、data、Experiences、Methods（如有显式独立根），缺失/重复/冲突路径、范围是否完整，不泄漏真实目录和配置内容 |
| `lfl backup --to <new-dir> --confirm-services-stopped` | **冷备份**；明确由操作者确认受影响服务已停止，但不能把这个确认冒充机械检测；复制文件字节和 SHA 到从未存在的新私有目录（目录0700、文件0600），完成回执最后落盘。已有目录、软链、运行时目录别名、不能读取的文件、跨设备符号链接、预算耗尽均拒绝，绝不覆盖已有文件 |
| `lfl backup verify --from <snapshot-dir> [--json]` | 完全只读；逐文件 SHA/长度、相对路径和完整目录清单核验，拒绝软链、路径穿越、重复路径、遗失或多余内容，已完成 manifest 才能 PASS；纯校验不是来源认证 |
| `lfl rollback --from <snapshot-dir> --into <empty-new-dir> --confirm-services-stopped` | **只恢复到新的隔离目录**，先 verify 再创建，禁止原地覆盖生产 data、source、配置或扩展；恢复结果展示下一步如何人为切换数据源/安装此前已核验 wheel，绝不自己控制服务、改 uv、回滚代码或迁移 schema |

### 强制设计约束

1. 版本升级 plan 与数据 snapshot 分开：源码工作区或未认证的 wheel 只给出资格未知及明确建议，不假装已经有可执行升级；不对任意 URL 自行下载。实际 `uv` 替换与重启另审批。
2. 备份源由**同一套现有 CLI + RuntimePaths + dotenv 解析**得出：含 `.env`（如果存在，独立配置 file）、data、推断 Experiences 根及显式 `EXPERIENCES_DIR`/`METHODS_DIR`；排除 code root、bundle、目标目录和自己备份目录；源层遇 overlap 按可验证规则只保留最外层/单一路径并精确记录。若无法证明所有数据 root，一律 `coverage=selected_roots`，**不能返回 full**。

   **去重修订（Stage B 窄修）：** 默认 `METHODS_DIR=<data>/methods` 属于 data 的子目录，不应另存一份。manifest v1 在不改变 `schema` 的前提下，新增可选 `aliases` 映射：`sources.methods="alias"` 与 `aliases.methods={"under":"data","relative":"methods"}`；`data/methods` 仅复制一次。同路径使用空的 relative。其他显式根覆盖关系同样选择最外层可读目录；只有被引用的物理源才复制。备份预览可报告 `captured_via` 角色，不包含本机绝对路径或凭证。`verify` 只能接受指向真实 manifest 文件/目录、无 `..`/绝对路径/自指/别名链的映射，恢复按物理目录复制并保留逻辑映射；**以前没有 `aliases` 且实体双拷的 v1 快照仍可校验和恢复**。`aliases` 是角色映射，不是符号链接，也不提供来源签名。
3. 每个快照带 manifest `lfl.install-backup/v1`：`complete=true`、源 role、相对安全路径、长度/SHA256、时间/版本 identity（去敏，不包含密钥原文、host路径或 URL）；实际 `.env` 明文只在私有 backup payload 中，不能出现在 stdout/JSON/日志/receipt。必须有严格总文件数/字节预算，禁止设备文件和符号链接。不能省略空目录（对恢复有意义）。
4. 不允许边写边宣称成功：新目录以原子 exclusive mkdir 预留，完成 payload、fsync 和目录 fsync 后才发布 final manifest；不完整/中断快照必须 fail-closed，后续 verify/rollback 不可继续，**绝不自动删除/覆盖**原有目录或用户数据。恢复目标同理，先复制后做完整校验；如果文件系统不支持保证，要如实阻断。
5. 恢复只产出**隔离备选状态**，不把旧 DB 写回运行中的新版本；兼容性、更新前后的迁移与回滚操作另做显式确认，不能把恢复成功等同于生产版本已回退。
6. 只接受显式 `--confirm-services-stopped` 进行写操作；该标记是操作者声明而非系统证明。后续可独立增加 service_control 真实状态核验和授权生命周期操作，但不得把“用户输入了标记”冒称服务确实停止。
7. 错误退出不泄漏目标绝对路径/文件内容/密钥；`backup --plan`、`upgrade --plan`、verify 不创建配置或持久数据目录，不加载 Engine/Provider、不访问网络或调用 service_control mutation。禁止 `--force` 或现存文件覆盖。

## 风险与 Stage A RED 矩阵

| RED 用例 | 期望 |
|---|---|
| `upgrade --plan --json` 安装来源未知 | 输出结构化 `lfl.upgrade.plan/v1`、资格及人类下一步，不下载不启动服务不写盘 |
| `backup --plan --json` 数据根与状态根不同 | 清楚报告 `data/config/experiences/methods` 角色及 coverage，不输出路径或秘密 |
| 缺少 `--confirm-services-stopped` | backup/rollback 写命令拒绝且退出码2，目标和源均不改变 |
| 目标预先存在或是 symlink | 绝不覆盖；不追随 alias 去写其他目录 |
| 备份内容含 `.env` 秘密 | 仅 payload 明文、私有0600；JSON/stdout/stderr 不回显；verify 不联网不解密、不打印秘密 |
| `.env`/data/experiences 分离 | 精确备份所有已声明根；任何未知根只称 selected coverage，不能“全量已备份” |
| 文件在拷贝中变化 / 中断 / fsync 失败 | 不完整标记/失败，不宣称快照可回滚；不能覆写已存在备份或用户数据 |
| 校验 hash 不符、manifest 多余/遗失文件 | 必须失败；不得提前创建恢复目标 |
| `../`、软链、绝对路径、目录循环、硬链接别名、大小预算溢出 | 预检拒绝，零越界读写/无异常执行 |
| `rollback --into` 目标已存在 | 拒绝，不清理现场；新目标复制/校验成功不代表 live cutover |

## 验收阶段和边界

- **Stage A：** 最新 main 隔离 worktree；本文 + 真实 CLI 缺失 RED；不得修改生产逻辑/main。
- **Stage B：** 从 RED 到 GREEN：优先离线 plan 与冷备份/verify/隔离 restore 闭环，真实文件/密钥/时序测试，wheel 脱 Git 环境验证。新 durable 写面按真实权威 DRC 登记，不修改数值基线求绿。源补丁独立 GLM-5.3 Reviewer 真实 Host PASS（P0/P1=0）后，才运行原版完整 R9 受管隔离提交。
- **Stage C：** 从新 main 隔离集成，Rule34 独立专门合并审查，只有单独授权才能本地 ff-only。远端 push、uv 更新真实软件、生产发布/重启、对已有持久数据执行 in-place restore **均不在本阶段授权范围内**。
