---
title: LFL 三服务并发启动撞 runtime_manifest.json.tmp 固定名竞态：启动即崩、飞书桥消失
scenario: "LFL 多服务（web/feishu/learning）在同一数据面 data/runtime/ 下同时启动，write_manifest 并发竞争固定名 runtime_manifest.json.tmp：先 replace 的进程移走 tmp，后到进程 os.replace 时 FileNotFoundError 启动即崩，服务\"消失\"但 web 正常，极易误判为飞书配置问题"
root_cause: ""
solution: "manifest.py:318 固定 tmp 名改为带 pid：tmp = out.with_name(f\"{out.name}.{os.getpid()}.tmp\")（同目录保证 rename 原子性）。已在 Deepin 工作区落地并 py_compile 通过，git 未提交、用户可见可回滚。运维侧规避：重启脚本三个 nohup 之间 sleep 错开（≥5s）。诊断侧：进程在但日志安静时用 ss -tnp grep pid 看对外 ESTAB + data/feishu_heartbeat.json mtime 判飞书桥活性"
evidence: "feishu.log FileNotFoundError traceback（evidence:// 会话内 20:39 崩溃记录）；修复后 git diff 单行改动 + py_compile COMPILE_OK（execute_command 回执 2026-10-29 20:4x）"
tags: [lfl-runtime, feishu-bridge, concurrency, manifest, deepin, restart-procedure]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T20:43:57.436078+08:00"
updated_at: "2026-10-29T20:43:57.436078+08:00"
---

故障：Deepin 机器（lfl-workspace git 树直跑形态）上 feishu/learning 服务 20:39 启动即崩，feishu.log 尾部 FileNotFoundError: runtime_manifest.json.tmp -> runtime_manifest.json。
根因：src/llm_loop/runtime/manifest.py write_manifest() 用固定 tmp 文件名 out.with_suffix(".json.tmp")，三个服务（web/feishu/learning）同一瞬间启动时并发写同一 tmp：先完成 replace 的进程把 tmp 移走，后来者 tmp.replace(out) 时文件不存在即崩。web 抢到幸存，feishu/learning 撞死。
修复（2026-10-29 已提交入库；本地 8 进程×20 次并发写冒烟全通过）：tmp = out.with_name(f"{out.name}.{os.getpid()}.tmp")，同目录保持 os.replace 原子性，各进程独立 tmp。注意：修复对下次启动生效，三服务同瞬间启动的原始触发场景未复测。
运维规避：重启三服务的脚本不要连发三个 nohup，逐个起并 sleep 5+ 错开。
诊断定位手段：进程在但日志安静时，用 ss -tnp | grep pid= 看对外 ESTAB 连接（飞书桥=对飞书 443 长连接）+ data/feishu_heartbeat.json mtime 判活，比等日志快。
工具坑（本次实际犯错）：经 printf '%s\n' 生成远端脚本、脚本内用 python re.subn 修改源码时，replacement 字符串里的 \" 会以字面反斜杠+引号写入目标文件，造成 SyntaxError。改源码行用"按行号整行重写"（splitlines + lines[n]= 正确内容 + assert 校验）比正则替换稳。