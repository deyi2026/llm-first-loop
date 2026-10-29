---
title: lfl web 从家目录启动崩溃：工作区根解析为家目录被注册白名单拒绝（修法=把工作区指向子目录，ALLOWED_ROOTS 无效）
scenario: "Linux 主机（/home/<user>）用托管安装（LFL-0.6.37，venv 在 ~/.local/share/lfl/releases/LFL-0.6.37）后，在家目录直接跑 `lfl web`，进程在 build_engine 阶段抛 WorkspaceNotAllowedError: 不允许把家目录或其祖先注册为工作区: /home/<user>，Web 未起来（前置的 scheduler/interop_watch INFO 只是引擎构建期线程已启动，不是根因）。"
root_cause: ""
solution: "根因链（源码核对，mirror main = 0.6.37）：cli.py:1153 prepare_environment 的 workspace = args.workspace or env LFL_WORKSPACE_ROOT or Path.cwd() → cwd=/home/<user>；cli.py:1514 把它作为 workspace_root 传给 web_main → factory._activate_default_workspace → workspace/store.py:457 register → store.py:129-135 _validate_workspace_allowed 显式拒绝 p==home 或 home 的祖先。修法三选一：① `lfl --workspace /home/<user>/lfl-workspace web`（全局选项必须放在命令前，放在 web 之后会被 \"web uses WEB_HOST/WEB_PORT configuration; unexpected arguments\" 拒）；② `mkdir -p ~/lfl-workspace && cd ~/lfl-workspace && lfl web`；③ export LFL_WORKSPACE_ROOT=/home/<user>/lfl-workspace 或写进 .env（托管安装下 .env 位于 ~/.local/share/lfl/.env，可用 `lfl paths` 打印实际 LFL_ENV_FILE/LFL_WORKSPACE_ROOT 绑定确认）。关键反直觉点：错误信息里提示的 LFL_WORKSPACE_ALLOWED_ROOTS 对本场景无效——家目录拒绝发生在允许根检查之前，把家目录加进该变量仍然会被拒；反而默认允许根本就包含家目录（store.py:82-84 把 home 作为候选根），所以家目录的任意子目录天然可注册。另一个缺口：lfl doctor 只检查工作区路径存在且是目录（doctor.py:131-135），/home/<user> 满足 → 报 pass，不会预警这个启动期崩溃。"
evidence: "用户 2026-10-28 20:26 提供的 traceback：cli.py:1514 web_main(workspace_root=bindings[\"LFL_WORKSPACE_ROOT\"]) → factory.py:2511 → factory.py:471 workspace_store.register(str(root)) → store.py:457 → store.py:136 WorkspaceNotAllowedError: /home/<user>。源码核对（本地镜像仓 /Users/<user>/Project/llm-first-loop-mirror，pyproject version=0.6.37，与宿主 release 版本一致）：cli.py:1153 workspace 解析式；cli.py:1155-1159 bindings；cli.py:1204-1215 全局选项须前置；cli.py:1508-1510 web 子命令拒绝额外参数；store.py:64-113 允许根集合（含 home 子树）；store.py:118-150 _validate_workspace_allowed 顺序（家目录拒绝先于允许根检查）；doctor.py:116-137 workspace 检查仅判存在性。宿主侧实际 .env 内容未核验（我在本机，无法读该主机）。"
tags: [lfl-web, workspace, 启动崩溃, 家目录, Linux, 0.6.37]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T20:27:58.223924+08:00"
updated_at: "2026-10-28T20:27:58.223924+08:00"
---