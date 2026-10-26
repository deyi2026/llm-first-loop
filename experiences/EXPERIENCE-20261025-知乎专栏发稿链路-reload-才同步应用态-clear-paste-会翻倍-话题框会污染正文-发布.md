---
title: 知乎专栏发稿链路：reload 才同步应用态、clear+paste 会翻倍、话题框会污染正文、发布按钮需 CDP 真实点击
scenario: 知乎专栏（zhuanlan.zhihu.com/p/<id>/edit）自动化发稿：注入正文、设创作声明、过发表闸、点发布、公网回读
root_cause: ""
solution: |
  ① 应用态与 DOM 不同步：粘贴后 DOM 已有内容但应用态仍是 0 字且「发布」禁用，reload 后状态才同步；② 「clear 再 paste」不会清掉应用态，只会得到两份正文（并多出孤立 token「人工智能」被审查判 P1），必须新建草稿页重贴；③ 话题输入框（无 placeholder 的 input）会把检索词用 Input.insertText 打进正文，话题要么用编辑器自带控件要么放弃；④ 发布按钮在浏览器工具语义层无可寻址 name（exact 寻址 target_not_found），走 CDP 真实鼠标点击可成功；⑤ 创作声明「包含 AI 辅助创作 作者对内容负责」是平台级开关，勾选后持久化到发布后的文章；⑥ 平台级声明不能替代正文内声明段——两处都要有。
  当前性验证：已发表文章 https://zhuanlan.zhihu.com/p/2097694420728537150 仍可读（用已登录浏览器打开，或用 _cdp_eval.py 对知乎 tab 读 .Post-RichText 的 h2 数=11、table 数=7）；复现编辑器差异：新开草稿页粘贴后先数 textarea 数量，未 reload 时应用态字数仍为 0。
evidence: "evidence://v1/023522b323ed7f6e592dcfdff8ccefc60c20117c4ceb21a0e6e03fcc4f2312f0, evidence://v1/da43b0c1c738fb5c92f89d90b92af210fdd5e23dd7814152b2b406105a8bea80, evidence://v1/48e7c62f93033a8e7e08f3ac486114ebc5b57090da7739ef6774dfbb7aa95da1"
tags: [知乎, zhihu, 发布, 专栏, CDP, 创作声明, 应用态]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-25T14:46:29.704860+08:00"
updated_at: "2026-10-25T14:46:29.704860+08:00"
supersedes: [EXPERIENCE-20261023-知乎专栏发稿可复制链路-d20-d23-先例-本次实测修正-发布前选定创作声明本次持久化-发布按钮须]
---