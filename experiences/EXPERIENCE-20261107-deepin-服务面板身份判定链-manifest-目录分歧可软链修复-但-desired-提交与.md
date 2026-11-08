---
title: deepin 服务面板身份判定链：manifest 目录分歧可软链修复，但 desired 提交与 wheel/repo 布局无可诚实匹配的运行形态
scenario: LFL 面板 desired deployment(gen6=eb51e82) 与 deepin 上真实运行进程的身份对账：面板四服务全 ⚠（运行身份需核验/重启），需判定绿卡条件并尝试收敛。
root_cause: ""
solution: 先读判定代码再动手；用 manifest 软链修复观察面路径分歧；识别 PYTHONPATH 身份切换的不可行性并保留 wheel/原形态；给出 desired 重锚或 release 安装两条真收敛路线。
evidence: "eb51e82 版 service_control.py（deepin wheel 与 .releases worktree md5 一致 ebddcf7d…）status/identity 判定代码；runtime_manifest.{feishu,learning}.json 实际落盘 repo/data/runtime（head=3f23358）；web 试切 repo venv 失败日志（FATAL_RUNTIME_IDENTITY_MISMATCH shadow WARN + 缺 LLM_API_KEY，/tmp/lfl_sw/web.out）；feishu PYTHONPATH 切换后 manifest head 仍 3f23358（/tmp/lfl_sw/ 回执）；软链后 /api/v1/services/status 四卡真实身份回显；飞书桥 ESTABLISHED 183.36.42.103:443（ss -tnp pid=1098169）；web /health knowledge healthy experience records=19。"
tags: [service_control, runtime-identity, deepin, deployment, panel, manifest]
source:
  session: "2026-11-07T06:13-06:35+08:00"
  machine: operator@[private LAN address redacted]
  deployment: gen6 eb51e82
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-07T06:32:08.044837+08:00"
updated_at: "2026-11-07T06:32:08.044837+08:00"
---

deepin（wheel 安装布局 + workspace repo editable venv 混布）上服务面板"运行身份需核验"的判定与修复边界：
1) 判定链（service_control.py status compose）：绿 = manifest_present ∧ pid 活 ∧ live.git_head==desired.git_head；**不需要重启回执**（代码注释明示不必仅为追平回执而重启）。
2) manifest 由各服务启动自写（web/__init__.py、runtime/launch.py:69），写到"各自 data_dir/runtime/"——web(wheel)=~/.local/share/lfl/data/runtime（面板 store），feishu/learning(repo)=repo/data/runtime。面板只读 store 目录 ⇒ "live_manifest_missing" 多数是**读取路径分歧**，软链 manifest 到 store 即可让身份如实上屏（零功能影响，进程重写自身文件后软链仍有效）。
3) manifest 的 git_head 从 **venv/运行锚定**（editable 安装指向的 repo src）解析，**PYTHONPATH 注入新 worktree src 改不了它**——只会触发 RUNTIME_IDENTITY_MODE=shadow 的 WARN（pythonpath_set 标记、identity_ok=false），head 仍是 venv 锚定的 repo HEAD。
4) web 从 repo venv lfl 启动会在 .env 锚点上翻车（缺 LLM_API_KEY 必填）——wheel lfl 与 repo lfl 的配置加载锚不同；web 保持 wheel 形态（lfl --workspace <ws> web，cwd=~/.local/share/lfl）。
5) 结论：desired=某 git 提交而服务跑在 wheel/异提交 repo 时，**没有可诚实匹配的运行形态**；换 interpreter/PYTHONPATH 都是伪路径（要么 head 不变、要么配置漂移）。要绿只能：desired 锚到真实谱系（如 3f23358=eb51e82+纯知识提交），或安装器把目标提交构建为带身份的 release。
6) 教训：动手换形态前先做"最小证据探针"（一次 python -c 验证 head 解析），避免 ~90 秒面板不可用的试错成本；回滚脚本必须支持 env 文件参数覆盖（新 pid 的 /proc env 不可得）。