---
title: Deepin 端 LFL 三服务对齐 Mac 端的操作路径（runtime.launch + runtime.toml 双位置）
scenario: Deepin 端 LFL 三服务（web/feishu/learning）需与 Mac 端对齐：统一启动方式、runtime.toml 放置位置、semantic 语义检索配置生效路径
root_cause: ""
solution: 统一用源码树 runtime.launch 启动三服务；runtime.toml 同时放工作树根与 .releases/<hash>/；.env 追加 Mac 通用行为键；learning 等 idle 再重启
evidence: "evidence://v1/7db8d99b526095f1f00ce812d2be754a822a1172cae95cccb83aaea7c56c5220（三服务重启+manifest 更新）；evidence://v1/9eb5dfbbd1b8b222a44d71e074f551615f37087c24595341c4777301614a9876（feishu ESTAB 长连接+learning manifest+services/status live）；最终 final26 回执：web 453660/feishu 452780/learning 457738 全 ALIVE，semantic_scopes web 与 learning 均 memory:true method:true experience:true"
tags: [lfl, deepin, service-alignment, runtime-toml, semantic-scopes]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-29T20:00:28.891228+08:00"
updated_at: "2026-10-29T20:00:28.891228+08:00"
---

Deepin 端（内网 Linux 主机，已配置免密远程登录）上 LFL 三服务的对齐要点：
1. 统一启动入口：cd ~/lfl-workspace/llm-first-loop && nohup .venv/bin/python -m llm_loop.runtime.launch {web|feishu|learning} &；release CLI 的 `lfl --workspace ... web` 能跑但不写 runtime_manifest.web.json，面板 services/status 显示异常，勿混用。
2. runtime.toml 放两处才对 web 生效：工作树根 + .releases/<git_hash>/runtime.toml（deployment.code_root 优先读 .releases 下的；本次只放工作树根时 method 未生效，拷到 .releases/<hash>/ 后 semantic_scope_sources=runtime_toml_service:web 出现）。
3. .env 在源码树根（~/lfl-workspace/llm-first-loop/.env），含 LLM_* + FEISHU_*；.feishu.env 冗余共存无害。
4. 配置改动后需重启对应服务才进 semantic_scopes；learning 正在 confirmed_busy(inflight learn 任务)时不要重启，等 confirmed_idle 再动。
5. 面板 services/status 的 curl http://127.0.0.1:8903/api/v1/services/status 是用户视角总验证口。
6. Mac 端 EMBEDDING_BASE_URL=127.0.0.1:8765 不可照搬到 Deepin（Deepin 8765 是别的 uvicorn 服务，/v1/models 404）；Deepin 用 EMBEDDING_PROVIDER=hash 本地向量。
7. service-control-barriers/<svc>.json 是 admission barrier：失败的 restart 留 orphan barrier，不影响已运行服务，下次服务动作时按 release/adopt/override 处理；手动 launch 不走 service_control 不会清它。