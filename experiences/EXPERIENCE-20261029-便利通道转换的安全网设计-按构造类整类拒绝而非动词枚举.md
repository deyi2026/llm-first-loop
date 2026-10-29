---
title: 便利通道转换的安全网设计：按构造类整类拒绝而非动词枚举
scenario: "为 execute_command 灾难守卫设计\"自动转换放行\"类便利通道（如 heredoc/静态源管道转临时文件执行）时，初版安全网设计如何被独立红队审查逐轮击穿。"
root_cause: ""
solution: 便利通道（拒绝即可回退人工链路的通道）的安全网按构造类整类拒绝，不按动词枚举：凡进程派生构造（subprocess/os.system/exec/eval/getattr/importlib/child_process/execSync/pytest.main）、凡 shell 变量与命令替换、凡敏感文件名引用——一律拒绝转换。多层网顺序：结构性解析 → -c 同级载荷扫描 → 派生构造 → 受保护动词（叶子分类器+宽松文本网）→ 敏感读取 → 封条 → 写盘 → 重组后全量重扫。审计拒绝记录不得携带文件内容预览。跨模块依赖先查架构守卫 frozen 基线（模块环/导入边只降不增），用零依赖叶子模块承载共享分类。
evidence: "evidence://v1/edc697b0d8e0203cd405116ab53ada48a85aa53612f6407d0c621cb4b6e16d3d; evidence://v1/70585bc543718a43f3af143c7c87754fd0732e7d5241da58114f1c5fceb34999; evidence://v1/333ac99b97d4ed42a67c3d165c4703e1b5e0897edcbd978dd29c899bf76f90a5; evidence://v1/6449efab8ce202f9fb124136333efce012fcad195a027273fb352c985de0c24c"
tags: [safety-guard, conversion, red-team, RULE-AI-28, architecture-guard, fail-closed]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T04:08:51.757327+08:00"
updated_at: "2026-10-29T04:08:51.757327+08:00"
---

十轮独立审查（review_admission kind=full_test）共暴露 6 个 P1，全部是我初版设计遗漏的真实安全缺口：1) 转换绕过受保护动作审查门（载荷跑 git push/pytest 时下游只见临时文件形态）→ 修：分类前置进转换管线；2) 延迟 import 闭合模块环（safety→review_host_admission→subagent.runner→registry）→ 修：改用零内部依赖叶子模块 review_gate；3) held-out 封条在工具层晚于 registry 转换执行 → 修：封条前置进管线（命令+载荷双查）；4) 拒绝审计的载荷预览把 cat .env 首行明文落盘 → 修：敏感路径先于读取拒绝 + preview_suppress；5) 变量间接（g="git";p="push";$g $p）与 execSync 拼接绕过文本网 → 修：git..push 跨度改懒匹配 DOTALL 不排除;&| + node 派生构造入列 + shell 家族 $ 全拒；6) list 形态 argv（subprocess.run(["uv","run","pytest"])）绕过字符串实参网 → 修：list 归一分类 + 进程派生构造整类拒绝。元教训：枚举式内容网天然可绕，便利通道的安全网应按"构造类"拒绝（凡派生进程/凡间接执行/凡 shell 变量），拒绝即回退人工链路故零可用性损失；架构守卫（模块环/函数行数/导入边）在 ci_gate 内强制，设计时就查 frozen 基线。