---
title: 程序化 Range 选择不被两端编辑器采纳、Cmd+Z 在知乎无效
scenario: 想在头条/知乎编辑器里把图片插到指定段落（而不是文末），尝试了程序化 Range 选择与撤销快捷键两条路
root_cause: 头条 ProseMirror 与知乎 Slate 的合成 paste 都读真实光标位置，DOM Range 只是显示选择；Mac 上 modifiers=4 的 Cmd+Z 事件未触发编辑器的撤销处理器（Backspace 有效）。
solution: "放弃 setStartBefore + 合成 paste，改为「找到目标 H2 前的空 FIGURE 块并用真实鼠标点击它，再合成 paste」；误插到文末的图用真实鼠标点击图块 + Backspace 删除（Cmd+Z 删不掉）。选区必须用真实鼠标事件（Input.dispatchMouseEvent mousePressed/mouseReleased）落点，合成事件不产生光标。发布前必须用 DOM 邻居关系核对每张图的前后文，而不是相信脚本顺序。当前性验证（2026-10-13 实跑）：跑 docs/promotion/_imgs14b.py（头条 Range 方案）应看到「SEL: anchor 落在文末 footer」；跑 docs/promotion/_zhfix14c.py（知乎 H2 前空块方案）应打印 pos 中「62 before:… | after:四、它敢让自己改自己」「75 … after:五、诚实的边界」，即图落在节末而非文末；换站点/版本后先 curl -s http://127.0.0.1:9229/json 确认目标页仍在，再跑对应脚本核对上面的 pos 字符串。"
evidence: 2026-10-13：两次尝试 Range.setStartBefore(段落) 后 paste，getSelection().anchorOffset 仍指向文末，两图都追加到 footer 之后；改用点击 H2 前空块后，img 落在 block 62（H2「四、它敢让自己改自己」之前）与 block 75（H2「五、诚实的边界…」之前）；12 次 Cmd+Z 无效，点击图块 + Backspace 一次删除成功
tags: [browser, cdp, editor, toutiao, zhihu, pitfall]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T21:01:03.014251+08:00"
updated_at: "2026-10-13T21:01:03.014251+08:00"
supersedes: [EXPERIENCE-20261013-头条-知乎图文配图与公网验收的可靠链路-2026-10-13-两平台实跑验证]
---