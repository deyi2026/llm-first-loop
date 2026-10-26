---
title: 外部 judge API 无凭据时：接口同构开源复现 + 本地部署替代（SemIf/Jev 案例）
scenario: LFL Jev 治理设计 P1b：外部 judge API（TypeSafe）无凭据、授权外发被卡时，用户指出存在接口同构的开源替代（SemIf，原 OpenJev）。
root_cause: ""
solution: "先一手核验再部署：GitHub/OpenRouter/HF 页面直读确认存在性与接口形态（二手文只作线索）；git 被墙时改走 codeload tarball vendor；venv 钉依赖+钉模型 revision；冒烟不用实验题；判分主体变更按\"先冻结新一轮预注册再跑\"纪律执行；开源复现的结果显式标注\"接口模式复现≠本体\"，不授予原模型任何资格。"
evidence: "outputs/jev-p1b-20261015/p1b_report.json（mode=local_semif, 5/6, resolved_model=semif-phase1+Qwen3.5-4B@851bf6e+mlx）；docs/DESIGN-20261014-jev-experience-method-loop-governance.md §11.2 + 附录C v0.8.1→v0.8.2（冻结时序先于首跑 10:58）；vendor/SemIf/.venv + ~/.cache/huggingface 模型快照"
tags: [closed-api-substitute, local-deployment, mlx, preregistration, vendor-tarball, proxy-environment]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T10:59:36.505168+08:00"
updated_at: "2026-10-15T10:59:36.505168+08:00"
---

完整过程：用户断言"网上有类似Jev的开源模型可替代可本地部署"并给出二手来源链接。处理顺序：(1) 不直接采信二手文，读一手源（GitHub repo 页 + OpenRouter 模型页 + HF 模型页直读）确认 SemIf 存在、MIT、原生 MLX 后端、钉住基线模型；(2) 部署：git clone 被网络阻断 → codeload.github.com tarball 可达（api.github.com 不可达），python3.11 venv + pip install -e '.[test,mlx]'，模型用 huggingface_hub snapshot_download 钉 revision；(3) 冒烟：官方 examples 因各行 state 不同被 shared 模式拒绝（恰好验证约束），自造同 state 2 题验证；(4) 纪律：judge 主体变更=新一轮预注册（DESIGN §11.2 冻结于任何真实评分之前，文档快照可证时序），原 TypeSafe 外发授权原样保留不重释；(5) adapter 实现为包外 transport（保住包内零网络 tripwire），概率映射注意 SemIf 输出是"按选项顺序的数组"而非字典，confidence:=p_selected 需显式声明为 adapter 定义。结果：6/6 schema-valid、5/6 与独立盲评一致、~17s 双批本地完成、零费用。