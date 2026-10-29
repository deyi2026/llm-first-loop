---
title: 隔离实例做 Web 冒烟必须清空继承的 LFL_ENV_FILE/LFL_DATA_DIR，否则写入生产配置
scenario: 在同一台机器上起第二个 LFL web 实例做 provider/默认模型冒烟验证，用 DATA_DIR 指向临时目录以为已隔离
root_cause: env_file_path() 的优先级是 LFL_ENV_FILE > <data_dir>.parent/.env；execute_command 继承 LFL 进程环境，其中已有 LFL_ENV_FILE 与 LFL_DATA_DIR，子进程被动继承，DATA_DIR 覆盖不了 LFL_ENV_FILE。
solution: 启动隔离子进程时用 env -i（只保留 HOME/PATH/TMPDIR/LANG）或显式 env -u LFL_ENV_FILE -u LFL_DATA_DIR，并同时给出 LFL_ENV_FILE=<tmp>/.env；运行前后比对生产 .env 的 sha256。仅设 DATA_DIR 不够：provider_admin.env_file_path() 优先读 LFL_ENV_FILE，而 LFL 会话 shell 环境就带着 LFL_ENV_FILE=<repo>/.env。凭据写入和默认模型持久化都走这个路径，会直接改生产配置。
evidence: 实测：首轮 smoke（仅设 DATA_DIR）后仓库根 .env 新增 SMOKE_API_KEY/DEAD_API_KEY 且 LLM_MODEL 被改写为 base/base-a；改用 env -i + LFL_ENV_FILE=<tmp>/.env 重跑，14/14 项通过且 .env sha256 全程保持 69bfb6ab333ef1755fd6f013853e330f038e094a3a860c218007d7fb8657aed。还原记录见 docs/governance/receipts/live-acceptance-web-model-admin-20261028.json 的 incident 段。
tags: [isolation, env-file, smoke-test, config-safety]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T22:38:35.096591+08:00"
updated_at: "2026-10-28T22:38:35.096591+08:00"
---

检查清单：1) 起隔离 web 实例前 `env | grep LFL_ENV_FILE` 确认继承情况；2) 用 `env -i HOME=$HOME PATH=$PATH TMPDIR=$TMPDIR LANG=... DATA_DIR=<tmp>/data LFL_ENV_FILE=<tmp>/.env ...` 启动；3) 记录生产 .env sha256 作为 before，冒烟后比对；4) 若发现漂移，按 .env 备份还原并把注入的 KEY= 行与 LLM_MODEL 一并恢复，再核对 live 实例的 runtime_default_model 与文件一致。反例：只设 DATA_DIR、只 sed 掉一个变量，都会留下另一条写入口。