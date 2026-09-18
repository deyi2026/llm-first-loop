---
title: EvolutionStore 落盘异区 split-brain：data_dir 相对路径随进程 cwd 漂移 + .env 显式配置覆盖修复
scenario: 演进建议提交回执成功（pending_review），但用户在主区 web（8902）审阅页看不到——EvolutionStore 落盘到了镜像区 data/audit/evolution_suggestions.jsonl，主区/镜像数据 split-brain。任何依赖 data_dir 相对路径的存储（演进/审计/会话归档）都会受影响。
root_cause: data_dir 默认相对路径随进程 cwd 漂移（主因）+ .env 显式 DATA_DIR=./data 覆盖代码默认值（次因）+ 引擎子进程 env 持久残留旧值干扰验证（复现坑）
solution: "①config.py 默认值改包位置锚定：_DEFAULT_DATA_DIR = str(Path(__file__).resolve().parents[2] / \"data\")，字段默认与 load_settings 默认同步替换（代码所在区=数据所在区，editable 安装下主区 venv→主区 data，镜像 venv→镜像 data，天然隔离）；②两区 .env 的 DATA_DIR=./data 行改注释（env 优先级高于默认值，不清掉则代码修复被覆盖）；③重启服务进程（env 在启动时注入）。验证三重：ps eww <pid> 看进程实际 env、env -u DATA_DIR -u PYTHONPATH 后 chdir 代码级验证、web API 运行层验证。测试注意：monkeypatch.chdir 后 load_env_file 若用 cwd 相对路径找 .env 会失败，必填 env 需 setenv 预置。"
evidence: 实例：EVO-20260829-6a78d4bb/06c96021 submit_evolution 回执成功（pending_review）但主区 evolution_suggestions.jsonl 130 条无此两条，镜像区文件 L44/L45 才有；修复后三重验证回执：新 web 52240 进程 env DATA_DIR=/Users/yyj/Project/llm-first-loop/data + PYTHONPATH=主区/src；env -u 后 cwd=/tmp 下 load_settings().data_dir 锚定主区；web API 返回 132 条含两条建议。
tags: [split-brain, data_dir, cwd-drift, PYTHONPATH, editable-install, env-priority, EvolutionStore]
source: {}
status: active
created_at: "2026-08-30T02:10:58.388139+08:00"
updated_at: "2026-08-30T02:10:58.388139+08:00"
---

根因三层：①config.py data_dir 默认 "./data" 相对路径，随进程 cwd 漂移——主区服务进程 cwd=镜像目录时演进建议落镜像区，主区 web 审阅页看不到；②.env 显式 DATA_DIR=./data（env 优先级高于代码默认）会覆盖代码层修复——改了代码默认值但 .env 显式配置仍在，修复无效；③引擎进程环境持久残留旧值——execute_command 子进程继承引擎 env，验证时需 env -u DATA_DIR -u PYTHONPATH 清污染才能测出代码真实行为。修复三件套：config.py 加 _DEFAULT_DATA_DIR = str(Path(__file__).resolve().parents[2]/"data")（包位置锚定，editable 安装下主区 venv→主区 src→主区 data，镜像 venv→镜像 data，两区天然隔离）+ 两区 .env DATA_DIR 行注释（让默认值生效）+ 重启服务。验证三重：ps eww <pid> 看进程实际 env（DATA_DIR 绝对+PYTHONPATH 指本区 src）、env -u 清污染后 chdir('/tmp') 代码级验证、web API 运行层验证（返回条数=主区文件真实条数）。坑：python -c 模式 sys.path[0]='' 随 cwd 动态解析，os.chdir 后 import 会解析到意外位置；test 里 monkeypatch.chdir 会破坏 load_env_file 的 .env 相对查找（该文件用 __file__ 锚定则不受影响），必填 env 需 monkeypatch.setenv 预置。