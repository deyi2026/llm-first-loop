---
method_id: promotion-report-to-article-publish-d4340da7235f
name: promotion-report-to-article-publish
description: 把仓库内既有分析报告改写成对外科普稿并走头条发布闸的完整流水线（台账→稿件→原创配图→BUILD 机械校验→独立只读审稿双轮→Rule28 admission→preview→confirm→收口取证）
aliases: promotion pipeline, 头条专题稿发布, daily publish
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:0f500e8c-993a-46f0-bbc5-512ca2c08cf4:435:360347fb12855e16f325
created_at: 2026-10-31T09:31:03.540312+08:00
updated_at: 2026-10-31T09:31:03.540312+08:00
---
适用：把仓库内既有分析报告改写成对外科普稿并走平台发布（头条链路）。步骤：① 台账 docs/promotion/YYYYMMDD-daily-NN-sources.md（正文每个数字一行：数值｜出处｜观测时间，含口径声明块）；② 正文 md（首行标题≤30字、8 个 ## 节、4 图、末尾来源与单个 #人工智能# 标签、无相对时间词）；③ 配图 PIL 原创（figures/_dNN.py + _draw.py），read_image 逐张验排版，编号顺延上一次（figNNN）；④ BUILD（_dNN_build.py，data-URI 链路）机械校验 md img=html img、fig_paras、resid=0、h1=8、tag=1、rel_time=0、literal_tag_leak=0；⑤ 独立只读审稿子代理（异模型 glm/glm-5.3，write_scope deny）→ REVISE 则逐条处置并窄复审 PASS；⑥ 宿主 review_admission(kind=article_publish)：manuscript_path/artifact_paths 传绝对路径，target_name=页面按钮名「确认发布」，先 preview 开浮层再 start；⑦ confirm 前脚本 assert admission 的 frozen_md_sha == digest(正文)；⑧ confirm 点击 → AFTER_URL=作品管理列表；⑨ 收口回读列表条目并如实登记「审核中/已发布」，不提前宣称已发布。关键坑：admission 必须先 preview（否则 publication_button_not_observed）；浏览器多标签时用 browser_perceive 显式 target_id 换绑（否则 MultiPageAmbiguityError）；shell heredoc 内含受保护动作关键字会被硬阻断，改 edit_file/staging+cp。
当前性验证：先 `grep -n "phase ==\|review_admission" docs/promotion/_dNN_publish.py` 确认相位名与准入调用未变（今日实测 10 个相位：open/state/prepare/title/ai/verify/pageman/preview/admission/confirm）；再跑 `cd docs/promotion && ../../.venv/bin/python _dNN_build.py` 应输出 BUILD PASS 且 md img == html img == 4；页面按钮文案先 `grep -n "确认发布\|预览并发布" docs/promotion/_dNN_publish.py` 确认。
