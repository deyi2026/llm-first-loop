---
title: "改稿脚本用列表切片赋值插入新行会覆盖原行——必须用 lines[i+1:i+1] 插入"
scenario: "d84 审稿意见处置脚本 _d84_patch4b.py 里，为了在指定行后插入新内容写了 `lines[115:116] = ins116`（ins116 是 2 个元素）并自注为「从后往前插入」。实际语义是**用 2 个元素替换掉 1 个元素**，原第 116 行（正文「写侧是 fail-closed 的——命中就抛 HeldoutContaminationError 拒写。」）与原第 25 行（「这就是本篇的全部主张…」）被静默丢弃。缺陷没被机检发现（build/audit/caption-check/spotcheck 全 PASS），是被父级随后逐行读稿时肉眼比对 R1 版才发现。"
root_cause: "Python 列表切片赋值是替换语义；`lines[i:i] = [...]` 会把原元素全部丢掉，脚本作者误当成插入。"
solution: "在 Python 列表上做插入必须用 `lines[i+1:i+1] = [new]`（插入到第 i 行之后）或 `lines[i:i] = [old, new]`（显式保留原行）；不要用 `lines[i:i] = [new…]` 冒充插入。改稿后必须做「行数守恒 + 关键原句仍在」的双重自检：比较改前改后的行数变化是否等于预期插入行数，并对被触及段落的关键句做子串断言（例如 `assert \"HeldoutContaminationError\" in md`）。本班据此写了 _d84_patch6.py 从 R1 版原句取回被覆盖的两行，并重跑全部机检（md sha 由 08fc32a3 变为 7426d5ba）。当前性验证：跑 `grep -n 'HeldoutContaminationError' docs/promotion/20261114-lfl-daily-84.md` 应命中第 117 行；跑 `grep -n 'lines\\[[0-9]*:[0-9]*\\] =' docs/promotion/_d84_patch*.py` 检查后续补丁脚本是否仍用切片赋值冒充插入；复现：把 _d84_patch4b.py 的 `lines[115:116] = ins116` 改成 `lines[116:116] = ins116` 再跑，行数应从 150 变 151 且原句仍在。"
evidence: docs/promotion/_d84_patch4b.py（C 段切片赋值）、docs/promotion/_d84_patch6.py（修复：assert 「这就是本篇的全部主张」与「HeldoutContaminationError」在位）、docs/promotion/receipts/d84-build.json（md_sha256=7426d5bae4a29f24c0325a1f6959c3f8939c6023b5f02dcd1f574626402de695）、独立复审子代理 subagent_811777917830 的定点核对第 1/2 题
tags: [patching, python-slice, content-loss, self-review, promotion]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-14T08:32:13.211499+08:00"
updated_at: "2026-11-14T08:32:13.211499+08:00"
---