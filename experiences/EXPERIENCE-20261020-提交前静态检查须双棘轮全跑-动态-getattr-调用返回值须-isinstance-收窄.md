---
title: 提交前静态检查须双棘轮全跑：动态 getattr 调用返回值须 isinstance 收窄
scenario: 提交含 src 改动的修复后跑 Rule28 全量门禁；或对构造器注入对象用 getattr 做能力探测（fail-open 防御）时。
root_cause: ""
solution: "① 提交前静态检查全链路：ruff 棘轮 + pyright 棘轮 + 定向 pytest，三者缺一不可（.venv/bin/pyright <file> 单文件秒级可先跑）；② getattr 取到的可调用返回值是静态 object，返回前用 isinstance(result, dict) 收窄而非 cast；③ 全量门禁失败修复提交后，须重新 review_admission 窄复审（新 SHA）再重跑 ci_gate。"
evidence: "evidence://v1/066e5493aa18b786ee011789205967cfb8e5bcfdb43a927be6b264940d50c8e3（第2轮 ci_gate exit 0，9643 passed）；commits 44a331eaa/b0f22cf1a/fdf285cd0；reviewer subagent_518f197f6733、subagent_d2879385d810"
tags: [rule28, ci_gate, pyright, type-safety, getattr, duck-typing, 提交纪律]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T16:40:21.053739+08:00"
updated_at: "2026-10-20T16:40:21.053739+08:00"
---

现象：EVO-20261020-91de7f8c 主体提交（44a331eaa）前只跑了 ruff + 定向 pytest（11 例新测试+1075 定向回归），漏掉 pyright 全树棘轮；Rule28 全量门禁首跑在 [3/5] 失败：browser_semantic_operation.py `_identity_search_safe` 通过 `getattr(self._perception, "identity_search", None)` 取鸭子型方法，pyright 将 `callable(search)` 收窄为返回 `object` 的可调用，直接 return 违反 `dict[str, Any] | None` 签名（reportReturnType）。
修复（b0f22cf1a）：动态调用结果先落局部变量，`return result if isinstance(result, dict) else None`——与下游既有 `isinstance(search, dict)` 判定一致，fail-open 语义保留（非 dict→None），无 cast。
验证：单文件 pyright 0 诊断；定向 11/11 过；窄复审（subagent_d2879385d810，新指纹 2fec2cf1）PASS 后全量 ci_gate exit 0（9643 passed, 137 skipped；ruff/pyright new=0）。
要点：① 修改 src 的提交，提交前静态检查必须 ruff+pyright 双棘轮都过，定向测试不能替代；② 对 `getattr` 动态取得的可调用，返回值静态类型是 object，签名收窄用 isinstance 判定而非 cast；③ 产物变化后旧的一次性放行资格失效，须按新指纹窄复审再重跑。