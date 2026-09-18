---
title: 端口劫持：主区仓库启动的 web 绑上镜像 8903——镜像 web 端显示主区内容的排查与恢复
scenario: "用户报\"镜像的 web 端变成主区的内容了\"。打开 127.0.0.1:8903 看到的是主区会话列表。排查发现 8903 监听进程 pid 27839：cwd=主区、PYTHONPATH=主区 src（还重复了两遍）、DSH_HOME=主区 data/dsh-home、命令是相对路径 `.venv/bin/python -m llm_loop.web`（镜像 restart_mirror.sh 用绝对路径）——它是从主区环境启动、绑了镜像端口的主区 web，跑主区代码+主区数据，自然显示主区内容。镜像自己的 web（restart_mirror.sh 所起 pid 38089）早已被杀。"
root_cause: "主区 AI 的一条孤儿操作（/bin/sh -c，PPID=1，2026-08-29 17:24）：`cd /Users/yyj/Project/llm-first-loop && kill 55878; WEB_PORT=8903 nohup .venv/bin/python -m llm_loop.web >> ./data/web_8903.log` —— 用 cd+WEB_PORT 覆盖的方式跨区起服务，抢占了镜像的 8903 端口。违反分区铁律：每区服务只能由本区脚本启动（脚本内含绝对路径、PYTHONPATH、DSH/LFL 环境隔离）。"
solution: "1) 定位（一眼定身份三要素）：`pid=$(lsof -tiTCP:8903 -sTCP:LISTEN)` → `ps eww -o command= -p $pid | tr ' ' '\\n' | grep -E '^(PWD|PYTHONPATH|LFL_DATA_DIR|DSH_HOME)='` + `lsof -p $pid | awk '$4==\"cwd\"'`。PWD/PYTHONPATH 指向哪区，进程就是哪区的——与端口无关；相对路径命令行（.venv/bin/python）是跨区启动的指纹（两区脚本都用绝对路径）。2) 恢复：kill 冒名 pid → `bash scripts/restart_mirror.sh web`（绝对路径+PYTHONPATH=镜像 src+DSH 隔离）夺回端口。3) 验证四件套：新进程环境四变量全指镜像；`GET /api/v1/sessions` 返回的会话 ID 在镜像磁盘命中、主区磁盘 0 命中；两区 /health 都 ok；镜像飞书心跳 pid 未变（劫持只影响 web）。4) 预防铁律：绝不用 `cd 别区 && WEB_PORT=<抢端口> nohup …` 方式起服务；需要 web 就用本区 restart 脚本；给别区补服务也必须 ssh 式切到该区脚本，而非借本区代码绑别区端口。"
evidence: "2026-08-29 17:24:43 主区孤儿 shell（PPID=1）执行 cd 主区 + WEB_PORT=8903 启动 web，日志写主区 data/web_8903.log。冒名进程 27839 环境：PWD=主区、PYTHONPATH=主区src:主区src、DSH_HOME=主区/data/dsh-home。镜像 web.log 显示自家 pid 38089 更早 Finished。18:04 kill 27839 → restart_mirror.sh web 新 pid 21842（PYTHONPATH/cwd/LFL_DATA_DIR 全指镜像），8903 API 会话镜像磁盘命中 9 / 主区 0，主区 8902 与镜像飞书（pid 38621 connected）全程无恙。"
tags: [端口劫持, 跨区污染, WEB_PORT, cwd身份判定, restart_mirror, 排障, 运维]
source: {}
status: active
created_at: "2026-08-29T18:04:33+08:00"
updated_at: "2026-08-29T18:04:33+08:00"
---

## 端口身份速查（AI 自用）

```bash
# 8903（或任何区端口）上进程到底是谁的——三要素一眼定身份：
pid=$(lsof -tiTCP:8903 -sTCP:LISTEN)
ps -o pid,ppid,lstart,command -p $pid        # 相对路径命令 = 跨区启动指纹；PPID=1 = 孤儿操作
ps eww -o command= -p $pid | tr ' ' '\n' | grep -E '^(PWD|PYTHONPATH|LFL_DATA_DIR|DSH_HOME)='
lsof -p $pid | awk '$4=="cwd" {print $NF}'    # cwd 指哪区，数据就在哪区
```

## 铁律

1. **端口不属于进程，区才属于进程**：8902 上跑镜像代码、8903 上跑主区代码，都是"端口劫持"，症状就是 web 端内容串区。
2. **每区服务只由本区脚本启动**：主区 `restart_system.sh`、镜像 `restart_mirror.sh`——绝对路径 + PYTHONPATH + DSH/LFL 环境隔离都在脚本里，手动 `cd + WEB_PORT + nohup` 绕过全部防护。
3. **恢复后必须验内容身份**：进程环境对只是第一步，还要 API 会话 ID 落盘交叉验证（本区命中、对区 0 命中）才算数。
