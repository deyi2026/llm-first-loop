---
title: LFL 受管重启：认证写回先独立重载，区分 live 代码与 stable 回执代次
scenario: 2026-10-25 Web 8903 重启失败；.env 的 WEB_LOGIN_PASSWORD_HASH 末尾被拼接 WEB_SESSION_TTL_SECONDS，错误重试仍起不来；只恢复 Web 后出现 desired/gen319、Feishu/Learning stable/gen315 而 live HEAD 一致。
root_cause: 历史登录哈希自动升级写回没有保留原行分隔符，将后一配置键拼进 PBKDF2 摘要，重新启动后认证解析报错。运维展示另将 live 代码一致与 stable 最近成功回执的代次一致混为同一状态。
solution: "目标版本启动前先核查实际配置加载结果；任何 .env 单键写回必须保留行终止符、写回后从磁盘独立重新加载、复核原哈希结构与下一键及权限 0600，保留非敏感校验结果和可回退备份。service_control 的 accepted 不是成功，按 action_id 读取 failed/succeeded 终态和定界日志；修复已证实的配置错误再按授权服务范围重启。判读 generation 时独立报告 desired、live(pid_alive/git_head)、stable(generation/succeeded_at) 和 restart_required；live HEAD 已匹配、restart_required=false 而 stable 回执旧，不要为了数字一致额外重启或伪造回执。CLI 命令必须按当前目标源码及 --help 现查，不沿用旧卡中不存在 restart CLI 的结论。"
evidence: "2026-10-25 data/web.log 22:07:52/22:09:23 WEB_LOGIN_PASSWORD_HASH 格式无效；.env 原值 116 字符=87 字符规范 PBKDF2 + 独立配置项 WEB_SESSION_TTL_SECONDS=43200，salt=16 字节/digest=32 字节；精确拆行后保持旧验证哈希，保存 0600 备份，独立读回后服务控制 action svc-a855f24b367649a2bfe9f895190484c4 终态 succeeded/confirmed_ok、/auth/status HTTP 200、Web pid43317/HEAD 7ad21715d/desired319；Feishu pid91278、Learning pid91766 未被重启，live HEAD 同为 7ad21715d，stable 315，restart_required=false；当前 CLI restart --help 有效。"
tags: [service-control, restart, auth-hash, dotenv, generation, live-stable, drift, preflight, recovery]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T22:38:00+08:00"
updated_at: "2026-10-25T22:38:00+08:00"
supersedes: [EXPERIENCE-20260919-service-control-cli-restart, EXPERIENCE-20260919-lfl-web-feishu-learning]
---

### 执行前：少而准确的资格核验

1. 从 service_control 的真实 `show/status` 确认 desired SHA、generation、目标服务、现役进程、阻塞/在飞任务与最近成功回执。`restart` **不会自动发布新代码**；纯恢复只重启已绑定版本。
2. 只针对目标服务真正使用的配置做只读预检。对 `WEB_LOGIN_PASSWORD_HASH` 要能由目标版本解析；对 `WEB_SESSION_TTL_SECONDS` 要单独成行且在约定范围内。写回不能吞掉行分隔符，必须原子替换并保持最严格权限，独立重新载入 `.env` 校验哈希、下一配置键与文件差分，不打印密码或哈希全文。
3. 目标版本身份、服务闲置条件与回滚配置要成对验证。服务不健康先看精确失败动作日志；不要用 `curl=000` 推断网络层故障，也不要反复尝试无诊断重启。只改变已证实损坏的配置项，并在新启动态复查认证。

### 执行与终态

4. 使用**当前版本**正式 `service_control(action=restart, target=web)` 或真实 `python -m llm_loop.runtime.service_control restart --help` 所列的 CLI，绑定已有 desired，不猜 `--expected-generation` / `--data-dir` 等当前命令是否支持。保留 action_id，等待 detached worker 终态；`accepted` 不是成功。运行中的 Web 自身发起重启时应结束持锁 run、由外部观察者复核终态。
5. `succeeded + PID alive + live HEAD == desired HEAD + HTTP/鉴权入口检查 + 相邻服务 PID 保持` 才能宣布 Web 恢复。`stable` 旧回执所代表的历史 SHA 在未绑定当前 desired 时是**未知**，不可伪称旧版代码正在运行。
6. 区分 **live matching** 与 **receipt converged**：例如 desired 319、Web stable319、Feishu/Learning stable315、三者 live HEAD 均匹配、`restart_required=false`，属于**代码一致、回执相差 4 代**。这不构成再次重启的充分理由；下次需要因真实变更正常发布或重启时再取得更新回执。

### 反例与范围

- 若 live HEAD 不一致、PID 已死、manifest 不可读、配置失效或实际功能探针失败，不能套用“仅回执差异无须重启”的结论。
- 不应把旧 `git checkout HEAD` 与发布的不可变 release HEAD 混为一谈；后者才是运行版本身份。
- 历史 2026-09-19 记录中“CLI 没有 restart”是当时事实，在当前 2026-10-25 CLI 已被证伪。历史材料保留供溯源，但停止作为现行操作指南。
- 本案例没有证明所有配置错误都能以拆分两行修复。只有**精确确认末尾附加键且原哈希内容完整**时才允许这种保真恢复；其他情况必须单独诊断，不得造哈希或禁用认证。
