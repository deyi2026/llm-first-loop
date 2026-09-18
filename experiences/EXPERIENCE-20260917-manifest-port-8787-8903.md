---
title: 验收读配置不得猜默认值：manifest 无 port 键时兜底 8787 实证错误（实际 8903）
scenario: "mirror 部署（gen 7, 6063c6c3）后做 HTTP 端点验收：从 data/runtime/runtime_manifest.json 提取 web 端口时用了 .get('port', 8787) 兜底默认值；manifest 实际无 port 键，脚本探测 8787 直接 Connection refused。真实端口 8903（.env 的 WEB_PORT，resolver 权威解析）。"
root_cause: 验收脚本假设 manifest 含 port 键并硬编码历史端口 8787 为兜底；runtime_manifest.json 实际无该键，真实端口 8903 来自 .env WEB_PORT（resolver 权威），猜测的默认值导致探测打到错误端口。
solution: 配置键缺失必须 fail loud（KeyError/显式报错），禁止用记忆中的历史值兜底；端口等运行配置从权威源取（.env/llm_loop.runtime.resolver），验收脚本先核到真实值再发起探测。
evidence: 本会话末次手动 HTTP 验收回执：8903 端口 /auth/status=200、/ui/v2/=303、/login=200；先前 8787 探测 Connection refused。磁盘留痕：data/runtime/runtime_manifest.json（无 port 键）、data/runtime/managed_service_deployment.json、data/restart-audit/20260917-211442-71031/。
tags: [deploy, verification, config-hygiene, port, fail-loud]
source:
  session: current-deploy-gen7
  files: "['data/runtime/runtime_manifest.json', 'data/restart-receipt.json', 'docs/LFL-restart-guide.md']"
  related_commit: 6063c6c3171e51590ea350241bd5f765cb582f99
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T22:15:12.707203+08:00"
updated_at: "2026-09-17T22:15:12.707203+08:00"
---

2026-09-17 mirror gen7 部署验收实证。教训：一次性验收脚本里给 manifest['web'].get('port', 8787) 这类"记忆型默认值"是错的——schema 里根本没有 port 键时，兜底值不是安全垫而是静默改写探测目标。正确做法：键缺失就让它 KeyError/fail loud；端口权威源是 .env 的 WEB_PORT（经 llm_loop.runtime.resolver 解析，restart_mirror.sh 同源），manifest 只有 git_head/pid/workspace_root 等身份字段。