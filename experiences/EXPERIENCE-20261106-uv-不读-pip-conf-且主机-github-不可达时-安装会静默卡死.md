---
title: uv 不读 pip.conf 且主机 GitHub 不可达时，安装会静默卡死
scenario: 在出网受限的 Linux 主机上执行 LFL 的 install_linux.sh（wheel/候选版安装），步骤卡住不返回
root_cause: ""
solution: "两处根因分别处理：① 索引——uv 不读 ~/.pip/pip.conf，须写 ~/.config/uv/uv.toml（[[index]] url=可达镜像, default=true），pip.conf 的 index-url 也同步改成同一可达镜像；② uv 二进制——安装器 bootstrap_uv 优先 `command -v uv`，找不到才从 GitHub releases 下载，GitHub 不通时会卡在 --max-time 120 的 curl，故非登录 ssh 重跑前必须 export PATH=\"$HOME/.local/bin:$PATH\"（本机 pipx 装了 uv 0.13.6）。诊断口诀：ps 看 uv 进程 CPU≈0 + 新 venv 的 site-packages 计数 0 = 卡在网络而非计算；再分别 curl 探测 PyPI/镜像/GitHub。"
evidence: "主机实测 2026-11-06：uv pip install 进程 4:54 仅 1 秒 CPU、新 venv site-packages 计数 0；curl 探测 pypi.org 与 pypi.tuna.tsinghua.edu.cn 均超时，mirrors.aliyun.com 返回 200；install_linux.sh L367 `uv_bin=\"$(command -v uv || true)\"`、L379-390 有 GitHub 下载分支；配置 ~/.config/uv/uv.toml + PATH 含 ~/.local/bin 后，同一安装 13 秒完成（77 包 3.55s 解析）。"
tags: [uv, pip.conf, 镜像, install_linux.sh, 离线, linux]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T20:03:23.160354+08:00"
updated_at: "2026-11-06T20:03:23.160354+08:00"
supersedes: [EXPERIENCE-20261028-linux-远程安装-lfl-引导-uv-的-120-秒总时长上限是慢链路主因]
---