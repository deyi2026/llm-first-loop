---
title: 资格门假 client 干跑不覆盖真实 HTTP header 路径：.env 行内注释腐蚀 API key 到运行时才显形
scenario: "hev0 P3 Stage-A 首跑：6 行真实 LLM 行全部 httpx UnicodeEncodeError（'\uff08' 无法 ASCII 编码，Authorization header position 75）。G2/G3/G4 资格门全绿但未拦截。定位：.env 第 7 行 GLM_API_KEY 带行内注释 `# 2026-...接入，provider=glm）`；run_ab.py 与 b0_gates.py 各有一份朴素 load_repo_env（split(\"=\",1)+strip 引号，不剥行内注释），而主运行时 config.load_env_file 有 `val.split(\" #\", 1)[0].strip()`。会话 env 不含任何 API key，行执行 key 只能来自 .env setdefault → 腐蚀值直达 httpx。"
root_cause: ""
solution: "1) 停任务、读完整 traceback 定位 header 来源（只可能是 Authorization Bearer {key}）；2) 掩码核对 .env 找到含全角字符的行；3) 不改 .env（主运行时正在正常解析它），而是让 eval 侧解析器与部署树同语义：`v.split(\" #\", 1)[0].strip()` + 成对引号剥离，两份拷贝同步修；4) 顺带修 summarize 零行容错（行全灭时 rows.jsonl 不存在应如实报 0 而非 FileNotFoundError）；5) 评估代码变更后按冻结纪律重建完整性链：新 preflight（记录新代码 hash）→ gates 重跑全绿 → 重放 Stage-A；旧 run 目录原样保留为事故记录。验证：env -i 干净进程断言 key 纯 ASCII + 数值变量可解析；engine 在真实 env 继承下解析结果与 manifest active_model 一致（注意 env -i 会丢 LLM_MODEL 之类会话变量造成解析差异伪影，验证 provider 解析必须模拟真实继承路径）。"
evidence: "evals/harness_evolution_v0/results/hev0-p3-20260921T011130Z/rows/t4_resume_oplog_b0_k1/worker.log（UnicodeEncodeError traceback: header value position 75）；.env line 7 GLM_API_KEY 带行内注释；.worktrees/compaction-merge-20260916/src/llm_loop/config.py load_env_file() 的 val.split(\" #\", 1)[0] 正确实现；修复后 env -i 解析 GLM_API_KEY len=49 ascii_ok=True，engine 解析 glm/glm-5.3 与 manifest 一致"
tags: [env-parsing, httpx, inline-comment, gates-coverage-gap, hev0, e2e-seam]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-21T09:29:36.148435+08:00"
updated_at: "2026-09-21T09:29:36.148435+08:00"
---

G2 假 client 干跑覆盖了消息构造/工具执行/判分链路，唯独不经过真实 HTTP——而 provider key 的注入缺陷只在 HTTP header 序列化时显形。教训：资格门的"全链路"声明要按网络边界重新审视；假 client 门绿 ≠ 环境注入正确。后续若新增资格门，凡涉及凭证的注入点应加纯机械 ASCII 校验（key 是 header-safe 是可静态断言的属性）。