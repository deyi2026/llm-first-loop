---
title: "未证实\"代理干扰\"假设前禁止修改用户系统代理配置(Surge)"
scenario: "排查与代理无关的远程连接故障时,怀疑用户系统代理(Surge)干扰目标应用流量"
root_cause: "以未证实的\"代理干扰\"假设替代当前证据,且未评估对用户主用途(正常代理上网)的影响面就执行了系统级配置变更"
solution: 禁止在无实证时修改用户系统级配置;观测优先于变更;变更必须最小化+备份+即时验证+可回滚
evidence: "用户 2026-09-30 12:38 确认:\"surge没问题了,记住今天的经验教训,不要这个错误的修改surge\";回滚动作及备份文件 Nexitally_Surge.conf.bak.20260930-awesun 详见当日会话记录"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-30T12:46:19.565650+08:00"
updated_at: "2026-09-30T12:46:19.565650+08:00"
---

2026-09-30 排查"远程登录不了"(向日葵远程)时,基于"Surge 代理可能干扰向日葵流量"的未证实假设,直接修改了用户的 Surge 配置文件加直连规则并重启 Surge,结果破坏了用户正常上网,事后被迫整体回滚到备份(Nexitally_Surge.conf.bak.20260930-awesun)。正确做法:(1) 系统级/用户在用的基础设施配置(Surge/hosts/launchd 等)默认不可触碰,除非拿到流量被干扰的实证(tcpdump/连接日志);(2) 若确需修改,必须:改前完整备份并声明、修改范围最小化、改后立即验证用户主用途不受影响、告知用户可一键回滚;(3) 怀疑网络层问题时优先旁路观测(抓包、日志、连接测试),而不是改转发路径。用户明确要求"记住今天的经验教训,不要这个错误的修改 surge"。
当前性验证:ls /Users/<user>/Project/llm-first-loop-mirror/Nexitally_Surge.conf.bak.20260930-awesun 确认回滚备份存在;diff 该备份与当前 Nexitally_Surge.conf 应一致(除时间戳注释);curl 经 Surge 代理(127.0.0.1:6152)访问 https://www.google.com 应 200。