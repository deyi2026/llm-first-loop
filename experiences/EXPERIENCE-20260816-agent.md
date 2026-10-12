---
title: 跨 Agent 安全审查闭环：独立上下文审查 → 分层防线修复 → 对抗性测试 → 实弹验证
scenario: 对 LLM 代码生成类工具（playwright_exec：模型写 Python 在子进程执行）做安全加固。主 agent 自己写的门控（AST import 拦截 + URL 正则白名单）存在盲区——静态门控可被动态导入绕过（__import__/importlib/sys.modules 14 种形态）、URL 正则无 $ 锚定可被 userinfo@host 逃逸、模型代码与 helper 共享命名空间可裸 API 直连。主 agent 自查无法发现自己写的代码的绕过路径。
root_cause: "安全门控的盲区来自\"设计者视角\"：写代码的人默认用户会按预期路径使用，而攻击者专找非预期路径（动态导入、属性链逃逸、正则锚定缺失、命名空间共享）。单 agent 自查同源代码无法跳出自身假设；独立上下文审查（无主 agent 的意图偏置）能发现设计者看不见的路径。另：Python 无实用 restricted mode（已废弃），纯语言层沙箱做不牢（ctypes/libc syscall 可达），须接受\"门槛\"定位或换进程/容器隔离。"
solution: "1) 派独立 agent（DSH 子代理）做红队审查，要求\"实弹验证每条 payload\"（真实浏览器启动 + 真实出网），不只静态分析；2) 审查发现按\"主防线 + 纵深防御\"分层修复：命名空间隔离（模型代码 exec 到独立命名空间，内部对象 _page/_browser 不可见）为主防线，AST 门控（动态导入/动态执行/sys.modules/getattr 间接引用全形态拦截）为纵深；3) URL 校验从正则匹配改 urlparse hostname 精确集合校验（防 userinfo@host/域后缀/IP 变体/IPv6，顺带修复大小写/裸域误拦）；4) 对抗性测试固化 payload 清单（14 种 AST 形态 + 15 条 URL 逃逸）；5) 每次修复后实弹验证（真实子进程跑 4 类用例：隔离生效/门控拦截/功能保留/产物落位）；6) 对\"做不牢\"的防护（Python 沙箱）诚实声明为\"门槛非沙箱\"，不宣称绝对安全，开放面交产品决策。"
evidence: DSH 审查发现 3 条真实绕过全部复核属实；修复提交 a3448c4（URL host 精确校验+命名空间隔离+门控纵深）与 82d0d7b（cwd 限定+env 敏感键剥离）；对抗性单测 56 全绿；实弹 7 项 PASS（隔离生效 NameError / 门控拦截 / 相对路径读不到仓库根 / env 敏感键剥离 / goto 功能保留 / 产物落限定目录）。
tags: [security, code-generation-tools, red-team, cross-agent, sandbox, defense-in-depth]
source:
  session: 20260816-playwright-exec-security
  agent: llm-first-loop + dsh
status: active
created_at: "2026-08-16T19:06:11.119084+08:00"
updated_at: "2026-08-16T19:06:11.119084+08:00"
---

本会话完成一次完整跨 agent 安全闭环：LFL 写 playwright_exec（模型写 Python 子进程执行）→ DSH 独立审查（实弹 3 条绕过）→ LFL 复核修复（三层）→ 对抗性测试固化 → 实弹验证 → DSH 二轮复核（修正 .env 事实 + 建议 a+c 加固）→ LFL 实施。核心可复用点：① 红队审查必须"实弹"而非静态；② 防线分层（隔离为主、门控为纵深）而非单点；③ 对做不牢的边界诚实声明并交产品决策，不夸大；④ 审查-修复-测试-验证形成闭环可追溯。跨 agent 价值实证：审查深度超过主 agent 自查（发现命名空间共享这一最致命路径）。