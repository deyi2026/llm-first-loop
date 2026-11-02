---
title: macOS 沙箱下用 WeasyPrint（brew python3.11 + pango）生成中文 PDF，替代失败的 Chrome headless
scenario: 需要把本地 HTML 报告转成中文 PDF。环境限制：execute_command 运行在 macOS sandbox-exec 下（仅允许写工作区/缓存目录）；/Applications/Google Chrome 的 --headless=new --print-to-pdf 因 ProcessSingleton 无法创建 socket 目录而终止（user-data-dir/TMPDIR/HOME 覆盖均无效）；pandoc 存在但无 xelatex/pdflatex/weasyprint；qlmanage 报 sandbox initialization failed；sips 不能转 PDF。
root_cause: ""
solution: "1) 用 /opt/homebrew/bin/python3.11 -m pip install --target <workspace>/.tmp-py311 weasyprint（系统 python3.9 装出的包在 brew python 下不兼容，反之亦然）。2) 运行时必须带 DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib——系统 /usr/bin/python3 受 SIP 保护会忽略 DYLD_*，导致 weasyprint 报 cannot load library libgobject-2.0-0；brew python 不受此限，能加载 Homebrew 的 libpango/libgobject/libharfbuzz。3) 脚本内 HTML(filename=...).render() 先取 len(doc.pages) 做页数校验，再 write_pdf()。4) CSS 用 @page{size:A4; margin:...; @bottom-center{content:counter(page)}}、@page:first 去首页页码、目录页码用 a::after{content:target-counter(attr(href),page)} 自动生成，避免手写页码与真实页数不符。5) 质量校验：写 Swift + PDFKit 小程序把指定页渲染成 PNG（CGContext + page.draw），再用 read_image 抽查封面/目录/表格页/末页。"
evidence: "本次实测：reports/LFL-vs-Anthropic-Subagent-20261031.html → PDF 23 页 1.3MB；WeasyPrint 70.0；目录页码 target-counter 生效（核对 p2 视觉回执：摘要 p3、第4章 p9、第5章 p15、第6章 p17、第8章 p20）；封面 p1、摘要表 p3、局限表 p19、末页 p23 视觉抽查均无乱码/溢出/截断。Chrome 失败回执：process_singleton_posix.cc:1046 Failed to create socket directory（三次不同 profile/TMPDIR/HOME 组合）。"
tags: [pdf, weasyprint, macos, sandbox, 中文字体, 报告生成]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T08:20:32.849421+08:00"
updated_at: "2026-10-31T08:20:32.849421+08:00"
---