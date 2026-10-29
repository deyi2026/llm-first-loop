---
title: Linux 远程安装 LFL：引导 uv 的 120 秒总时长上限是慢链路主因
scenario: 在局域网 Linux 主机（Deepin 25 / Python 3.12 / 无 uv）远程安装 LFL，按 docs/installation.md 的标准脚本路径失败
root_cause: "scripts/install_linux.sh 引导 uv 运行时用 curl --max-time 120（总时长上限），慢链路下 16.8MB 下载超时即中止安装：curl: (28) Operation timed out after 120008 milliseconds ... + LFL installer: could not download the official uv binary。该超时与 Release/摘要校验无关。"
solution: 先 pipx install uv（发行版 Python 受 PEP 668 保护时 pip3 install --user uv 会被拒），export UV_DEFAULT_INDEX 指向国内 PyPI 源，uv python install 3.13（由 uv 下载，不受脚本 120 秒总时长上限约束），再运行安装脚本；脚本的 bootstrap_uv 会优先复用 PATH 上已有的 uv，跳过有上限的引导下载。安装后 PATH 需含 ~/.local/bin，验证用 lfl --version 与 lfl check-install（退出 0）。
evidence: "远端 /tmp/lfl-install.log 原文；修复后同一脚本 EXIT=0，lfl --version=0.6.37，lfl check-install ok:true/345 文件；上游 GitHub main（落后 31 提交的 gitee 镜像之外）scripts/install_linux.sh 第 410 行仍为 --max-time 120，说明该缺陷在上游当前 main 依然存在"
tags: [lfl, linux, install, uv, timeout, pep668, gitee]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T14:34:11.431373+08:00"
updated_at: "2026-10-28T14:34:11.431373+08:00"
---