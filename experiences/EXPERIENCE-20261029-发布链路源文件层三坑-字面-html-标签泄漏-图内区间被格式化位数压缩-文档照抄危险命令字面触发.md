---
title: 发布链路源文件层三坑：字面 HTML 标签泄漏、图内区间被格式化位数压缩、文档照抄危险命令字面触发 E6
scenario: LFL 每日推广写稿-发布链路（sched-0300b296 常驻授权班次），md 源文件经 md2html 转 HTML 再以 data-URI 粘贴进平台编辑器；稿件须过独立审稿子代理 + Rule28 review_admission 双闸。d40（2026-10-29）实际命中：首闸 REVISE 判 P1「5 段字面 HTML 标签将原文展示给读者」；信息图 0.835–0.840 区间被两位小数格式压缩成 0.84–0.84（read_image 复核发现）；STATUS 落盘时正文描述性引用 heredoc 命令字面再次触发 E6 硬阻断。
root_cause: ""
solution: 写作期自查清单：a) grep md 源中字面 p/strong 标签，必须为 0——需要加粗一律用星号语法；b) 图内数值标签位数与数据精度对齐（生成脚本格式化位数参数化，窄区间三位小数），read_image 复核时除排版外专项核对区间未失真；c) 文档/STATUS 里描述危险命令时只写行为名（「heredoc 直喂解释器」），不照抄完整命令字面；d) 被 P1 类问题打回后修复路径：改 md → rebuild（BUILD 断言过）→ 关旧编辑器 tab 重开 → 重贴 → title/ai/verify → 重抓渲染态送审稿 → 闸复审，全程 8-12 分钟。
evidence: docs/promotion/STATUS-20261029-daily40.md 第四节（首闸 REVISE 0P0+1P1+2P2 记录，subagent_8b88500b76a9）；docs/promotion/receipts/daily40-admission.json（二闸 PASS，candidate 2a3ff940）；read_image fig171 两轮回执（0.84–0.84 失真→0.835–0.840 修复）；E6 硬阻断回执 2 次（本会话 execute_command，STATUS 落盘与 heredoc 各一次）
tags: [推广发布, md2html, Rule28, 信息图, 区间保真, E6阻断]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-29T08:33:27.843771+08:00"
updated_at: "2026-10-29T08:33:27.843771+08:00"
---

头条/知乎图文发布链路（md 源 → md2html → data-URI 粘贴 → 平台编辑器）中，三类「源文件层与产出层混淆」缺陷都会通过 Rule28/独立审稿闸被拦，写作期规避成本远低于发布期返工：1) md 源文件里写字面 <p><strong> 标签，md2html 会转义成纯文本，读者看到原始标签字符串（判 P1）；任务指令「三级标题改用 p+strong」指的是 HTML 产出层，md 源层应写 **星号加粗** 让转换器生成。2) 信息图数值标签的格式化位数必须与数据精度匹配：区间 0.835–0.840 用 f"{:.2f}" 会压成 0.84–0.84，属区间失真，与「实测区间不得取端点」审稿红线同源；修法=格式化位数 nd 参数化，窄区间用三位小数。3) STATUS/文档正文里描述性照抄危险命令字面（如 heredoc 直喂解释器的完整命令行）同样触发 E6 硬阻断——文档写作应转述行为而非照抄命令字面。