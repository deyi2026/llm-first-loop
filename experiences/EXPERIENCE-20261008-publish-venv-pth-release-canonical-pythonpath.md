---
title: 发布链自举缺口：publish 工具与 .venv .pth 绑定旧 release，新发布链代码首次生效需 canonical PYTHONPATH 自举
scenario: "发布链/生命周期代码（service_control.py、restart 链）的自举部署：修改\"发布/重启行为本身\"的提交在首次上线时，publish 与 .venv 均由旧运行时代码执行"
root_cause: ""
solution: "先用 `inspect`/hasattr 探针核 import 来源；需要新逻辑物化新 release 时，用 `PYTHONPATH=<canonical>/src .venv/bin/python -c \"from llm_loop.runtime.service_control import build_deployment; build_deployment(...)\"` 走复用路径由生产函数自身完成，而非手写文件。设计上应把此类发布链缺口记为\"切换代一次性自举\"，不作为机制缺陷回滚。"
evidence: module.__file__=.releases/b6a5d4a2.../src/llm_loop/runtime/service_control.py（hasattr _materialize_release_sidecar=False）；PYTHONPATH=canonical/src 后 True 且 build_deployment 复用路径物化 release .env（0600/135B），--check-binding exit 0
tags: [service-control, publish-chain, bootstrap, venv-pth, release-checkout]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-08T08:25:53.313787+08:00"
updated_at: "2026-10-08T08:25:53.313787+08:00"
---

2026-10-08 发布 release sidecar 自动物化（commit 51f7f4755）时发现：(1) service_control publish 由当前运行服务进程执行——若代码尚未部署，publish 走的是旧逻辑；(2) `.venv/bin/python -c "import llm_loop"` 解析到 `.releases/<旧head>/src/`（site-packages .pth 绑定 release），canonical 树上 cwd 运行也导入旧代码。首次部署含发布链改动的代码存在自举缺口：新 release 由旧代码物化，天生缺新产物。自举法：`PYTHONPATH=<canonical>/src .venv/bin/python -c "build_deployment(...)"` 走复用路径，用生产函数自身物化/修复 release 衍生工件，避免手写补丁。此后 gen+1 起服务自身即具备新发布逻辑，缺口只存在于切换代。
当前性验证：`.venv/bin/python -c "import llm_loop.runtime.service_control as m; print(m.__file__, hasattr(m,'_materialize_release_sidecar'))"`——若输出不含 `_materialize_release_sidecar True` 或路径非当前期望 release/canonical，说明 venv 绑定已漂移，需重验本卡结论；也可 `ls .releases/<当前 desired head>/.env` 确认物化仍在。