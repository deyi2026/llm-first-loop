---
title: 插图上传失败先查路径拼接；某域名全站不通先做对照实验区分网络层与业务层
scenario: CDP DOM.setFileInputFiles 后头条弹窗显示「上传失败」；以及 zhuanlan.zhihu.com 打不开而其他站点正常
root_cause: ""
solution: "上传失败的真实原因是路径拼错：脚本里用 os.path.dirname(os.path.abspath(\".\")) 得到的是**父目录**，拼出来是 .../docs/img/x.png（不存在），面板只显示「上传失败」不报错。规则：插图路径一律 os.path.abspath(\"img/x.png\") 并先 os.path.exists() 断言。域名不可达要区分层次：同一时刻 www.zhihu.com 302、www.toutiao.com 200，只有 zhuanlan.zhihu.com 解析到 198.18.x.x fake-ip 段且 TLS 握手被重置（curl 000 / Chrome chrome-error）——这属于本机代理对单子域的阻断，不是账号或文章问题，不该无脑重试，应如实上报阻塞。"
evidence: "docs/promotion/receipts/20261013-daily13-toutiao.json 的 known_issues_fixed_this_run 与 zhihu.attempts（11:35 复测 000、zhihu.com 302、toutiao.com 200）"
tags: [故障定位, CDP, 网络, 上传失败]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T11:38:01.375577+08:00"
updated_at: "2026-10-13T11:38:01.375577+08:00"
---