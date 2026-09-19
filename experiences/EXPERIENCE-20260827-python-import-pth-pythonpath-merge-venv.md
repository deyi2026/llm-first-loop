---
title: 跨工作区 Python import 污染三层排查（.pth/PYTHONPATH/宿主进程环境）与 merge venv 事故防御
scenario: "双工作区（主区+镜像）共享 venv（符号链接）+ Agent 宿主进程注入环境时，测试/服务 import 了错误工作区的代码——且\"全量绿\"可能是假象"
root_cause: ""
solution: "三层层剥定位: editable .pth → PYTHONPATH（含宿主进程 ps eww 实测，警惕 ps eww 无参列出自身）→ 宿主 worker 环境残留。防御机制化: 启动脚本 unset PYTHONPATH；git 严禁提交 .venv 链接；venv 重建后 pip install -e 自动正确指向；跑测试显式 PYTHONPATH= 前缀"
evidence: "2026-08-27 主区三起连锁事故：①共享 venv editable .pth 指镜像 → 主区服务/测试全跑镜像代码；②hermes worker 环境 export 残留（PYTHONPATH=镜像src + WEB_PORT=8903）→ restart 抢镜像端口失败+shell 污染；③镜像 d02fceb 曾提交 .venv 符号链接 → merge 检出覆盖主区实体 venv 成自引用环。修复链: .pth 重指/venv 重建/镜像侧 5d281ce 出库/restart_system.sh unset（5e72925）/宿主 worker 自然退出消残"
tags: [python, venv, 环境污染, 双工作区, 镜像协议, git-merge, editable-install, PYTHONPATH]
source: {}
status: active
created_at: "2026-08-27T20:42:23.517608+08:00"
updated_at: "2026-08-27T20:42:23.517608+08:00"
---

排查顺序（症状: import 的工作区与预期不符）: ①python -c "import xx; print(xx.__file__)" 确认实际解析；②cat .venv/lib/*/site-packages/__editable__*.pth 看 editable 指向；③echo $PYTHONPATH——注意环境变量优先级高于 .pth，且每轮独立 shell 也会从宿主继承（宿主常驻则污染常驻）；④ps eww <pid> | tr ' ' '\n' | grep -E '^VAR=' 看目标进程真实环境（ps eww 无 PID 参数时会列自身，误导）；⑤查宿主进程树 pgrep -f 宿主名，逐 pid 扫污染特征。防御: 启动脚本 unset PYTHONPATH；git 仓库绝不提交 .venv 符号链接（merge 检出会覆盖实体目录成自引用环，两区 venv 同时失效——cp -R 到已存在目录还会嵌套，用 ls 确认后再挪正）；跨区 git 对齐用 merge（自动跳过已 cherry-pick 等价物）而非逐文件拷贝；全量测试必须显式 PYTHONPATH= 前缀且判定只看 pytest_exit 行不信外层退出码；merge 冲突清单别用 tail 看（吃掉清单尾部，实际 42 个冲突只看到 4 个）