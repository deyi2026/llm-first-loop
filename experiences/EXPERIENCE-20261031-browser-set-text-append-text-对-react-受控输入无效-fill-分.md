---
title: browser set_text/append_text 对 React 受控输入无效：fill 分支仍用 this.value 赋值
scenario: 在 LFL Web V2 面板（React 受控 input）上用 browser_operate do=set_text 写值，回执 status=completed，但输入框 value 未变（仍为旧值），且 wait kind=object_text 断言新值失败。改用 do=type 后同一目标写入成功。
root_cause: cdp_action_host.py 的 fill/select 分支使用 this.value 直接赋值 + 合成事件，未走 React 可识别的原生 setter 路径（native value setter + InputEvent），导致 React 受控组件回滚 DOM 值。
solution: "写 React 受控输入必须用 do=type（走 Input.insertText 真实输入管线）；do=set_text/append_text 对 React 受控组件无效。根因在 src/llm_loop/browser/cdp_action_host.py 的 verb==\"fill\" 分支：它用 `this.value=next` + 合成 input/change 事件赋值，React 受控组件会在下一次 render 时用 state 覆盖 DOM 值，事件也不进入 React 的 onChange。该文件同一分支旁的 type 注释明确写了「never a this.value assignment with synthesized events (PR2 root cause)」，即 fill 分支是未清理的旧模式（type 已修，fill 未修）。同理 verb==\"select\" 分支也是 this.value 赋值，对 React 受控 select 可能同样不生效。排查方法：用 browser_perceive wait kind=object_text field=value_text 做写入后断言，不要只看回执 status。"
evidence: "browser_operate set_text 回执 evidence://v1/8338b51d4b5ec70c3ffd7181b9b453c586504232c06fce154ddff2553647ebb7 与 evidence://v1/7ea56584f396bf3456818dd5a27549069ad34b9ded2c0122171c0834a8ecfd26 均 status=completed；wait object_text value_text=zzz-cap-test 未匹配（evidence://v1/37b24665d46469915bedb5ac69b140dc2e91e8b3b08a33a7fe105f8db2487374）；type 路径写入成功（evidence://v1/cb067cbdb572cb2b6c5232283fc2112fc15b8df43e0bdb708a79655b795a94e5）；源码 src/llm_loop/browser/cdp_action_host.py:1036-1049（fill/select 分支）与 1071-1079（type 分支注释）"
tags: [browser, set_text, react, defect, cdp]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T14:38:29.281307+08:00"
updated_at: "2026-10-31T14:38:29.281307+08:00"
---

当前性验证：执行 `grep -n 'verb == "fill"' src/llm_loop/browser/cdp_action_host.py` 应仍命中 fill 分支（第 1036 行附近）；若该行已改为原生 setter 路径或已删除，则本条结论失效，需重新实测。复现路径：任选 React 受控 input，browser_operate do=set_text 写入后用 browser_perceive wait kind=object_text field=value_text 断言——旧实现断言失败、新实现断言通过。