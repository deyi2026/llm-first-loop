# 跨区污染存证 (2026-08-28)

主区 web(75219)/feishu(74294) 于 02:39-02:59 携带 shell 继承的
LFL_DATA_DIR=镜像路径 启动, 本区会话(5ac62833/9d27d9ee 等)的
trace(45条)/exception(1条) 误写镜像区 data。

- 本目录: 该批记录副本（镜像区原文件 append-only 未动）
- 根因修复: restart_system.sh / restart_mirror.sh +unset LFL_DATA_DIR DSH_HOME
- 净化重启: web 1379 / feishu 1455, 环境已验证干净
