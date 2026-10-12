# 设计：工作区切换与运行中会话解耦（EVO-20260920）

## 用户问题
1. 会话推理中无法切换工作区（`workspace_busy` / "工作区切换失败；当前工作区和会话均未改变。"）。
2. 会话推理中新建会话后无法发送首条消息（发送键被锁）。

## 根因
### 后端（问题1）
`workspace_transition()` 对任意 active run（background registry 非空或 sync run）整体 fail-fast。
其保护的真实不变量是：运行中 run 的落盘不因 `activate_prepared_root` 换 `_dir_fs` 而漂移。
经核查，依赖面其实已收敛：
- 工具 cwd：run 启动即以 ContextVar 锚定（`lifecycle.py` `run_workspace`），不随根切换变。
- 事件库：`settings.event_logs_dir` 全局目录，非工作区分区。
- run lease / 文件锁：取得时打开 fd，持锁期稳定。
残留三个写时依赖：
1. `_save_locked` 经 `_path()` 按**当前** `_dir_fs` 解析；
2. `activate_prepared_root` 清空 `_run_save_tokens`（剥运行中 run 的落盘权）；
3. identity owner key 按**当前**根计算，切区后误判"已被其他工作区占用"。

### 前端（问题2）
`conversationStore.streaming` 是全局单布尔。会话 A 流式中新建会话：
订阅器 detach 时 abort A 的前台 fetch；A 的终态路径因会话守卫提前 return，
无人清除 `streaming` → 新会话视图 Composer 永久锁死。

## 修复
### 后端
- `SessionStore` 增加 sid 归属 pin（`_pinned_locations`: sid → (目录, owner_key)）：
  `_path`/`_session_lock`/`run_lease`/`management_lease` 锁路径与 identity 校验优先走 pin；
  物化（load/create/branch）overwrite，准入（run_lease）set-if-absent；
  sid 持活跃 run save token 时禁止 overwrite（防 run 中重定向）。
- `activate_prepared_root` 不再清 run save token / fallback 锁表（身份缓存仍清，按 pin 复核语义不变）。
- `workspace_transition` 去除 run fail-fast，改为有界阻塞排队（10s）——仅保留切换/准入互斥。
- `file_routes.edit_human_file` 的 workspace 快照收窄到 scope 捕获（编辑全程不再持守卫；
  编辑以捕获的绝对 scope 解析路径，会话事件经 pin 落回原工作区）。

### 前端
- `conversation.ts` 订阅器：用户切换/新建会话时重置视图流式态
  （`streaming` 语义收敛为"当前视图会话在流式"）；机械绑定（run_started 先行
  publish `abortSessionId`=新 sid）不视为切换，不重置。旧 run 转后台，
  切回经 `loadHistory → checkBackgroundRun → resume` 接管。

## 契约变化（测试同步更新）
- `tests/web/test_file_collaboration.py`：编辑持 lease 时切换**成功**，编辑写回原文件，
  会话 JSON 不漂移到新分区。
- `tests/web/test_workspaces_api.py`：run 中 register/switch 返回 200，切换原子生效，
  run 继续产出，最终落盘写回原分区、目标分区无该会话文件。
- `tests/web/test_api.py`：A 会话推理中 `new_session=true` 新建成功且共享当前切到新会话。

## 竞态残留（接受）
切换落在"准入 epoch 校验后、worker 取 lease 前"的毫秒级窗口：
pinned identity root 下 load 抛 SessionIdConflictError（run 干净失败，用户重试）；
unpinned 测试模式下仅在新分区产生杂散新文件，不污染原会话。
