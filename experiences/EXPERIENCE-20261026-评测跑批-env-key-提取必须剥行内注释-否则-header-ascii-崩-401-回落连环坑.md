---
title: 评测跑批 .env key 提取必须剥行内注释，否则 header ascii 崩+401 回落连环坑
scenario: LFL 评测跑批（run_eval.py 真实 LLM 调用）从 .env 提取 API key 后启动，引擎请求 401 或 ascii encode 崩溃
root_cause: ""
solution: "key 提取统一用 python 单行（split('#',1)[0].strip().strip('\"')）与 load_env_file 同口径；401 时先用 key 尾 4 位比对判断带的是哪个 key；排 encode 崩时绕过 main 的兜底 except 直接调 evaluate 打全栈；真实跑批一律 run_in_background + wait 轮询"
evidence: "evidence://v1/5a7eac642e1f8ebfe80ad859e293e8bc62b200f9c5182aa8a4bbdfd55c306679 source=execute_command:command#a5fa9f8c0209；evidence://v1/c9b47225740524f14a09586fbf99c05fdee7bc62f337fc28b3740a72a7b183dc source=execute_command:command#858324815dae；evidence://v1/3bc71a40d249bee156ad82c448c8a5a631852d4103bacdd6b830f2d7182b971"
tags: [eval-harness, env-key, httpx-encoding, run_eval]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T14:42:58.792268+08:00"
updated_at: "2026-10-26T14:42:58.792268+08:00"
---

症状：评测子进程 LLM 调用报 UnicodeEncodeError('ascii', position N, 全角括号)，PYTHONIOENCODING/LC_ALL 均无效。根因：shell 管道从 .env 提取 key（grep ^KEY= | cut -d= -f2-）没剥行内中文注释（KEY=xxxx # 套餐（…）），注释进入 Authorization header，httpx 对 header value 强制 ascii 编码崩。次生坑：(1) key 缺失时 _resolve_api_key 按 provider api_key_env→DEEPSEEK→LLM 顺序回落，glm 请求带 deepseek key 得 401（尾号可对出是谁的 key）；(2) run_eval 主循环 except 吞 traceback 只打 str(e)，需绕过 main 直接调 evaluate 拿栈。正确提取：取 '#' 前段+strip 引号。跑批还要 --code-source=worktree（判据在工作树 WIP 时）+ 后台跑（真实样本 1-2 分钟/个，60s 前台必超时）。